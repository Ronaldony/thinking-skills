#!/usr/bin/env python3
"""Execute one frozen single-turn Feynman integration-smoke job via ChatGPT-authenticated Codex.

This is intentionally *not* a general behavioral-evaluation runner. It accepts
only the preregistered tools-10 integration smoke and only after structural
preflight plus the coarse ChatGPT subscription auth gate succeed. It never reads
credential files and launches Codex from a scrubbed environment with no API-key
variables.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Mapping

try:
    from .feynman_subscription_auth_gate import CONFIG_TEXT, check as check_auth
    from .feynman_full_runner_contract import (
        FIXED_CANDIDATE_FILE,
        FIXED_TEST_COMMAND,
        TOOL_NAMES,
        build_full_runner_override,
    )
    from .feynman_subscription_run_preflight import preflight_files
    from .feynman_rpc_path_proxy import SAFE_TELEMETRY_OPTIONAL_FIELDS
except ImportError:
    from feynman_subscription_auth_gate import CONFIG_TEXT, check as check_auth
    from feynman_full_runner_contract import (
        FIXED_CANDIDATE_FILE,
        FIXED_TEST_COMMAND,
        TOOL_NAMES,
        build_full_runner_override,
    )
    from feynman_subscription_run_preflight import preflight_files
    from feynman_rpc_path_proxy import SAFE_TELEMETRY_OPTIONAL_FIELDS

EXPECTED_ANALYSIS_USE = "not-for-skill-performance-inference"
EXPECTED_CASE_ID = "tools-10"
EXPECTED_CONDITIONS = {"baseline", "feynman-v05"}
RETIRED_API_ENV_KEYS = {"OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"}
EXPECTED_REASONING_POLICY = "model-default"
WINDOWS_SYSTEM_ENV_KEYS = ("SystemRoot", "ComSpec", "PATHEXT", "WINDIR")
# These are the only completed item types that the executor treats as a
# candidate-initiated tool call.  The list intentionally covers the stable
# Codex trace names without retaining a command, tool name, arguments, or
# output in the result record.
CANDIDATE_TOOL_ITEM_TYPES = frozenset({
    "command_execution",
    "function_call",
    "mcp_tool_call",
    "tool_call",
})

_STARTUP_NOTIFICATION_METHODS = frozenset({
    "unknown", "configWarning", "environment/connection",
    "environment/connection/updated", "error", "thread/closed",
    "thread/environment/connected", "thread/environment/disconnected",
    "thread/started", "thread/status/changed", "warning",
})
_STARTUP_CHECK_BOOLEAN_FIELDS = frozenset({
    "thread_started", "ephemeral_thread", "instruction_sources_present",
    "instruction_sources_allowed", "response_payload_preserved",
    "initialize_completed", "process_tree_reaped", "cleanup_verified",
    "proxy_telemetry_complete", "proxy_request_response_correlated",
    "request_mapping_clean",
})
_STARTUP_CHECK_FIELDS = frozenset({
    *_STARTUP_CHECK_BOOLEAN_FIELDS,
    "error_code", "error_category", "error_signals", "error_data_kind",
    "turn_requests_sent", "model_generation_requests_sent",
})
_STARTUP_TELEMETRY_REQUIRED_FIELDS = frozenset({
    "schema_version", "request_methods", "response_error_codes",
    "requests_seen", "requests_forwarded", "request_mapping_rejections",
    "request_mapping_rejection_methods", "request_mapping_rejection_reasons",
    "request_mapping_rejection_method_reasons",
    "request_mapping_rejection_method_reason_fields", "malformed_requests",
    "responses_seen", "responses_forwarded", "response_mapping_rejections",
    "malformed_responses", "probe_policy_rejections", "probe_read_limit_applied",
    "probe_response_rejections", "probe_rejected_read_max_bytes",
    "child_exit_code", "request_write_failures", "request_id_duplicates",
    "responses_matched", "responses_unmatched", "notifications_seen",
    "pending_request_ids",
})
_STARTUP_TELEMETRY_FIELDS = (
    _STARTUP_TELEMETRY_REQUIRED_FIELDS | SAFE_TELEMETRY_OPTIONAL_FIELDS
)
_STARTUP_TELEMETRY_COUNTER_FIELDS = frozenset({
    "request_methods", "response_error_codes",
    "request_mapping_rejection_methods", "request_mapping_rejection_reasons",
})
_STARTUP_TELEMETRY_COUNT_FIELDS = _STARTUP_TELEMETRY_FIELDS - {
    "schema_version", *_STARTUP_TELEMETRY_COUNTER_FIELDS,
    "request_mapping_rejection_method_reasons",
    "request_mapping_rejection_method_reason_fields", "child_exit_code",
    *SAFE_TELEMETRY_OPTIONAL_FIELDS,
}
_STARTUP_PRIVACY_FIELDS = frozenset({
    "request_or_response_payload_preserved", "thread_id_preserved",
    "instruction_source_paths_preserved", "raw_stderr_preserved",
    "credential_files_directly_read_by_probe", "control_home_contents_serialized",
})


def _validate_startup_telemetry_snapshot(value: Any) -> dict[str, Any]:
    """Validate sanitized telemetry as evidence, not just as a mapping.

    This is deliberately independent of the report booleans: a producer may
    claim that telemetry is complete, but the consumer recomputes the
    accounting invariants from the payload-free snapshot before allowing a
    model command to start.
    """
    fields = set(value) if isinstance(value, dict) else set()
    if (not isinstance(value, dict)
            or not _STARTUP_TELEMETRY_REQUIRED_FIELDS <= fields <= _STARTUP_TELEMETRY_FIELDS
            or (fields & SAFE_TELEMETRY_OPTIONAL_FIELDS
                and not SAFE_TELEMETRY_OPTIONAL_FIELDS <= fields)):
        raise ValueError("subscription startup telemetry schema is invalid")
    if value.get("schema_version") != 3:
        raise ValueError("subscription startup telemetry schema version is unsupported")

    def counter_map(name: str, allowed: frozenset[str] | None = None) -> dict[str, int]:
        counter = value.get(name)
        if not isinstance(counter, dict) or any(
            not isinstance(key, str) or type(count) is not int or count < 0
            for key, count in counter.items()
        ):
            raise ValueError(f"subscription startup telemetry counter is invalid: {name}")
        if allowed is not None and not set(counter).issubset(allowed):
            raise ValueError(f"subscription startup telemetry label is invalid: {name}")
        return counter

    request_methods = counter_map("request_methods")
    response_errors = counter_map("response_error_codes")
    rejection_methods = counter_map("request_mapping_rejection_methods")
    rejection_reasons = counter_map("request_mapping_rejection_reasons")
    allowed_rejection_methods = {
        "unknown", "command/exec", "process/exec", "process/start",
        "environmentConfig/read", "fs/canonicalize", "fs/getMetadata", "fs/walk",
        "fs/readFile", "fs/writeFile", "resources/read",
    }
    method_reasons = value["request_mapping_rejection_method_reasons"]
    if not isinstance(method_reasons, dict):
        raise ValueError("subscription startup telemetry method-reason map is invalid")
    safe_reasons = {
        "unsupported-file-uri", "unsupported-file-uri-components", "host-path-not-absolute",
        "host-path-traversal", "invalid-host-path", "host-path-outside-declared-mount",
        "container-path-not-absolute", "container-path-traversal", "invalid-container-path",
        "container-path-outside-declared-mount", "invalid-container-file-uri",
        "invalid-path-field-type", "invalid-path-array-shape", "ambiguous-relative-environment-path",
        "unsafe-relative-environment-path", "candidate-mount-not-declared", "malformed-request",
        "probe-method-not-allowed", "probe-read-path-type", "probe-config-policy",
        "probe-filesystem-path-policy", "invalid-request-structure", "unclassified",
    }
    if any(
        method not in allowed_rejection_methods
        or not isinstance(reasons, dict)
        or any(not isinstance(reason, str) or type(count) is not int or count < 0
               for reason, count in reasons.items())
        for method, reasons in method_reasons.items()
    ):
        raise ValueError("subscription startup telemetry method-reason map is invalid")
    method_reason_fields = value["request_mapping_rejection_method_reason_fields"]
    if not isinstance(method_reason_fields, dict):
        raise ValueError("subscription startup telemetry field map is invalid")
    allowed_rejection_fields = {
        "unknown", "cwd", "path", "uri", "configPaths", "requirementsPaths",
    }
    if any(
        not isinstance(method, str) or not isinstance(reasons, dict)
        or method not in allowed_rejection_methods
        or any(not isinstance(reason, str) or not isinstance(fields, dict)
               or reason not in safe_reasons
               or any(not isinstance(field, str) or type(count) is not int or count < 0
                      or field not in allowed_rejection_fields
                      for field, count in fields.items())
               for reason, fields in reasons.items())
        for method, reasons in method_reason_fields.items()
    ):
        raise ValueError("subscription startup telemetry field map is invalid")
    if not request_methods.keys() <= {
        "unknown", "initialize", "initialized", "thread/start", "environment/info",
        "command/exec", "process/exec", "process/start", "environmentConfig/read",
        "fs/canonicalize", "fs/getMetadata", "fs/walk", "fs/readFile",
        "fs/writeFile", "resources/read",
    }:
        raise ValueError("subscription startup telemetry request method is invalid")
    if not rejection_methods.keys() <= {
        "unknown", "command/exec", "process/exec", "process/start",
        "environmentConfig/read", "fs/canonicalize", "fs/getMetadata", "fs/walk",
        "fs/readFile", "fs/writeFile", "resources/read",
    }:
        raise ValueError("subscription startup telemetry rejection method is invalid")
    if not rejection_reasons.keys() <= safe_reasons:
        raise ValueError("subscription startup telemetry rejection reason is invalid")
    if any(
        reason not in safe_reasons
        for reasons in method_reasons.values()
        for reason in reasons
    ):
        raise ValueError("subscription startup telemetry method reason is invalid")
    if any(not isinstance(value.get(field), int) or value[field] < 0
           for field in _STARTUP_TELEMETRY_COUNT_FIELDS):
        raise ValueError("subscription startup telemetry count is invalid")
    if value["child_exit_code"] is not None and type(value["child_exit_code"]) is not int:
        raise ValueError("subscription startup telemetry child exit code is invalid")
    if SAFE_TELEMETRY_OPTIONAL_FIELDS <= fields:
        if (type(value["child_stderr_bytes"]) is not int
                or value["child_stderr_bytes"] < 0
                or any(type(value[name]) is not bool for name in (
                    "child_stderr_nonempty", "child_stderr_truncated",
                    "child_stderr_read_error", "child_stderr_drained"))):
            raise ValueError("subscription startup telemetry stderr evidence is invalid")

    if sum(request_methods.values()) != value["requests_seen"]:
        raise ValueError("subscription startup telemetry request total is inconsistent")
    if value["requests_forwarded"] + value["request_mapping_rejections"] + value["request_write_failures"] != value["requests_seen"]:
        raise ValueError("subscription startup telemetry request accounting is inconsistent")
    if sum(response_errors.values()) > value["responses_seen"]:
        raise ValueError("subscription startup telemetry response errors are inconsistent")
    if value["responses_forwarded"] > value["responses_seen"]:
        raise ValueError("subscription startup telemetry response total is inconsistent")
    if value["notifications_seen"] > value["responses_seen"]:
        raise ValueError("subscription startup telemetry notification total is inconsistent")
    response_records = (
        value["responses_seen"] - value["notifications_seen"] - value["malformed_responses"]
    )
    if response_records < 0 or value["responses_matched"] + value["responses_unmatched"] > response_records:
        raise ValueError("subscription startup telemetry response correlation is inconsistent")
    return value


def _startup_model_generation_requests(startup_gate: Mapping[str, Any]) -> int:
    """Read the startup result whether it is a full report or a sentinel."""
    checks = startup_gate.get("checks", startup_gate)
    if not isinstance(checks, Mapping):
        raise ValueError("startup gate result has no checks object")
    value = checks.get("model_generation_requests_sent")
    if type(value) is not int or value != 0:
        raise ValueError("startup gate reported model generation")
    return value


def _validate_startup_gate(startup_gate: Mapping[str, Any]) -> None:
    """Require complete model-free startup evidence before model execution."""
    try:
        from .feynman_subscription_startup_diagnostic import _proxy_telemetry_ready
    except ImportError:
        from feynman_subscription_startup_diagnostic import _proxy_telemetry_ready
    if not isinstance(startup_gate, dict) or startup_gate.get("schema_version") != 3:
        raise ValueError("subscription startup gate schema version is unsupported")
    if startup_gate.get("verdict") != "subscription-startup-thread-ready":
        raise ValueError("subscription startup gate did not pass")
    allowed_top_level = {
        "schema_version", "preparation_fingerprint", "verdict", "failure_stage", "model", "checks",
        "notification_methods", "proxy_telemetry_status", "proxy_telemetry",
        "privacy", "scope",
    }
    required_top_level = allowed_top_level - {"failure_stage"}
    if not required_top_level.issubset(startup_gate) or not set(startup_gate).issubset(allowed_top_level):
        raise ValueError("subscription startup gate has unexpected fields")
    if "failure_stage" in startup_gate and (
        not isinstance(startup_gate["failure_stage"], str)
        or not startup_gate["failure_stage"]
        or any(not ("a" <= char <= "z" or "0" <= char <= "9" or char == "-")
               for char in startup_gate["failure_stage"])
    ):
        raise ValueError("subscription startup gate failure stage is invalid")
    fingerprint = startup_gate.get("preparation_fingerprint")
    if (not isinstance(fingerprint, str) or len(fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in fingerprint)):
        raise ValueError("subscription startup gate preparation fingerprint is invalid")
    if not isinstance(startup_gate.get("model"), str) or not startup_gate["model"]:
        raise ValueError("subscription startup gate model is invalid")
    checks = startup_gate.get("checks")
    if not isinstance(checks, dict) or set(checks) != _STARTUP_CHECK_FIELDS:
        raise ValueError("subscription startup gate has no checks object")
    if any(type(checks.get(name)) is not bool for name in _STARTUP_CHECK_BOOLEAN_FIELDS):
        raise ValueError("subscription startup gate boolean evidence is invalid")
    if checks.get("error_code") is not None and type(checks.get("error_code")) is not int:
        raise ValueError("subscription startup gate error code is invalid")
    if checks.get("error_category") is not None and not isinstance(checks.get("error_category"), str):
        raise ValueError("subscription startup gate error category is invalid")
    if checks.get("error_category") not in {
        None, "remote-path-error", "remote-environment-error", "mcp-startup-error",
        "model-configuration-error", "authentication-error", "configuration-error",
        "internal-error",
    }:
        raise ValueError("subscription startup gate error category is unsupported")
    if not isinstance(checks.get("error_signals"), dict) or any(
        type(value) is not bool for value in checks["error_signals"].values()
    ):
        raise ValueError("subscription startup gate error signals are invalid")
    if set(checks["error_signals"]) != {
        "mentions_environment", "mentions_exec_server", "mentions_connection",
        "mentions_initialize", "mentions_exit", "mentions_closed", "mentions_timeout",
        "mentions_config", "mentions_path", "mentions_not_found",
    }:
        raise ValueError("subscription startup gate error signals are incomplete")
    if checks.get("error_data_kind") not in {
        "none", "boolean", "string", "number", "array", "object", "other",
    }:
        raise ValueError("subscription startup gate error data kind is invalid")
    for name in ("turn_requests_sent", "model_generation_requests_sent"):
        if type(checks.get(name)) is not int or checks[name] != 0:
            raise ValueError("subscription startup gate reported a model request")
    if checks["response_payload_preserved"] is not False:
        raise ValueError("subscription startup gate preserves response payload")
    required_true = (
        "initialize_completed", "thread_started", "ephemeral_thread",
        "instruction_sources_allowed", "process_tree_reaped",
        "cleanup_verified", "proxy_telemetry_complete",
        "proxy_request_response_correlated", "request_mapping_clean",
    )
    if any(checks.get(name) is not True for name in required_true):
        raise ValueError("subscription startup gate evidence is incomplete")
    if checks.get("error_code") is not None or checks.get("error_category") is not None:
        raise ValueError("subscription startup gate contains an RPC error")
    if checks.get("instruction_sources_allowed") and not checks.get("instruction_sources_present"):
        raise ValueError("subscription startup gate instruction source evidence is inconsistent")
    if startup_gate.get("proxy_telemetry_status") != "available":
        raise ValueError("subscription startup gate telemetry is unavailable")
    notifications = startup_gate.get("notification_methods")
    if not isinstance(notifications, dict) or any(
        not isinstance(name, str) or name not in _STARTUP_NOTIFICATION_METHODS
        or type(count) is not int or count < 0
        for name, count in notifications.items()
    ):
        raise ValueError("subscription startup gate notification evidence is invalid")
    privacy = startup_gate.get("privacy")
    if not isinstance(privacy, dict) or set(privacy) != _STARTUP_PRIVACY_FIELDS or any(
        value is not False for value in privacy.values()
    ):
        raise ValueError("subscription startup gate privacy evidence is invalid")
    if not isinstance(startup_gate.get("scope"), str) or not startup_gate["scope"]:
        raise ValueError("subscription startup gate scope is invalid")
    telemetry = startup_gate.get("proxy_telemetry")
    if not isinstance(telemetry, dict):
        raise ValueError("subscription startup gate telemetry is missing")
    _validate_startup_telemetry_snapshot(telemetry)
    if not _proxy_telemetry_ready(telemetry):
        raise ValueError("subscription startup gate telemetry is incomplete")
    if checks["proxy_telemetry_complete"] is not True:
        raise ValueError("subscription startup gate telemetry completeness is inconsistent")
    expected_mapping_clean = (
        telemetry["request_mapping_rejections"] == 0
        and telemetry["response_mapping_rejections"] == 0
    )
    if checks["request_mapping_clean"] is not expected_mapping_clean:
        raise ValueError("subscription startup gate mapping evidence is inconsistent")
    if checks["proxy_request_response_correlated"] is not (
        telemetry["responses_unmatched"] == 0
        and telemetry["pending_request_ids"] == 0
    ):
        raise ValueError("subscription startup gate correlation evidence is inconsistent")
    expected_cleanup = (
        checks["process_tree_reaped"]
        and _proxy_telemetry_ready(telemetry)
        and telemetry["child_exit_code"] == 0
    )
    if checks["cleanup_verified"] is not expected_cleanup:
        raise ValueError("subscription startup gate cleanup evidence is inconsistent")
    _startup_model_generation_requests(startup_gate)


def _no_symlink_components(path: Path, label: str, *, must_exist: bool) -> Path:
    absolute = path.expanduser().absolute()
    parts = absolute.parts
    if not parts:
        raise ValueError(f"{label} path is empty")
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} path contains symlink component: {current}")
        if not current.exists():
            break
    if must_exist and not absolute.exists():
        raise ValueError(f"{label} does not exist: {absolute}")
    return absolute.resolve(strict=False)


def _regular(path: Path, label: str) -> Path:
    value = _no_symlink_components(path, label, must_exist=True)
    if not value.is_file():
        raise ValueError(f"{label} must be a regular file: {value}")
    return value.resolve()


def _directory(path: Path, label: str) -> Path:
    value = _no_symlink_components(path, label, must_exist=True)
    if not value.is_dir():
        raise ValueError(f"{label} must be a directory: {value}")
    return value.resolve()


def _load(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(_regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} JSON root must be object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_executable(value: str, *, platform_name: str | None = None) -> str:
    platform_name = os.name if platform_name is None else platform_name
    if not value.strip():
        raise ValueError("codex executable must be nonempty")
    if any(sep in value for sep in ("/", "\\")):
        path = Path(value).expanduser().absolute()
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"codex executable is missing or unsafe: {path}")
        if platform_name == "nt" and path.suffix.casefold() == ".ps1":
            companion = path.with_suffix(".cmd")
            if companion.is_symlink() or not companion.is_file():
                raise ValueError("Windows PowerShell Codex launcher has no safe cmd companion")
            return str(companion.resolve())
        if platform_name != "nt" and not os.access(path, os.X_OK):
            raise ValueError(f"codex executable is not executable: {path}")
        return str(path.resolve())
    resolved = shutil.which(value)
    if resolved is None:
        raise ValueError(f"codex executable not found on PATH: {value}")
    return resolved


def _inside(root: Path, child: Path) -> bool:
    return child == root or child.is_relative_to(root)


def _validate_smoke_spec(spec: dict[str, Any]) -> None:
    expected = {
        "schema_version": 2,
        "purpose": "integration-only-chatgpt-subscription-smoke",
        "analysis_use": EXPECTED_ANALYSIS_USE,
        "cases": [EXPECTED_CASE_ID],
        "conditions": ["baseline", "feynman-v05"],
        "repeats": 1,
        "seed": 20260908,
        "authentication_mode": "chatgpt-subscription",
        "control_plane_auth_source": "codex-session",
        "api_key_auth_allowed": False,
        "requires_trusted_local_or_self_hosted_control_plane": True,
        "model_reasoning_effort_policy": EXPECTED_REASONING_POLICY,
    }
    for field, value in expected.items():
        if spec.get(field) != value:
            raise ValueError(f"subscription smoke spec contract drift: {field}")


def _validate_smoke_contract(plan: dict[str, Any], job: dict[str, Any], *, smoke_spec_sha256: str) -> None:
    if plan.get("analysis_use") != EXPECTED_ANALYSIS_USE:
        raise ValueError("subscription smoke executor accepts integration-only plans")
    if plan.get("authentication_mode") != "chatgpt-subscription" or plan.get("api_key_auth_allowed") is not False:
        raise ValueError("subscription smoke plan authentication contract is invalid")
    if plan.get("model_reasoning_effort_policy") != EXPECTED_REASONING_POLICY:
        raise ValueError("subscription smoke plan reasoning-effort policy is not frozen")
    if plan.get("smoke_spec_sha256") != smoke_spec_sha256:
        raise ValueError("subscription smoke plan is not bound to the supplied smoke spec bytes")
    jobs = plan.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != 2:
        raise ValueError("subscription smoke executor requires the exact two-job smoke plan")
    if {j.get("case_id") for j in jobs if isinstance(j, dict)} != {EXPECTED_CASE_ID}:
        raise ValueError("subscription smoke plan case set drift")
    if {j.get("condition") for j in jobs if isinstance(j, dict)} != EXPECTED_CONDITIONS:
        raise ValueError("subscription smoke plan condition set drift")
    info = job.get("job")
    if not isinstance(info, dict):
        raise ValueError("runner job has no job object")
    if info.get("case_id") != EXPECTED_CASE_ID:
        raise ValueError("subscription smoke executor accepts only tools-10")
    if info.get("condition_id") not in EXPECTED_CONDITIONS:
        raise ValueError("subscription smoke executor accepts only baseline/feynman-v05")
    if info.get("repeat") != 1 or info.get("has_followup") is not False:
        raise ValueError("subscription smoke executor accepts one single-turn repeat only")


def _validate_control_files(job: dict[str, Any], remote_environment_path: Path) -> tuple[Path, Path]:
    paths = job.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("runner job has no paths object")
    control_raw = paths.get("control_codex_home")
    if not isinstance(control_raw, str) or not control_raw:
        raise ValueError("runner job has invalid control_codex_home")
    control_home = _directory(Path(control_raw), "control CODEX_HOME")
    config_path = _regular(control_home / "config.toml", "control config")
    if config_path.read_text(encoding="utf-8") != CONFIG_TEXT:
        raise ValueError("control config differs from dedicated ChatGPT auth-gate configuration")
    remote_path = _regular(remote_environment_path, "remote environment")
    expected_remote = (control_home / "environments.toml").resolve(strict=False)
    if remote_path != expected_remote:
        raise ValueError("remote environment must be the canonical control CODEX_HOME/environments.toml")
    return control_home, remote_path


def _prepare_output_dir(output_dir: Path, evaluator_dir: Path) -> Path:
    evaluator = _directory(evaluator_dir, "evaluator directory")
    output = _no_symlink_components(output_dir, "execution output directory", must_exist=False)
    if output.exists():
        raise ValueError("execution output directory must not already exist")
    if output == evaluator or not _inside(evaluator, output):
        raise ValueError("execution output directory must be a new descendant of evaluator_dir")
    output.mkdir(parents=True, mode=0o700)
    try:
        os.chmod(output, 0o700)
    except OSError:
        pass
    return output.resolve()


def _assert_invocation_context() -> None:
    for key in RETIRED_API_ENV_KEYS:
        if key in os.environ:
            raise ValueError(f"retired API authentication environment is set: {key}")
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        raise ValueError("ChatGPT account auth smoke execution is prohibited in GitHub Actions")


def _source_env_get(source: Mapping[str, str], key: str) -> str | None:
    direct = source.get(key)
    if direct:
        return direct
    target = key.upper()
    for name, value in source.items():
        if name.upper() == target and value:
            return value
    return None


def _windows_docker_path_entry(source: Mapping[str, str]) -> str | None:
    """Find Docker Desktop's CLI without inheriting the host environment."""
    roots: list[Path] = []
    for key in ("LOCALAPPDATA", "ProgramFiles", "ProgramW6432"):
        value = _source_env_get(source, key)
        if value:
            roots.append(Path(value))
    candidates = [
        root / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
        for root in roots
    ] + [
        root / "Docker" / "resources" / "bin" / "docker.exe"
        for root in roots
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.parent)
    return None


