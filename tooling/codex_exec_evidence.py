#!/usr/bin/env python3
"""Extract evaluator-trusted evidence from `codex exec --json` JSONL.

The extractor intentionally excludes reasoning items. It is an evidence-reduction
step, not a semantic judge and not a security boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

MAX_LINE_BYTES = 10 * 1024 * 1024
MAX_STORED_EVIDENCE_BYTES = 256 * 1024
TRUSTED_COMMAND_STATUSES = {"completed", "failed"}


def _safe_text_file(output_dir: Path, ordinal: int, kind: str, text: str) -> dict[str, Any]:
    encoded = text.encode("utf-8", errors="replace")
    full_sha = hashlib.sha256(encoded).hexdigest()
    truncated = len(encoded) > MAX_STORED_EVIDENCE_BYTES
    stored = encoded[:MAX_STORED_EVIDENCE_BYTES]
    if truncated:
        stored = stored.decode("utf-8", errors="replace").encode("utf-8")
    filename = f"{ordinal:04d}-{kind}.txt"
    path = output_dir / filename
    path.write_bytes(stored)
    return {
        "file": filename,
        "sha256": full_sha,
        "original_bytes": len(encoded),
        "stored_bytes": len(stored),
        "truncated": truncated,
    }


def _require_item_id(item: dict[str, Any], seen: set[str]) -> str:
    item_id = item.get("id")
    if not isinstance(item_id, str) or not item_id.strip():
        raise ValueError("completed evidence item is missing a nonempty id")
    if item_id in seen:
        raise ValueError(f"duplicate completed evidence item id: {item_id}")
    seen.add(item_id)
    return item_id


def extract(trace_path: Path, output_dir: Path) -> dict[str, Any]:
    trace_path = trace_path.resolve()
    if not trace_path.is_file():
        raise ValueError(f"trace not found: {trace_path}")
    output_dir = output_dir.absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"refusing to overwrite: {output_dir}")
    raw_trace = trace_path.read_bytes()
    trace_sha = hashlib.sha256(raw_trace).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=False)
    evidence_dir = output_dir / "evidence"
    evidence_dir.mkdir()

    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    trusted_execution_ids: list[str] = []
    final_message = ""
    thread_id: str | None = None
    relevant_ordinal = 0

    try:
        for line_no, raw_line in enumerate(raw_trace.splitlines(), 1):
            if not raw_line.strip():
                continue
            if len(raw_line) > MAX_LINE_BYTES:
                raise ValueError(f"trace line {line_no} exceeds {MAX_LINE_BYTES} bytes")
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {line_no}: {exc}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"trace line {line_no} must be a JSON object")
            if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
                thread_id = event["thread_id"]
            if event.get("type") != "item.completed":
                continue
            item = event.get("item")
            if not isinstance(item, dict):
                raise ValueError(f"item.completed at line {line_no} has no object item")
            item_type = item.get("type")
            if item_type == "reasoning":
                # Never copy reasoning summaries/content into evaluator evidence bundles.
                continue
            if item_type == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    final_message = text
                continue
            if item_type not in {"command_execution", "mcp_tool_call", "web_search", "file_change"}:
                continue

            item_id = _require_item_id(item, seen)
            relevant_ordinal += 1
            evidence_id = f"{item_type}:{item_id}"
            record: dict[str, Any] = {
                "evidence_id": evidence_id,
                "source_item_id": item_id,
                "kind": item_type,
                "trace_line": line_no,
            }

            if item_type == "command_execution":
                status = item.get("status")
                if status not in {"in_progress", "completed", "failed", "declined"}:
                    raise ValueError(f"invalid command status for {item_id}: {status!r}")
                command = item.get("command")
                if not isinstance(command, str):
                    raise ValueError(f"command_execution {item_id} has no command string")
                output = item.get("aggregated_output", "")
                if not isinstance(output, str):
                    raise ValueError(f"command_execution {item_id} has non-string aggregated_output")
                record.update({
                    "status": status,
                    "command": command,
                    "exit_code": item.get("exit_code"),
                    "output": _safe_text_file(evidence_dir, relevant_ordinal, "command", output),
                })
                if status in TRUSTED_COMMAND_STATUSES:
                    trusted_execution_ids.append(evidence_id)

            elif item_type == "mcp_tool_call":
                status = item.get("status")
                if status not in {"in_progress", "completed", "failed"}:
                    raise ValueError(f"invalid MCP status for {item_id}: {status!r}")
                payload = {
                    "server": item.get("server"),
                    "tool": item.get("tool"),
                    "arguments": item.get("arguments"),
                    "result": item.get("result"),
                    "error": item.get("error"),
                }
                serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
                record.update({"status": status,
                               "server": item.get("server"),
                               "tool": item.get("tool"),
                               "payload": _safe_text_file(evidence_dir, relevant_ordinal, "mcp", serialized)})

            elif item_type == "web_search":
                query = item.get("query")
                if not isinstance(query, str):
                    raise ValueError(f"web_search {item_id} has no query string")
                record.update({"query": query,
                               "note": "Codex exec web_search item proves the search action, not the truth of cited results."})

            elif item_type == "file_change":
                changes = item.get("changes")
                status = item.get("status")
                if not isinstance(changes, list) or status not in {"completed", "failed"}:
                    raise ValueError(f"invalid file_change item: {item_id}")
                record.update({"status": status, "changes": changes})

            records.append(record)

        index = {
            "schema_version": 1,
            "source": "codex-exec-jsonl",
            "source_trace_sha256": trace_sha,
            "thread_id": thread_id,
            "trusted_execution_ids": trusted_execution_ids,
            "records": records,
            "reasoning_items_copied": 0,
            "scope": "evaluator evidence extraction; actions are not semantic proof of conclusions",
        }
        (output_dir / "evidence-index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "final.md").write_text(final_message, encoding="utf-8")
        return index
    except Exception:
        shutil.rmtree(output_dir)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        index = extract(args.trace, args.output)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(index, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
