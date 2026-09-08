#!/usr/bin/env python3
"""Run synthetic read/write/env/network canaries *inside* an external eval boundary.

This program does not create a sandbox and does not decide whether a runner is
secure. It records direct observations without copying protected file contents.
An evaluator outside the boundary must verify the artifact with
`feynman_boundary_probe_verify.py`.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import socket
from typing import Any

SECRET_KEY_PATTERN = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE|AUTH|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)",
    re.IGNORECASE,
)
DENIAL_ERRNOS = {errno.EACCES, errno.EPERM, errno.EROFS}


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _program_sha() -> str:
    return _sha_bytes(Path(__file__).read_bytes())


def _error(exc: OSError) -> dict[str, Any]:
    return {"type": type(exc).__name__, "errno": exc.errno, "message": str(exc)[:240]}


def _read(path: Path, expected_marker: str | None) -> dict[str, Any]:
    record: dict[str, Any] = {"path": str(path.absolute()), "succeeded": False, "denied": False}
    try:
        data = path.read_bytes()
    except OSError as exc:
        record["denied"] = exc.errno in DENIAL_ERRNOS
        record["error"] = _error(exc)
        return record
    record["succeeded"] = True
    record["bytes"] = len(data)
    record["sha256"] = _sha_bytes(data)
    if expected_marker is not None:
        marker = expected_marker.encode("utf-8")
        record["expected_marker_sha256"] = _sha_bytes(marker)
        record["marker_match"] = data == marker
    return record


def _write(path: Path, marker: str) -> dict[str, Any]:
    data = marker.encode("utf-8")
    record: dict[str, Any] = {
        "path": str(path.absolute()),
        "succeeded": False,
        "denied": False,
        "marker_sha256": _sha_bytes(data),
    }
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        record["denied"] = exc.errno in DENIAL_ERRNOS
        record["error"] = _error(exc)
        return record
    record["succeeded"] = True
    return record


def _network(host: str | None, port: int | None, timeout: float) -> dict[str, Any]:
    if host is None or port is None:
        return {"attempted": False}
    record: dict[str, Any] = {"attempted": True, "host": host, "port": port, "connected": False}
    try:
        with socket.create_connection((host, port), timeout=timeout):
            record["connected"] = True
    except OSError as exc:
        record["error"] = _error(exc)
    return record


def run_probe(*, run_id: str, candidate_read: Path, candidate_read_marker: str,
              evaluator_read: Path, source_read: Path, real_home_read: Path,
              candidate_write: Path, candidate_write_marker: str,
              forbidden_writes: list[Path], forbidden_write_marker: str,
              network_host: str | None = None, network_port: int | None = None,
              network_timeout: float = 1.5) -> dict[str, Any]:
    if not run_id.strip():
        raise ValueError("run_id must be nonempty")
    if not forbidden_writes:
        raise ValueError("at least one forbidden write path is required")
    env_keys = sorted(os.environ)
    return {
        "schema_version": 1,
        "run_id": run_id,
        "probe_program_sha256": _program_sha(),
        "observations": {
            "candidate_read": _read(candidate_read, candidate_read_marker),
            "protected_reads": {
                "evaluator": _read(evaluator_read, None),
                "source": _read(source_read, None),
                "real_home": _read(real_home_read, None),
            },
            "candidate_write": _write(candidate_write, candidate_write_marker),
            "forbidden_writes": [_write(path, forbidden_write_marker) for path in forbidden_writes],
            "environment": {
                "keys": env_keys,
                "secret_like_keys": [key for key in env_keys if SECRET_KEY_PATTERN.search(key)],
            },
            "network": _network(network_host, network_port, network_timeout),
        },
        "scope": "direct observations inside the supplied boundary; not a proof that the boundary or runner is honest",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--candidate-read", type=Path, required=True)
    parser.add_argument("--candidate-read-marker", required=True)
    parser.add_argument("--evaluator-read", type=Path, required=True)
    parser.add_argument("--source-read", type=Path, required=True)
    parser.add_argument("--real-home-read", type=Path, required=True)
    parser.add_argument("--candidate-write", type=Path, required=True)
    parser.add_argument("--candidate-write-marker", required=True)
    parser.add_argument("--forbidden-write", type=Path, action="append", required=True)
    parser.add_argument("--forbidden-write-marker", required=True)
    parser.add_argument("--network-host")
    parser.add_argument("--network-port", type=int)
    parser.add_argument("--network-timeout", type=float, default=1.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if (args.network_host is None) != (args.network_port is None):
            raise ValueError("network host and port must be supplied together")
        result = run_probe(
            run_id=args.run_id,
            candidate_read=args.candidate_read,
            candidate_read_marker=args.candidate_read_marker,
            evaluator_read=args.evaluator_read,
            source_read=args.source_read,
            real_home_read=args.real_home_read,
            candidate_write=args.candidate_write,
            candidate_write_marker=args.candidate_write_marker,
            forbidden_writes=args.forbidden_write,
            forbidden_write_marker=args.forbidden_write_marker,
            network_host=args.network_host,
            network_port=args.network_port,
            network_timeout=args.network_timeout,
        )
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"refusing to overwrite: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps({"run_id": result["run_id"], "probe_program_sha256": result["probe_program_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
