#!/usr/bin/env python3
"""Verify a bounded MCP tool is visible to Codex App Server without a model turn.

The command uses a caller-provided isolated CODEX_HOME. It records only server
names, runtime states, tool names, and fixed schema booleans; it never records
MCP auth status, tool descriptions, arguments, environment values, or output.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
from typing import Any, Sequence

try:
    from .feynman_transient_bounded_mcp import BoundedMcpOverride, build_bounded_mcp_override
except ImportError:
    from feynman_transient_bounded_mcp import BoundedMcpOverride, build_bounded_mcp_override


SYSTEM_ENV_KEYS = ("PATH", "SystemRoot", "WINDIR", "ComSpec", "PATHEXT", "TEMP", "TMP")
TARGET_TOOL = "feynman_read_probe_byte"


def _safe_env(codex_home: Path) -> dict[str, str]:
    environment = {key: os.environ[key] for key in SYSTEM_ENV_KEYS if os.environ.get(key)}
    environment["CODEX_HOME"] = str(codex_home)
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        environment.pop(key, None)
    return environment


def _request(identifier: int, method: str, params: dict[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}) + "\n").encode()


def _notification(method: str, params: dict[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n").encode()


def summarize_status(result: Any, *, target_tool: str = TARGET_TOOL,
                     target_tools: Sequence[str] | None = None) -> dict[str, Any]:
    """Keep only the tool-catalog facts needed by the readiness gate."""
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise ValueError("MCP status result has no data list")
    servers = []
    for entry in result["data"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ValueError("MCP status entry is invalid")
        tools = entry.get("tools")
        if not isinstance(tools, dict):
            raise ValueError("MCP status tool catalog is invalid")
        target = tools.get(target_tool)
        input_schema = target.get("inputSchema") if isinstance(target, dict) else None
        server_summary = {
            "name": entry["name"],
            "runtime_status": entry.get("runtimeStatus"),
            "tool_names": sorted(name for name in tools if isinstance(name, str)),
            "tools_error_present": entry.get("toolsError") is not None,
            "target_tool_present": isinstance(target, dict),
            "target_tool_has_empty_input_schema": (
                isinstance(input_schema, dict)
                and input_schema.get("type") == "object"
                and input_schema.get("additionalProperties") is False
                and input_schema.get("properties") == {}
            ),
        }
        if target_tools is not None:
            schemas: dict[str, dict[str, Any]] = {}
            for name in target_tools:
                tool = tools.get(name)
                schema = tool.get("inputSchema") if isinstance(tool, dict) else None
                if not isinstance(schema, dict):
                    schemas[name] = {"present": False}
                    continue
                properties = schema.get("properties")
                required = schema.get("required")
                schemas[name] = {
                    "present": True,
                    "type": schema.get("type"),
                    "additional_properties": schema.get("additionalProperties"),
                    "property_names": sorted(properties) if isinstance(properties, dict) else None,
                    "required_names": sorted(required) if isinstance(required, list) else None,
                    "content_type": (
                        properties.get("content", {}).get("type")
                        if isinstance(properties, dict) and isinstance(properties.get("content"), dict)
                        else None
                    ),
                    "content_max_length": (
                        properties.get("content", {}).get("maxLength")
                        if isinstance(properties, dict) and isinstance(properties.get("content"), dict)
                        else None
                    ),
                }
            server_summary["target_tool_schemas"] = schemas
        servers.append(server_summary)
    return {"server_count": len(servers), "servers": servers}


def run(*, codex_bin: str, codex_home: Path, output: Path, timeout_seconds: int = 20,
        config_overrides: Sequence[str] = (),
        override_lineage: dict[str, object] | None = None,
        target_tool: str = TARGET_TOOL,
        target_tools: Sequence[str] | None = None) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise ValueError("catalog preflight output must be new")
    if not codex_home.is_dir() or codex_home.is_symlink():
        raise ValueError("catalog preflight requires an existing isolated CODEX_HOME directory")
    if config_overrides and any(codex_home.iterdir()):
        raise ValueError("transient catalog preflight requires an empty isolated CODEX_HOME")
    command = [codex_bin, "app-server"]
    for value in config_overrides:
        command.extend(("-c", value))
    command.append("--stdio")
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_safe_env(codex_home),
        bufsize=0,
    )
    assert process.stdin is not None and process.stdout is not None
    received: queue.Queue[Any] = queue.Queue()

    def receive() -> None:
        try:
            for line in process.stdout:
                try:
                    received.put(json.loads(line))
                except json.JSONDecodeError:
                    received.put(None)
        except OSError:
            received.put(None)

    reader = threading.Thread(target=receive, daemon=True)
    reader.start()

    def request(identifier: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
        process.stdin.write(_request(identifier, method, params))
        process.stdin.flush()
        while True:
            message = received.get(timeout=timeout_seconds)
            if isinstance(message, dict) and message.get("id") == identifier:
                return message

    try:
        initialized = request(1, "initialize", {
            "clientInfo": {"name": "feynman-mcp-catalog-preflight", "version": "0.1.0"},
        })
        if "error" in initialized:
            raise ValueError("App Server initialize failed")
        process.stdin.write(_notification("initialized", {}))
        process.stdin.flush()
        status = request(2, "mcpServerStatus/list", {
            "detail": "toolsAndAuthOnly", "limit": 10,
        })
        if "error" in status:
            raise ValueError("MCP server status request failed")
        catalog = summarize_status(
            status.get("result"), target_tool=target_tool, target_tools=target_tools)
        report = {
            "schema_version": 1,
            "verdict": "bounded-mcp-catalog-visible",
            "model_calls": 0,
            "authentication_used": False,
            "auth_status_preserved": False,
            "tool_payloads_preserved": False,
            "catalog": catalog,
            "target_tool_visible": any(
                server["target_tool_present"] for server in catalog["servers"]
            ),
            "configuration": {
                "transport": "cli-overrides" if config_overrides else "codex-home-config",
                "user_config_file_required": not bool(config_overrides),
                "override_lineage": override_lineage,
            },
        }
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        reader.join(timeout=2)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--node-bin", type=Path)
    parser.add_argument("--bounded-adapter", type=Path)
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    try:
        transient_values = (args.node_bin, args.bounded_adapter, args.candidate)
        if any(value is not None for value in transient_values) and not all(
                value is not None for value in transient_values):
            raise ValueError("transient MCP mode requires node, adapter, and candidate together")
        override: BoundedMcpOverride | None = None
        if all(value is not None for value in transient_values):
            override = build_bounded_mcp_override(
                node_bin=args.node_bin, adapter=args.bounded_adapter, candidate=args.candidate)
        report = run(codex_bin=args.codex_bin, codex_home=args.codex_home,
                     output=args.output, timeout_seconds=args.timeout_seconds,
                     config_overrides=override.values if override else (),
                     override_lineage=override.sanitized_lineage() if override else None)
    except (OSError, ValueError, queue.Empty, subprocess.SubprocessError) as exc:
        parser.exit(2, "error: MCP catalog preflight failed: " + type(exc).__name__ + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
