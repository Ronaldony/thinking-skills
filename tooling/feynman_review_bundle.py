#!/usr/bin/env python3
"""Assemble an evaluator-only semantic review package from case + evidence artifacts.

This does not call a judge model. It validates evidence file hashes and creates a
self-contained review input that can be supplied to a blinded human/model judge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _copy_regular(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"missing or unsafe evaluator asset: {source}")
    shutil.copyfile(source, target)


def _evidence_refs(index: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    records = index.get("records")
    if not isinstance(records, list):
        raise ValueError("evidence index records must be a list")
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("evidence record must be an object")
        for key in ("output", "payload"):
            ref = record.get(key)
            if ref is not None:
                if not isinstance(ref, dict):
                    raise ValueError(f"evidence reference {key} must be an object")
                refs.append(ref)
    return refs


def assemble(evaluator_dir: Path, evidence_bundle: Path, output_dir: Path,
             *, include_followup: bool = False) -> dict[str, Any]:
    evaluator_dir = evaluator_dir.resolve()
    evidence_bundle = evidence_bundle.resolve()
    output_dir = output_dir.absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"refusing to overwrite: {output_dir}")
    case = _load_json(evaluator_dir / "case.json")
    index = _load_json(evidence_bundle / "evidence-index.json")
    final_path = evidence_bundle / "final.md"
    if final_path.is_symlink() or not final_path.is_file():
        raise ValueError("candidate final is missing or unsafe")
    if index.get("reasoning_items_copied") != 0:
        raise ValueError("evidence bundle claims reasoning items were copied")
    prompt = case.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("evaluator case is missing the original prompt")
    followup = case.get("followup")
    if include_followup and not isinstance(followup, str):
        raise ValueError("followup phase requested for a case without followup")

    evidence_text: dict[str, str] = {}
    for ref in _evidence_refs(index):
        filename = ref.get("file")
        expected_sha = ref.get("stored_sha256")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError(f"unsafe evidence filename: {filename!r}")
        if not isinstance(expected_sha, str):
            raise ValueError(f"missing stored_sha256 for evidence file: {filename}")
        path = evidence_bundle / "evidence" / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or unsafe evidence file: {filename}")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha:
            raise ValueError(f"stored evidence hash mismatch: {filename}")
        evidence_text[filename] = raw.decode("utf-8", errors="replace")

    final_text = final_path.read_text(encoding="utf-8", errors="replace")
    review_input = {
        "schema_version": 1,
        "case_id": case.get("case_id"),
        "phase": "followup" if include_followup else "initial",
        "task": prompt,
        "followup": followup if include_followup else None,
        "rubric": case.get("rubric"),
        "candidate_final": final_text,
        "evidence_index": index,
        "evidence_files": evidence_text,
        "scope": "evaluator-only semantic review input; candidate must never receive this package",
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        _copy_regular(evaluator_dir / "judge-prompt.md", output_dir / "judge-prompt.md")
        _copy_regular(evaluator_dir / "review-schema.json", output_dir / "review-schema.json")
        (output_dir / "review-input.json").write_text(
            json.dumps(review_input, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "case_id": case.get("case_id"),
            "phase": review_input["phase"],
            "review_input_sha256": hashlib.sha256(
                (output_dir / "review-input.json").read_bytes()).hexdigest(),
            "judge_prompt_sha256": hashlib.sha256(
                (output_dir / "judge-prompt.md").read_bytes()).hexdigest(),
            "review_schema_sha256": hashlib.sha256(
                (output_dir / "review-schema.json").read_bytes()).hexdigest(),
            "source_trace_sha256": index.get("source_trace_sha256"),
            "trusted_execution_ids": index.get("trusted_execution_ids", []),
        }
        (output_dir / "review-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    except Exception:
        shutil.rmtree(output_dir)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluator-dir", type=Path, required=True)
    parser.add_argument("--evidence-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-followup", action="store_true")
    args = parser.parse_args()
    try:
        manifest = assemble(args.evaluator_dir, args.evidence_bundle, args.output,
                            include_followup=args.include_followup)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