def _safe_exec_env(
    control_home: Path,
    temp_dir: Path,
    *,
    platform_name: str | None = None,
    source_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    platform_name = os.name if platform_name is None else platform_name
    source = os.environ if source_env is None else source_env
    path_value = _source_env_get(source, "PATH") or (
        r"C:\Windows\System32" if platform_name == "nt" else "/usr/local/bin:/usr/bin:/bin"
    )
    if platform_name == "nt":
        docker_dir = _windows_docker_path_entry(source)
        if docker_dir and docker_dir not in path_value.split(os.pathsep):
            path_value = docker_dir + os.pathsep + path_value
        temp_value = str(temp_dir)
        result = {
            "HOME": str(control_home.parent),
            "USERPROFILE": str(control_home.parent),
            "CODEX_HOME": str(control_home),
            "PATH": path_value,
            "TEMP": temp_value,
            "TMP": temp_value,
            "TMPDIR": temp_value,
        }
        for key in WINDOWS_SYSTEM_ENV_KEYS:
            value = _source_env_get(source, key)
            if value:
                result[key] = value
        return result
    return {
        "HOME": str(control_home.parent),
        "CODEX_HOME": str(control_home),
        "PATH": path_value,
        "TMPDIR": str(temp_dir),
    }


def _failure_category(stderr: str) -> str:
    """Return only fixed diagnostic labels; never expose subprocess text."""
    text = stderr.lower()
    if "cannot be used with" in text or "unexpected argument" in text:
        return "cli-argument-error"
    if "usage limit" in text or "usage_limit" in text:
        return "usage-limit"
    if "unknown field" in text or "error loading config" in text:
        return "configuration-error"
    if "environments.toml" in text or "exec-server" in text:
        return "remote-environment-error"
    return "unclassified"


def _parse_trace(path: Path) -> dict[str, Any]:
    thread_ids: set[str] = set()
    final_messages: list[str] = []
    usage: dict[str, Any] | None = None
    reasoning_events = 0
    completed_tool_item_types: set[str] = set()
    completed_tool_item_count = 0
    failures: list[str] = []
    events = 0
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        events += 1
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Codex trace line {line_no} is not valid JSON") from exc
        if not isinstance(event, dict):
            raise ValueError(f"Codex trace line {line_no} root must be object")
        kind = event.get("type")
        if kind == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                thread_ids.add(thread_id)
        elif kind in {"error", "turn.failed"}:
            failures.append(str(kind))
        elif kind == "turn.completed":
            value = event.get("usage")
            if isinstance(value, dict):
                usage = value
        elif kind in {"item.started", "item.completed"}:
            item = event.get("item")
            if isinstance(item, dict):
                if item.get("type") == "reasoning":
                    reasoning_events += 1
                item_type = item.get("type")
                if kind == "item.completed" and item_type in CANDIDATE_TOOL_ITEM_TYPES:
                    completed_tool_item_count += 1
                    completed_tool_item_types.add(item_type)
                if kind == "item.completed" and item.get("type") == "agent_message":
                    text = item.get("text")
                    if isinstance(text, str):
                        final_messages.append(text)
    if failures:
        raise ValueError("Codex trace contains failed/error events: " + ", ".join(failures))
    if len(thread_ids) != 1:
        raise ValueError("successful smoke trace must contain exactly one nonempty thread_id")
    if not final_messages:
        raise ValueError("successful smoke trace contains no completed agent message")
    if events < 3:
        raise ValueError("successful smoke trace is unexpectedly short")
    return {
        "thread_id": next(iter(thread_ids)),
        "final_message": final_messages[-1],
        "usage": usage or {},
        "reasoning_events_observed": reasoning_events,
        "event_count": events,
        "completed_tool_item_count": completed_tool_item_count,
        "completed_tool_item_types": sorted(completed_tool_item_types),
    }


def build_codex_exec_command(*, executable: str, model: str, candidate_dir: Path,
                             config_overrides: tuple[str, ...] = ()) -> list[str]:
    """Build the canonical smoke command with optional fixed MCP overrides.

    The caller supplies only deterministic, already-validated ``-c`` values.
    This function does not read configuration, authenticate, start Codex, or
    inspect a model response.  The model still cannot choose the executable,
    candidate cwd, or stdin task.
    """
    if not executable or not model:
        raise ValueError("Codex command requires executable and model")
    command = [
        executable, "exec",
        "--json",
        "--ephemeral",
        "--strict-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        # Set the frozen non-interactive policy explicitly. --approve-for-me
        # selects automatic review and conflicts with --sandbox on 0.153.4.
        "-c", 'approval_policy="never"',
        "--sandbox", "workspace-write",
        "--model", model,
        "--cd", str(candidate_dir),
        "-c", 'web_search="disabled"',
        "-c", "hide_agent_reasoning=true",
        "-c", "show_raw_agent_reasoning=false",
        "-c", "check_for_update_on_startup=false",
    ]
    for value in config_overrides:
        if not isinstance(value, str) or not value:
            raise ValueError("Codex config override must be a nonempty string")
        command.extend(("-c", value))
    command.append("-")
    return command


def _validate_full_runner_binding(*, binding_path: Path, runner_job_path: Path,
                                  boundary_profile_path: Path, job: dict[str, Any],
                                  node_bin: Path, adapter: Path, docker_bin: Path,
                                  docker_config: Path, docker_image_id: str,
                                  candidate_dir: Path) -> Any:
    """Validate the immutable full-runner inputs before auth or model use."""
    binding = _load(binding_path, "full-runner binding")
    info = job.get("job")
    versions = job.get("versions")
    digests = job.get("digests")
    if not isinstance(info, dict) or not isinstance(versions, dict) or not isinstance(digests, dict):
        raise ValueError("runner job lacks binding identity blocks")
    expected_identity = {
        "schema_version": 1,
        "verdict": "full-runner-mcp-artifact-chain-bound",
        "run_id": job.get("run_id"),
        "case_id": info.get("case_id"),
        "condition_id": info.get("condition_id"),
        "model": versions.get("model"),
        "codex_cli": versions.get("codex_cli"),
    }
    if any(binding.get(field) != value for field, value in expected_identity.items()):
        raise ValueError("full-runner binding identity differs from runner job")
    lineage = binding.get("lineage")
    if lineage != {
        "runner_job_sha256": _sha(runner_job_path),
        "boundary_profile_sha256": _sha(boundary_profile_path),
        "eval_plan_sha256": digests.get("eval_plan_sha256"),
        "candidate_prompt_sha256": digests.get("candidate_prompt_sha256"),
        "runtime_sha256": digests.get("runtime_sha256"),
    }:
        raise ValueError("full-runner binding lineage differs from runner job")
    full_runner = binding.get("full_runner")
    if not isinstance(full_runner, dict):
        raise ValueError("full-runner binding implementation block is missing")
    override = build_full_runner_override(
        node_bin=node_bin,
        adapter=adapter,
        candidate=candidate_dir,
        docker_bin=docker_bin,
        docker_config=docker_config,
        docker_image_id=docker_image_id,
    )
    expected_runner = {
        "server_name": "feynman_full_runner",
        "tool_names": list(TOOL_NAMES),
        "adapter_sha256": override.adapter_sha256,
        "docker_image_id": override.docker_image_id,
        "initial_candidate_sha256": override.initial_candidate_sha256,
        "test_sha256": override.test_sha256,
        "fixed_candidate_file": FIXED_CANDIDATE_FILE,
        "fixed_test_command": list(FIXED_TEST_COMMAND),
        "network_mode": "none",
    }
    if any(full_runner.get(field) != value for field, value in expected_runner.items()):
        raise ValueError("full-runner binding implementation lineage drift")
    return override


def _wiring_fingerprint(*, resolved_codex: str, model: str, candidate_dir: Path,
                        runner_job_path: Path, boundary_profile_path: Path,
                        binding_path: Path, node_bin: Path, adapter: Path,
                        docker_bin: Path, docker_config: Path, docker_image_id: str,
                        all_config_overrides: tuple[str, ...], command: list[str]) -> str:
    """Return an opaque digest for one immutable executor preparation.

    The descriptor is held only in memory.  Its digest is safe to place in a
    gate because it does not expose paths, config values, or command payloads,
    while still binding the exact files, image, overrides, and model command.
    """
    def path_digest(path: Path) -> str:
        return _sha(path) if path.is_file() else hashlib.sha256(
            str(path.resolve()).encode("utf-8")
        ).hexdigest()

    descriptor = {
        "schema_version": 1,
        "model": model,
        "candidate_path_sha256": hashlib.sha256(
            str(candidate_dir.resolve()).casefold().encode("utf-8")
        ).hexdigest(),
        "resolved_codex_sha256": path_digest(Path(resolved_codex)),
        "runner_job_sha256": _sha(runner_job_path),
        "boundary_profile_sha256": _sha(boundary_profile_path),
        "binding_sha256": _sha(binding_path),
        "node_sha256": path_digest(node_bin),
        "adapter_sha256": path_digest(adapter),
        "docker_sha256": path_digest(docker_bin),
        "docker_config_path_sha256": hashlib.sha256(
            str(docker_config.resolve()).casefold().encode("utf-8")
        ).hexdigest(),
        "docker_image_id": docker_image_id,
        "config_override_count": len(all_config_overrides),
        "config_overrides_sha256": hashlib.sha256(
            json.dumps(list(all_config_overrides), separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "command_sha256": hashlib.sha256(
            json.dumps(command, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def prepare_full_runner_executor_wiring(*, codex_bin: str, binding_path: Path,
                                        runner_job_path: Path,
                                        boundary_profile_path: Path,
                                        job: dict[str, Any],
                                        candidate_dir: Path, node_bin: Path,
                                        adapter: Path, docker_bin: Path,
                                        docker_config: Path,
                                        docker_image_id: str,
                                        timeout_seconds: int,
                                        deadline: float | None = None) -> dict[str, Any]:
    """Prepare the full-runner command and skill isolation without auth/model use."""
    override = _validate_full_runner_binding(
        binding_path=binding_path,
        runner_job_path=runner_job_path,
        boundary_profile_path=boundary_profile_path,
        job=job,
        node_bin=node_bin,
        adapter=adapter,
        docker_bin=docker_bin,
        docker_config=docker_config,
        docker_image_id=docker_image_id,
        candidate_dir=candidate_dir,
    )
    # Imported lazily to keep this module's unit-test fixtures independent of
    # the App Server probe module.  At runtime this module is fully loaded,
    # so the probe's import of the command builder is not cyclic.
    try:
        from .feynman_skill_tool_wiring_preflight import _app_server_probe
    except ImportError:
        from feynman_skill_tool_wiring_preflight import _app_server_probe

    wiring_root = Path(tempfile.mkdtemp(prefix="feynman-executor-wiring-"))
    try:
        isolated_codex_home = wiring_root / "codex-home"
        candidate_home = wiring_root / "candidate-home"
        temp_dir = wiring_root / "temp"
        isolated_codex_home.mkdir()
        candidate_home.mkdir()
        temp_dir.mkdir()
        resolved_codex = _resolve_executable(codex_bin)
        app_server = _app_server_probe(
            codex_bin=Path(resolved_codex),
            codex_home=isolated_codex_home,
            candidate_home=candidate_home,
            temp_dir=temp_dir,
            candidate=candidate_dir,
            override=override,
            expected_skills=job["skills"]["expected_candidate_skills"],
            timeout_seconds=min(timeout_seconds, 30),
            deadline=deadline,
        )
    finally:
        shutil.rmtree(wiring_root, ignore_errors=True)
    all_overrides = tuple(app_server["transient_config_overrides"])
    if all_overrides[:len(override.values)] != override.values:
        raise ValueError("skill discovery changed the full-runner override prefix")
    skill_overrides = all_overrides[len(override.values):]
    model = job["versions"]["model"]
    command = build_codex_exec_command(
        executable=resolved_codex,
        model=model,
        candidate_dir=candidate_dir,
        config_overrides=all_overrides,
    )
    if command[-1] != "-" or command.count("-c") != 5 + len(all_overrides):
        raise ValueError("full-runner executor command has unexpected override count")
    preparation_fingerprint = _wiring_fingerprint(
        resolved_codex=resolved_codex,
        model=model,
        candidate_dir=candidate_dir,
        runner_job_path=runner_job_path,
        boundary_profile_path=boundary_profile_path,
        binding_path=binding_path,
        node_bin=node_bin,
        adapter=adapter,
        docker_bin=docker_bin,
        docker_config=docker_config,
        docker_image_id=docker_image_id,
        all_config_overrides=all_overrides,
        command=command,
    )
    return {
        "full_runner_override": override,
        "skill_config_overrides": skill_overrides,
        "all_config_overrides": all_overrides,
        "command": command,
        "app_server": app_server,
        # This opaque digest binds the validated preparation inputs, exact
        # override tuple, and exact model command.  Consumers use the digest
        # to detect drift without persisting paths or command payloads.
        "preparation_fingerprint": preparation_fingerprint,
    }


def execute_smoke_job(*, plan_path: Path, smoke_spec_path: Path, ordinal: int, evaluator_case_path: Path,
                      runner_job_path: Path, boundary_profile_path: Path,
                      remote_environment_path: Path, output_dir: Path,
                      codex_bin: str = "codex", timeout_seconds: int = 600,
                      full_runner_binding_path: Path | None = None,
                      full_runner_node_bin: Path | None = None,
                      full_runner_adapter: Path | None = None,
                      full_runner_docker_bin: Path | None = None,
                      full_runner_docker_config: Path | None = None,
                      full_runner_image_id: str | None = None) -> dict[str, Any]:
    if type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 3600:
        raise ValueError("timeout_seconds must be an integer in 30..3600")
    _assert_invocation_context()

    plan_path = _regular(plan_path, "eval plan")
    smoke_spec_path = _regular(smoke_spec_path, "subscription smoke spec")
    evaluator_case_path = _regular(evaluator_case_path, "evaluator case")
    runner_job_path = _regular(runner_job_path, "runner job")
    boundary_profile_path = _regular(boundary_profile_path, "boundary profile")
    remote_environment_path = _regular(remote_environment_path, "remote environment")

    plan = _load(plan_path, "eval plan")
    smoke_spec = _load(smoke_spec_path, "subscription smoke spec")
    _validate_smoke_spec(smoke_spec)
    smoke_spec_sha = _sha(smoke_spec_path)
    job = _load(runner_job_path, "runner job")
    _validate_smoke_contract(plan, job, smoke_spec_sha256=smoke_spec_sha)

    preflight = preflight_files(
        plan_path=plan_path,
        ordinal=ordinal,
        evaluator_case_path=evaluator_case_path,
        runner_job_path=runner_job_path,
        boundary_profile_path=boundary_profile_path,
        remote_environment_path=remote_environment_path,
    )
    if preflight.get("verdict") != "ready-for-local-chatgpt-session-check":
        raise ValueError("subscription structural preflight did not pass")

    full_runner_inputs = (
        full_runner_binding_path, full_runner_node_bin, full_runner_adapter,
        full_runner_docker_bin, full_runner_docker_config, full_runner_image_id,
    )
    if any(value is not None for value in full_runner_inputs) and not all(
        value is not None for value in full_runner_inputs
    ):
        raise ValueError("full-runner binding, adapter, Docker, and image inputs are all required")
    # The fixed tools-10 smoke is only meaningful when its model-facing tool
    # boundary and model-free startup gate are both actually bound.  A
    # missing full-runner set must stop before auth and before any model
    # subprocess; the old sentinel path allowed an unbound generic `codex exec`
    # to continue.
    if not all(value is not None for value in full_runner_inputs):
        raise ValueError("tools-10 smoke requires the complete full-runner startup gate inputs")

    versions = job.get("versions")
    paths = job.get("paths")
    if not isinstance(versions, dict) or not isinstance(paths, dict):
        raise ValueError("runner job lacks versions/paths")
    model = versions.get("model")
    if not isinstance(model, str) or not model:
        raise ValueError("runner job has invalid model")
    if model.lower().startswith("mock"):
        raise ValueError("subscription smoke executor refuses mock model IDs")
    candidate_dir = _directory(Path(paths["candidate_dir"]), "candidate directory")
    evaluator_dir = _directory(Path(paths["evaluator_dir"]), "evaluator directory")
    control_home, remote_environment_path = _validate_control_files(job, remote_environment_path)
    if _inside(control_home, evaluator_dir) or _inside(evaluator_dir, control_home):
        raise ValueError("evaluator directory and control CODEX_HOME must be disjoint")
    if (candidate_dir / ".codex").exists():
        raise ValueError("candidate workspace must not contain project-local .codex configuration")
    task_path = _regular(candidate_dir / "task.txt", "candidate task")
    prompt = task_path.read_text(encoding="utf-8")
    # Allocate the complete evaluator-owned execution directory before any
    # control-plane, startup, auth, or model process can run.  Startup
    # evidence must not be placed in system TEMP: the startup checkpoint
    # validator deliberately rejects paths outside the evaluator boundary.
    output = _prepare_output_dir(output_dir, evaluator_dir)
    startup_dir = output / "startup-gate"
    startup_dir.mkdir(mode=0o700)
    startup_telemetry_path = startup_dir / "startup-rpc-telemetry.json"
    startup_report_path = startup_dir / "startup-report.json"
    full_runner_wiring = prepare_full_runner_executor_wiring(
        codex_bin=codex_bin,
        binding_path=full_runner_binding_path,
        runner_job_path=runner_job_path,
        boundary_profile_path=boundary_profile_path,
        job=job,
        candidate_dir=candidate_dir,
        node_bin=full_runner_node_bin,
        adapter=full_runner_adapter,
        docker_bin=full_runner_docker_bin,
        docker_config=full_runner_docker_config,
        docker_image_id=full_runner_image_id,
        timeout_seconds=timeout_seconds,
    )
    full_runner_override = full_runner_wiring["full_runner_override"]

    # Freeze the complete non-secret execution contract after model-free
    # wiring preparation.  The artifact is evaluator-owned and is rechecked
    # before control-plane/auth/model boundaries, so a stale report or a
    # changed input cannot be promoted by the later stages.
    try:
        from .feynman_subscription_execution_spec import (
            assert_execution_spec_current, build_execution_spec,
            load_execution_spec, write_execution_spec,
        )
    except ImportError:
        from feynman_subscription_execution_spec import (
            assert_execution_spec_current, build_execution_spec,
            load_execution_spec, write_execution_spec,
        )
    spec_path = output / "execution-spec.json"
    execution_spec = build_execution_spec(
        plan_path=plan_path, smoke_spec_path=smoke_spec_path,
        evaluator_case_path=evaluator_case_path, runner_job_path=runner_job_path,
        boundary_profile_path=boundary_profile_path,
        remote_environment_path=remote_environment_path,
        binding_path=full_runner_binding_path, codex_bin=Path(_resolve_executable(codex_bin)),
        node_bin=full_runner_node_bin, adapter=full_runner_adapter,
        docker_bin=full_runner_docker_bin, docker_config=full_runner_docker_config,
        docker_image_id=full_runner_image_id, candidate_dir=candidate_dir,
        evaluator_dir=evaluator_dir, control_home=control_home, output_dir=output,
        job=job, preparation_fingerprint=full_runner_wiring["preparation_fingerprint"],
        preflight=preflight,
    )
    write_execution_spec(spec_path, execution_spec)
    execution_spec = load_execution_spec(spec_path)

    def assert_frozen_inputs() -> None:
        assert_execution_spec_current(
            execution_spec,
            plan_path=plan_path, smoke_spec_path=smoke_spec_path,
            evaluator_case_path=evaluator_case_path, runner_job_path=runner_job_path,
            boundary_profile_path=boundary_profile_path,
            remote_environment_path=remote_environment_path,
            binding_path=full_runner_binding_path,
            codex_bin=Path(_resolve_executable(codex_bin)),
            node_bin=full_runner_node_bin, adapter=full_runner_adapter,
            docker_bin=full_runner_docker_bin, docker_config=full_runner_docker_config,
            docker_image_id=full_runner_image_id, candidate_dir=candidate_dir,
            evaluator_dir=evaluator_dir, control_home=control_home,
            output_dir=output, job=job, preflight=preflight,
        )

    assert_frozen_inputs()

    # This must run before the auth gate and any model-facing command.  It
    # verifies that the actual protected control home can hand off to its
    # selected remote environment with the exact transient full-runner and
    # skill-isolation overrides.  Its disposable telemetry never touches the
    # evaluator's canonical runtime telemetry.
    try:
        from .feynman_subscription_control_plane_preflight import run as control_plane_preflight
    except ImportError:
        from feynman_subscription_control_plane_preflight import run as control_plane_preflight
    with tempfile.TemporaryDirectory(prefix="feynman-control-plane-") as control_plane_root:
        control_plane_dir = Path(control_plane_root)
        control_plane = control_plane_preflight(
            codex_bin=codex_bin,
            control_home=control_home,
            temp_dir=control_plane_dir,
            proxy_telemetry=control_plane_dir / "rpc-proxy-telemetry.json",
            config_overrides=full_runner_wiring["all_config_overrides"],
            timeout_seconds=min(timeout_seconds, 30),
            cwd=candidate_dir,
        )
    if control_plane.get("verdict") != "subscription-control-plane-ready":
        raise ValueError("subscription control-plane preflight did not pass")
    assert_frozen_inputs()
    # The model-facing executor must consume a fresh startup result for the
    # same job, binding, image, and control home.  A previous model-free report
    # cannot be replayed as evidence for this process.
    try:
        from .feynman_subscription_startup_diagnostic import run as startup_diagnostic
    except ImportError:
        from feynman_subscription_startup_diagnostic import run as startup_diagnostic
    startup_gate = startup_diagnostic(
        runner_job_path=runner_job_path,
        boundary_profile_path=boundary_profile_path,
        remote_environment_path=remote_environment_path,
        binding_path=full_runner_binding_path,
        codex_bin=Path(_resolve_executable(codex_bin)),
        node_bin=full_runner_node_bin,
        adapter=full_runner_adapter,
        docker_bin=full_runner_docker_bin,
        docker_config=full_runner_docker_config,
        docker_image_id=full_runner_image_id,
        telemetry_path=startup_telemetry_path,
        output_path=startup_report_path,
        timeout_seconds=min(timeout_seconds, 60),
        prepared_wiring=full_runner_wiring,
    )
    if startup_gate.get("preparation_fingerprint") != full_runner_wiring.get("preparation_fingerprint"):
        raise ValueError("startup gate preparation fingerprint differs from model command")
    _validate_startup_gate(startup_gate)
    persisted_startup_gate = _load(startup_report_path, "startup gate report")
    if persisted_startup_gate != startup_gate:
        raise ValueError("startup gate report does not match returned startup evidence")
    startup_telemetry = _regular(startup_telemetry_path, "startup gate telemetry")
    startup_report = _regular(startup_report_path, "startup gate report")
    assert_frozen_inputs()
    auth = check_auth(control_home, codex_bin=codex_bin, timeout_seconds=min(timeout_seconds, 120))
    if auth.get("verdict") != "chatgpt-subscription-authenticated":
        raise ValueError("ChatGPT subscription auth gate did not pass")

    if versions.get("codex_cli") != auth.get("codex_cli"):
        raise ValueError("runner-job Codex version differs from authenticated control Codex")
    assert_frozen_inputs()

    trace_path = output / "codex-trace.jsonl"
    final_path = output / "candidate-final.txt"
    result_path = output / "subscription-exec-result.json"
    control_temp = output / ".control-tmp"
    control_temp.mkdir(mode=0o700)

    executable = _resolve_executable(codex_bin)
    env = _safe_exec_env(control_home, control_temp)
    command = (
        full_runner_wiring["command"] if full_runner_wiring is not None
        else build_codex_exec_command(
            executable=executable, model=model, candidate_dir=candidate_dir)
    )

    stderr_text = ""
    try:
        with trace_path.open("w", encoding="utf-8") as trace_handle:
            proc = subprocess.run(
                command,
                input=prompt,
                env=env,
                cwd=candidate_dir,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=trace_handle,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
            )
        stderr_text = proc.stderr or ""
        if proc.returncode != 0:
            category = _failure_category(stderr_text)
            raise ValueError(f"Codex exec failed with exit code {proc.returncode}; category={category}; raw stderr was not preserved")
        trace = _parse_trace(trace_path)
        final_path.write_text(trace["final_message"], encoding="utf-8")
        tool_use_observed = trace["completed_tool_item_count"] > 0
        result = {
            "schema_version": 3,
            "verdict": "subscription-codex-smoke-exec-completed",
            "run_id": job["run_id"],
            "job": dict(job["job"]),
            "versions": {
                "model_requested": model,
                "codex_cli": auth["codex_cli"],
                "model_reasoning_effort": EXPECTED_REASONING_POLICY,
            },
            "authentication": {
                "mode": "chatgpt-subscription",
                "source": "codex-session",
                "api_key_auth_allowed": False,
                "auth_gate_verdict": auth["verdict"],
                "raw_status_output_preserved": False,
                "credential_files_read_by_executor": False,
            },
            "execution_controls": {
                "non_interactive": True,
                "jsonl_trace": True,
                "ephemeral_session": True,
                "approval_policy": "never",
                "sandbox": "workspace-write",
                "web_search": "disabled",
                "ignore_execpolicy_rules": True,
                "strict_config": True,
                "local_execution_disabled": True,
                "full_runner_mcp_bound": full_runner_override is not None,
                "transient_skill_isolation_bound": full_runner_wiring is not None,
            },
            "startup_gate": {
                "verdict": startup_gate["verdict"],
                "model_generation_requests_sent": _startup_model_generation_requests(startup_gate),
                "preparation_fingerprint": startup_gate["preparation_fingerprint"],
                "artifacts": {
                    "report": startup_report.relative_to(output).as_posix(),
                    "telemetry": startup_telemetry.relative_to(output).as_posix(),
                    "report_sha256": _sha(startup_report),
                    "telemetry_sha256": _sha(startup_telemetry),
                },
            },
            "execution_spec": {
                "verdict": execution_spec["verdict"],
                "preparation_fingerprint": execution_spec["wiring"]["preparation_fingerprint"],
                "artifact": "execution-spec.json",
                "artifact_sha256": _sha(spec_path),
            },
            "conversation": {
                "thread_id": trace["thread_id"],
                "event_count": trace["event_count"],
                "reasoning_events_observed": trace["reasoning_events_observed"],
            },
            "candidate_tool_activity": {
                "completed_tool_item_count": trace["completed_tool_item_count"],
                "completed_tool_item_types": trace["completed_tool_item_types"],
                "tool_use_verdict": (
                    "candidate-tool-use-observed" if tool_use_observed
                    else "candidate-tool-use-not-observed"
                ),
                # A tool-call trace is only the minimum condition for
                # extracting post-run evidence.  It is not a claim that the
                # requested test actually ran or that it passed.
                "postrun_evidence_eligibility": (
                    "eligible-for-trace-evidence-extraction" if tool_use_observed
                    else "blocked-no-candidate-tool-call"
                ),
            },
            "usage": trace["usage"],
            "digests": {
                "eval_plan_sha256": _sha(plan_path),
                "smoke_spec_sha256": smoke_spec_sha,
                "evaluator_case_sha256": _sha(evaluator_case_path),
                "runner_job_sha256": _sha(runner_job_path),
                "boundary_profile_sha256": _sha(boundary_profile_path),
                "remote_environment_sha256": _sha(remote_environment_path),
                "candidate_task_sha256": _sha(task_path),
                "codex_trace_sha256": _sha(trace_path),
                "candidate_final_sha256": _sha(final_path),
            },
            "privacy": {
                "process_environment_inherited": False,
                "raw_stderr_preserved": False,
                "stderr_nonempty": bool(stderr_text),
                "raw_auth_status_preserved": False,
                "control_codex_home_contents_serialized": False,
                "full_runner_binding_contents_serialized": False,
                "skill_discovery_paths_serialized": False,
            },
            "limitations": [
                "integration smoke only; result must not be used for Feynman skill-effect inference",
                "model reasoning effort policy is explicitly model-default for integration smoke; behavioral pilot requires a new contract that freezes an explicit effort",
                "successful model execution does not by itself prove the post-run boundary canary/attestation lineage",
                "candidate tool activity is a trace-level eligibility signal only; test execution and outcome require separately extracted trusted evidence",
            ],
            "scope": (
                "single-turn tools-10 ChatGPT-subscription integration smoke execution after structural/auth gates; "
                "no API-key path and no behavioral-performance inference"
            ),
        }
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        shutil.rmtree(control_temp, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--smoke-spec", type=Path, required=True)
    parser.add_argument("--ordinal", type=int, required=True)
    parser.add_argument("--evaluator-case", type=Path, required=True)
    parser.add_argument("--runner-job", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--remote-environment", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--full-runner-binding", type=Path, required=True)
    parser.add_argument("--full-runner-node-bin", type=Path, required=True)
    parser.add_argument("--full-runner-adapter", type=Path, required=True)
    parser.add_argument("--full-runner-docker-bin", type=Path, required=True)
    parser.add_argument("--full-runner-docker-config", type=Path, required=True)
    parser.add_argument("--full-runner-image-id", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()
    try:
        result = execute_smoke_job(
            plan_path=args.plan,
            smoke_spec_path=args.smoke_spec,
            ordinal=args.ordinal,
            evaluator_case_path=args.evaluator_case,
            runner_job_path=args.runner_job,
            boundary_profile_path=args.boundary_profile,
            remote_environment_path=args.remote_environment,
            output_dir=args.output_dir,
            codex_bin=args.codex_bin,
            timeout_seconds=args.timeout_seconds,
            full_runner_binding_path=args.full_runner_binding,
            full_runner_node_bin=args.full_runner_node_bin,
            full_runner_adapter=args.full_runner_adapter,
            full_runner_docker_bin=args.full_runner_docker_bin,
            full_runner_docker_config=args.full_runner_docker_config,
            full_runner_image_id=args.full_runner_image_id,
        )
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
