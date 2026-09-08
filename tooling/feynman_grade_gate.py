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
    hard = review.get("hard_failures", [])
    if not isinstance(hard, list) or not all(isinstance(x, str) for x in hard):
        raise ValueError("hard_failures must be a list of strings")
    claimed = review.get("executed_evidence_ids", [])
    if not isinstance(claimed, list) or not all(isinstance(x, str) for x in claimed):
        raise ValueError("executed_evidence_ids must be a list of strings")
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
    reasons.extend(f"hard failure: {x}" for x in hard if x.strip())
    unsupported = set(claimed) - trusted_execution_ids
    if unsupported:
        reasons.append("execution claims lack trusted matching records: " + ", ".join(sorted(unsupported)))
    if rubric.get("requires_execution") and not (set(claimed) & trusted_execution_ids):
        unverified.append("required execution evidence is absent")
    verdict = "failed" if reasons else "unverified" if unverified else "passed"
    return {"verdict": verdict, "reasons": reasons, "unverified": unverified,
            "scope": "structural gate over evaluator judgments, not an independent correctness finding"}
