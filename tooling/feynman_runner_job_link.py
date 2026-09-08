#!/usr/bin/env python3
"""Bind a validated runner-job artifact to a verified runner attestation.

This creates an evaluator-side immutable linkage record. It does not launch a
model and does not prove the external boundary is honest; it ensures that the job
planned before execution and the attestation recorded after execution describe
the same run, model, paths, profile, network policy, authentication architecture,
skills and digests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_runner_attestation import validate as validate_attestation
    from .feynman_runner_job_validate import validate_job_files
except ImportError:
    from feynman_boundary_profile import validate_profile_file
    from feynman_runner_attestation import validate as validate_attestation
    from feynman_runner_job_validate import validate_job_files


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind(*, runner_job_path: Path, boundary_profile_path: Path,
         probe_report_path: Path, attestation_path: Path,
         allowed_system_skills: set[str] | None = None,
         allow_plugins: bool = False) -> dict[str, Any]:
    runner_job_path = runner_job_path.resolve()
    boundary_profile_path = boundary_profile_path.resolve()
    probe_report_path = probe_report_path.resolve()
    attestation_path = attestation_path.resolve()

    job = _load(runner_job_path)
    job_validation = validate_job_files(runner_job_path, boundary_profile_path)
    _, profile_sha, _ = validate_profile_file(boundary_profile_path)
    report = _load(probe_report_path)
    report_sha = _sha(probe_report_path)
    attestation = _load(attestation_path)
    attestation_result = validate_attestation(
        attestation,
        allow_plugins=allow_plugins,
        allowed_system_skills=allowed_system_skills or set(),
        probe_report=report,
        probe_report_sha256=report_sha,
    )
    if job_validation.get("verdict") != "runner-job-valid":
        raise ValueError("runner job is not valid")
    if attestation_result.get("verdict") != "contract-valid" or attestation_result.get("probe_report_bound") is not True:
        raise ValueError("runner attestation is not bound to a valid boundary report")

    job_info = job["job"]
    job_versions = job["versions"]
    job_paths = job["paths"]
    job_boundary = job["boundary"]
    job_network = job["network"]
    job_auth = job["authentication"]
    job_skills = job["skills"]
    job_digests = job["digests"]

    if job.get("run_id") != attestation.get("run_id"):
        raise ValueError("runner-job/attestation run_id mismatch")
    if job_info.get("case_id") != attestation.get("case_id"):
        raise ValueError("runner-job/attestation case_id mismatch")
    if job_info.get("condition_id") != attestation.get("condition_id"):
        raise ValueError("runner-job/attestation condition mismatch")
    if job_versions != attestation.get("versions"):
        raise ValueError("runner-job/attestation model or Codex version mismatch")

    attested_paths = attestation.get("paths")
    if not isinstance(attested_paths, dict):
        raise ValueError("attestation has no paths object")
    for field, value in job_paths.items():
        if attested_paths.get(field) != value:
            raise ValueError(f"runner-job/attestation path mismatch: {field}")

    attested_boundary = attestation.get("boundary")
    if not isinstance(attested_boundary, dict):
        raise ValueError("attestation has no boundary object")
    for field in ("profile_sha256", "backend", "backend_version"):
        if job_boundary.get(field) != attested_boundary.get(field):
            raise ValueError(f"runner-job/attestation boundary mismatch: {field}")
    if job_boundary.get("profile_sha256") != profile_sha:
        raise ValueError("runner job does not bind the supplied boundary profile bytes")

    attested_network = attestation.get("network")
    if not isinstance(attested_network, dict):
        raise ValueError("attestation has no network object")
    for field in (
        "case_requires_tool_network", "tool_network",
        "allowed_tool_destinations", "control_plane_separate_from_tool_network",
    ):
        if job_network.get(field) != attested_network.get(field):
            raise ValueError(f"runner-job/attestation network mismatch: {field}")

    attested_environment = attestation.get("environment")
    if not isinstance(attested_environment, dict):
        raise ValueError("attestation has no environment object")
    if sorted(job_boundary.get("candidate_env_keys", [])) != sorted(attested_environment.get("candidate_env_keys", [])):
        raise ValueError("runner-job/attestation candidate env-key mismatch")
    if job_skills.get("expected_candidate_skills") != attested_environment.get("expected_candidate_skills"):
        raise ValueError("runner-job/attestation expected skill-set mismatch")

    auth_pairs = {
        "mode": "control_plane_auth_mode",
        "control_plane_credential_source": "control_plane_credential_source",
        "control_plane_credential_env_key": "control_plane_credential_env_key",
    }
    for job_field, attestation_field in auth_pairs.items():
        if job_auth.get(job_field) != attested_environment.get(attestation_field):
            raise ValueError(
                f"runner-job/attestation authentication mismatch: {job_field}/{attestation_field}"
            )
    if attested_environment.get("api_auth_exposed_to_candidate_tools") is not False:
        raise ValueError("attestation claims candidate tool auth exposure")
    if job_auth.get("candidate_tool_auth_env_keys") != []:
        raise ValueError("runner job contains candidate tool auth env keys")
    if job_auth.get("candidate_readable_credential_files") != []:
        raise ValueError("runner job contains candidate-readable credential files")
    if job_auth.get("credential_command_arguments") != []:
        raise ValueError("runner job contains credential command arguments")

    attested_digests = attestation.get("digests")
    if not isinstance(attested_digests, dict):
        raise ValueError("attestation has no digests object")
    for field in ("eval_plan_sha256", "candidate_prompt_sha256", "runtime_sha256"):
        if job_digests.get(field) != attested_digests.get(field):
            raise ValueError(f"runner-job/attestation digest mismatch: {field}")
    if attested_digests.get("probe_report_sha256") != report_sha:
        raise ValueError("attestation does not bind supplied probe report bytes")

    credential_key = job_auth["control_plane_credential_env_key"]
    return {
        "schema_version": 2,
        "verdict": "runner-job-attestation-bound",
        "run_id": job["run_id"],
        "case_id": job_info["case_id"],
        "condition_id": job_info["condition_id"],
        "runner_job_sha256": _sha(runner_job_path),
        "boundary_profile_sha256": profile_sha,
        "probe_report_sha256": report_sha,
        "runner_attestation_sha256": _sha(attestation_path),
        "eval_plan_sha256": job_digests["eval_plan_sha256"],
        "candidate_prompt_sha256": job_digests["candidate_prompt_sha256"],
        "runtime_sha256": job_digests["runtime_sha256"],
        "model": job_versions["model"],
        "codex_cli": job_versions["codex_cli"],
        "authentication_mode": "control-plane-only",
        "control_plane_credential_source": "environment",
        "control_plane_credential_env_key": credential_key,
        "scope": "evaluator-side linkage between pre-execution runner job and post-execution verified attestation, including authentication architecture",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-job", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--probe-report", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--allowed-system-skill", action="append", default=[])
    parser.add_argument("--allow-plugins", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = bind(
            runner_job_path=args.runner_job,
            boundary_profile_path=args.boundary_profile,
            probe_report_path=args.probe_report,
            attestation_path=args.attestation,
            allowed_system_skills=set(args.allowed_system_skill),
            allow_plugins=args.allow_plugins,
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
