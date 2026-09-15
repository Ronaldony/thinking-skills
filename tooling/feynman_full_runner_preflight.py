#!/usr/bin/env python3
"""Verify the fixed full-runner MCP catalog without a model turn.

This preflight builds the three-tool contract, starts Codex App Server only to
inspect the transient MCP catalog, and records sanitized schema facts. It does
not authenticate, start a thread, launch a model, or run the candidate tests.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .feynman_full_runner_contract import (
        READ_TOOL_NAME, TEST_TOOL_NAME, TOOL_NAMES, WRITE_TOOL_NAME,
        build_full_runner_override, contract_document,
    )
    from .feynman_mcp_catalog_preflight import run as verify_catalog
except ImportError:
    from feynman_full_runner_contract import (
        READ_TOOL_NAME, TEST_TOOL_NAME, TOOL_NAMES, WRITE_TOOL_NAME,
        build_full_runner_override, contract_document,
    )
    from feynman_mcp_catalog_preflight import run as verify_catalog


def _expected_schema(name: str) -> dict[str, Any]:
    if name == WRITE_TOOL_NAME:
        return {
            "present": True,
            "type": "object",
            "additional_properties": False,
            "property_names": ["content"],
            "required_names": ["content"],
            "content_type": "string",
            "content_max_length": 131072,
        }
    return {
        "present": True,
        "type": "object",
        "additional_properties": False,
        "property_names": [],
        "required_names": None,
        "content_type": None,
        "content_max_length": None,
    }


def _catalog_ready(report: dict[str, Any], lineage: dict[str, object]) -> bool:
    catalog = report.get("catalog")
    configuration = report.get("configuration")
    if not isinstance(catalog, dict):
        return False
    servers = catalog.get("servers")
    if report.get("verdict") != "bounded-mcp-catalog-visible" or report.get("model_calls") != 0:
        return False
    if (report.get("authentication_used") is not False
            or catalog.get("server_count") != 1
            or not isinstance(configuration, dict)
            or configuration.get("transport") != "cli-overrides"
            or configuration.get("user_config_file_required") is not False
            or configuration.get("override_lineage") != lineage):
        return False
    if not isinstance(servers, list) or len(servers) != 1 or not isinstance(servers[0], dict):
        return False
    server = servers[0]
    return (
        server.get("name") == lineage.get("server_name")
        and server.get("tool_names") == sorted(TOOL_NAMES)
        and server.get("tools_error_present") is False
        and server.get("target_tool_present") is True
        and server.get("target_tool_schemas") == {
            name: _expected_schema(name) for name in TOOL_NAMES
        }
    )


def run(*, codex_bin: str, codex_home: Path, output: Path, node_bin: Path,
        adapter: Path, candidate: Path, docker_bin: Path, docker_config: Path,
        docker_image_id: str, timeout_seconds: int = 30) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise ValueError("full-runner preflight output must be new")
    override = build_full_runner_override(
        node_bin=node_bin, adapter=adapter, candidate=candidate,
        docker_bin=docker_bin, docker_config=docker_config,
        docker_image_id=docker_image_id,
    )
    catalog_home = codex_home.absolute()
    if not catalog_home.is_dir() or catalog_home.is_symlink():
        raise ValueError("full-runner catalog preflight requires an existing isolated CODEX_HOME")
    if any(catalog_home.iterdir()):
        raise ValueError("full-runner catalog preflight requires an empty CODEX_HOME")
    catalog = verify_catalog(
        codex_bin=codex_bin,
        codex_home=catalog_home,
        output=output.with_name(output.stem + "-catalog.json"),
        timeout_seconds=min(timeout_seconds, 30),
        config_overrides=override.values,
        override_lineage=override.sanitized_lineage(),
        target_tool=READ_TOOL_NAME,
        target_tools=TOOL_NAMES,
    )
    if not _catalog_ready(catalog, override.sanitized_lineage()):
        raise ValueError("full-runner MCP catalog did not match the fixed contract")
    result = {
        **contract_document(override.sanitized_lineage()),
        "model_calls": 0,
        "authentication_used": False,
        "catalog": {
            "verdict": catalog["verdict"],
            "server_count": catalog["catalog"]["server_count"],
            "server_name": catalog["catalog"]["servers"][0]["name"],
            "tool_names": catalog["catalog"]["servers"][0]["tool_names"],
            "target_tool_schemas": catalog["catalog"]["servers"][0]["target_tool_schemas"],
        },
        "lineage": override.sanitized_lineage(),
        "privacy": {
            "model_request_started": False,
            "credential_files_read": False,
            "tool_payloads_preserved": False,
        },
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node-bin", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--docker-bin", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--docker-image-id", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    try:
        result = run(
            codex_bin=args.codex_bin, codex_home=args.codex_home, output=args.output,
            node_bin=args.node_bin, adapter=args.adapter, candidate=args.candidate,
            docker_bin=args.docker_bin, docker_config=args.docker_config,
            docker_image_id=args.docker_image_id, timeout_seconds=args.timeout_seconds,
        )
    except (OSError, ValueError, json.JSONDecodeError, TimeoutError) as exc:
        parser.exit(2, "error: full-runner MCP preflight failed: " + type(exc).__name__ + "\n")
    print(json.dumps({"verdict": result["verdict"], "model_calls": result["model_calls"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
