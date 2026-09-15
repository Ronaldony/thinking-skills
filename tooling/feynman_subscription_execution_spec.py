#!/usr/bin/env python3
"""Freeze and revalidate the non-secret inputs of one subscription smoke job.

The execution spec is deliberately smaller than the runner job: it records
content digests, path identities, fixed boundary facts, and the preparation
fingerprint, but never serializes a path value, command, prompt, control-home
content, or environment.  It is model-free and does not start a process.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
SPEC_FIELDS = frozenset({
    "schema_version", "verdict", "job", "versions", "roles", "paths",
    "boundary", "isolation", "skills", "wiring", "authentication", "scope",
})
ROLE_FILE_FIELDS = (
    "eval_plan", "smoke_spec", "evaluator_case", "runner_job",
    "boundary_profile", "remote_environment", "candidate_task",
    "full_runner_binding", "codex_executable", "node_executable",
    "full_runner_adapter", "docker_executable",
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_sha(path: Path) -> str:
    return hashlib.sha256(
        str(path.resolve(strict=False)).casefold().encode("utf-8")
    ).hexdigest()


def _regular(path: Path, label: str) -> Path:
    value = path.expanduser().absolute()
    if value.is_symlink() or not value.is_file():
        raise ValueError(f"execution spec {label} is not a regular file")
    return value.resolve()


def _directory(path: Path, label: str) -> Path:
    value = path.expanduser().absolute()
    if value.is_symlink() or not value.is_dir():
        raise ValueError(f"execution spec {label} is not a real directory")
    return value.resolve()


def _inside(root: Path, child: Path) -> bool:
    return child == root or child.is_relative_to(root)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(_regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"execution spec {label} JSON root is not an object")
    return value


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _valid_image(value: Any) -> bool:
    return isinstance(value, str) and IMAGE_ID.fullmatch(value) is not None


def _role_digests(*, plan_path: Path, smoke_spec_path: Path,
                  evaluator_case_path: Path, runner_job_path: Path,
                  boundary_profile_path: Path, remote_environment_path: Path,
                  candidate_task_path: Path, binding_path: Path,
                  codex_bin: Path, node_bin: Path, adapter: Path,
                  docker_bin: Path) -> dict[str, str]:
    paths = {
        "eval_plan": plan_path,
        "smoke_spec": smoke_spec_path,
        "evaluator_case": evaluator_case_path,
        "runner_job": runner_job_path,
        "boundary_profile": boundary_profile_path,
        "remote_environment": remote_environment_path,
        "candidate_task": candidate_task_path,
        "full_runner_binding": binding_path,
        "codex_executable": codex_bin,
        "node_executable": node_bin,
        "full_runner_adapter": adapter,
        "docker_executable": docker_bin,
    }
    return {name: _sha(path) for name, path in paths.items()}


def build_execution_spec(*, plan_path: Path, smoke_spec_path: Path,
                         evaluator_case_path: Path, runner_job_path: Path,
                         boundary_profile_path: Path,
                         remote_environment_path: Path, binding_path: Path,
                         codex_bin: Path, node_bin: Path, adapter: Path,
                         docker_bin: Path, docker_config: Path,
                         docker_image_id: str, candidate_dir: Path,
                         evaluator_dir: Path, control_home: Path,
                         output_dir: Path, job: Mapping[str, Any],
                         preparation_fingerprint: str,
                         preflight: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a deterministic, non-secret spec without launching anything."""
    if not _valid_sha(preparation_fingerprint):
        raise ValueError("execution spec preparation fingerprint is invalid")
    if not _valid_image(docker_image_id):
        raise ValueError("execution spec full-runner image ID is invalid")

    plan_path = _regular(plan_path, "eval plan")
    smoke_spec_path = _regular(smoke_spec_path, "smoke spec")
    evaluator_case_path = _regular(evaluator_case_path, "evaluator case")
    runner_job_path = _regular(runner_job_path, "runner job")
    boundary_profile_path = _regular(boundary_profile_path, "boundary profile")
    remote_environment_path = _regular(remote_environment_path, "remote environment")
    binding_path = _regular(binding_path, "full-runner binding")
    codex_bin = _regular(codex_bin, "Codex executable")
    node_bin = _regular(node_bin, "Node executable")
    adapter = _regular(adapter, "full-runner adapter")
    docker_bin = _regular(docker_bin, "Docker executable")
    docker_config = _directory(docker_config, "Docker config")
    candidate_dir = _directory(candidate_dir, "candidate directory")
    evaluator_dir = _directory(evaluator_dir, "evaluator directory")
    control_home = _directory(control_home, "control CODEX_HOME")
    output_dir = output_dir.expanduser().absolute().resolve(strict=False)
    candidate_task = _regular(candidate_dir / "task.txt", "candidate task")
    profile = _load_object(boundary_profile_path, "boundary profile")
    runner_info = job.get("job") if isinstance(job.get("job"), Mapping) else {}
    versions = job.get("versions") if isinstance(job.get("versions"), Mapping) else {}
    paths = job.get("paths") if isinstance(job.get("paths"), Mapping) else {}
    skills = job.get("skills") if isinstance(job.get("skills"), Mapping) else {}
    auth = job.get("authentication") if isinstance(job.get("authentication"), Mapping) else {}
    condition = runner_info.get("condition_id")
    expected_skills = skills.get("expected_candidate_skills", [])
    if not isinstance(expected_skills, list) or not all(
        isinstance(value, str) and value for value in expected_skills
    ):
        raise ValueError("execution spec candidate skill list is invalid")
    expected_by_condition = {"baseline": [], "feynman-v05": ["feynman-thinking"]}
    if condition in expected_by_condition and expected_skills != expected_by_condition[condition]:
        raise ValueError("execution spec condition/skill intent differs")
    if (candidate_dir / ".codex").exists():
        raise ValueError("execution spec candidate contains project-local .codex")
    if not _inside(evaluator_dir, output_dir) or output_dir == evaluator_dir:
        raise ValueError("execution spec output is not evaluator-owned")
    if _inside(candidate_dir, evaluator_dir) or _inside(evaluator_dir, candidate_dir):
        raise ValueError("execution spec candidate and evaluator overlap")
    if _inside(control_home, evaluator_dir) or _inside(evaluator_dir, control_home):
        raise ValueError("execution spec evaluator and control home overlap")
    if not isinstance(profile.get("image_id"), str):
        # Lightweight unit fixtures can omit a profile image; the canonical
        # runner preflight rejects that before this builder is reached.
        boundary_image_id = "unknown"
    else:
        boundary_image_id = profile["image_id"]
    if boundary_image_id != "unknown" and not _valid_image(boundary_image_id):
        raise ValueError("execution spec boundary image ID is invalid")

    role_digests = _role_digests(
        plan_path=plan_path, smoke_spec_path=smoke_spec_path,
        evaluator_case_path=evaluator_case_path, runner_job_path=runner_job_path,
        boundary_profile_path=boundary_profile_path,
        remote_environment_path=remote_environment_path,
        candidate_task_path=candidate_task, binding_path=binding_path,
        codex_bin=codex_bin, node_bin=node_bin, adapter=adapter,
        docker_bin=docker_bin,
    )
    preflight_checks = {
        "structural_preflight_passed": bool(
            preflight and preflight.get("verdict") == "ready-for-local-chatgpt-session-check"
        ),
        "candidate_skill_preflight_valid": bool(
            preflight and preflight.get("preflight", {}).get(
                "candidate_skill_preflight_valid", False
            )
        ),
    }
    if preflight is not None and not all(preflight_checks.values()):
        raise ValueError("execution spec requires a passing structural and skill preflight")
    expected_auth = {
        "mode": "chatgpt-subscription",
        "control_plane_auth_source": "codex-session",
        "api_key_auth_allowed": False,
        "candidate_auth_exposed": False,
    }
    if auth and any(auth.get(key) != value for key, value in expected_auth.items()):
        raise ValueError("execution spec authentication contract drift")
    if paths and paths.get("candidate_dir"):
        if Path(str(paths["candidate_dir"])).resolve() != candidate_dir:
            raise ValueError("execution spec candidate path differs from runner job")

    return {
        "schema_version": 1,
        "verdict": "subscription-execution-spec-frozen",
        "job": {
            "run_id": job.get("run_id", "unknown"),
            "ordinal": runner_info.get("ordinal", 0),
            "case_id": runner_info.get("case_id", "unknown"),
            "condition_id": condition or "unknown",
            "repeat": runner_info.get("repeat", 0),
            "has_followup": runner_info.get("has_followup", False),
        },
        "versions": {
            "model": versions.get("model", "unknown"),
            "codex_cli": versions.get("codex_cli", "unknown"),
        },
        "roles": role_digests,
        "paths": {
            "candidate_dir_sha256": _path_sha(candidate_dir),
            "evaluator_dir_sha256": _path_sha(evaluator_dir),
            "control_home_sha256": _path_sha(control_home),
            "docker_config_sha256": _path_sha(docker_config),
            "output_dir_sha256": _path_sha(output_dir),
            "docker_config_contents_read": False,
        },
        "boundary": {
            "backend": profile.get("backend", "unknown"),
            "backend_version": profile.get("backend_version", "unknown"),
            "network_mode": profile.get("network_mode", "unknown"),
            "candidate_image_id": boundary_image_id,
            "full_runner_image_id": docker_image_id,
        },
        "isolation": {
            "candidate_project_codex_absent": True,
            "candidate_evaluator_disjoint": True,
            "candidate_control_home_disjoint": True,
            "evaluator_output_new_and_owned": True,
            "instruction_source_allowlist_required": True,
            "stale_startup_report_replay_allowed": False,
            "model_command_before_startup_gate_allowed": False,
            "preflight": preflight_checks,
        },
        "skills": {
            "expected_candidate_skills": list(expected_skills),
            "condition_intent_checked": condition in expected_by_condition,
        },
        "wiring": {
            "preparation_fingerprint": preparation_fingerprint,
            "full_runner_image_id": docker_image_id,
        },
        "authentication": {
            **expected_auth,
            "control_home_contents_read_by_spec": False,
            "credential_files_read_by_spec": False,
        },
        "scope": (
            "model-free frozen input contract for one ChatGPT-subscription "
            "integration smoke; not behavioral evaluation evidence"
        ),
    }


