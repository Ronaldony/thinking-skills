#!/usr/bin/env python3
"""Assemble one linkage-complete analysis-ready Feynman result (schema v3).

Schema v3 adds the missing pre-run edge to the existing evidence chain.  A
result is not analysis-ready unless the exact pre-execution runner job is bound
to the post-execution verified attestation through a recomputed runner-job-link.

The underlying semantic/evidence/review checks remain the v2 implementation;
this module wraps that implementation and upgrades only after the new linkage
checks succeed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .feynman_eval_result_v2_legacy import assemble as assemble_v2
    from .feynman_runner_job_link import bind as bind_runner_job
except ImportError:
    from feynman_eval_result_v2_legacy import assemble as assemble_v2
    from feynman_runner_job_link import bind as bind_runner_job

PRIMARY_CONDITIONS = {"baseline", "generic", "legacy-clean", "feynman-v05"}


def _load(path: Path, label: str) -> dict[str, Any]:
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe {label}: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} JSON root must be object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.resolve().read_bytes()).hexdigest()


def _planned_job(plan: dict[str, Any], ordinal: int) -> dict[str, Any]:
    jobs = plan.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("eval plan has no jobs list")
    matches = [j for j in jobs if isinstance(j, dict) and j.get("ordinal") == ordinal]
    if len(matches) != 1:
        raise ValueError(f"eval plan must contain exactly one job with ordinal {ordinal}")
    return matches[0]


def _verify_runner_job_against_plan(
    runner_job: dict[str, Any], plan: dict[str, Any], plan_path: Path, ordinal: int
) -> None:
    if runner_job.get("schema_version") != 2:
        raise ValueError("analysis result v3 requires runner-job schema v2")
    planned = _planned_job(plan, ordinal)
    info = runner_job.get("job")
    digests = runner_job.get("digests")
    if not isinstance(info, dict) or not isinstance(digests, dict):
        raise ValueError("runner job lacks job/digests objects")

    expected = {
        "ordinal": planned.get("ordinal"),
        "case_id": planned.get("case_id"),
        "condition_id": planned.get("condition"),
        "repeat": planned.get("repeat"),
        "has_followup": planned.get("has_followup"),
    }
    for field, value in expected.items():
        if info.get(field) != value:
            raise ValueError(f"runner job differs from frozen plan field: {field}")

    condition = info.get("condition_id")
    if condition not in PRIMARY_CONDITIONS:
        raise ValueError("runner job has unsupported primary condition")
    if digests.get("eval_plan_sha256") != _sha(plan_path):
        raise ValueError("runner job is not bound to the supplied frozen plan bytes")
    if digests.get("candidate_prompt_sha256") != planned.get("candidate_prompt_sha256"):
        raise ValueError("runner job prompt digest differs from frozen plan")
    if digests.get("runtime_sha256") != runner_job.get("skills", {}).get("runtime_sha256"):
        raise ValueError("runner job runtime digest differs between skills and digests")


def _verify_saved_link(
    saved: dict[str, Any], recomputed: dict[str, Any], *, runner_job_path: Path,
    attestation_path: Path, plan_path: Path
) -> None:
    if saved != recomputed:
        raise ValueError("saved runner-job-link differs from recomputed linkage")
    if saved.get("schema_version") != 2 or saved.get("verdict") != "runner-job-attestation-bound":
        raise ValueError("runner-job-link is not canonical schema v2")
    if saved.get("runner_job_sha256") != _sha(runner_job_path):
        raise ValueError("runner-job-link does not bind supplied runner job bytes")
    if saved.get("runner_attestation_sha256") != _sha(attestation_path):
        raise ValueError("runner-job-link does not bind supplied attestation bytes")
    if saved.get("eval_plan_sha256") != _sha(plan_path):
        raise ValueError("runner-job-link does not bind supplied eval plan bytes")


def assemble(
    plan_path: Path,
    ordinal: int,
    evaluator_case_path: Path,
    attestation_path: Path,
    semantic_review_path: Path,
    gate_path: Path,
    *,
    runner_job_path: Path | None = None,
    runner_job_link_path: Path | None = None,
    review_bundle_path: Path | None = None,
    probe_report_path: Path | None = None,
    boundary_profile_path: Path | None = None,
    allowed_system_skills: set[str] | None = None,
    allow_plugins: bool = False,
) -> dict[str, Any]:
    if runner_job_path is None:
        raise ValueError("analysis-ready result v3 requires the pre-execution runner job")
    if runner_job_link_path is None:
        raise ValueError("analysis-ready result v3 requires the runner-job-link artifact")
    if review_bundle_path is None:
        raise ValueError("analysis-ready result v3 requires the evaluator review bundle")
    if probe_report_path is None:
        raise ValueError("analysis-ready result v3 requires a verified boundary probe report")
    if boundary_profile_path is None:
        raise ValueError("analysis-ready result v3 requires the original boundary profile manifest")

    plan_path = plan_path.resolve()
    runner_job_path = runner_job_path.resolve()
    runner_job_link_path = runner_job_link_path.resolve()
    attestation_path = attestation_path.resolve()
    boundary_profile_path = boundary_profile_path.resolve()
    probe_report_path = probe_report_path.resolve()

    plan = _load(plan_path, "eval plan")
    runner_job = _load(runner_job_path, "runner job")
    saved_link = _load(runner_job_link_path, "runner-job-link")
    _verify_runner_job_against_plan(runner_job, plan, plan_path, ordinal)

    recomputed_link = bind_runner_job(
        runner_job_path=runner_job_path,
        boundary_profile_path=boundary_profile_path,
        probe_report_path=probe_report_path,
        attestation_path=attestation_path,
        allowed_system_skills=allowed_system_skills or set(),
        allow_plugins=allow_plugins,
    )
    _verify_saved_link(
        saved_link,
        recomputed_link,
        runner_job_path=runner_job_path,
        attestation_path=attestation_path,
        plan_path=plan_path,
    )

    legacy = assemble_v2(
        plan_path,
        ordinal,
        evaluator_case_path,
        attestation_path,
        semantic_review_path,
        gate_path,
        review_bundle_path=review_bundle_path,
        probe_report_path=probe_report_path,
        boundary_profile_path=boundary_profile_path,
        allowed_system_skills=allowed_system_skills or set(),
        allow_plugins=allow_plugins,
    )
    if legacy.get("schema_version") != 2 or legacy.get("valid_for_analysis") is not True:
        raise ValueError("legacy evidence/review linkage did not produce a valid schema-v2 base result")

    if legacy.get("run_id") != saved_link.get("run_id"):
        raise ValueError("runner-job-link run_id differs from evidence result")
    result_job = legacy.get("job", {})
    if result_job.get("case_id") != saved_link.get("case_id"):
        raise ValueError("runner-job-link case differs from evidence result")
    if result_job.get("condition") != saved_link.get("condition_id"):
        raise ValueError("runner-job-link condition differs from evidence result")
    versions = legacy.get("versions", {})
    if versions.get("model") != saved_link.get("model") or versions.get("codex_cli") != saved_link.get("codex_cli"):
        raise ValueError("runner-job-link model/Codex versions differ from evidence result")

    result = deepcopy(legacy)
    result["schema_version"] = 3
    result["authentication"] = {
        "mode": saved_link["authentication_mode"],
        "control_plane_credential_source": saved_link["control_plane_credential_source"],
        "control_plane_credential_env_key": saved_link["control_plane_credential_env_key"],
        "candidate_auth_exposed": False,
    }
    result["lineage"] = {
        "runner_job_attestation_bound": True,
        "runner_job_link_verdict": saved_link["verdict"],
    }
    result["digests"].update({
        "runner_job_sha256": _sha(runner_job_path),
        "runner_job_link_sha256": _sha(runner_job_link_path),
    })

    # Cross-check every digest duplicated by the saved linkage record.
    checks = {
        "eval_plan_sha256": saved_link["eval_plan_sha256"],
        "candidate_prompt_sha256": saved_link["candidate_prompt_sha256"],
        "runtime_sha256": saved_link["runtime_sha256"],
        "boundary_profile_sha256": saved_link["boundary_profile_sha256"],
        "probe_report_sha256": saved_link["probe_report_sha256"],
        "attestation_sha256": saved_link["runner_attestation_sha256"],
        "runner_job_sha256": saved_link["runner_job_sha256"],
    }
    for field, expected in checks.items():
        if result["digests"].get(field) != expected:
            raise ValueError(f"schema-v3 result/link digest mismatch: {field}")

    result["scope"] = (
        "frozen plan -> pre-run runner job -> verified boundary/profile/probe -> post-run attestation -> "
        "runner-job-link -> evidence/review/gate linkage; analysis-ready does not itself imply causal skill benefit"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--ordinal", type=int, required=True)
    parser.add_argument("--evaluator-case", type=Path, required=True)
    parser.add_argument("--runner-job", type=Path, required=True)
    parser.add_argument("--runner-job-link", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--probe-report", type=Path, required=True)
    parser.add_argument("--review-bundle", type=Path, required=True)
    parser.add_argument("--semantic-review", type=Path, required=True)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--allowed-system-skill", action="append", default=[])
    parser.add_argument("--allow-plugins", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = assemble(
            args.plan,
            args.ordinal,
            args.evaluator_case,
            args.attestation,
            args.semantic_review,
            args.gate,
            runner_job_path=args.runner_job,
            runner_job_link_path=args.runner_job_link,
            review_bundle_path=args.review_bundle,
            probe_report_path=args.probe_report,
            boundary_profile_path=args.boundary_profile,
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
