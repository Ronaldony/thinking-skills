#!/usr/bin/env python3
"""Validate public Feynman development cases and evaluator rubrics.

The validator catches structural leakage and rubric-shape regressions before model
runs. It does not prove that rubric content is substantively correct; domain and
numeric expectations still require independent review.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SKILL_NAME = "feynman-thinking"
ALLOWED_BEHAVIORS = {
    "mechanism",
    "honesty",
    "direct_check",
    "correctness",
    "revision",
    "representation",
    "discrimination",
    "efficiency",
}
EVALUATOR_ONLY_KEYS = {
    "required_findings",
    "required_behaviors",
    "hard_failures",
    "requires_execution",
    "notes",
}
REQUIRED_CONTROL_CATEGORIES = {
    "positive-control",
    "multi-turn-reversal",
    "multi-turn-confirmation",
    "negative-trigger",
    "execution-integrity",
}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSONL file: {path}")
    values: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{line_no}: object required")
        values.append(item)
    return values


def _index(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError(f"{label} has missing id")
        if item_id in result:
            raise ValueError(f"duplicate {label} id: {item_id}")
        result[item_id] = item
    return result


def _definition_list(value: Any, *, case_id: str, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{case_id}: {label} must be a nonempty list")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{case_id}: {label} entries must be objects")
        item_id = item.get("id")
        text = item.get("text")
        if not isinstance(item_id, str) or not item_id or item_id in result:
            raise ValueError(f"{case_id}: invalid or duplicate {label} id: {item_id!r}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{case_id}: {label} {item_id} lacks text")
        result[item_id] = item
    return result


def validate(base: Path) -> dict[str, Any]:
    base = base.resolve()
    cases = _jsonl(base / "cases.jsonl")
    rubrics = _jsonl(base / "rubrics.jsonl")
    if not cases or not rubrics:
        raise ValueError("cases and rubrics must be nonempty")
    case_index = _index(cases, "case")
    rubric_index = _index(rubrics, "rubric")
    if set(case_index) != set(rubric_index):
        missing_rubric = sorted(set(case_index) - set(rubric_index))
        missing_case = sorted(set(rubric_index) - set(case_index))
        raise ValueError(
            f"case/rubric ids differ: missing_rubric={missing_rubric} missing_case={missing_case}"
        )

    categories: set[str] = set()
    followup_cases: list[str] = []
    execution_cases: list[str] = []
    hard_failure_count = 0

    for case_id, case in case_index.items():
        if case.get("split") != "public-development":
            raise ValueError(f"{case_id}: split must be public-development")
        prompt = case.get("prompt")
        category = case.get("category")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"{case_id}: nonempty prompt required")
        if not isinstance(category, str) or not category.strip():
            raise ValueError(f"{case_id}: category required")
        categories.add(category)
        leaked = EVALUATOR_ONLY_KEYS & set(case)
        if leaked:
            raise ValueError(f"{case_id}: evaluator-only keys leaked into case: {sorted(leaked)}")
        if "followup" in case:
            if not isinstance(case["followup"], str) or not case["followup"].strip():
                raise ValueError(f"{case_id}: followup must be a nonempty string")
            followup_cases.append(case_id)

        rubric = rubric_index[case_id]
        findings = _definition_list(rubric.get("required_findings"), case_id=case_id,
                                    label="required_findings")
        hard_failures = _definition_list(rubric.get("hard_failures"), case_id=case_id,
                                         label="hard_failures")
        overlap = set(findings) & set(hard_failures)
        if overlap:
            raise ValueError(f"{case_id}: finding/hard-failure IDs overlap: {sorted(overlap)}")
        hard_failure_count += len(hard_failures)

        behaviors = rubric.get("required_behaviors")
        if (not isinstance(behaviors, list) or not behaviors
                or not all(isinstance(x, str) and x for x in behaviors)
                or len(set(behaviors)) != len(behaviors)):
            raise ValueError(f"{case_id}: required_behaviors must be unique nonempty strings")
        unknown = sorted(set(behaviors) - ALLOWED_BEHAVIORS)
        if unknown:
            raise ValueError(f"{case_id}: unknown required behaviors: {unknown}")

        requires_execution = rubric.get("requires_execution")
        if type(requires_execution) is not bool:
            raise ValueError(f"{case_id}: requires_execution must be boolean")
        if requires_execution:
            execution_cases.append(case_id)
            fixture = base / "fixtures" / case_id
            if not fixture.is_dir() or fixture.is_symlink():
                raise ValueError(f"{case_id}: execution case requires a real fixture directory")
            regular_files = [
                path for path in fixture.rglob("*")
                if path.is_file() and not path.is_symlink()
            ]
            if not regular_files:
                raise ValueError(f"{case_id}: execution fixture is empty")

        notes = rubric.get("notes")
        if notes is not None and (not isinstance(notes, str) or not notes.strip()):
            raise ValueError(f"{case_id}: notes must be a nonempty string when present")

    missing_controls = REQUIRED_CONTROL_CATEGORIES - categories
    if missing_controls:
        raise ValueError(f"missing required control categories: {sorted(missing_controls)}")
    if len(followup_cases) < 2:
        raise ValueError("public development set must contain both revision and retention follow-up controls")
    if not execution_cases:
        raise ValueError("public development set must contain at least one execution-integrity case")

    return {
        "schema_version": 1,
        "cases": len(cases),
        "rubrics": len(rubrics),
        "followup_cases": sorted(followup_cases),
        "execution_cases": sorted(execution_cases),
        "hard_failure_definitions": hard_failure_count,
        "categories": sorted(categories),
        "scope": "structural/leakage validation only; substantive rubric truth requires separate review",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "evals" / SKILL_NAME,
    )
    args = parser.parse_args()
    try:
        result = validate(args.base)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
