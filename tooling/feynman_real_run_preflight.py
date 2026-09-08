#!/usr/bin/env python3
"""Validate a frozen Feynman job up to the first external-credential boundary.

This preflight deliberately does not read the control-plane credential value and
does not call a model service. It proves that the frozen plan job, runner-job v2,
candidate task bytes, boundary profile, canonical remote environment, real-model
control config, and filesystem skill preflight agree. A successful artifact means
"the next missing input is the operator-controlled model credential", not that a
model run, boundary canary, or behavioral result has succeeded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

try:
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_eval_preflight import preflight as skill_preflight
    from .feynman_real_model_control_config import validate_files as validate_control_config
    from .feynman_remote_exec_environment import validate_files as validate_remote_environment
    from .feynman_runner_job_validate import _load as load_job_json
    from .feynman_runner_job_validate import validate_job_files
except ImportError:
    from feynman_boundary_profile import validate_profile_file
    from feynman_eval_preflight import preflight as skill_preflight
    from feynman_real_model_control_config import validate_files as validate_control_config
    from feynman_remote_exec_environment import validate_files as validate_remote_environment
    from feynman_runner_job_validate import _load as load_job_json
    from feynman_runner_job_validate import validate_job_files

SHA_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PRIMARY_CONDITIONS = {"baseline", "generic", "legacy-clean", "feynman-v05"}


def _without_symlink_components(path: Path, label: str) -> Path:
    absolute = path.expanduser().absolute()
    parts = absolute.parts
    if not parts:
        raise ValueError(f"{label} path is empty")
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} path contains symlink component: {current}")
    return absolute


def _regular(path: Path, label: str) -> Path:
    absolute = _without_symlink_components(path, label)
    if not absolute.is_file():
        raise ValueError(f"{label} must be a regular file: {absolute}")
    return absolute.resolve()


def _real_directory(path: Path, label: str) -> Path:
    absolute = _without_symlink_components(path, label)
    if not absolute.is_dir():
        raise ValueError(f"{label} must be a real directory: {absolute}")
    return absolute.resolve()


def _json_object(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} JSON root must be object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_PATTERN.fullmatch(value) is not None


def _planned_job(plan: dict[str, Any], ordinal: int) -> dict[str, Any]:
    jobs = plan.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("eval plan has no jobs list")
    matches = [job for job in jobs if isinstance(job, dict) and job.get("ordinal") == ordinal]
    if len(matches) != 1:
        raise ValueError(f"eval plan must contain exactly one job with ordinal {ordinal}")
    return matches[0]


def _validate_plan_job(plan_path: Path, runner_job: dict[str, Any], ordinal: int) -> dict[str, Any]:
    plan = _json_object(plan_path, "eval plan")
    planned = _planned_job(plan, ordinal)
    job = runner_job.get("job")
    digests = runner_job.get("digests")
    if not isinstance(job, dict) or not isinstance(digests, dict):
        raise ValueError("runner job lacks job/digests objects")
    expected = {
        "ordinal": planned.get("ordinal"),
        "case_id": planned.get("case_id"),
        "condition_id": planned.get("condition"),
        "repeat": planned.get("repeat"),
        "has_followup": planned.get("has_followup") is True,
    }
    for field, value in expected.items():
        if job.get(field) != value:
            raise ValueError(f"runner job differs from frozen plan field: {field}")
    if job.get("condition_id") not in PRIMARY_CONDITIONS:
        raise ValueError("runner job has unsupported primary condition")
    if digests.get("eval_plan_sha256") != _sha(plan_path):
        raise ValueError("runner job does not bind supplied eval-plan bytes")
    prompt_sha = planned.get("candidate_prompt_sha256")
    if not _valid_sha(prompt_sha) or digests.get("candidate_prompt_sha256") != prompt_sha:
        raise ValueError("runner job prompt digest differs from frozen plan")
    return planned


def _validate_evaluator_case(
    evaluator_case_path: Path, runner_job: dict[str, Any], planned: dict[str, Any]
) -> dict[str, Any]:
    evaluator_case = _json_object(evaluator_case_path, "evaluator case")
    job = runner_job["job"]
    if evaluator_case.get("case_id") != job.get("case_id"):
        raise ValueError("evaluator case id differs from runner job")
    if evaluator_case.get("condition_id") != job.get("condition_id"):
        raise ValueError("evaluator condition differs from runner job")
    if evaluator_case.get("candidate_prompt_sha256") != planned.get("candidate_prompt_sha256"):
        raise ValueError("evaluator prompt digest differs from frozen plan")
    if evaluator_case.get("expected_skills") != runner_job.get("skills", {}).get("expected_candidate_skills"):
        raise ValueError("evaluator expected skills differ from runner job")
    return evaluator_case


def _validate_candidate_task(runner_job: dict[str, Any]) -> tuple[Path, str]:
    paths = runner_job.get("paths")
    digests = runner_job.get("digests")
    if not isinstance(paths, dict) or not isinstance(digests, dict):
        raise ValueError("runner job lacks paths/digests")
    candidate_raw = paths.get("candidate_dir")
    if not isinstance(candidate_raw, str) or not candidate_raw:
        raise ValueError("runner job has invalid candidate directory")
    candidate_dir = _real_directory(Path(candidate_raw), "candidate directory")
    task = _regular(candidate_dir / "task.txt", "candidate task")
    task_sha = _sha(task)
    if task_sha != digests.get("candidate_prompt_sha256"):
        raise ValueError("candidate task bytes differ from frozen prompt digest")
    return task, task_sha


def preflight_files(
    *,
    plan_path: Path,
    ordinal: int,
    evaluator_case_path: Path,
    runner_job_path: Path,
    boundary_profile_path: Path,
    remote_environment_path: Path,
    control_config_path: Path,
) -> dict[str, Any]:
    plan_path = _regular(plan_path, "eval plan")
    evaluator_case_path = _regular(evaluator_case_path, "evaluator case")
    runner_job_path = _regular(runner_job_path, "runner job")
    boundary_profile_path = _regular(boundary_profile_path, "boundary profile")
    remote_environment_path = _regular(remote_environment_path, "remote environment")
    control_config_path = _regular(control_config_path, "control config")

    runner_job = load_job_json(runner_job_path)
    if runner_job.get("schema_version") != 2:
        raise ValueError("real-run preflight requires runner-job schema v2")
    runner_validation = validate_job_files(runner_job_path, boundary_profile_path)
    if runner_validation.get("verdict") != "runner-job-valid":
        raise ValueError("runner job failed strict validation")

    planned = _validate_plan_job(plan_path, runner_job, ordinal)
    _validate_evaluator_case(evaluator_case_path, runner_job, planned)
    task_path, task_sha = _validate_candidate_task(runner_job)

    profile, profile_sha, _ = validate_profile_file(boundary_profile_path)
    if runner_job.get("boundary", {}).get("profile_sha256") != profile_sha:
        raise ValueError("runner job boundary profile digest drift")

    remote_validation = validate_remote_environment(
        runner_job_path, boundary_profile_path, remote_environment_path
    )
    if remote_validation.get("verdict") != "remote-exec-environment-valid":
        raise ValueError("remote environment failed canonical validation")

    control_validation = validate_control_config(
        runner_job_path, boundary_profile_path, control_config_path
    )
    if control_validation.get("verdict") != "real-model-control-config-valid":
        raise ValueError("real-model control config failed canonical validation")

    paths = runner_job["paths"]
    expected_skills = set(runner_job.get("skills", {}).get("expected_candidate_skills", []))
    skill_result = skill_preflight(
        Path(paths["candidate_dir"]),
        expected_skills,
        home=Path(paths["ephemeral_home"]),
        codex_home=Path(paths["codex_home"]),
    )

    auth = runner_job.get("authentication")
    if not isinstance(auth, dict):
        raise ValueError("runner job lacks authentication contract")
    env_key = auth.get("control_plane_credential_env_key")
    if control_validation.get("credential_env_key_name") != env_key:
        raise ValueError("control config credential env key differs from runner job")
    if auth.get("mode") != "control-plane-only" or auth.get("control_plane_credential_source") != "environment":
        raise ValueError("unsupported control-plane authentication architecture")
    if env_key in profile.get("candidate_env_keys", []):
        raise ValueError("control-plane credential env key is candidate-visible")

    return {
        "schema_version": 1,
        "verdict": "ready-for-control-plane-auth",
        "run_id": runner_job["run_id"],
        "job": {
            "ordinal": runner_job["job"]["ordinal"],
            "case_id": runner_job["job"]["case_id"],
            "condition_id": runner_job["job"]["condition_id"],
            "repeat": runner_job["job"]["repeat"],
            "has_followup": runner_job["job"]["has_followup"],
        },
        "versions": dict(runner_job["versions"]),
        "authentication": {
            "mode": auth["mode"],
            "credential_source": auth["control_plane_credential_source"],
            "credential_env_key_name": env_key,
            "credential_value_read_by_preflight": False,
            "candidate_auth_exposed": False,
        },
        "digests": {
            "eval_plan_sha256": _sha(plan_path),
            "evaluator_case_sha256": _sha(evaluator_case_path),
            "runner_job_sha256": _sha(runner_job_path),
            "boundary_profile_sha256": profile_sha,
            "remote_environment_sha256": _sha(remote_environment_path),
            "control_config_sha256": _sha(control_config_path),
            "candidate_task_sha256": task_sha,
        },
        "preflight": {
            "runner_job_valid": True,
            "frozen_plan_job_match": True,
            "candidate_task_bytes_match": True,
            "boundary_profile_valid": True,
            "remote_environment_valid": True,
            "real_model_control_config_valid": True,
            "candidate_skill_preflight_valid": True,
            "expected_candidate_skills": sorted(expected_skills),
            "system_skill_roots_observed": skill_result["system_skill_roots_observed"],
        },
        "required_external_input": {
            "kind": "control-plane-environment-credential",
            "env_key_name": env_key,
            "value_must_not_be_written_to_repository_or_candidate_artifacts": True,
        },
        "next_required_evidence": [
            "same-profile boundary canary/report for the actual run",
            "actual external model-service request/response trace",
            "post-run runner attestation schema v2",
            "recomputed runner-job-link schema v2",
            "analysis-result schema v3 after semantic review/gate",
        ],
        "scope": (
            "credential-free readiness proof only; no credential lookup, no external model request, "
            "no post-run boundary attestation, and no behavioral result"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--ordinal", type=int, required=True)
    parser.add_argument("--evaluator-case", type=Path, required=True)
    parser.add_argument("--runner-job", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--remote-environment", type=Path, required=True)
    parser.add_argument("--control-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = preflight_files(
            plan_path=args.plan,
            ordinal=args.ordinal,
            evaluator_case_path=args.evaluator_case,
            runner_job_path=args.runner_job,
            boundary_profile_path=args.boundary_profile,
            remote_environment_path=args.remote_environment,
            control_config_path=args.control_config,
        )
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"refusing to overwrite: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
