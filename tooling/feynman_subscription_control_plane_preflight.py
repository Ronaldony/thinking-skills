#!/usr/bin/env python3
"""Verify the Codex control-plane remote-environment handoff without a model.

The probe starts ``codex app-server`` with the canonical protected control
home and the exact transient full-runner/skill overrides used by the
subscription executor.  It sends only ``initialize`` and the documented
experimental ``environment/info`` request.  It never starts a thread or turn,
submits a model prompt, invokes an MCP tool, or serializes auth/config/prompt
payloads.  Subprocess stderr is inspected only in memory to assign a fixed
failure category and is never written to a report.
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
    from .feynman_subscription_smoke_exec import _resolve_executable, _safe_exec_env
    from .feynman_rpc_path_proxy import TELEMETRY_OVERRIDE_ENV
except ImportError:
    from feynman_subscription_smoke_exec import _resolve_executable, _safe_exec_env
    from feynman_rpc_path_proxy import TELEMETRY_OVERRIDE_ENV


class ControlPlaneError(ValueError):
    """A model-free control-plane check failed with a safe fixed category."""


def _request(identifier: int, method: str, params: dict[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "id": identifier,
                        "method": method, "params": params}, separators=(",", ":"))
            + "\n").encode("utf-8")


def _notification(method: str, params: dict[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "method": method, "params": params},
                       separators=(",", ":")) + "\n").encode("utf-8")


def _read_json_lines(stream: Any, received: queue.Queue[dict[str, Any] | None]) -> None:
    try:
        for line in stream:
            try:
                value = json.loads(line)
            except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
                received.put(None)
                continue
            received.put(value if isinstance(value, dict) else None)
    except OSError:
        received.put(None)


def _failure_category(stderr: str) -> str:
    """Map private stderr to a small public category without retaining text."""
    text = stderr.lower()
    if "environments.toml" in text or "exec-server" in text or "environment" in text:
        return "remote-environment-error"
    if "mcp" in text:
        return "mcp-startup-error"
    if "config" in text or "unknown field" in text:
        return "configuration-error"
    if "auth" in text or "login" in text or "subscription" in text:
        return "authentication-error"
    if "docker" in text or "container" in text:
        return "docker-launch-error"
    return "unclassified"


def _wait_response(received: queue.Queue[dict[str, Any] | None], identifier: int,
                   timeout_seconds: int) -> dict[str, Any]:
    while True:
        try:
            value = received.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise ControlPlaneError("control-plane-timeout") from exc
        if value is None:
            raise ControlPlaneError("control-plane-protocol-error")
        if value.get("id") == identifier:
            return value


def _environment_summary(response: dict[str, Any]) -> dict[str, bool]:
    if "error" in response:
        raise ControlPlaneError("remote-environment-request-error")
    result = response.get("result")
    if not isinstance(result, dict):
        raise ControlPlaneError("remote-environment-protocol-error")
    shell = result.get("shell")
    if not isinstance(shell, dict) or not isinstance(shell.get("name"), str):
        raise ControlPlaneError("remote-environment-protocol-error")
    return {
        "remote_environment_connected": True,
        "shell_metadata_present": True,
        "default_cwd_present": isinstance(result.get("cwd"), str),
        "response_payload_preserved": False,
    }


def _stop_diagnostic_process(process: subprocess.Popen[bytes]) -> bool:
    """Stop only the App Server process tree created by this probe.

    On Windows the ``.cmd`` launcher can outlive a normal terminate request
    while its child App Server waits for remote-environment teardown.  Kill
    this known child tree after the bounded grace period; it cannot target an
    unrelated PID because the PID comes directly from ``Popen`` above.
    """
    if process.poll() is not None:
        return True
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False)
    else:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        # The termination request has been issued to the exact Popen process
        # tree.  Do not let a launcher that refuses to reap its child prevent
        # a completed, model-free diagnostic from emitting its safe report.
        return False
    return True


def run(*, codex_bin: str, control_home: Path, temp_dir: Path,
        proxy_telemetry: Path, config_overrides: Sequence[str], timeout_seconds: int = 30) -> dict[str, Any]:
    """Connect App Server to the selected remote environment without a turn."""
    if type(timeout_seconds) is not int or not 5 <= timeout_seconds <= 120:
        raise ValueError("timeout_seconds must be an integer in 5..120")
    if control_home.is_symlink() or not control_home.is_dir():
        raise ValueError("control CODEX_HOME must be an existing non-symlink directory")
    if temp_dir.is_symlink() or not temp_dir.is_dir():
        raise ValueError("control-plane temp directory must be an existing non-symlink directory")
    if (not proxy_telemetry.is_absolute() or proxy_telemetry.is_symlink()
            or proxy_telemetry.exists()):
        raise ValueError("control-plane proxy telemetry must be a new absolute non-symlink path")
    if any("API_KEY" in value or "ACCESS_TOKEN" in value for value in config_overrides):
        raise ValueError("control-plane overrides contain a retired credential name")

    command = [_resolve_executable(codex_bin), "app-server"]
    for value in config_overrides:
        command.extend(("-c", value))
    command.append("--stdio")
    environment = _safe_exec_env(control_home.resolve(), temp_dir.resolve())
    environment[TELEMETRY_OVERRIDE_ENV] = str(proxy_telemetry)
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, bufsize=0,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    received: queue.Queue[dict[str, Any] | None] = queue.Queue()
    reader = threading.Thread(target=_read_json_lines, args=(process.stdout, received), daemon=True)
    reader.start()
    stderr_text = ""
    forced_shutdown = False
    process_tree_reaped = True
    try:
        process.stdin.write(_request(1, "initialize", {
            "clientInfo": {"name": "feynman-control-plane-preflight", "version": "0.1.0"},
            "capabilities": {"experimentalApi": True},
        }))
        process.stdin.flush()
        initialized = _wait_response(received, 1, timeout_seconds)
        if "error" in initialized:
            raise ControlPlaneError("app-server-initialize-error")
        process.stdin.write(_notification("initialized", {}))
        process.stdin.write(_request(2, "environment/info", {"environmentId": "candidate"}))
        process.stdin.flush()
        environment = _environment_summary(_wait_response(received, 2, timeout_seconds))
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # App Server may keep its stdio loop alive while its just-opened
            # remote environment finishes teardown.  The successful response
            # above is the contract under test; terminate only our ephemeral
            # diagnostic process and record that bounded shutdown behavior.
            forced_shutdown = True
            process_tree_reaped = _stop_diagnostic_process(process)
        reader.join(timeout=2)
        try:
            if process_tree_reaped:
                stderr_text = process.stderr.read().decode("utf-8", errors="replace")
        finally:
            if process_tree_reaped:
                process.stdout.close()
                process.stderr.close()
    if process.returncode != 0 and not forced_shutdown:
        raise ControlPlaneError("app-server-exit-" + _failure_category(stderr_text))
    if not proxy_telemetry.is_file() or proxy_telemetry.is_symlink():
        raise ControlPlaneError("remote-environment-telemetry-missing")
    return {
        "schema_version": 1,
        "verdict": "subscription-control-plane-ready",
        "checks": {
            "app_server_initialized": True,
            "app_server_graceful_shutdown": not forced_shutdown,
            "app_server_process_tree_reaped": process_tree_reaped,
            **environment,
            "model_requests": 0,
            "threads_started": 0,
            "turns_started": 0,
            "mcp_tools_invoked": 0,
            "diagnostic_proxy_telemetry_written": proxy_telemetry.is_file(),
        },
        "privacy": {
            "raw_stderr_preserved": False,
            "stderr_inspected_in_memory_only": bool(stderr_text),
            "credential_files_directly_read_by_probe": False,
            "control_home_contents_serialized": False,
            "config_payload_preserved": False,
        },
        "scope": (
            "model-free App Server environment/info check using the canonical control "
            "CODEX_HOME and transient executor overrides"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument("--control-home", type=Path, required=True)
    parser.add_argument("--temp-dir", type=Path, required=True)
    parser.add_argument("--proxy-telemetry", type=Path, required=True)
    parser.add_argument("--override", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.exit(2, "error: control-plane preflight output must be new\n")
    try:
        result = run(codex_bin=args.codex_bin, control_home=args.control_home,
                     temp_dir=args.temp_dir, proxy_telemetry=args.proxy_telemetry,
                     config_overrides=args.override,
                     timeout_seconds=args.timeout_seconds)
    except (ControlPlaneError, OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, "error: control-plane preflight failed: " + str(exc) + "\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "verdict": result["verdict"],
        "remote_environment_connected": result["checks"]["remote_environment_connected"],
        "model_requests": result["checks"]["model_requests"],
        "threads_started": result["checks"]["threads_started"],
        "turns_started": result["checks"]["turns_started"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
