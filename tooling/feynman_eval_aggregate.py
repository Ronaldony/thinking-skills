#!/usr/bin/env python3
"""Aggregate analysis-ready Feynman evaluation records against a frozen plan.

The output is descriptive. It rejects duplicates/mismatched jobs and reports
missing jobs instead of silently changing denominators. It does not claim
statistical significance or causal skill effectiveness.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
from typing import Any, Iterable

PRIMARY_CONDITIONS = ("baseline", "generic", "legacy-clean", "feynman-v05")
DECISION_SCORE = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return value


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 6) if values else None


def _expected_phase(job: dict[str, Any]) -> str:
    return "followup" if job.get("has_followup") is True else "initial"


def _result_key(record: dict[str, Any]) -> tuple[str, str, int, str]:
    job = record.get("job")
    if not isinstance(job, dict):
        raise ValueError("result has no job object")
    case_id = job.get("case_id")
    condition = job.get("condition")
    repeat = job.get("repeat")
    phase = job.get("phase")
    if not isinstance(case_id, str) or condition not in PRIMARY_CONDITIONS:
        raise ValueError("result has invalid case/condition")
    if type(repeat) is not int or repeat < 1 or phase not in {"initial", "followup"}:
        raise ValueError("result has invalid repeat/phase")
    return case_id, condition, repeat, phase


def _validate_result(record: dict[str, Any]) -> None:
    if record.get("schema_version") != 1 or record.get("valid_for_analysis") is not True:
        raise ValueError("result is not marked analysis-ready")
    _result_key(record)
    metrics = record.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("result has no metrics object")
    if metrics.get("decision_correctness") not in {"correct", "partial", "incorrect", "unverified"}:
        raise ValueError("invalid decision_correctness")
    if metrics.get("execution_integrity") not in {"clean", "failure", "unverified"}:
        raise ValueError("invalid execution_integrity")
    if metrics.get("update_behavior") not in {
        "not_applicable", "justified_revision", "justified_retention",
        "unjustified_revision", "unjustified_retention", "unverified"
    }:
        raise ValueError("invalid update_behavior")
    supported = metrics.get("required_findings_supported")
    total = metrics.get("required_findings_total")
    if type(supported) is not int or type(total) is not int or total < 1 or not 0 <= supported <= total:
        raise ValueError("invalid required finding counts")
    if metrics.get("critical_failure") is not bool(metrics.get("hard_failure_ids")):
        raise ValueError("critical_failure flag differs from hard_failure_ids")
    if metrics.get("gate_verdict") not in {"passed", "failed", "unverified"}:
        raise ValueError("invalid gate verdict")
    behavior = metrics.get("behavior_scores")
    if not isinstance(behavior, dict) or not all(type(v) is int and v in {0, 1, 2} for v in behavior.values()):
        raise ValueError("invalid behavior_scores")


def _condition_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = [r["metrics"]["decision_correctness"] for r in records]
    supported = sum(r["metrics"]["required_findings_supported"] for r in records)
    total_findings = sum(r["metrics"]["required_findings_total"] for r in records)
    critical = sum(bool(r["metrics"]["critical_failure"]) for r in records)
    execution_failure = sum(r["metrics"]["execution_integrity"] == "failure" for r in records)
    execution_unverified = sum(r["metrics"]["execution_integrity"] == "unverified" for r in records)
    verdicts = defaultdict(int)
    updates = defaultdict(int)
    behavior_values: dict[str, list[float]] = defaultdict(list)
    for record in records:
        verdicts[record["metrics"]["gate_verdict"]] += 1
        updates[record["metrics"]["update_behavior"]] += 1
        for name, score in record["metrics"]["behavior_scores"].items():
            behavior_values[name].append(float(score))
    count = len(records)
    return {
        "runs": count,
        "decision_correct": decisions.count("correct"),
        "decision_partial": decisions.count("partial"),
        "decision_incorrect": decisions.count("incorrect"),
        "decision_unverified": decisions.count("unverified"),
        "decision_correct_rate_over_all_runs": round(decisions.count("correct") / count, 6) if count else None,
        "required_finding_completion": round(supported / total_findings, 6) if total_findings else None,
        "critical_failure_runs": critical,
        "critical_failure_rate": round(critical / count, 6) if count else None,
        "execution_integrity_failures": execution_failure,
        "execution_integrity_failure_rate": round(execution_failure / count, 6) if count else None,
        "execution_integrity_unverified": execution_unverified,
        "gate_verdicts": dict(sorted(verdicts.items())),
        "update_behavior": dict(sorted(updates.items())),
        "mean_behavior_scores": {name: _mean(values) for name, values in sorted(behavior_values.items())},
    }


def _paired(records_by_key: dict[tuple[str, str, int, str], dict[str, Any]],
            comparator: str, target: str) -> dict[str, Any]:
    units: dict[tuple[str, int, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for (case_id, condition, repeat, phase), record in records_by_key.items():
        if condition in {comparator, target}:
            units[(case_id, repeat, phase)][condition] = record
    pairs = [pair for pair in units.values() if comparator in pair and target in pair]
    decision_deltas: list[float] = []
    finding_deltas: list[float] = []
    critical_deltas: list[float] = []
    execution_deltas: list[float] = []
    decision_unpaired = 0
    for pair in pairs:
        left, right = pair[comparator], pair[target]
        left_decision = DECISION_SCORE.get(left["metrics"]["decision_correctness"])
        right_decision = DECISION_SCORE.get(right["metrics"]["decision_correctness"])
        if left_decision is None or right_decision is None:
            decision_unpaired += 1
        else:
            decision_deltas.append(right_decision - left_decision)
        left_find = left["metrics"]["required_findings_supported"] / left["metrics"]["required_findings_total"]
        right_find = right["metrics"]["required_findings_supported"] / right["metrics"]["required_findings_total"]
        finding_deltas.append(right_find - left_find)
        critical_deltas.append(float(right["metrics"]["critical_failure"]) - float(left["metrics"]["critical_failure"]))
        execution_deltas.append(
            float(right["metrics"]["execution_integrity"] == "failure")
            - float(left["metrics"]["execution_integrity"] == "failure")
        )
    return {
        "comparator": comparator,
        "target": target,
        "paired_units": len(pairs),
        "decision_unverified_pairs": decision_unpaired,
        "mean_decision_score_delta_target_minus_comparator": _mean(decision_deltas),
        "mean_required_finding_completion_delta": _mean(finding_deltas),
        "mean_critical_failure_indicator_delta": _mean(critical_deltas),
        "mean_execution_integrity_failure_indicator_delta": _mean(execution_deltas),
        "scope": "paired descriptive deltas only; no uncertainty interval or significance claim",
    }


def aggregate(plan: dict[str, Any], records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    jobs = plan.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("eval plan jobs must be nonempty")
    expected: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("plan job must be object")
        key = (job.get("case_id"), job.get("condition"), job.get("repeat"), _expected_phase(job))
        if key in expected:
            raise ValueError(f"duplicate expected job key: {key}")
        expected[key] = job

    observed: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    models: set[str] = set()
    cli_versions: set[str] = set()
    runner_profiles: set[str] = set()
    for record in records:
        _validate_result(record)
        key = _result_key(record)
        if key in observed:
            raise ValueError(f"duplicate result job key: {key}")
        if key not in expected:
            raise ValueError(f"result does not correspond to frozen plan job: {key}")
        observed[key] = record
        versions = record.get("versions")
        if not isinstance(versions, dict):
            raise ValueError("result has no versions object")
        model, cli = versions.get("model"), versions.get("codex_cli")
        if not isinstance(model, str) or not model or not isinstance(cli, str) or not cli:
            raise ValueError("result model/Codex versions must be nonempty")
        models.add(model)
        cli_versions.add(cli)
        runner = record.get("runner")
        if not isinstance(runner, dict) or not isinstance(runner.get("profile_sha256"), str):
            raise ValueError("result has no runner profile")
        runner_profiles.add(runner["profile_sha256"])

    missing = sorted(expected.keys() - observed.keys())
    extra = sorted(observed.keys() - expected.keys())
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key, record in observed.items():
        by_condition[key[1]].append(record)

    return {
        "schema_version": 1,
        "status": "complete" if not missing and not extra else "incomplete",
        "expected_runs": len(expected),
        "observed_runs": len(observed),
        "missing_jobs": [
            {"case_id": c, "condition": k, "repeat": r, "phase": p} for c, k, r, p in missing
        ],
        "extra_jobs": [
            {"case_id": c, "condition": k, "repeat": r, "phase": p} for c, k, r, p in extra
        ],
        "environment_consistency": {
            "models": sorted(models),
            "codex_cli_versions": sorted(cli_versions),
            "runner_profile_sha256": sorted(runner_profiles),
            "single_model": len(models) <= 1,
            "single_codex_cli_version": len(cli_versions) <= 1,
            "single_runner_profile": len(runner_profiles) <= 1,
        },
        "conditions": {
            condition: _condition_summary(by_condition.get(condition, []))
            for condition in PRIMARY_CONDITIONS if condition in set(plan.get("conditions", []))
        },
        "paired_descriptive": {
            "generic_vs_feynman_v05": _paired(observed, "generic", "feynman-v05"),
            "legacy_clean_vs_feynman_v05": _paired(observed, "legacy-clean", "feynman-v05"),
            "baseline_vs_feynman_v05": _paired(observed, "baseline", "feynman-v05"),
        },
        "scope": "descriptive preregistered metrics; incomplete/mixed-environment results must not be presented as final validation",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--result", type=Path, action="append", default=[])
    parser.add_argument("--result-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = _load(args.plan.resolve())
        paths = list(args.result)
        if args.result_dir:
            paths.extend(sorted(args.result_dir.glob("*.json")))
        if not paths:
            raise ValueError("at least one --result or --result-dir JSON file is required")
        records = [_load(path.resolve()) for path in paths]
        result = aggregate(plan, records)
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
