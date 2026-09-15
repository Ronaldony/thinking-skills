#!/usr/bin/env python3
"""Assemble an evaluator-only semantic review package from case + evidence artifacts.

This does not call a judge model. It validates evidence/final hashes and creates a
self-contained review input that can be supplied to a blinded human/model judge.
For follow-up cases it also verifies that initial and follow-up evidence belong to
the same Codex thread and exposes both candidate answers to the evaluator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

TRUSTED_COMMAND_STATUSES = {"completed", "failed"}


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


def _validate_trusted_execution_ids(index: dict[str, Any]) -> list[str]:
    records = index.get("records")
    if not isinstance(records, list):
        raise ValueError("evidence index records must be a list")
    expected: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("evidence record must be an object")
        if record.get("kind") == "command_execution" and record.get("status") in TRUSTED_COMMAND_STATUSES:
            evidence_id = record.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id:
                raise ValueError("trusted command record has no evidence_id")
            expected.append(evidence_id)
    observed = index.get("trusted_execution_ids")
    if not isinstance(observed, list) or not all(isinstance(x, str) for x in observed):
        raise ValueError("trusted_execution_ids must be a list of strings")
    if observed != expected:
        raise ValueError("trusted_execution_ids do not match trusted command records")
    return observed


def _verified_evidence_bundle(bundle: Path) -> dict[str, Any]:
    bundle = bundle.resolve()
    index = _load_json(bundle / "evidence-index.json")
    final_path = bundle / "final.md"
    if final_path.is_symlink() or not final_path.is_file():
        raise ValueError("candidate final is missing or unsafe")
    if index.get("reasoning_items_copied") != 0:
        raise ValueError("evidence bundle claims reasoning items were copied")

    expected_final_sha = index.get("final_sha256")
    if not isinstance(expected_final_sha, str) or re.fullmatch(r"[0-9a-f]{64}", expected_final_sha) is None:
        raise ValueError("evidence index has invalid final_sha256")
    final_raw = final_path.read_bytes()
    actual_final_sha = hashlib.sha256(final_raw).hexdigest()
    if actual_final_sha != expected_final_sha:
        raise ValueError("candidate final hash mismatch")

    trusted_execution_ids = _validate_trusted_execution_ids(index)
    evidence_text: dict[str, str] = {}
    for ref in _evidence_refs(index):
        filename = ref.get("file")
        expected_sha = ref.get("stored_sha256")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError(f"unsafe evidence filename: {filename!r}")
        if not isinstance(expected_sha, str):
            raise ValueError(f"missing stored_sha256 for evidence file: {filename}")
        path = bundle / "evidence" / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or unsafe evidence file: {filename}")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha:
            raise ValueError(f"stored evidence hash mismatch: {filename}")
        evidence_text[filename] = raw.decode("utf-8", errors="replace")

    return {
        "index": index,
        "final_text": final_raw.decode("utf-8", errors="replace"),
        "final_sha256": actual_final_sha,
        "evidence_files": evidence_text,
        "trusted_execution_ids": trusted_execution_ids,
    }


def _same_thread(initial: dict[str, Any], followup: dict[str, Any]) -> str:
    initial_thread = initial["index"].get("thread_id")
    followup_thread = followup["index"].get("thread_id")
    if not isinstance(initial_thread, str) or not initial_thread.strip():
        raise ValueError("initial evidence has no thread_id; cannot prove conversation continuity")
    if not isinstance(followup_thread, str) or not followup_thread.strip():
        raise ValueError("followup evidence has no thread_id; cannot prove conversation continuity")
    if initial_thread != followup_thread:
        raise ValueError("initial and followup evidence belong to different Codex threads")
    initial_trace = initial["index"].get("source_trace_sha256")
    followup_trace = followup["index"].get("source_trace_sha256")
    if not isinstance(initial_trace, str) or not isinstance(followup_trace, str):
        raise ValueError("initial/followup evidence lacks source trace digests")
    if initial_trace == followup_trace:
        raise ValueError("followup evidence must come from a distinct resumed-turn trace")
    return initial_thread


def assemble(evaluator_dir: Path, evidence_bundle: Path, output_dir: Path,
             *, include_followup: bool = False,
             initial_evidence_bundle: Path | None = None) -> dict[str, Any]:
    evaluator_dir = evaluator_dir.resolve()
    evidence_bundle = evidence_bundle.resolve()
    output_dir = output_dir.absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"refusing to overwrite: {output_dir}")
    case = _load_json(evaluator_dir / "case.json")
    current = _verified_evidence_bundle(evidence_bundle)
    prompt = case.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("evaluator case is missing the original prompt")
    followup = case.get("followup")
    if include_followup and not isinstance(followup, str):
        raise ValueError("followup phase requested for a case without followup")
    if include_followup and initial_evidence_bundle is None:
        raise ValueError("followup review requires --initial-evidence-bundle")
    if not include_followup and initial_evidence_bundle is not None:
        raise ValueError("initial evidence bundle is only valid with --include-followup")

    initial: dict[str, Any] | None = None
    conversation_thread_id: str | None = None
    if include_followup:
        initial_path = initial_evidence_bundle.resolve()  # type: ignore[union-attr]
        if initial_path == evidence_bundle:
            raise ValueError("initial and followup evidence bundles must be distinct")
        initial = _verified_evidence_bundle(initial_path)
        conversation_thread_id = _same_thread(initial, current)

    review_input = {
        "schema_version": 2 if include_followup else 1,
        "case_id": case.get("case_id"),
        "phase": "followup" if include_followup else "initial",
        "task": prompt,
        "followup": followup if include_followup else None,
        "rubric": case.get("rubric"),
        "initial_candidate_final": initial["final_text"] if initial else None,
        "initial_evidence_index": initial["index"] if initial else None,
        "initial_evidence_files": initial["evidence_files"] if initial else None,
        "candidate_final": current["final_text"],
        "evidence_index": current["index"],
        "evidence_files": current["evidence_files"],
        "conversation_thread_id": conversation_thread_id,
        "scope": "evaluator-only semantic review input; candidate must never receive this package",
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        _copy_regular(evaluator_dir / "judge-prompt.md", output_dir / "judge-prompt.md")
        _copy_regular(evaluator_dir / "review-schema.json", output_dir / "review-schema.json")
        (output_dir / "review-input.json").write_text(
            json.dumps(review_input, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest = {
            "schema_version": 2 if include_followup else 1,
            "case_id": case.get("case_id"),
            "phase": review_input["phase"],
            "review_input_sha256": hashlib.sha256(
                (output_dir / "review-input.json").read_bytes()).hexdigest(),
            "judge_prompt_sha256": hashlib.sha256(
                (output_dir / "judge-prompt.md").read_bytes()).hexdigest(),
            "review_schema_sha256": hashlib.sha256(
                (output_dir / "review-schema.json").read_bytes()).hexdigest(),
            "source_trace_sha256": current["index"].get("source_trace_sha256"),
            "candidate_final_sha256": current["final_sha256"],
            "trusted_execution_ids": current["trusted_execution_ids"],
            "conversation_thread_id": conversation_thread_id,
            "initial_source_trace_sha256": (
                initial["index"].get("source_trace_sha256") if initial else None
            ),
            "initial_candidate_final_sha256": initial["final_sha256"] if initial else None,
            "initial_trusted_execution_ids": initial["trusted_execution_ids"] if initial else [],
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
    parser.add_argument("--initial-evidence-bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-followup", action="store_true")
    args = parser.parse_args()
    try:
        manifest = assemble(
            args.evaluator_dir,
            args.evidence_bundle,
            args.output,
            include_followup=args.include_followup,
            initial_evidence_bundle=args.initial_evidence_bundle,
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
