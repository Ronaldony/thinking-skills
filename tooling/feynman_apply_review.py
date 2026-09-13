#!/usr/bin/env python3
"""Apply the structural grade gate to a semantic review + trusted evidence bundle.

The review must be produced by a separate evaluator. This tool does not judge
semantic correctness; it verifies case/evidence linkage and applies gate rules.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .feynman_grade_gate import gate
except ImportError:  # direct script execution
    from feynman_grade_gate import gate


def _load_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(review_bundle: Path, review_path: Path, output_path: Path) -> dict[str, Any]:
    review_bundle = review_bundle.resolve()
    review_input_path = review_bundle / "review-input.json"
    review_manifest_path = review_bundle / "review-manifest.json"
    review_input = _load_object(review_input_path)
    manifest = _load_object(review_manifest_path)
    review = _load_object(review_path.resolve())
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite: {output_path}")

    if review_input.get("case_id") != manifest.get("case_id"):
        raise ValueError("review bundle case mismatch")
    expected_input_sha = manifest.get("review_input_sha256")
    actual_input_sha = _sha(review_input_path)
    if expected_input_sha != actual_input_sha:
        raise ValueError("review-input hash mismatch")
    if review.get("id") != review_input.get("case_id"):
        raise ValueError("semantic review case id mismatch")
    rubric = review_input.get("rubric")
    if not isinstance(rubric, dict):
        raise ValueError("review input has no rubric object")
    trusted_ids = manifest.get("trusted_execution_ids", [])
    if not isinstance(trusted_ids, list) or not all(isinstance(x, str) for x in trusted_ids):
        raise ValueError("trusted_execution_ids must be a list of strings")

    phase = review_input.get("phase")
    if phase not in {"initial", "followup"} or manifest.get("phase") != phase:
        raise ValueError("review bundle phase mismatch")
    if phase == "followup":
        thread_id = manifest.get("conversation_thread_id")
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError("followup review bundle lacks conversation continuity thread_id")
        if review_input.get("conversation_thread_id") != thread_id:
            raise ValueError("followup review input/manifest thread_id mismatch")
        if not isinstance(review_input.get("initial_candidate_final"), str):
            raise ValueError("followup review input lacks initial candidate answer")

    result = gate(rubric, review, set(trusted_ids))
    semantic_outcomes = result.get("semantic_outcomes")
    output = {
        "schema_version": 2 if semantic_outcomes is not None else 1,
        "case_id": review_input.get("case_id"),
        "phase": phase,
        "verdict": result["verdict"],
        "reasons": result["reasons"],
        "unverified": result["unverified"],
        "hard_failure_ids": result.get("hard_failure_ids", []),
        "semantic_outcomes": semantic_outcomes,
        "semantic_review_sha256": _sha(review_path.resolve()),
        "review_input_sha256": actual_input_sha,
        "review_manifest_sha256": _sha(review_manifest_path),
        "candidate_final_sha256": manifest.get("candidate_final_sha256"),
        "initial_candidate_final_sha256": manifest.get("initial_candidate_final_sha256"),
        "source_trace_sha256": manifest.get("source_trace_sha256"),
        "initial_source_trace_sha256": manifest.get("initial_source_trace_sha256"),
        "conversation_thread_id": manifest.get("conversation_thread_id"),
        "trusted_execution_ids": trusted_ids,
        "scope": "structural gate over an external semantic review; not independent semantic validation",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-bundle", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = apply(args.review_bundle, args.review, args.output)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
