#!/usr/bin/env python3
"""Prepare separate candidate/evaluator directories for one public Feynman eval case.

This reduces accidental evaluator-data exposure but is not an OS or network sandbox.
The runner must expose only candidate_dir to the candidate process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

try:
    from .feynman_package import SKILL_NAME, build
except ImportError:  # direct script execution
    from feynman_package import SKILL_NAME, build


def _load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        item = json.loads(raw)
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError(f"{path}:{line_no}: invalid object/id")
        if item["id"] in result:
            raise ValueError(f"{path}:{line_no}: duplicate id {item['id']}")
        result[item["id"]] = item
    return result


def _ensure_disjoint(candidate_dir: Path, evaluator_dir: Path) -> None:
    c = candidate_dir.absolute()
    e = evaluator_dir.absolute()
    if c == e or c.resolve().is_relative_to(e.resolve()) or e.resolve().is_relative_to(c.resolve()):
        raise ValueError("candidate and evaluator directories must not contain one another")
    for path in (c, e):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"refusing to overwrite: {path}")


def prepare(repo_root: Path, case_id: str, candidate_dir: Path, evaluator_dir: Path,
            install_skill: bool = True) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    base = repo_root / "evals" / SKILL_NAME
    cases = _load_jsonl(base / "cases.jsonl")
    rubrics = _load_jsonl(base / "rubrics.jsonl")
    if case_id not in cases or case_id not in rubrics:
        raise ValueError(f"unknown case id: {case_id}")
    case = cases[case_id]
    rubric = rubrics[case_id]
    candidate_dir = candidate_dir.absolute()
    evaluator_dir = evaluator_dir.absolute()
    _ensure_disjoint(candidate_dir, evaluator_dir)
    for label, path in (("candidate", candidate_dir), ("evaluator", evaluator_dir)):
        if path.resolve().is_relative_to(repo_root):
            raise ValueError(f"{label} directory must be outside the source repository")

    candidate_dir.mkdir(parents=True)
    evaluator_dir.mkdir(parents=True)
    try:
        (candidate_dir / "task.txt").write_text(str(case["prompt"]) + "\n", encoding="utf-8")
        fixture_source = base / "fixtures" / case_id
        fixture_hashes: dict[str, str] = {}
        if fixture_source.is_dir():
            for source in sorted(fixture_source.rglob("*")):
                if source.is_symlink():
                    raise ValueError(f"fixture symlink is not allowed: {source}")
                if not source.is_file():
                    continue
                relative = source.relative_to(fixture_source)
                target = candidate_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                data = source.read_bytes()
                target.write_bytes(data)
                fixture_hashes[relative.as_posix()] = hashlib.sha256(data).hexdigest()

        runtime_manifest = None
        if install_skill:
            with tempfile.TemporaryDirectory(prefix="feynman-package-") as tmp:
                package_dir = Path(tmp) / "package"
                runtime_manifest = build(repo_root, package_dir)
                skill_target = candidate_dir / ".agents" / "skills" / SKILL_NAME
                skill_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(package_dir / SKILL_NAME, skill_target)

        for evaluator_asset in ("review-schema.json", "judge-prompt.md"):
            source = base / evaluator_asset
            if not source.is_file() or source.is_symlink():
                raise ValueError(f"missing or unsafe evaluator asset: {source}")
            shutil.copyfile(source, evaluator_dir / evaluator_asset)

        evaluator_record = {
            "schema_version": 1,
            "case_id": case_id,
            "split": case.get("split"),
            "followup": case.get("followup"),
            "rubric": rubric,
            "fixture_sha256": fixture_hashes,
            "skill_installed": install_skill,
            "runtime_manifest": runtime_manifest,
            "candidate_prompt_sha256": hashlib.sha256((str(case["prompt"]) + "\n").encode("utf-8")).hexdigest(),
            "scope": "workspace separation only; runner must sandbox candidate from evaluator and host files",
        }
        (evaluator_dir / "case.json").write_text(
            json.dumps(evaluator_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return evaluator_record
    except Exception:
        shutil.rmtree(candidate_dir, ignore_errors=True)
        shutil.rmtree(evaluator_dir, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--case", required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--evaluator-dir", type=Path, required=True)
    parser.add_argument("--no-skill", action="store_true")
    args = parser.parse_args()
    try:
        record = prepare(args.root, args.case, args.candidate_dir, args.evaluator_dir,
                         install_skill=not args.no_skill)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
