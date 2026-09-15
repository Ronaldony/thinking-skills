#!/usr/bin/env python3
"""Verify MCP catalog visibility inside the isolated Docker runtime.

This is a model-free diagnostic. It creates a fresh non-authenticated Codex
home with one fixed MCP server, starts the pinned container's App Server, and
records only sanitized catalog facts. It never starts a thread or turn.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
from typing import Any
from uuid import uuid4

from tooling.feynman_mcp_catalog_preflight import summarize_status


TARGET_TOOL = "feynman_read_probe_byte"
ADAPTER_PATH = "/opt/feynman/feynman_bounded_read_adapter.mjs"


def _config_text() -> str:
    return """[mcp_servers.feynman_bounded_read]
command = "node"
args = ["/opt/feynman/feynman_bounded_read_adapter.mjs"]
cwd = "/run/candidate"
required = true
enabled_tools = ["feynman_read_probe_byte"]
startup_timeout_sec = 10
tool_timeout_sec = 10

[mcp_servers.feynman_bounded_read.env]
FEYNMAN_BOUNDED_READ_ROOT = "/run/candidate"
FEYNMAN_BOUNDED_READ_FILE = "/run/candidate/candidate.py"
"""


def _request(identifier: int, method: str, params: dict[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}) + "\n").encode()


def _notification(method: str, params: dict[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n").encode()


def _directory_without_symlinks(path: Path, label: str) -> Path:
    absolute = path.absolute()
    if not absolute.exists() or not absolute.is_dir():
        raise ValueError(f"{label} is not an existing directory")
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} contains a symbolic link")
    return absolute


def _docker_command(*, docker: str, docker_config: Path, image: str, candidate: Path,
                    codex_home: Path, home: Path, temp: Path) -> list[str]:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("remote catalog requires an immutable sha256 image ID")
    return [
        docker, "--config", str(docker_config), "run", "--rm", "--name",
        "feynman-mcp-catalog-" + uuid4().hex[:12],
        "-i", "--network", "none", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--read-only", "--user", "1000:1000",
        "--tmpfs", "/tmp:rw,nosuid,nodev",
        "-v", f"{candidate}:/run/candidate:ro",
        "-v", f"{codex_home}:/run/codex:rw",
        "-v", f"{home}:/run/home:rw",
        "-v", f"{temp}:/run/temp:rw",
        image, "env", "-i",
        "HOME=/run/home", "CODEX_HOME=/run/codex",
        "PATH=/usr/local/bin:/usr/bin:/bin", "TMPDIR=/tmp",
        "codex", "app-server", "--stdio",
    ]


def run(*, docker: str, docker_config: Path, image: str, candidate: Path, output_root: Path,
        output: Path, timeout_seconds: int = 30) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise ValueError("remote catalog output must be new")
    candidate = _directory_without_symlinks(candidate, "remote catalog candidate fixture")
    if not (candidate / "candidate.py").is_file() or (candidate / "candidate.py").is_symlink():
        raise ValueError("remote catalog candidate fixture is invalid")
    if docker_config.is_symlink() or not docker_config.is_dir():
        raise ValueError("remote catalog requires an existing Docker config directory")
    output_root = output_root.absolute()
    if output_root.exists():
        raise ValueError("remote catalog output root must be new")
    output_root.mkdir(parents=True)
    codex_home, home, temp = (output_root / name for name in ("codex-home", "home", "temp"))
    for directory in (codex_home, home, temp):
        directory.mkdir()
    (codex_home / "config.toml").write_text(_config_text(), encoding="utf-8", newline="\n")

    process = subprocess.Popen(
        _docker_command(docker=docker, docker_config=docker_config, image=image, candidate=candidate,
                        codex_home=codex_home, home=home, temp=temp),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
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
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            message = received.get(timeout=max(0.1, deadline - time.monotonic()))
            if isinstance(message, dict) and message.get("id") == identifier:
                return message
        raise queue.Empty

    try:
        initialized = request(1, "initialize", {
            "clientInfo": {"name": "feynman-remote-mcp-catalog-preflight", "version": "0.1.0"},
        })
        if "error" in initialized:
            raise ValueError("remote App Server initialize failed")
        process.stdin.write(_notification("initialized", {}))
        process.stdin.flush()
        status = request(2, "mcpServerStatus/list", {
            "detail": "toolsAndAuthOnly", "limit": 10,
        })
        if "error" in status:
            raise ValueError("remote MCP status request failed")
        catalog = summarize_status(status.get("result"))
        report = {
            "schema_version": 1,
            "verdict": "remote-container-mcp-catalog-visible",
            "model_calls": 0,
            "thread_started": False,
            "turn_started": False,
            "authentication_used": False,
            "auth_status_preserved": False,
            "tool_payloads_preserved": False,
            "network_mode": "none",
            "image": image,
            "adapter_path": ADAPTER_PATH,
            "catalog": catalog,
            "target_tool_visible": any(
                server["target_tool_present"] and
                server["target_tool_has_empty_input_schema"]
                for server in catalog["servers"]
            ),
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
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    try:
        report = run(docker=args.docker, docker_config=args.docker_config, image=args.image,
                     candidate=args.candidate,
                     output_root=args.output_root, output=args.output,
                     timeout_seconds=args.timeout_seconds)
    except (OSError, ValueError, queue.Empty, subprocess.SubprocessError) as exc:
        parser.exit(2, "error: remote MCP catalog preflight failed: " + type(exc).__name__ + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
