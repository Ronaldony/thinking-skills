#!/usr/bin/env python3
"""Create a deterministic randomized Feynman evaluation job plan; does not run models."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
from typing import Any

SKILL_NAME = "feynman-thinking"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_cases(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        item = json.loads(raw)
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError(f"{path}:{line_no}: invalid case")
        if item["id"] in result:
            raise ValueError(f"duplicate case id: {item['id']}")
        result[item["id"]] = item
    return result


def _load_conditions(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("conditions"), list):
        raise ValueError("conditions.json has invalid structure")
    result: dict[str, dict[str, Any]] = {}
    for item in data["conditions"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("invalid condition")
        if item["id"] in result:
            raise ValueError(f"duplicate condition id: {item['id']}")
        if not isinstance(item.get("prompt_prefix"), str):
            raise ValueError(f"condition {item['id']} has no prompt_prefix")
        expected = item.get("expected_skills")
        if not isinstance(expected, list) or not all(isinstance(x, str) for x in expected):
            raise ValueError(f"condition {item['id']} has invalid expected_skills")
        result[item["id"]] = item
    return result


def _candidate_prompt(prefix: str, task: str) -> str:
    return task if not prefix.strip() else f"{prefix.strip()}\n\n사용자 과제:\n{task}"


def _candidate_prompt_bytes(prompt: str) -> bytes:
    """Canonical bytes written to task.txt and attested by candidate_prompt_sha256."""
    return (prompt + "\n").encode("utf-8")


def build_plan(repo_root: Path, *, case_ids: list[str] | None = None,
               condition_ids: list[str] | None = None, repeats: int = 1,
               seed: int = 20260908) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be >=1")
    base = repo_root.resolve() / "evals" / SKILL_NAME
    cases_path = base / "cases.jsonl"
    conditions_path = base / "conditions.json"
    cases = _load_cases(cases_path)
    conditions = _load_conditions(conditions_path)
    selected_cases = list(cases) if not case_ids else case_ids
    selected_conditions = list(conditions) if not condition_ids else condition_ids
    unknown_cases = sorted(set(selected_cases) - set(cases))
    unknown_conditions = sorted(set(selected_conditions) - set(conditions))
    if unknown_cases:
        raise ValueError(f"unknown case ids: {unknown_cases}")
    if unknown_conditions:
        raise ValueError(f"unknown condition ids: {unknown_conditions}")
    if len(set(selected_cases)) != len(selected_cases) or len(set(selected_conditions)) != len(selected_conditions):
        raise ValueError("case and condition selections must not contain duplicates")

    jobs: list[dict[str, Any]] = []
    for case_id in selected_cases:
        case = cases[case_id]
        if case.get("split") != "public-development":
            raise ValueError(f"this planner only accepts public-development cases: {case_id}")
        task = str(case["prompt"])
        for condition_id in selected_conditions:
            condition = conditions[condition_id]
            prompt = _candidate_prompt(condition["prompt_prefix"], task)
            for repeat in range(1, repeats + 1):
                jobs.append({
                    "case_id": case_id,
                    "condition": condition_id,
                    "repeat": repeat,
                    "split": case["split"],
                    "has_followup": isinstance(case.get("followup"), str),
                    "skill_source": condition.get("skill_source"),
                    "expected_skills": condition["expected_skills"],
                    "required_source_commit": condition.get("required_source_commit"),
                    "candidate_prompt": prompt,
                    "candidate_prompt_sha256": hashlib.sha256(_candidate_prompt_bytes(prompt)).hexdigest(),
                })
    random.Random(seed).shuffle(jobs)
    for ordinal, job in enumerate(jobs, 1):
        job["ordinal"] = ordinal
    return {
        "schema_version": 1,
        "status": "execution-plan-no-model-results",
        "seed": seed,
        "repeats": repeats,
        "cases": selected_cases,
        "conditions": selected_conditions,
        "cases_sha256": _sha(cases_path),
        "conditions_sha256": _sha(conditions_path),
        "jobs": jobs,
        "scope": "public-development plan only; held-out final planning must use a separately frozen dataset",
    }


def write_plan(plan: dict[str, Any], output: Path) -> None:
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--condition", action="append", dest="condition_ids")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260908)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = build_plan(args.root, case_ids=args.case_ids, condition_ids=args.condition_ids,
                          repeats=args.repeats, seed=args.seed)
        write_plan(plan, args.output)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps({k: plan[k] for k in ("status", "seed", "repeats", "cases", "conditions")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
