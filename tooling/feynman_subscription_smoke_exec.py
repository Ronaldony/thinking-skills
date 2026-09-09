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
from typing import Any, Mapping

try:
    from .feynman_subscription_auth_gate import CONFIG_TEXT, check as check_auth
    from .feynman_subscription_run_preflight import preflight_files
except ImportError:
    from feynman_subscription_auth_gate import CONFIG_TEXT, check as check_auth
    from feynman_subscription_run_preflight import preflight_files

EXPECTED_ANALYSIS_USE = "not-for-skill-performance-inference"
EXPECTED_CASE_ID = "tools-10"
EXPECTED_CONDITIONS = {"baseline", "feynman-v05"}
RETIRED_API_ENV_KEYS = {"OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"}
EXPECTED_REASONING_POLICY = "model-default"
WINDOWS_SYSTEM_ENV_KEYS = ("SystemRoot", "ComSpec", "PATHEXT", "WINDIR")


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


def _resolve_executable(value: str) -> str:
    if not value.strip():
        raise ValueError("codex executable must be nonempty")
    if any(sep in value for sep in ("/", "\\")):
        path = Path(value).expanduser().absolute()
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"codex executable is missing or unsafe: {path}")
        if os.name != "nt" and not os.access(path, os.X_OK):
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


def _parse_trace(path: Path) -> dict[str, Any]:
    thread_ids: set[str] = set()
    final_messages: list[str] = []
    usage: dict[str, Any] | None = None
    reasoning_events = 0
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
    }


def execute_smoke_job(*, plan_path: Path, smoke_spec_path: Path, ordinal: int, evaluator_case_path: Path,
                      runner_job_path: Path, boundary_profile_path: Path,
                      remote_environment_path: Path, output_dir: Path,
                      codex_bin: str = "codex", timeout_seconds: int = 600) -> dict[str, Any]:
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

    control_home, remote_environment_path = _validate_control_files(job, remote_environment_path)
    auth = check_auth(control_home, codex_bin=codex_bin, timeout_seconds=min(timeout_seconds, 120))
    if auth.get("verdict") != "chatgpt-subscription-authenticated":
        raise ValueError("ChatGPT subscription auth gate did not pass")

    versions = job.get("versions")
    paths = job.get("paths")
    if not isinstance(versions, dict) or not isinstance(paths, dict):
        raise ValueError("runner job lacks versions/paths")
    if versions.get("codex_cli") != auth.get("codex_cli"):
        raise ValueError("runner-job Codex version differs from authenticated control Codex")
    model = versions.get("model")
    if not isinstance(model, str) or not model:
        raise ValueError("runner job has invalid model")
    if model.lower().startswith("mock"):
        raise ValueError("subscription smoke executor refuses mock model IDs")

    candidate_dir = _directory(Path(paths["candidate_dir"]), "candidate directory")
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
    command = [
        executable, "exec",
        "--json",
        "--ephemeral",
        "--strict-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--ask-for-approval", "never",
        "--sandbox", "workspace-write",
        "--model", model,
        "--cd", str(candidate_dir),
        "-c", 'web_search="disabled"',
        "-c", "hide_agent_reasoning=true",
        "-c", "show_raw_agent_reasoning=false",
        "-c", "check_for_update_on_startup=false",
        "-",
    ]

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
            raise ValueError(f"Codex exec failed with exit code {proc.returncode}; raw stderr was not preserved")
        trace = _parse_trace(trace_path)
        final_path.write_text(trace["final_message"], encoding="utf-8")
        result = {
            "schema_version": 1,
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
            },
            "conversation": {
                "thread_id": trace["thread_id"],
                "event_count": trace["event_count"],
                "reasoning_events_observed": trace["reasoning_events_observed"],
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
            },
            "limitations": [
                "integration smoke only; result must not be used for Feynman skill-effect inference",
                "model reasoning effort policy is explicitly model-default for integration smoke; behavioral pilot requires a new contract that freezes an explicit effort",
                "successful model execution does not by itself prove the post-run boundary canary/attestation lineage",
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
        )
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
