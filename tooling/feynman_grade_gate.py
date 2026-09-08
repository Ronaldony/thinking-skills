"""Structural grade gate. Semantic judgments and trusted execution IDs come from the evaluator."""
from __future__ import annotations
from typing import Any

VALID_FINDING_STATES = {"supported", "missed", "contradicted", "unverified"}


def _unique(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        raise ValueError(f"{label} must be a list")
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError(f"invalid {label} id")
        if item["id"] in result:
            raise ValueError(f"duplicate {label} id: {item['id']}")
        result[item["id"]] = item
    return result


def gate(rubric: dict[str, Any], review: dict[str, Any],
         trusted_execution_ids: set[str] | None = None) -> dict[str, Any]:
    """Return passed/failed/unverified; never infer semantic correctness from labels alone.

    trusted_execution_ids must be supplied by the evaluator from verified tool logs,
    not by the candidate. This helper does not parse or authenticate logs itself.

    Production/public-development rubrics predefine hard-failure IDs. A legacy
    synthetic rubric that omits the `hard_failures` field may still report a
    free-text hard failure, but such a report can only make the verdict fail; it
    can never pass or be promoted into a standardized critical-failure metric.
    """
    trusted_execution_ids = trusted_execution_ids or set()
    if rubric.get("id") != review.get("id"):
        raise ValueError("case id mismatch")
    expected = _unique(rubric["required_findings"], "rubric finding")
    found = _unique(review["findings"], "review finding")
    if set(expected) != set(found):
        raise ValueError("missing or unexpected finding ids")

    required = rubric["required_behaviors"]
    if not isinstance(required, list) or len(set(required)) != len(required):
        raise ValueError("required behavior ids must be unique")
    behavior = review.get("behaviors")
    if not isinstance(behavior, dict) or set(behavior) != set(required):
        raise ValueError("missing or unexpected behavior ids")
    for score in behavior.values():
        if type(score) is not int or score not in {0, 1, 2}:
            raise ValueError("required scores must be integer 0/1/2, not NA or boolean")

    hard_specified = "hard_failures" in rubric
    hard_definitions = _unique(rubric.get("hard_failures", []), "rubric hard failure")
    hard = review.get("hard_failures", [])
    if (not isinstance(hard, list)
            or not all(isinstance(x, str) and x for x in hard)
            or len(set(hard)) != len(hard)):
        raise ValueError("hard_failures must be unique nonempty strings")
    if hard_specified:
        unknown_hard = sorted(set(hard) - set(hard_definitions))
        if unknown_hard:
            raise ValueError("semantic review reported undefined hard failure IDs: " + ", ".join(unknown_hard))

    claimed = review.get("executed_evidence_ids", [])
    if (not isinstance(claimed, list)
            or not all(isinstance(x, str) and x for x in claimed)
            or len(set(claimed)) != len(claimed)):
        raise ValueError("executed_evidence_ids must be unique nonempty strings")

    reasons: list[str] = []
    unverified: list[str] = []
    for fid, item in found.items():
        status = item.get("status")
        if status not in VALID_FINDING_STATES:
            raise ValueError(f"invalid finding status for {fid}")
        if status in {"missed", "contradicted"}:
            reasons.append(f"required finding not satisfied: {fid}")
        evidence = item.get("evidence")
        if status == "unverified" or not isinstance(evidence, str) or not evidence.strip():
            unverified.append(f"finding lacks reviewed evidence: {fid}")

    reasons.extend(f"required behavior below 2: {key}" for key, score in behavior.items() if score < 2)
    if hard_specified:
        for hard_id in hard:
            text = hard_definitions[hard_id].get("text")
            detail = f": {text}" if isinstance(text, str) and text.strip() else ""
            reasons.append(f"hard failure {hard_id}{detail}")
    else:
        reasons.extend(f"legacy unstructured hard failure: {item}" for item in hard)

    unsupported = set(claimed) - trusted_execution_ids
    if unsupported:
        reasons.append("execution claims lack trusted matching records: " + ", ".join(sorted(unsupported)))
    if rubric.get("requires_execution") and not (set(claimed) & trusted_execution_ids):
        unverified.append("required execution evidence is absent")

    verdict = "failed" if reasons else "unverified" if unverified else "passed"
    return {
        "verdict": verdict,
        "reasons": reasons,
        "unverified": unverified,
        "hard_failure_ids": hard if hard_specified else [],
        "unstructured_hard_failures": [] if hard_specified else hard,
        "scope": "structural gate over evaluator judgments, not an independent correctness finding",
    }
