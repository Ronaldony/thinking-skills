#!/usr/bin/env python3
"""Fail-closed exact-byte credential leak scanner for evaluation references.

The secret is read from a protected file so its raw value never appears in the
scanner command line. Candidate-owned roots and explicit evidence files are
walked without following symlinks. Every regular file is scanned for the exact
secret byte sequence. Oversized files, symlinks, special files, duplicate scan
targets, and total-byte limit exhaustion are errors rather than silent skips.

The report records only the secret SHA-256, never the secret bytes. This scanner
proves absence of the exact byte sequence in the scanned files; it does not prove
absence of encoded, transformed, encrypted, compressed, or otherwise derived
representations unless those bytes contain the exact secret sequence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

DEFAULT_MAX_FILE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_SECRET_BYTES = 4096


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _regular(path: Path, label: str) -> Path:
    path = path.absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file: {path}")
    return path.resolve()


def _root(path: Path, label: str) -> Path:
    path = path.absolute()
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{label} must be a directory and not a symlink: {path}")
    return path.resolve()


def _read_secret(path: Path) -> bytes:
    path = _regular(path, "secret file")
    data = path.read_bytes()
    if not data:
        raise ValueError("secret file must not be empty")
    if len(data) > MAX_SECRET_BYTES:
        raise ValueError(f"secret file exceeds maximum {MAX_SECRET_BYTES} bytes")
    # A trailing newline introduced by a shell write is not part of the secret.
    # Only one conventional line ending is stripped; embedded whitespace remains.
    if data.endswith(b"\r\n"):
        data = data[:-2]
    elif data.endswith(b"\n"):
        data = data[:-1]
    if not data:
        raise ValueError("secret becomes empty after removing trailing line ending")
    return data


def _iter_root_files(root: Path) -> Iterable[Path]:
    stack = [root]
    while stack:
        directory = stack.pop()
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
        for entry in entries:
            if entry.is_symlink():
                raise ValueError(f"symlink encountered in scan root: {entry}")
            if entry.is_dir():
                stack.append(entry)
                continue
            if not entry.is_file():
                raise ValueError(f"special/non-regular file encountered in scan root: {entry}")
            yield entry.resolve()


def scan(
    *,
    secret_file: Path,
    roots: list[Path],
    files: list[Path],
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    if type(max_file_bytes) is not int or max_file_bytes < 1:
        raise ValueError("max_file_bytes must be a positive integer")
    if type(max_total_bytes) is not int or max_total_bytes < 1:
        raise ValueError("max_total_bytes must be a positive integer")
    if max_total_bytes < max_file_bytes:
        raise ValueError("max_total_bytes must be >= max_file_bytes")
    if not roots and not files:
        raise ValueError("at least one scan root or explicit file is required")

    secret = _read_secret(secret_file)
    secret_sha = _sha_bytes(secret)
    resolved_roots = [_root(path, "scan root") for path in roots]
    resolved_files = [_regular(path, "explicit scan file") for path in files]
    if len(set(resolved_roots)) != len(resolved_roots):
        raise ValueError("duplicate scan roots are not allowed")
    if len(set(resolved_files)) != len(resolved_files):
        raise ValueError("duplicate explicit scan files are not allowed")

    candidates: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for root in resolved_roots:
        for path in _iter_root_files(root):
            if path in seen:
                raise ValueError(f"file is covered by multiple scan targets: {path}")
            seen.add(path)
            candidates.append((path, "root"))
    for path in resolved_files:
        if path in seen:
            raise ValueError(f"explicit file is already covered by a scan root: {path}")
        seen.add(path)
        candidates.append((path, "explicit"))

    total = 0
    scanned: list[dict[str, Any]] = []
    for path, source in sorted(candidates, key=lambda item: str(item[0])):
        stat = path.stat()
        size = stat.st_size
        if size > max_file_bytes:
            raise ValueError(f"scan file exceeds per-file byte limit ({size} > {max_file_bytes}): {path}")
        total += size
        if total > max_total_bytes:
            raise ValueError(f"scan total exceeds byte limit ({total} > {max_total_bytes})")
        data = path.read_bytes()
        if len(data) != size:
            raise ValueError(f"file size changed while scanning: {path}")
        if secret in data:
            raise ValueError(f"exact credential bytes found in scanned file: {path}")
        scanned.append({
            "path": str(path),
            "source": source,
            "size_bytes": size,
            "sha256": _sha_bytes(data),
        })

    if not scanned:
        raise ValueError("scan target set contains no regular files")

    return {
        "schema_version": 1,
        "verdict": "credential-exact-bytes-not-found",
        "secret_sha256": secret_sha,
        "secret_length_bytes": len(secret),
        "roots": [str(path) for path in sorted(resolved_roots, key=str)],
        "explicit_files": [str(path) for path in sorted(resolved_files, key=str)],
        "scanned_file_count": len(scanned),
        "scanned_total_bytes": total,
        "max_file_bytes": max_file_bytes,
        "max_total_bytes": max_total_bytes,
        "files": scanned,
        "exact_secret_found": False,
        "symlinks_allowed": False,
        "scope": "exact secret byte-sequence absence in enumerated regular files only; transformed/encoded variants are outside this assertion",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secret-file", type=Path, required=True)
    parser.add_argument("--root", type=Path, action="append", default=[])
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = scan(
            secret_file=args.secret_file,
            roots=args.root,
            files=args.file,
            max_file_bytes=args.max_file_bytes,
            max_total_bytes=args.max_total_bytes,
        )
        output = args.output.resolve()
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"refusing to overwrite: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
