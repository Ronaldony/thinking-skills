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
except ImportError:
    from feynman_subscription_auth_gate import CONFIG_TEXT, check as check_auth
    from feynman_full_runner_contract import (
        FIXED_CANDIDATE_FILE,
        FIXED_TEST_COMMAND,
        TOOL_NAMES,
        build_full_runner_override,
    )
    from feynman_subscription_run_preflight import preflight_files

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


def prepare_full_runner_executor_wiring(*, codex_bin: str, binding_path: Path,
                                        runner_job_path: Path,
                                        boundary_profile_path: Path,
                                        job: dict[str, Any],
                                        candidate_dir: Path, node_bin: Path,
                                        adapter: Path, docker_bin: Path,
                                        docker_config: Path,
                                        docker_image_id: str,
                                        timeout_seconds: int) -> dict[str, Any]:
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
    return {
        "full_runner_override": override,
        "skill_config_overrides": skill_overrides,
        "all_config_overrides": all_overrides,
        "command": command,
        "app_server": app_server,
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
    full_runner_wiring = None
    full_runner_override = None
    if all(value is not None for value in full_runner_inputs):
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

    control_home, remote_environment_path = _validate_control_files(job, remote_environment_path)
    if full_runner_wiring is not None:
        # This must run before the auth gate and any model-facing command.  It
        # verifies that the actual protected control home can hand off to its
        # selected remote environment with the exact transient full-runner and
        # skill-isolation overrides.  Its disposable telemetry never touches
        # the evaluator's canonical runtime telemetry.
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
            )
        if control_plane.get("verdict") != "subscription-control-plane-ready":
            raise ValueError("subscription control-plane preflight did not pass")
    auth = check_auth(control_home, codex_bin=codex_bin, timeout_seconds=min(timeout_seconds, 120))
    if auth.get("verdict") != "chatgpt-subscription-authenticated":
        raise ValueError("ChatGPT subscription auth gate did not pass")

    if versions.get("codex_cli") != auth.get("codex_cli"):
        raise ValueError("runner-job Codex version differs from authenticated control Codex")

    evaluator_dir = _directory(Path(paths["evaluator_dir"]), "evaluator directory")
    if _inside(control_home, evaluator_dir) or _inside(evaluator_dir, control_home):
        raise ValueError("evaluator directory and control CODEX_HOME must be disjoint")
    if (candidate_dir / ".codex").exists():
        raise ValueError("candidate workspace must not contain project-local .codex configuration")
    task_path = _regular(candidate_dir / "task.txt", "candidate task")
    prompt = task_path.read_text(encoding="utf-8")

    output = _prepare_output_dir(output_dir, evaluator_dir)
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
            "schema_version": 2,
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
