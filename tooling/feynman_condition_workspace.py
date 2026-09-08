#!/usr/bin/env python3
"""Prepare one condition-specific candidate/evaluator workspace from a frozen eval plan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

try:
    from .feynman_eval_plan import build_plan
    from .feynman_eval_workspace import prepare
    from .feynman_legacy_package import build as build_legacy
except ImportError:  # direct script execution
    from feynman_eval_plan import build_plan
    from feynman_eval_workspace import prepare
    from feynman_legacy_package import build as build_legacy


def prepare_condition(repo_root: Path, case_id: str, condition_id: str,
                      candidate_dir: Path, evaluator_dir: Path,
                      *, legacy_root: Path | None = None) -> dict[str, Any]:
    plan = build_plan(repo_root, case_ids=[case_id], condition_ids=[condition_id], repeats=1, seed=0)
    job = plan["jobs"][0]
    source = job["skill_source"]
    install_current = source == "current-runtime"
    if source not in {"none", "current-runtime", "external-pinned-legacy-v0.4"}:
        raise ValueError(f"unsupported skill_source: {source}")
    if source == "external-pinned-legacy-v0.4" and legacy_root is None:
        raise ValueError("legacy-clean condition requires --legacy-root")

    record = prepare(repo_root, case_id, candidate_dir, evaluator_dir, install_skill=install_current)
    candidate_dir = candidate_dir.absolute()
    evaluator_dir = evaluator_dir.absolute()
    runtime_manifest = record.get("runtime_manifest")

    try:
        if source == "external-pinned-legacy-v0.4":
            with tempfile.TemporaryDirectory(prefix="feynman-legacy-clean-") as tmp:
                package = Path(tmp) / "package"
                runtime_manifest = build_legacy(legacy_root, package)  # fixed pinned commit by default
                target = candidate_dir / ".agents" / "skills" / "feynman-thinking"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(package / "feynman-thinking", target)

        candidate_prompt = job["candidate_prompt"]
        (candidate_dir / "task.txt").write_text(candidate_prompt + "\n", encoding="utf-8")
        case_path = evaluator_dir / "case.json"
        evaluator_record = json.loads(case_path.read_text(encoding="utf-8"))
        evaluator_record.update({
            "condition_id": condition_id,
            "skill_source": source,
            "expected_skills": job["expected_skills"],
            "required_source_commit": job.get("required_source_commit"),
            "skill_installed": bool(job["expected_skills"]),
            "runtime_manifest": runtime_manifest,
            "candidate_prompt_sha256": hashlib.sha256((candidate_prompt + "\n").encode("utf-8")).hexdigest(),
            "conditions_sha256": plan["conditions_sha256"],
            "note": "condition metadata is evaluator-side run metadata and is intentionally omitted from semantic review-input.json",
        })
        case_path.write_text(json.dumps(evaluator_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return evaluator_record
    except Exception:
        shutil.rmtree(candidate_dir, ignore_errors=True)
        shutil.rmtree(evaluator_dir, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--case", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--evaluator-dir", type=Path, required=True)
    parser.add_argument("--legacy-root", type=Path)
    args = parser.parse_args()
    try:
        result = prepare_condition(args.root, args.case, args.condition,
                                   args.candidate_dir, args.evaluator_dir,
                                   legacy_root=args.legacy_root)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
