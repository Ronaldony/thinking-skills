#!/usr/bin/env python3
"""Run the fixed full-runner MCP tools against a disposable Docker fixture.

This is a model-free, opt-in preflight. It creates only a temporary synthetic
candidate, exercises initialize/catalog/read/write/fixed-test, and emits
sanitized booleans and fixed labels. It never uses an evaluation candidate,
ChatGPT auth home, model prompt, or API credential.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "tooling" / "docker" / "codex-remote" / "feynman_full_runner_adapter.mjs"
READ_TOOL = "feynman_read_candidate"
WRITE_TOOL = "feynman_write_candidate"
TEST_TOOL = "feynman_run_tests"
TOOL_NAMES = [READ_TOOL, WRITE_TOOL, TEST_TOOL]
IMAGE_PATTERN = "sha256:"


def _regular(path: Path, label: str) -> Path:
    value = path.expanduser().absolute()
    if value.is_symlink() or not value.is_file():
        raise ValueError(f"{label} must be a regular file")
    return value.resolve(strict=True)


def _directory(path: Path, label: str) -> Path:
    value = path.expanduser().absolute()
    if value.is_symlink() or not value.is_dir():
        raise ValueError(f"{label} must be an existing directory")
    return value.resolve(strict=True)


def _safe_env(docker_config: Path, *, node_bin: Path) -> dict[str, str]:
    keys = ("PATH", "SystemRoot", "WINDIR", "ComSpec", "PATHEXT", "TEMP", "TMP")
    result = {key: os.environ[key] for key in keys if os.environ.get(key)}
    result["PATH"] = str(node_bin.parent) + os.pathsep + result.get("PATH", "")
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        result.pop(key, None)
    return result


def _request(identifier: int, method: str, params: dict[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "id": identifier,
                        "method": method, "params": params}) + "\n").encode()


def _notification(method: str, params: dict[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n").encode()


def _reader(stream, received: queue.Queue[dict[str, Any] | None]) -> None:
    try:
        for line in stream:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                received.put(None)
                continue
            if isinstance(value, dict):
                received.put(value)
    except OSError:
        received.put(None)


def _run(*, node_bin: Path, docker_bin: Path, docker_config: Path,
         docker_image_id: str, output: Path) -> dict[str, Any]:
    node_bin = _regular(node_bin, "Node executable")
    docker_bin = _regular(docker_bin, "Docker executable")
    docker_config = _directory(docker_config, "Docker config directory")
    adapter = _regular(ADAPTER, "full-runner adapter")
    if not docker_image_id.startswith(IMAGE_PATTERN) or len(docker_image_id) != 71:
        raise ValueError("Docker image ID must be a sha256 digest")
    if output.exists() or output.is_symlink():
        raise ValueError("preflight output must be new")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="feynman-full-runner-docker-") as raw:
        root = Path(raw)
        candidate = root / "candidate"
        candidate.mkdir()
        (candidate / "candidate.py").write_text("value = 1\n", encoding="utf-8")
        (candidate / "test_candidate.py").write_text(
            "import runpy\nassert runpy.run_path('/run/candidate/candidate.py')['value'] == 2\n",
            encoding="utf-8",
        )
        environment = _safe_env(docker_config, node_bin=node_bin)
        environment.update({
            "FEYNMAN_FULL_RUNNER_ROOT": str(candidate),
            "FEYNMAN_FULL_RUNNER_DOCKER": str(docker_bin),
            "FEYNMAN_FULL_RUNNER_DOCKER_CONFIG": str(docker_config),
            "FEYNMAN_FULL_RUNNER_IMAGE": docker_image_id,
        })
        process = subprocess.Popen(
            [str(node_bin), str(adapter)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=environment, bufsize=0,
        )
        assert process.stdin is not None and process.stdout is not None
        received: queue.Queue[dict[str, Any] | None] = queue.Queue()
        thread = threading.Thread(target=_reader, args=(process.stdout, received), daemon=True)
        thread.start()

        def request(identifier: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
            process.stdin.write(_request(identifier, method, params))
            process.stdin.flush()
            while True:
                value = received.get(timeout=75)
                if value is None:
                    raise ValueError("full-runner adapter emitted invalid JSON")
                if value.get("id") == identifier:
                    return value

        try:
            initialized = request(1, "initialize", {})
            process.stdin.write(_notification("notifications/initialized", {}))
            process.stdin.flush()
            catalog = request(2, "tools/list", {})
            initial_read = request(3, "tools/call", {
                "name": READ_TOOL, "arguments": {},
            })
            write_result = request(4, "tools/call", {
                "name": WRITE_TOOL, "arguments": {"content": "value = 2\n"},
            })
            test_result = request(5, "tools/call", {
                "name": TEST_TOOL, "arguments": {},
            })
            final_read = request(6, "tools/call", {
                "name": READ_TOOL, "arguments": {},
            })
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
            thread.join(timeout=2)

        if process.returncode != 0:
            raise ValueError("full-runner adapter did not exit cleanly")
        tools = catalog.get("result", {}).get("tools", [])
        catalog_names = [item.get("name") for item in tools if isinstance(item, dict)]
        write_payload = write_result.get("result", {}).get("content", [{}])[0]
        test_payload = test_result.get("result", {}).get("content", [{}])[0]
        initial_payload = initial_read.get("result", {}).get("content", [{}])[0]
        final_payload = final_read.get("result", {}).get("content", [{}])[0]
        initial_data = json.loads(initial_payload.get("text", "{}"))
        write_data = json.loads(write_payload.get("text", "{}"))
        test_data = json.loads(test_payload.get("text", "{}"))
        final_data = json.loads(final_payload.get("text", "{}"))
        checks = {
            "initialize_ok": "result" in initialized and "error" not in initialized,
            "exact_tool_catalog": catalog_names == TOOL_NAMES,
            "fixed_read_observed": initial_data.get("file") == "candidate.py" and initial_data.get("bytesRead") > 0,
            "fixed_write_observed": write_data == {
                "file": "candidate.py", "bytesWritten": len("value = 2\n".encode()),
                "verdict": "candidate-written",
            },
            "fixed_test_passed": test_data.get("file") == "test_candidate.py" and
                                  test_data.get("networkMode") == "none" and
                                  test_data.get("passed") is True and
                                  test_result.get("result", {}).get("isError") is False,
            "write_visible_to_followup_read": final_data.get("file") == "candidate.py" and
                                               "value = 2" in final_data.get("source", ""),
        }
        if not all(checks.values()):
            raise ValueError("full-runner Docker protocol checks did not pass")
        result = {
            "schema_version": 1,
            "verdict": "full-runner-mcp-docker-preflight-passed",
            "model_calls": 0,
            "authentication_used": False,
            "checks": checks,
            "fixed_policy": {
                "tool_names": TOOL_NAMES,
                "candidate_file": "candidate.py",
                "test_file": "test_candidate.py",
                "test_command": ["python3", "-B", "-I", "/run/candidate/test_candidate.py"],
                "network_mode": "none",
                "read_only_root": True,
                "candidate_mount_access": "ro",
                "write_target": "candidate.py",
            },
            "privacy": {
                "model_request_started": False,
                "credential_files_read": False,
                "raw_tool_payloads_preserved": False,
                "candidate_fixture_discarded": True,
            },
            "scope": "model-free disposable Docker MCP adapter contract; not evaluation evidence",
        }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-bin", type=Path, required=True)
    parser.add_argument("--docker-bin", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--docker-image-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = _run(
            node_bin=args.node_bin, docker_bin=args.docker_bin,
            docker_config=args.docker_config, docker_image_id=args.docker_image_id,
            output=args.output,
        )
    except (OSError, ValueError, json.JSONDecodeError, queue.Empty, subprocess.SubprocessError) as exc:
        parser.exit(2, "error: full-runner Docker preflight failed: " + type(exc).__name__ + "\n")
    print(json.dumps({"verdict": result["verdict"], "model_calls": result["model_calls"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
