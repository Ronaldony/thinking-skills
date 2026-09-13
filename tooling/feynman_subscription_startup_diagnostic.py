#!/usr/bin/env python3
"""Exercise subscription remote startup through thread/start without a turn.

The diagnostic uses the canonical control home and exact transient full-runner
and skill-isolation overrides.  It creates only an ephemeral App Server thread;
it never sends ``turn/start``, a prompt, or a model-generation request.  Reports
contain fixed counters and response shape metadata, never paths, thread IDs,
credentials, config values, stderr, or request/response payloads.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
from typing import Any

try:
    from .feynman_path_mapping import CONTAINER_DESTINATIONS
    from .feynman_remote_exec_environment import validate_files
    from .feynman_rpc_path_proxy import TELEMETRY_OVERRIDE_ENV
    from .feynman_subscription_control_plane_preflight import (
        _failure_category, _notification, _read_json_lines, _request,
        _stop_diagnostic_process,
    )
    from .feynman_subscription_smoke_exec import (
        _directory, _load, _regular, _resolve_executable, _safe_exec_env,
        _validate_control_files, prepare_full_runner_executor_wiring,
    )
except ImportError:
    from feynman_path_mapping import CONTAINER_DESTINATIONS
    from feynman_remote_exec_environment import validate_files
    from feynman_rpc_path_proxy import TELEMETRY_OVERRIDE_ENV
    from feynman_subscription_control_plane_preflight import (
        _failure_category, _notification, _read_json_lines, _request,
        _stop_diagnostic_process,
    )
    from feynman_subscription_smoke_exec import (
        _directory, _load, _regular, _resolve_executable, _safe_exec_env,
        _validate_control_files, prepare_full_runner_executor_wiring,
    )


class StartupDiagnosticError(ValueError):
    """The model-free startup diagnostic failed before producing a report."""


def _thread_start_params(*, model: str) -> dict[str, Any]:
    # TurnEnvironmentParams paths use the selected environment's native
    # syntax.  The canonical candidate destination is fixed by the validated
    # boundary profile and must not be replaced with the Windows host source.
    cwd = CONTAINER_DESTINATIONS["candidate_dir"]
    return {
        "model": model,
        "cwd": cwd,
        "approvalPolicy": "never",
        "sandbox": "workspace-write",
        "ephemeral": True,
        "environments": [{
            "environmentId": "candidate",
            "cwd": cwd,
            "runtimeWorkspaceRoots": [cwd],
        }],
    }


def _thread_error_category(message: Any) -> str:
    text = message.lower() if isinstance(message, str) else ""
    if "cwd" in text or "path" in text or "linux" in text:
        return "remote-path-error"
    if "environment" in text or "exec-server" in text:
        return "remote-environment-error"
    if "mcp" in text:
        return "mcp-startup-error"
    if "model" in text:
        return "model-configuration-error"
    if "auth" in text or "login" in text or "subscription" in text:
        return "authentication-error"
    if "config" in text:
        return "configuration-error"
    return "internal-error"


def _thread_summary(response: dict[str, Any]) -> dict[str, Any]:
    error = response.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        return {
            "thread_started": False,
            "error_code": code if type(code) is int else None,
            "error_category": _thread_error_category(error.get("message")),
            "ephemeral_thread": False,
            "instruction_sources_present": False,
            "response_payload_preserved": False,
        }
    result = response.get("result")
    if not isinstance(result, dict):
        raise StartupDiagnosticError("thread-start-response-shape")
    thread = result.get("thread")
    if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
        raise StartupDiagnosticError("thread-start-response-shape")
    if thread.get("ephemeral") is not True:
        raise StartupDiagnosticError("thread-start-was-not-ephemeral")
    sources = result.get("instructionSources")
    if sources is not None and not isinstance(sources, list):
        raise StartupDiagnosticError("thread-start-response-shape")
    return {
        "thread_started": True,
        "error_code": None,
        "error_category": None,
        "ephemeral_thread": True,
        "instruction_sources_present": bool(sources),
        "response_payload_preserved": False,
    }


def _wait_for_thread_start(received: queue.Queue[dict[str, Any] | None],
                           identifier: int, timeout_seconds: int
                           ) -> tuple[dict[str, Any], dict[str, int]]:
    notifications: Counter[str] = Counter()
    while True:
        try:
            value = received.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise StartupDiagnosticError("thread-start-timeout") from exc
        if value is None:
            raise StartupDiagnosticError("app-server-protocol-error")
        method = value.get("method")
        if isinstance(method, str):
            # Preserve fixed method names and counts only.
            notifications[method] += 1
            if method.startswith("turn/") or method.startswith("item/"):
                raise StartupDiagnosticError("unexpected-turn-or-item-event")
        if value.get("id") == identifier:
            return value, dict(sorted(notifications.items()))


def _safe_proxy_telemetry(path: Path) -> dict[str, Any]:
    value = json.loads(_regular(path, "startup proxy telemetry").read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise StartupDiagnosticError("startup-telemetry-shape")
    allowed = {
        "schema_version", "request_methods", "response_error_codes",
        "requests_seen", "requests_forwarded", "request_mapping_rejections",
        "request_mapping_rejection_methods", "request_mapping_rejection_reasons",
        "malformed_requests", "responses_seen", "responses_forwarded",
        "response_mapping_rejections", "malformed_responses",
        "probe_policy_rejections", "probe_read_limit_applied",
        "probe_response_rejections", "probe_rejected_read_max_bytes",
        "child_exit_code",
    }
    if set(value) - allowed:
        raise StartupDiagnosticError("startup-telemetry-unexpected-fields")
    return value


def run(*, runner_job_path: Path, boundary_profile_path: Path,
        remote_environment_path: Path, binding_path: Path, codex_bin: Path,
        node_bin: Path, adapter: Path, docker_bin: Path, docker_config: Path,
        docker_image_id: str, telemetry_path: Path, output_path: Path,
        timeout_seconds: int = 30) -> dict[str, Any]:
    if type(timeout_seconds) is not int or not 10 <= timeout_seconds <= 120:
        raise ValueError("timeout_seconds must be an integer in 10..120")
    for path, label in ((telemetry_path, "telemetry"), (output_path, "output")):
        if not path.is_absolute() or path.exists() or path.is_symlink():
            raise ValueError(f"startup diagnostic {label} must be a new absolute path")
    runner_job_path = _regular(runner_job_path, "runner job")
    boundary_profile_path = _regular(boundary_profile_path, "boundary profile")
    remote_environment_path = _regular(remote_environment_path, "remote environment")
    binding_path = _regular(binding_path, "full-runner binding")
    codex_bin = _regular(codex_bin, "Codex executable")
    node_bin = _regular(node_bin, "Node executable")
    adapter = _regular(adapter, "full-runner adapter")
    docker_bin = _regular(docker_bin, "Docker executable")
    docker_config = _directory(docker_config, "Docker config directory")
    if validate_files(runner_job_path, boundary_profile_path,
                      remote_environment_path).get("verdict") != "remote-exec-environment-valid":
        raise ValueError("remote environment validation did not pass")
    job = _load(runner_job_path, "runner job")
    paths = job.get("paths")
    versions = job.get("versions")
    if not isinstance(paths, dict) or not isinstance(versions, dict):
        raise ValueError("runner job lacks paths/versions")
    candidate = _directory(Path(paths["candidate_dir"]), "candidate directory")
    model = versions.get("model")
    if not isinstance(model, str) or not model or model.lower().startswith("mock"):
        raise ValueError("runner job has invalid subscription model")
    control_home, _ = _validate_control_files(job, remote_environment_path)
    wiring = prepare_full_runner_executor_wiring(
        codex_bin=str(codex_bin), binding_path=binding_path,
        runner_job_path=runner_job_path, boundary_profile_path=boundary_profile_path,
        job=job, candidate_dir=candidate, node_bin=node_bin, adapter=adapter,
        docker_bin=docker_bin, docker_config=docker_config,
        docker_image_id=docker_image_id, timeout_seconds=timeout_seconds,
    )
    with tempfile.TemporaryDirectory(prefix="feynman-startup-diagnostic-") as temporary:
        temp_dir = Path(temporary).resolve()
        command = [_resolve_executable(str(codex_bin)), "app-server", "--strict-config"]
        for value in wiring["all_config_overrides"]:
            command.extend(("-c", value))
        for value in (
            'web_search="disabled"', "hide_agent_reasoning=true",
            "show_raw_agent_reasoning=false", "check_for_update_on_startup=false",
        ):
            command.extend(("-c", value))
        command.append("--stdio")
        environment = _safe_exec_env(control_home, temp_dir)
        environment[TELEMETRY_OVERRIDE_ENV] = str(telemetry_path)
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, bufsize=0,
        )
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        received: queue.Queue[dict[str, Any] | None] = queue.Queue()
        reader = threading.Thread(
            target=_read_json_lines, args=(process.stdout, received), daemon=True)
        reader.start()
        stderr_text = ""
        forced_shutdown = False
        process_tree_reaped = True
        try:
            process.stdin.write(_request(1, "initialize", {
                "clientInfo": {"name": "feynman-startup-diagnostic", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            }))
            process.stdin.flush()
            initialized, _ = _wait_for_thread_start(received, 1, timeout_seconds)
            if "error" in initialized:
                raise StartupDiagnosticError("app-server-initialize-error")
            process.stdin.write(_notification("initialized", {}))
            process.stdin.write(_request(
                2, "thread/start", _thread_start_params(model=model)))
            process.stdin.flush()
            response, notifications = _wait_for_thread_start(received, 2, timeout_seconds)
            thread = _thread_summary(response)
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                forced_shutdown = True
                process_tree_reaped = _stop_diagnostic_process(process)
            stderr_text = process.stderr.read().decode("utf-8", errors="replace")
            reader.join(timeout=2)
            process.stdout.close()
            process.stderr.close()
        if process.returncode not in {0, None} and not forced_shutdown:
            raise StartupDiagnosticError("app-server-exit-" + _failure_category(stderr_text))
    telemetry = _safe_proxy_telemetry(telemetry_path)
    result = {
        "schema_version": 1,
        "verdict": (
            "subscription-startup-thread-ready" if thread["thread_started"]
            else "subscription-startup-thread-blocked"
        ),
        "model": model,
        "checks": {
            **thread,
            "initialize_completed": True,
            "turn_requests_sent": 0,
            "model_generation_requests_sent": 0,
            "process_tree_reaped": process_tree_reaped,
        },
        "notification_methods": notifications,
        "proxy_telemetry": telemetry,
        "privacy": {
            "request_or_response_payload_preserved": False,
            "thread_id_preserved": False,
            "instruction_source_paths_preserved": False,
            "raw_stderr_preserved": False,
            "credential_files_directly_read_by_probe": False,
            "control_home_contents_serialized": False,
        },
        "scope": (
            "ephemeral App Server thread/start startup diagnostic with no turn/start, "
            "prompt, or model generation"
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-job", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--remote-environment", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--codex-bin", type=Path, required=True)
    parser.add_argument("--node-bin", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--docker-bin", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--docker-image-id", required=True)
    parser.add_argument("--telemetry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    try:
        result = run(
            runner_job_path=args.runner_job,
            boundary_profile_path=args.boundary_profile,
            remote_environment_path=args.remote_environment,
            binding_path=args.binding, codex_bin=args.codex_bin,
            node_bin=args.node_bin, adapter=args.adapter,
            docker_bin=args.docker_bin, docker_config=args.docker_config,
            docker_image_id=args.docker_image_id,
            telemetry_path=args.telemetry, output_path=args.output,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError,
            subprocess.SubprocessError, queue.Empty) as exc:
        parser.exit(2, "error: startup diagnostic failed: " + str(exc) + "\n")
    print(json.dumps({
        "verdict": result["verdict"],
        "thread_started": result["checks"]["thread_started"],
        "error_code": result["checks"]["error_code"],
        "error_category": result["checks"]["error_category"],
        "turn_requests_sent": result["checks"]["turn_requests_sent"],
        "model_generation_requests_sent": result["checks"]["model_generation_requests_sent"],
        "request_mapping_rejection_methods": result["proxy_telemetry"].get(
            "request_mapping_rejection_methods", {}),
        "request_mapping_rejection_reasons": result["proxy_telemetry"].get(
            "request_mapping_rejection_reasons", {}),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
