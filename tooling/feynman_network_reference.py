#!/usr/bin/env python3
"""Create a network-reference JSON only after a control-plane TCP connect succeeds."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket


def endpoint_identity(host: str, port: int) -> str:
    return hashlib.sha256(f"tcp://{host}:{port}".encode("utf-8")).hexdigest()


def verify_reachable(host: str, port: int, *, timeout: float = 2.0) -> dict:
    if not host.strip():
        raise ValueError("host must be nonempty")
    if not (1 <= port <= 65535):
        raise ValueError("port must be between 1 and 65535")
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        raise ValueError(f"control-plane endpoint is not reachable: {host}:{port}: {exc}") from exc
    return {
        "schema_version": 1,
        "host": host,
        "port": port,
        "reachable_from_control_plane": True,
        "probe_method": "tcp-connect:v1",
        "endpoint_identity_sha256": endpoint_identity(host, port),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_reachable(args.host, args.port, timeout=args.timeout)
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"refusing to overwrite: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