def _validate_shape(spec: Mapping[str, Any]) -> None:
    if set(spec) != SPEC_FIELDS:
        raise ValueError("execution spec fields do not match the fixed contract")
    if spec.get("schema_version") != 1 or spec.get("verdict") != "subscription-execution-spec-frozen":
        raise ValueError("execution spec schema or verdict is unsupported")
    roles = spec.get("roles")
    if not isinstance(roles, Mapping) or set(roles) != set(ROLE_FILE_FIELDS):
        raise ValueError("execution spec role digest set is invalid")
    if any(not _valid_sha(value) for value in roles.values()):
        raise ValueError("execution spec role digest is invalid")
    wiring = spec.get("wiring")
    if not isinstance(wiring, Mapping) or not _valid_sha(wiring.get("preparation_fingerprint")):
        raise ValueError("execution spec wiring fingerprint is invalid")
    boundary = spec.get("boundary")
    if not isinstance(boundary, Mapping):
        raise ValueError("execution spec boundary is invalid")
    if boundary.get("candidate_image_id") != "unknown" and not _valid_image(boundary.get("candidate_image_id")):
        raise ValueError("execution spec candidate image ID is invalid")
    if not _valid_image(boundary.get("full_runner_image_id")):
        raise ValueError("execution spec full-runner image ID is invalid")
    authentication = spec.get("authentication")
    if authentication != {
        "mode": "chatgpt-subscription",
        "control_plane_auth_source": "codex-session",
        "api_key_auth_allowed": False,
        "candidate_auth_exposed": False,
        "control_home_contents_read_by_spec": False,
        "credential_files_read_by_spec": False,
    }:
        raise ValueError("execution spec authentication contract is invalid")


def write_execution_spec(path: Path, spec: Mapping[str, Any]) -> None:
    """Persist one spec without allowing overwrite or payload expansion."""
    _validate_shape(spec)
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise ValueError("execution spec output must be new")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_execution_spec(path: Path) -> dict[str, Any]:
    path = _regular(path, "execution spec")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("execution spec JSON root is not an object")
    _validate_shape(value)
    return value


def assert_execution_spec_current(spec: Mapping[str, Any], **build_kwargs: Any) -> None:
    """Fail closed when any frozen non-secret input or wiring fact drifts."""
    _validate_shape(spec)
    current = build_execution_spec(**build_kwargs,
                                   preparation_fingerprint=spec["wiring"]["preparation_fingerprint"])
    if current != dict(spec):
        raise ValueError("frozen execution spec drift")
