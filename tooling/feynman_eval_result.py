#!/usr/bin/env python3
"""Assemble one analysis-ready Feynman evaluation result record.

This joins a frozen eval-plan job, evaluator-side condition record, externally
validated runner attestation, evaluator review bundle, semantic review, and
structural gate output. It does not run a model or judge correctness itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

try:
    from .feynman_grade_gate import gate as recompute_gate
    from .feynman_runner_attestation import validate as validate_attestation
except ImportError:
    from feynman_grade_gate import gate as recompute_gate
    from feynman_runner_attestation import validate as validate_attestation

PRIMARY_CONDITIONS = {"baseline", "generic", "legacy-clean", "feynman-v05"}


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} must be SHA-256")
    return value


def _job(plan: dict[str, Any], ordinal: int) -> dict[str, Any]:
    jobs = plan.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("eval plan has no jobs list")
    matches = [item for item in jobs if isinstance(item, dict) and item.get("ordinal") == ordinal]
    if len(matches) != 1:
        raise ValueError(f"eval plan must contain exactly one job with ordinal {ordinal}")
    return matches[0]


def assemble(plan_path: Path, ordinal: int, evaluator_case_path: Path,
             attestation_path: Path, semantic_review_path: Path, gate_path: Path,
             *, review_bundle_path: Path | None = None,
             allowed_system_skills: set[str] | None = None,
             allow_plugins: bool = False) -> dict[str, Any]:
    plan_path = plan_path.resolve()
    evaluator_case_path = evaluator_case_path.resolve()
    attestation_path = attestation_path.resolve()
    semantic_review_path = semantic_review_path.resolve()
    gate_path = gate_path.resolve()
    if review_bundle_path is None:
        raise ValueError("analysis-ready result requires the evaluator review bundle")
    review_bundle_path = review_bundle_path.resolve()
    review_input_path = review_bundle_path / "review-input.json"
    review_manifest_path = review_bundle_path / "review-manifest.json"

    plan = _load(plan_path)
    job = _job(plan, ordinal)
    evaluator_case = _load(evaluator_case_path)
    attestation = _load(attestation_path)
    review_input = _load(review_input_path)
    review_manifest = _load(review_manifest_path)
    review = _load(semantic_review_path)
    gate = _load(gate_path)

    condition = job.get("condition")
    case_id = job.get("case_id")
    repeat = job.get("repeat")
    if condition not in PRIMARY_CONDITIONS:
        raise ValueError(f"unsupported primary condition: {condition!r}")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("job has invalid case_id")
    if type(repeat) is not int or repeat < 1:
        raise ValueError("job has invalid repeat")

    plan_sha = _sha(plan_path)
    attestation_result = validate_attestation(
        attestation,
        allow_plugins=allow_plugins,
        allowed_system_skills=allowed_system_skills or set(),
    )
    if attestation_result.get("verdict") != "contract-valid":
        raise ValueError("runner attestation is not contract-valid")
    if attestation.get("case_id") != case_id or attestation.get("condition_id") != condition:
        raise ValueError("runner attestation case/condition does not match eval-plan job")
    digests = attestation.get("digests")
    if not isinstance(digests, dict):
        raise ValueError("runner attestation has no digests object")
    if digests.get("eval_plan_sha256") != plan_sha:
        raise ValueError("runner attestation is not bound to this eval plan")
    if digests.get("candidate_prompt_sha256") != job.get("candidate_prompt_sha256"):
        raise ValueError("runner candidate prompt digest does not match eval-plan job")

    if evaluator_case.get("case_id") != case_id or evaluator_case.get("condition_id") != condition:
        raise ValueError("evaluator condition record does not match eval-plan job")
    if evaluator_case.get("candidate_prompt_sha256") != job.get("candidate_prompt_sha256"):
        raise ValueError("evaluator candidate prompt digest does not match eval-plan job")
    if evaluator_case.get("required_source_commit") != job.get("required_source_commit"):
        raise ValueError("evaluator required_source_commit differs from eval-plan job")

    runtime_manifest = evaluator_case.get("runtime_manifest")
    attested_runtime = digests.get("runtime_sha256")
    if condition in {"baseline", "generic"}:
        if runtime_manifest is not None or attested_runtime is not None:
            raise ValueError("no-skill condition must not have a runtime manifest/digest")
    else:
        if not isinstance(runtime_manifest, dict):
            raise ValueError("skill condition requires evaluator runtime manifest")
        if runtime_manifest.get("runtime_sha256") != attested_runtime:
            raise ValueError("runner runtime digest differs from evaluator runtime manifest")
        required_commit = job.get("required_source_commit")
        if required_commit is not None and runtime_manifest.get("source_commit") != required_commit:
            raise ValueError("legacy runtime source commit differs from preregistered commit")

    # Rebind semantic judging to the actual evaluator review package. Without this,
    # a hand-edited gate file could point at a different candidate/evidence bundle.
    actual_review_input_sha = _sha(review_input_path)
    actual_review_manifest_sha = _sha(review_manifest_path)
    if review_manifest.get("case_id") != case_id or review_input.get("case_id") != case_id:
        raise ValueError("review bundle case does not match eval-plan job")
    if review_manifest.get("review_input_sha256") != actual_review_input_sha:
        raise ValueError("review manifest is not bound to review-input.json")
    if gate.get("review_input_sha256") != actual_review_input_sha:
        raise ValueError("gate output is not bound to review-input.json")
    if gate.get("review_manifest_sha256") != actual_review_manifest_sha:
        raise ValueError("gate output is not bound to review-manifest.json")
    if review_input.get("task") != evaluator_case.get("prompt"):
        raise ValueError("review input task differs from evaluator case prompt")
    if review_input.get("rubric") != evaluator_case.get("rubric"):
        raise ValueError("review input rubric differs from evaluator case rubric")

    if review.get("schema_version") != 2 or review.get("id") != case_id:
        raise ValueError("analysis-ready result requires semantic review schema v2 for the same case")
    if gate.get("schema_version") != 2 or gate.get("case_id") != case_id:
        raise ValueError("analysis-ready result requires gate schema v2 for the same case")
    if gate.get("semantic_review_sha256") != _sha(semantic_review_path):
        raise ValueError("gate output is not bound to this semantic review")

    trusted_ids = review_manifest.get("trusted_execution_ids", [])
    if not isinstance(trusted_ids, list) or not all(isinstance(item, str) for item in trusted_ids):
        raise ValueError("review manifest trusted_execution_ids must be strings")
    if gate.get("trusted_execution_ids") != trusted_ids:
        raise ValueError("gate trusted execution IDs differ from review manifest")

    candidate_final_sha = _sha256_string(
        review_manifest.get("candidate_final_sha256"), "review candidate_final_sha256"
    )
    if gate.get("candidate_final_sha256") != candidate_final_sha:
        raise ValueError("gate candidate final digest differs from review manifest")
    source_trace_sha = _sha256_string(
        review_manifest.get("source_trace_sha256"), "review source_trace_sha256"
    )
    if gate.get("source_trace_sha256") != source_trace_sha:
        raise ValueError("gate source trace digest differs from review manifest")

    has_followup = isinstance(evaluator_case.get("followup"), str)
    phase = review_manifest.get("phase")
    conversation_thread_id: str | None = None
    initial_candidate_final_sha: str | None = None
    initial_source_trace_sha: str | None = None
    if has_followup:
        if phase != "followup" or gate.get("phase") != "followup" or review_input.get("phase") != "followup":
            raise ValueError("multi-turn case requires a followup review/gate phase")
        if review_input.get("followup") != evaluator_case.get("followup"):
            raise ValueError("review input followup differs from evaluator case")
        conversation_thread_id = review_manifest.get("conversation_thread_id")
        if not isinstance(conversation_thread_id, str) or not conversation_thread_id.strip():
            raise ValueError("multi-turn result lacks same-thread continuity proof")
        if review_input.get("conversation_thread_id") != conversation_thread_id:
            raise ValueError("review input/manifest conversation thread mismatch")
        if gate.get("conversation_thread_id") != conversation_thread_id:
            raise ValueError("gate/review-manifest conversation thread mismatch")
        if not isinstance(review_input.get("initial_candidate_final"), str):
            raise ValueError("multi-turn review input lacks initial candidate answer")
        initial_candidate_final_sha = _sha256_string(
            review_manifest.get("initial_candidate_final_sha256"),
            "review initial_candidate_final_sha256",
        )
        initial_source_trace_sha = _sha256_string(
            review_manifest.get("initial_source_trace_sha256"),
            "review initial_source_trace_sha256",
        )
        if gate.get("initial_candidate_final_sha256") != initial_candidate_final_sha:
            raise ValueError("gate initial final digest differs from review manifest")
        if gate.get("initial_source_trace_sha256") != initial_source_trace_sha:
            raise ValueError("gate initial trace digest differs from review manifest")
        if initial_source_trace_sha == source_trace_sha:
            raise ValueError("multi-turn result reuses the same trace for initial and followup")
        if review.get("update_behavior") == "not_applicable":
            raise ValueError("multi-turn semantic review must evaluate update_behavior")
    else:
        if phase != "initial" or gate.get("phase") != "initial" or review_input.get("phase") != "initial":
            raise ValueError("single-turn case requires initial review/gate phase")
        if review.get("update_behavior") != "not_applicable":
            raise ValueError("single-turn semantic review must use update_behavior=not_applicable")
        if review_manifest.get("conversation_thread_id") is not None:
            raise ValueError("single-turn result must not claim multi-turn continuity")

    # The saved gate is an artifact, not a trusted authority. Recompute it from
    # the semantic review, evaluator rubric, and review-manifest trusted IDs.
    recomputed = recompute_gate(evaluator_case["rubric"], review, set(trusted_ids))
    for field in ("verdict", "reasons", "unverified", "hard_failure_ids", "semantic_outcomes"):
        if gate.get(field) != recomputed.get(field):
            raise ValueError(f"saved gate differs from recomputed gate field: {field}")

    semantic_outcomes = gate.get("semantic_outcomes")
    expected_outcomes = {
        "decision_correctness": review.get("decision_correctness"),
        "execution_integrity": review.get("execution_integrity"),
        "update_behavior": review.get("update_behavior"),
    }
    if semantic_outcomes != expected_outcomes:
        raise ValueError("gate semantic outcomes differ from semantic review")
    if gate.get("hard_failure_ids") != review.get("hard_failures"):
        raise ValueError("gate hard-failure IDs differ from semantic review")

    findings = review.get("findings")
    if not isinstance(findings, list) or not findings:
        raise ValueError("semantic review findings must be a nonempty list")
    supported = sum(1 for item in findings if isinstance(item, dict) and item.get("status") == "supported")
    if any(not isinstance(item, dict) for item in findings):
        raise ValueError("semantic review finding entries must be objects")
    behaviors = review.get("behaviors")
    if not isinstance(behaviors, dict):
        raise ValueError("semantic review behaviors must be an object")

    return {
        "schema_version": 2,
        "valid_for_analysis": True,
        "run_id": attestation.get("run_id"),
        "job": {
            "ordinal": ordinal,
            "case_id": case_id,
            "condition": condition,
            "repeat": repeat,
            "phase": phase,
        },
        "versions": attestation.get("versions"),
        "runner": {
            "backend": attestation.get("boundary", {}).get("backend"),
            "backend_version": attestation.get("boundary", {}).get("backend_version"),
            "profile_sha256": attestation.get("boundary", {}).get("profile_sha256"),
        },
        "conversation": {
            "thread_id": conversation_thread_id,
            "initial_source_trace_sha256": initial_source_trace_sha,
            "followup_source_trace_sha256": source_trace_sha if has_followup else None,
        },
        "digests": {
            "eval_plan_sha256": plan_sha,
            "candidate_prompt_sha256": job.get("candidate_prompt_sha256"),
            "runtime_sha256": attested_runtime,
            "review_input_sha256": actual_review_input_sha,
            "review_manifest_sha256": actual_review_manifest_sha,
            "candidate_final_sha256": candidate_final_sha,
            "initial_candidate_final_sha256": initial_candidate_final_sha,
            "semantic_review_sha256": _sha(semantic_review_path),
            "gate_sha256": _sha(gate_path),
            "attestation_sha256": _sha(attestation_path),
            "evaluator_case_sha256": _sha(evaluator_case_path),
        },
        "metrics": {
            "decision_correctness": review.get("decision_correctness"),
            "required_findings_supported": supported,
            "required_findings_total": len(findings),
            "required_finding_completion": supported / len(findings),
            "critical_failure": bool(review.get("hard_failures")),
            "hard_failure_ids": review.get("hard_failures"),
            "execution_integrity": review.get("execution_integrity"),
            "update_behavior": review.get("update_behavior"),
            "behavior_scores": behaviors,
            "gate_verdict": gate.get("verdict"),
            "review_confidence": review.get("confidence"),
        },
        "limitations": attestation.get("limitations", []),
        "scope": "validated plan-to-run-to-evidence-to-review linkage and descriptive metrics; not a causal performance conclusion",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--ordinal", type=int, required=True)
    parser.add_argument("--evaluator-case", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
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
            review_bundle_path=args.review_bundle,
            allowed_system_skills=set(args.allowed_system_skill),
            allow_plugins=args.allow_plugins,
        )
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"refusing to overwrite: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
