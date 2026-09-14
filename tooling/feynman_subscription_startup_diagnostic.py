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
from pathlib import PurePosixPath
import queue
import re
import subprocess
import tempfile
import threading
import time
from typing import Any

try:
    from .feynman_subscription_checkpoint import (
        from_run_inputs, load as load_checkpoint, validate as validate_checkpoint,
    )
    from .feynman_remote_exec_environment import validate_files
    from .feynman_rpc_path_proxy import (
        SAFE_REJECTION_FIELDS, SAFE_REJECTION_METHODS, SAFE_TELEMETRY_METHODS,
        SAFE_TELEMETRY_REASONS, TELEMETRY_OVERRIDE_ENV,
    )
    from .feynman_subscription_control_plane_preflight import (
        _failure_category, _notification, _read_json_lines, _request,
        _stop_diagnostic_process,
    )
    from .feynman_subscription_smoke_exec import (
        _directory, _load, _regular, _resolve_executable, _safe_exec_env,
        _validate_control_files, prepare_full_runner_executor_wiring,
    )
except ImportError:
    from feynman_subscription_checkpoint import (
        from_run_inputs, load as load_checkpoint, validate as validate_checkpoint,
    )
    from feynman_remote_exec_environment import validate_files
    from feynman_rpc_path_proxy import (
        SAFE_REJECTION_FIELDS, SAFE_REJECTION_METHODS, SAFE_TELEMETRY_METHODS,
        SAFE_TELEMETRY_REASONS, TELEMETRY_OVERRIDE_ENV,
    )
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

    def __init__(self, stage: str, *, initialize_completed: bool = False) -> None:
        super().__init__(stage)
        self.initialize_completed = initialize_completed


