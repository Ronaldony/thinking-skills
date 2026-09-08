#!/usr/bin/env python3
"""Validate an external model-runner job against its original boundary profile.

Runner-job schema v2 describes the architecture actually exercised by the
references: model-service credential ownership belongs to the host-side control
plane, while candidate tools receive no auth material. The credential value is
never present in the job; only the environment-variable name that supplies the
control plane is recorded.
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
except ImportError:
    from feynman_boundary_profile import validate_profile_file

SHA_PATTERN = re.compile(r"[0-9a-f]{64}")
ENV_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SKILL_CONDITIONS = {"legacy-clean", "feynman-v05"}
NO_SKILL_CONDITIONS = {"baseline", "generic"}


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_PATTERN.fullmatch(value) is not None


def _absolute_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    return str(path.resolve(strict=False))


def validate_job(job: dict[str, Any], profile: dict[str, Any], profile_sha: str) -> dict[str, Any]:
    if job.get("schema_version") != 2:
        raise ValueError("unsupported runner job schema_version; expected 2")
    run_id = job.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("runner job run_id must be nonempty")

    job_info = job.get("job")
    versions = job.get("versions")
    paths = job.get("paths")
    boundary = job.get("boundary")
    network = job.get("network")
    auth = job.get("authentication")
    skills = job.get("skills")
    digests = job.get("digests")
    for name, value in (
        ("job", job_info), ("versions", versions), ("paths", paths),
        ("boundary", boundary), ("network", network), ("authentication", auth),
        ("skills", skills), ("digests", digests),
    ):
        if not isinstance(value, dict):
            raise ValueError(f"runner job {name} must be an object")

    condition = job_info.get("condition_id")
    if condition not in SKILL_CONDITIONS | NO_SKILL_CONDITIONS:
        raise ValueError("unsupported runner job condition")
    if not isinstance(job_info.get("case_id"), str) or not job_info["case_id"]:
        raise ValueError("runner job case_id must be nonempty")
    if type(job_info.get("ordinal")) is not int or job_info["ordinal"] < 1:
        raise ValueError("runner job ordinal must be positive integer")
    if type(job_info.get("repeat")) is not int or job_info["repeat"] < 1:
        raise ValueError("runner job repeat must be positive integer")
    if type(job_info.get("has_followup")) is not bool:
        raise ValueError("runner job has_followup must be boolean")

    for field in ("model", "codex_cli"):
        if not isinstance(versions.get(field), str) or not versions[field].strip():
            raise ValueError(f"runner job versions.{field} must be nonempty")

    path_values = {
        name: _absolute_string(paths.get(name), f"paths.{name}")
        for name in (
            "candidate_dir", "evaluator_dir", "source_repo", "ephemeral_home",
            "codex_home", "temp_dir", "real_home"
        )
    }
    candidate_owned = {
        path_values["candidate_dir"],
        path_values["ephemeral_home"],
        path_values["codex_home"],
        path_values["temp_dir"],
    }
    protected = {
        path_values["evaluator_dir"],
        path_values["source_repo"],
        path_values["real_home"],
    }
    if candidate_owned & protected:
        raise ValueError("candidate-owned and protected path roots must be disjoint")

    if not _valid_sha(profile_sha):
        raise ValueError("boundary profile digest must be SHA-256")
    if boundary.get("profile_sha256") != profile_sha or digests.get("boundary_profile_sha256") != profile_sha:
        raise ValueError("runner job boundary profile digest mismatch")
    if boundary.get("backend") != profile.get("backend"):
        raise ValueError("runner job boundary backend differs from profile")
    if boundary.get("backend_version") != profile.get("backend_version"):
        raise ValueError("runner job boundary backend version differs from profile")
    if boundary.get("network_mode") != profile.get("network_mode"):
        raise ValueError("runner job boundary network mode differs from profile")

    profile_env = profile.get("candidate_env_keys")
    job_env = boundary.get("candidate_env_keys")
    if not isinstance(profile_env, list) or not isinstance(job_env, list) or sorted(profile_env) != sorted(job_env):
        raise ValueError("runner job candidate env-key allowlist differs from profile")
    if not all(isinstance(key, str) and ENV_KEY_PATTERN.fullmatch(key) for key in job_env):
        raise ValueError("runner job candidate env keys must be valid environment variable names")

    profile_rw = profile.get("read_write_mounts")
    if not isinstance(profile_rw, list):
        raise ValueError("boundary profile read_write_mounts must be a list")
    normalized_profile_rw = {_absolute_string(value, "profile.read_write_mounts[]") for value in profile_rw}
    if normalized_profile_rw != candidate_owned:
        raise ValueError(
            "boundary profile writable mounts must equal candidate_dir + ephemeral_home + codex_home + temp_dir"
        )
    if any(root in normalized_profile_rw for root in protected):
        raise ValueError("protected path appears in boundary profile writable mounts")

    if auth.get("mode") != "control-plane-only":
        raise ValueError("runner job authentication mode must be control-plane-only")
    if auth.get("control_plane_credential_source") != "environment":
        raise ValueError("runner job currently supports only environment-sourced control-plane credentials")
    credential_key = auth.get("control_plane_credential_env_key")
    if not isinstance(credential_key, str) or ENV_KEY_PATTERN.fullmatch(credential_key) is None:
        raise ValueError("runner job control-plane credential env key is invalid")
    for field in (
        "candidate_tool_auth_env_keys",
        "candidate_readable_credential_files",
        "credential_command_arguments",
    ):
        if auth.get(field) != []:
            raise ValueError(f"runner job authentication field must stay empty: {field}")
    if credential_key in job_env or credential_key in profile_env:
        raise ValueError("control-plane credential env key must not be exposed to candidate tools")
    expected_auth_keys = {
        "mode", "control_plane_credential_source", "control_plane_credential_env_key",
        "candidate_tool_auth_env_keys", "candidate_readable_credential_files",
        "credential_command_arguments",
    }
    if set(auth) != expected_auth_keys:
        raise ValueError("runner job authentication contains missing or unexpected fields")

    case_requires_network = network.get("case_requires_tool_network")
    tool_network = network.get("tool_network")
    destinations = network.get("allowed_tool_destinations")
    if type(case_requires_network) is not bool or not isinstance(destinations, list):
        raise ValueError("runner job network fields are invalid")
    if len(set(destinations)) != len(destinations) or not all(isinstance(x, str) and x for x in destinations):
        raise ValueError("runner job network destinations must be unique nonempty strings")
    if network.get("control_plane_separate_from_tool_network") is not True:
        raise ValueError("runner job requires control-plane/tool-network separation")
    expected_tool_network = {"none": "blocked", "restricted": "restricted", "open": "open"}.get(profile["network_mode"])
    if tool_network != expected_tool_network:
        raise ValueError("runner job tool-network policy differs from profile")
    if not case_requires_network:
        if tool_network != "blocked" or destinations:
            raise ValueError("closed-network runner job must block tool network with no destinations")
    elif tool_network == "restricted" and not destinations:
        raise ValueError("restricted network runner job requires explicit destinations")

    expected_skills = ["feynman-thinking"] if condition in SKILL_CONDITIONS else []
    if skills.get("expected_candidate_skills") != expected_skills:
        raise ValueError("runner job expected skill set differs from condition")
    runtime_sha = skills.get("runtime_sha256")
    if digests.get("runtime_sha256") != runtime_sha:
        raise ValueError("runner job runtime digest fields disagree")
    if condition in SKILL_CONDITIONS:
        if not _valid_sha(runtime_sha):
            raise ValueError("skill condition requires runtime SHA-256")
    elif runtime_sha is not None:
        raise ValueError("no-skill condition must not have runtime SHA")

    for field in ("eval_plan_sha256", "candidate_prompt_sha256", "boundary_profile_sha256"):
        if not _valid_sha(digests.get(field)):
            raise ValueError(f"runner job digests.{field} must be SHA-256")

    return {
        "verdict": "runner-job-valid",
        "run_id": run_id,
        "case_id": job_info["case_id"],
        "condition_id": condition,
        "boundary_profile_sha256": profile_sha,
        "candidate_owned_roots": sorted(candidate_owned),
        "protected_roots": sorted(protected),
        "tool_network": tool_network,
        "authentication_mode": "control-plane-only",
        "control_plane_credential_source": "environment",
        "control_plane_credential_env_key": credential_key,
        "scope": "pre-execution runner-job/profile consistency; does not prove backend enforcement or real model-service auth",
    }


def validate_job_files(job_path: Path, profile_path: Path) -> dict[str, Any]:
    job = _load(job_path.resolve())
    profile, profile_sha, _ = validate_profile_file(profile_path.resolve())
    result = validate_job(job, profile, profile_sha)
    result["runner_job_sha256"] = _sha(job_path.resolve())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_job_files(args.job, args.boundary_profile)
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