def _write_failure_artifact(path: Path, stage: str, *, initialize_completed: bool = False) -> None:
    """Persist a payload-free blocked record when the diagnostic itself fails."""
    if not path.is_absolute() or path.exists() or path.is_symlink():
        return
    if not isinstance(stage, str) or not stage or any(
        char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in stage
    ):
        stage = "diagnostic-failure"
    result = {
        "schema_version": 3,
        "verdict": "subscription-startup-thread-blocked",
        "failure_stage": stage,
        "model": "unknown",
        "checks": {
            "thread_started": False,
            "error_code": None,
            "error_category": "internal-error",
            "error_signals": _thread_error_signals(None),
            "error_data_kind": "none",
            "ephemeral_thread": False,
            "instruction_sources_present": False,
            "instruction_sources_allowed": False,
            "response_payload_preserved": False,
            "initialize_completed": initialize_completed,
            "turn_requests_sent": 0,
            "model_generation_requests_sent": 0,
            "process_tree_reaped": False,
            "cleanup_verified": False,
            "proxy_telemetry_complete": False,
            "proxy_request_response_correlated": False,
            "request_mapping_clean": False,
        },
        "notification_methods": {},
        "proxy_telemetry_status": "missing",
        "proxy_telemetry": None,
        "privacy": {
            "request_or_response_payload_preserved": False,
            "thread_id_preserved": False,
            "instruction_source_paths_preserved": False,
            "raw_stderr_preserved": False,
            "credential_files_directly_read_by_probe": False,
            "control_home_contents_serialized": False,
        },
        "scope": "startup diagnostic failed before a complete evidence record was available",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _consume_private_stderr(stream: Any, sink: list[bytes], *, limit: int = 262144) -> None:
    """Drain stderr without persisting it; retain only a bounded in-memory sample."""
    captured = 0
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            if captured < limit:
                selected = chunk[:limit - captured]
                sink.append(selected)
                captured += len(selected)
    except (OSError, ValueError):
        return


_SAFE_NOTIFICATION_METHODS = frozenset({
    "configWarning",
    "environment/connection",
    "environment/connection/updated",
    "error",
    "thread/closed",
    "thread/environment/connected",
    "thread/environment/disconnected",
    "thread/started",
    "thread/status/changed",
    "warning",
})

_ALLOWED_INSTRUCTION_SOURCE_ROOTS = (
    PurePosixPath("/run/candidate"),
    PurePosixPath("/run/codex"),
)

# The startup probe must exercise the configured remote environment, not the
# repository that happens to launch the probe.  These are Codex config keys
# (not thread/start fields) and are intentionally scoped to this probe's
# transient App Server process.  The actual smoke executor keeps its own
# candidate cwd and --skip-git-repo-check contract unchanged.
APP_SERVER_LOCAL_ISOLATION_OVERRIDES = (
    "project_root_markers=[]",
    "project_doc_max_bytes=0",
)

_ERROR_SIGNAL_TERMS = {
    "mentions_environment": ("environment",),
    "mentions_exec_server": ("exec-server", "exec server"),
    "mentions_connection": ("connect", "connection"),
    "mentions_initialize": ("initialize", "initialization"),
    "mentions_exit": ("exit", "exited"),
    "mentions_closed": ("closed", "closure"),
    "mentions_timeout": ("timeout", "timed out"),
    "mentions_config": ("config", "configuration"),
    "mentions_path": ("path", "cwd", "linux"),
    "mentions_not_found": ("not found", "missing"),
}


def _thread_start_params(*, model: str) -> dict[str, Any]:
    # The canonical remote environment document declares candidate as its
    # default and owns the environment-native cwd.  Omitting the optional
    # thread/start cwd prevents App Server's local discovery cwd from being
    # reintroduced into environmentConfig/read.  Do not manufacture the
    # unsupported environments/runtimeWorkspaceRoots fields here.
    return {
        "model": model,
        "approvalPolicy": "never",
        "sandbox": "workspace-write",
        "ephemeral": True,
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


def _thread_error_signals(message: Any) -> dict[str, bool]:
    """Reduce an error message to fixed booleans without retaining its text."""
    text = message.lower() if isinstance(message, str) else ""
    return {
        label: any(term in text for term in terms)
        for label, terms in _ERROR_SIGNAL_TERMS.items()
    }


def _json_value_kind(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "other"


def _instruction_source_path(source: str) -> PurePosixPath | None:
    if source.startswith("file:///"):
        value = source[7:]
    elif source.startswith("/"):
        value = source
    else:
        return None
    if not value or "\\" in value or "?" in value or "#" in value:
        return None
    path = PurePosixPath(value)
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        return None
    return path


def _instruction_sources_allowed(sources: list[str]) -> bool:
    """Allow only absolute instruction paths under declared remote mounts."""
    for source in sources:
        path = _instruction_source_path(source)
        if path is None or not any(
                path == root or root in path.parents
                for root in _ALLOWED_INSTRUCTION_SOURCE_ROOTS):
            return False
    return True


def _thread_summary(response: dict[str, Any]) -> dict[str, Any]:
    error = response.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        return {
            "thread_started": False,
            "error_code": code if type(code) is int else None,
            "error_category": _thread_error_category(error.get("message")),
            "error_signals": _thread_error_signals(error.get("message")),
            "error_data_kind": _json_value_kind(error.get("data")),
            "ephemeral_thread": False,
            "instruction_sources_present": False,
            "instruction_sources_allowed": False,
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
    if not isinstance(sources, list) or any(not isinstance(source, str) for source in sources):
        raise StartupDiagnosticError("thread-start-response-shape")
    if not _instruction_sources_allowed(sources):
        raise StartupDiagnosticError("instruction-source-not-allowed")
    return {
        "thread_started": True,
        "error_code": None,
        "error_category": None,
        "error_signals": _thread_error_signals(None),
        "error_data_kind": "none",
        "ephemeral_thread": True,
        "instruction_sources_present": bool(sources),
        "instruction_sources_allowed": True,
        "response_payload_preserved": False,
    }


def _wait_for_thread_start(received: queue.Queue[dict[str, Any] | None],
                           identifier: int, timeout_seconds: float,
                           *, timeout_stage: str = "thread-start-timeout"
                           ) -> tuple[dict[str, Any], dict[str, int]]:
    notifications: Counter[str] = Counter()
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            value = received.get(timeout=remaining)
        except queue.Empty as exc:
            raise StartupDiagnosticError(timeout_stage) from exc
        if value is None:
            raise StartupDiagnosticError("app-server-protocol-error")
        method = value.get("method")
        if isinstance(method, str):
            # Preserve only bounded method names and counts.  A peer-provided
            # arbitrary method string must not become durable diagnostic data.
            method_key = method if method in _SAFE_NOTIFICATION_METHODS else "unknown"
            notifications[method_key] += 1
            if method.startswith("turn/") or method.startswith("item/"):
                raise StartupDiagnosticError("unexpected-turn-or-item-event")
        if value.get("id") == identifier:
            return value, dict(sorted(notifications.items()))


def _safe_proxy_telemetry(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.exists():
        raise StartupDiagnosticError("startup-proxy-telemetry-missing")
    try:
        value = json.loads(_regular(path, "startup proxy telemetry").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StartupDiagnosticError("startup-proxy-telemetry-unreadable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 3:
        raise StartupDiagnosticError("startup-telemetry-shape")
    allowed = {
        "schema_version", "request_methods", "response_error_codes",
        "requests_seen", "requests_forwarded", "request_mapping_rejections",
        "request_mapping_rejection_methods", "request_mapping_rejection_reasons",
        "request_mapping_rejection_method_reasons",
        "request_mapping_rejection_method_reason_fields",
        "malformed_requests", "responses_seen", "responses_forwarded",
        "response_mapping_rejections", "malformed_responses",
        "probe_policy_rejections", "probe_read_limit_applied",
        "probe_response_rejections", "probe_rejected_read_max_bytes",
        "child_exit_code", "request_write_failures", "request_id_duplicates",
        "responses_matched", "responses_unmatched", "notifications_seen",
        "pending_request_ids",
    }
    if set(value) != allowed:
        raise StartupDiagnosticError("startup-telemetry-unexpected-fields")
    for key in (
        "request_methods", "response_error_codes",
        "request_mapping_rejection_methods", "request_mapping_rejection_reasons",
    ):
        counter = value.get(key)
        if not isinstance(counter, dict) or any(
            not isinstance(item, str) or type(count) is not int or count < 0
            for item, count in counter.items()
        ):
            raise StartupDiagnosticError("startup-telemetry-counter-shape")
    if any(not re.fullmatch(r"-?[0-9]{1,9}", item)
           for item in value["response_error_codes"]):
        raise StartupDiagnosticError("startup-telemetry-error-code-shape")
    if not set(value["request_methods"]).issubset(SAFE_TELEMETRY_METHODS):
        raise StartupDiagnosticError("startup-telemetry-method-not-allowed")
    if not set(value["request_mapping_rejection_methods"]).issubset(SAFE_REJECTION_METHODS):
        raise StartupDiagnosticError("startup-telemetry-method-not-allowed")
    if not set(value["request_mapping_rejection_reasons"]).issubset(SAFE_TELEMETRY_REASONS):
        raise StartupDiagnosticError("startup-telemetry-reason-not-allowed")
    for method, reasons in value["request_mapping_rejection_method_reasons"].items():
        if method not in SAFE_REJECTION_METHODS or not isinstance(reasons, dict) or any(
            not isinstance(reason, str) or type(count) is not int or count < 0
            for reason, count in reasons.items()
        ):
            raise StartupDiagnosticError("startup-telemetry-counter-shape")
        if not set(reasons).issubset(SAFE_TELEMETRY_REASONS):
            raise StartupDiagnosticError("startup-telemetry-reason-not-allowed")
    for method, reasons in value["request_mapping_rejection_method_reason_fields"].items():
        if method not in SAFE_REJECTION_METHODS or not isinstance(reasons, dict):
            raise StartupDiagnosticError("startup-telemetry-counter-shape")
        for reason, fields in reasons.items():
            if (not isinstance(reason, str) or not isinstance(fields, dict)
                    or any(not isinstance(field, str) or type(count) is not int or count < 0
                           for field, count in fields.items())):
                raise StartupDiagnosticError("startup-telemetry-counter-shape")
            if reason not in SAFE_TELEMETRY_REASONS or not set(fields).issubset(SAFE_REJECTION_FIELDS):
                raise StartupDiagnosticError("startup-telemetry-field-not-allowed")
    count_fields = {
        key for key in allowed if key not in {
            "schema_version", "request_methods", "response_error_codes",
            "request_mapping_rejection_methods", "request_mapping_rejection_reasons",
            "request_mapping_rejection_method_reasons",
            "request_mapping_rejection_method_reason_fields", "child_exit_code",
        }
    }
    for key in count_fields:
        if type(value.get(key)) is not int or value[key] < 0:
            raise StartupDiagnosticError("startup-telemetry-count-shape")
    if value.get("child_exit_code") is not None and type(value["child_exit_code"]) is not int:
        raise StartupDiagnosticError("startup-telemetry-count-shape")
    return value


def _wait_for_proxy_telemetry_exit(path: Path, *, deadline: float) -> bool:
    """Wait for the proxy's final child-exit snapshot within cleanup budget.

    App Server owns the proxy process, so closing App Server stdin does not
    guarantee that its descendant has written the final telemetry snapshot
    before the parent exits.  Poll only the already-declared, payload-free
    telemetry file; never wait beyond the caller's cleanup deadline.
    """
    while True:
        try:
            value = _safe_proxy_telemetry(path)
        except StartupDiagnosticError:
            value = None
        if value is not None and value["child_exit_code"] is not None:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))


def _proxy_telemetry_ready(value: dict[str, Any]) -> bool:
    """Require complete request/response accounting before declaring ready."""
    response_records = (
        value["responses_seen"] - value["notifications_seen"]
        - value["malformed_responses"]
    )
    return (
        value["requests_seen"] > 0
        and value["responses_seen"] > 0
        and response_records >= 0
        and value["malformed_responses"] == 0
        and value["requests_seen"] == value["requests_forwarded"]
        and value["responses_seen"] == value["responses_forwarded"]
        and value["responses_matched"] + value["responses_unmatched"] == response_records
        and value["responses_unmatched"] == 0
        and value["pending_request_ids"] == 0
        and value["request_write_failures"] == 0
        and value["request_id_duplicates"] == 0
        and value["request_mapping_rejections"] == 0
        and value["response_mapping_rejections"] == 0
        and value["child_exit_code"] == 0
    )


def run(*, runner_job_path: Path, boundary_profile_path: Path,
        remote_environment_path: Path, binding_path: Path, codex_bin: Path,
        node_bin: Path, adapter: Path, docker_bin: Path, docker_config: Path,
        docker_image_id: str, telemetry_path: Path, output_path: Path,
        timeout_seconds: int = 30) -> dict[str, Any]:
    if type(timeout_seconds) is not int or not 10 <= timeout_seconds <= 120:
        raise ValueError("timeout_seconds must be an integer in 10..120")
    # A startup diagnostic has one bounded budget.  The public argument keeps
    # its historical range for callers, but no startup attempt may use more
    # than the planned 60-second preparation/handshake window.
    startup_timeout = min(timeout_seconds, 60)
    startup_deadline = time.monotonic() + startup_timeout
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
    # Direct Python callers must pass through the same immutable checkpoint
    # contract as the CLI.  This runs before validate_files or Popen and keeps
    # evaluator ownership, binding identity, canonical control-home paths, and
    # new output paths consistent across both entry points.
    checkpoint = from_run_inputs(
        runner_job_path=runner_job_path,
        boundary_profile_path=boundary_profile_path,
        remote_environment_path=remote_environment_path,
        binding_path=binding_path,
        codex_bin=codex_bin,
        node_bin=node_bin,
        adapter=adapter,
        docker_bin=docker_bin,
        docker_config=docker_config,
        docker_image_id=docker_image_id,
        telemetry_path=telemetry_path,
        output_path=output_path,
    )
    try:
        validate_checkpoint(checkpoint)
    except ValueError as exc:
        raise StartupDiagnosticError("startup-input-validation-failed") from exc
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
    try:
        wiring_remaining = startup_deadline - time.monotonic()
        if wiring_remaining <= 0:
            raise StartupDiagnosticError("startup-timeout")
        wiring = prepare_full_runner_executor_wiring(
            codex_bin=str(codex_bin), binding_path=binding_path,
            runner_job_path=runner_job_path, boundary_profile_path=boundary_profile_path,
            job=job, candidate_dir=candidate, node_bin=node_bin, adapter=adapter,
            docker_bin=docker_bin, docker_config=docker_config,
            docker_image_id=docker_image_id,
            timeout_seconds=max(1, min(startup_timeout, int(wiring_remaining))),
        )
    except ValueError as exc:
        # Keep the underlying validation text private while identifying the
        # bounded pre-start stage that rejected the wiring inputs.
        raise StartupDiagnosticError("startup-wiring-input-invalid") from exc
    with tempfile.TemporaryDirectory(prefix="feynman-startup-diagnostic-") as temporary:
        temp_dir = Path(temporary).resolve()
        command = [_resolve_executable(str(codex_bin)), "app-server", "--strict-config"]
        for value in wiring["all_config_overrides"]:
            command.extend(("-c", value))
        for value in (
            *APP_SERVER_LOCAL_ISOLATION_OVERRIDES,
            'web_search="disabled"', "hide_agent_reasoning=true",
            "show_raw_agent_reasoning=false", "check_for_update_on_startup=false",
        ):
            command.extend(("-c", value))
        command.append("--stdio")
        environment = _safe_exec_env(control_home, temp_dir)
        environment[TELEMETRY_OVERRIDE_ENV] = str(telemetry_path)
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                # The proxy can map only declared host mounts.  Keep the App
                # Server's local cwd on the declared candidate mount, while the
                # isolation overrides above prevent the host repository's project
                # discovery from being pulled into the remote startup request.
                env=environment, cwd=candidate, bufsize=0,
            )
        except ValueError as exc:
            raise StartupDiagnosticError("startup-process-input-invalid") from exc
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        received: queue.Queue[dict[str, Any] | None] = queue.Queue()
        reader = threading.Thread(
            target=_read_json_lines, args=(process.stdout, received), daemon=True)
        reader.start()
        stderr_text = ""
        stderr_chunks: list[bytes] = []
        stderr_reader = threading.Thread(
            target=_consume_private_stderr, args=(process.stderr, stderr_chunks), daemon=True)
        stderr_reader.start()
        forced_shutdown = False
        process_tree_reaped = False
        initialize_completed = False
        if startup_deadline <= time.monotonic():
            raise StartupDiagnosticError("startup-timeout")
        try:
            try:
                process.stdin.write(_request(1, "initialize", {
                    "clientInfo": {"name": "feynman-startup-diagnostic", "version": "0.1.0"},
                    "capabilities": {"experimentalApi": True},
                }))
                process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise StartupDiagnosticError("startup-protocol-write-initialize-invalid") from exc
            initialized, _ = _wait_for_thread_start(
                received, 1, max(0.0, startup_deadline - time.monotonic()),
                timeout_stage="initialize-timeout")
            if "error" in initialized:
                raise StartupDiagnosticError("app-server-initialize-error")
            initialize_completed = True
            try:
                process.stdin.write(_notification("initialized", {}))
                process.stdin.write(_request(
                    2, "thread/start", _thread_start_params(model=model)))
                process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise StartupDiagnosticError(
                    "startup-protocol-write-thread-start-invalid",
                    initialize_completed=True,
                ) from exc
            try:
                response, notifications = _wait_for_thread_start(
                    received, 2, max(0.0, startup_deadline - time.monotonic()))
                thread = _thread_summary(response)
            except StartupDiagnosticError as exc:
                raise StartupDiagnosticError(
                    str(exc), initialize_completed=True) from exc
        finally:
            cleanup_deadline = time.monotonic() + 15
            graceful_cleanup_deadline = min(
                cleanup_deadline, time.monotonic() + 10)
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass
            process_wait_timed_out = False
            try:
                process.wait(timeout=max(
                    0.1, graceful_cleanup_deadline - time.monotonic()))
                process_tree_reaped = True
            except subprocess.TimeoutExpired:
                forced_shutdown = True
                process_wait_timed_out = True
            # Give the proxy a chance to publish child_exit_code before
            # taskkill can reap the App Server process tree.  This turns the
            # previous null exit-code artifact into either complete evidence
            # or an explicit cleanup-timeout result.
            telemetry_exit_observed = _wait_for_proxy_telemetry_exit(
                telemetry_path, deadline=graceful_cleanup_deadline)
            if process_wait_timed_out and process.poll() is None:
                process_tree_reaped = _stop_diagnostic_process(
                    process, deadline=cleanup_deadline)
            if not telemetry_exit_observed:
                # A child that did not publish its exit during the graceful
                # window may still finish after the parent is stopped.  Allow
                # only the remaining cleanup budget for one final snapshot.
                _wait_for_proxy_telemetry_exit(
                    telemetry_path, deadline=cleanup_deadline)
            cleanup_remaining = max(0.1, cleanup_deadline - time.monotonic())
            stderr_reader.join(timeout=min(2, cleanup_remaining))
            stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")
            cleanup_remaining = max(0.1, cleanup_deadline - time.monotonic())
            reader.join(timeout=min(2, cleanup_remaining))
            try:
                process.stdout.close()
            except (OSError, ValueError):
                pass
            try:
                process.stderr.close()
            except (OSError, ValueError):
                pass
        if process.returncode not in {0, None} and not forced_shutdown:
            raise StartupDiagnosticError(
                "app-server-exit-" + _failure_category(stderr_text),
                initialize_completed=initialize_completed,
            )
    try:
        telemetry = _safe_proxy_telemetry(telemetry_path)
        telemetry_status = "available"
    except StartupDiagnosticError as exc:
        if str(exc) != "startup-proxy-telemetry-missing":
            raise
        # Missing proxy telemetry is an inconclusive diagnostic signal, not a
        # green result and not a reason to discard the already observed
        # thread/start outcome.  Keep the absence explicit and payload-free.
        telemetry = None
        telemetry_status = "missing"
    telemetry_complete = telemetry is not None and _proxy_telemetry_ready(telemetry)
    cleanup_verified = bool(
        process_tree_reaped and telemetry_complete
        and telemetry is not None and telemetry["child_exit_code"] == 0
    )
    result = {
        "schema_version": 3,
        "verdict": (
            "subscription-startup-thread-ready"
            if (thread["thread_started"] and thread["instruction_sources_allowed"]
                    and telemetry_complete and cleanup_verified)
            else "subscription-startup-thread-blocked"
        ),
        "model": model,
        "checks": {
            **thread,
            "initialize_completed": True,
            "turn_requests_sent": 0,
            "model_generation_requests_sent": 0,
            "process_tree_reaped": process_tree_reaped,
            "cleanup_verified": cleanup_verified,
            "proxy_telemetry_complete": telemetry_complete,
            "proxy_request_response_correlated": telemetry_complete,
            "request_mapping_clean": bool(
                telemetry is not None
                and telemetry["request_mapping_rejections"] == 0
                and telemetry["response_mapping_rejections"] == 0
            ),
        },
        "notification_methods": notifications,
        "proxy_telemetry_status": telemetry_status,
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
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--runner-job", type=Path)
    parser.add_argument("--boundary-profile", type=Path)
    parser.add_argument("--remote-environment", type=Path)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--codex-bin", type=Path)
    parser.add_argument("--node-bin", type=Path)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--docker-bin", type=Path)
    parser.add_argument("--docker-config", type=Path)
    parser.add_argument("--docker-image-id")
    parser.add_argument("--telemetry", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    checkpoint: dict[str, Any] | None = None
    try:
        if args.checkpoint is not None:
            if any(getattr(args, name) is not None for name in (
                    "runner_job", "boundary_profile", "remote_environment", "binding",
                    "codex_bin", "node_bin", "adapter", "docker_bin", "docker_config",
                    "docker_image_id", "telemetry", "output")):
                raise ValueError("checkpoint cannot be combined with individual input arguments")
            checkpoint = load_checkpoint(args.checkpoint)
        else:
            fields = (
                "runner_job", "boundary_profile", "remote_environment", "binding",
                "codex_bin", "node_bin", "adapter", "docker_bin", "docker_config",
                "docker_image_id", "telemetry", "output",
            )
            missing = next((name for name in fields if getattr(args, name) is None), None)
            if missing is not None:
                raise ValueError("missing startup diagnostic input: " + missing)
            checkpoint = {"schema_version": 1, **{
                name: str(getattr(args, name)) for name in fields
            }}
        # Validate every file, boundary, and binding before any execution
        # path can launch a subprocess.  This is deliberately shared by the
        # checkpoint and individual-argument CLI forms.
        validation_result = validate_checkpoint(checkpoint)
        if args.validate_only:
            print(json.dumps(validation_result, ensure_ascii=False, indent=2))
            return 0
        result = run(
            runner_job_path=Path(checkpoint["runner_job"]),
            boundary_profile_path=Path(checkpoint["boundary_profile"]),
            remote_environment_path=Path(checkpoint["remote_environment"]),
            binding_path=Path(checkpoint["binding"]), codex_bin=Path(checkpoint["codex_bin"]),
            node_bin=Path(checkpoint["node_bin"]), adapter=Path(checkpoint["adapter"]),
            docker_bin=Path(checkpoint["docker_bin"]), docker_config=Path(checkpoint["docker_config"]),
            docker_image_id=checkpoint["docker_image_id"],
            telemetry_path=Path(checkpoint["telemetry"]), output_path=Path(checkpoint["output"]),
            timeout_seconds=args.timeout_seconds,
        )
    except StartupDiagnosticError as exc:
        if checkpoint is not None:
            try:
                _write_failure_artifact(
                    Path(checkpoint["output"]), str(exc),
                    initialize_completed=exc.initialize_completed)
            except OSError:
                # A sandbox or operator ACL may deny the requested artifact
                # directory.  Preserve the fixed failure label on stdout/stderr
                # without turning it into an unbounded traceback.
                pass
        blocked = str(exc) in {
            "initialize-timeout", "thread-start-timeout", "app-server-protocol-error",
            "app-server-initialize-error", "thread-start-response-shape",
            "thread-start-was-not-ephemeral", "startup-proxy-telemetry-missing",
            "instruction-source-not-allowed",
        } or str(exc).startswith("app-server-exit-")
        parser.exit(1 if blocked else 2,
                    "error: startup diagnostic failed: " + str(exc) + "\n")
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError,
            subprocess.SubprocessError, queue.Empty) as exc:
        # Do not echo filesystem paths or peer-provided diagnostic text.
        if isinstance(exc, OSError):
            label = "os-error"
        elif isinstance(exc, (UnicodeDecodeError, json.JSONDecodeError)):
            label = "json-error"
        elif isinstance(exc, subprocess.SubprocessError):
            label = "subprocess-error"
        elif isinstance(exc, queue.Empty):
            label = "queue-error"
        else:
            label = "value-error"
        parser.exit(2, "error: startup diagnostic failed: "
                    "startup-diagnostic-input-invalid-" + label
                    + "\n")
    telemetry = result.get("proxy_telemetry") or {}
    print(json.dumps({
        "verdict": result["verdict"],
        "thread_started": result["checks"]["thread_started"],
        "error_code": result["checks"]["error_code"],
        "error_category": result["checks"]["error_category"],
        "turn_requests_sent": result["checks"]["turn_requests_sent"],
        "model_generation_requests_sent": result["checks"]["model_generation_requests_sent"],
        "proxy_telemetry_status": result["proxy_telemetry_status"],
        "request_mapping_rejection_methods": telemetry.get(
            "request_mapping_rejection_methods", {}),
        "request_mapping_rejection_reasons": telemetry.get(
            "request_mapping_rejection_reasons", {}),
        "request_mapping_rejection_method_reasons": telemetry.get(
            "request_mapping_rejection_method_reasons", {}),
        "request_mapping_rejection_method_reason_fields": telemetry.get(
            "request_mapping_rejection_method_reason_fields", {}),
    }, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "subscription-startup-thread-ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
