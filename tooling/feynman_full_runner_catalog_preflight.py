#!/usr/bin/env python3
"""Run the full-runner MCP catalog preflight on a disposable fixture.

This starts Codex App Server only for MCP catalog discovery. It does not log
in, start a thread, send a model prompt, or execute Docker tests.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

try:
    from .feynman_full_runner_preflight import run
except ImportError:
    from feynman_full_runner_preflight import run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument("--node-bin", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--docker-bin", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--docker-image-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="feynman-full-runner-catalog-") as raw:
            root = Path(raw)
            candidate = root / "candidate"
            candidate.mkdir()
            (candidate / "candidate.py").write_text("value = 1\n", encoding="utf-8")
            (candidate / "test_candidate.py").write_text("assert True\n", encoding="utf-8")
            codex_home = root / "codex-home"
            codex_home.mkdir()
            result = run(
                codex_bin=args.codex_bin, codex_home=codex_home, output=args.output,
                node_bin=args.node_bin, adapter=args.adapter, candidate=candidate,
                docker_bin=args.docker_bin, docker_config=args.docker_config,
                docker_image_id=args.docker_image_id, timeout_seconds=30,
            )
    except (OSError, ValueError, json.JSONDecodeError, TimeoutError) as exc:
        parser.exit(2, "error: full-runner catalog preflight failed: " + type(exc).__name__ + "\n")
    print(json.dumps({"verdict": result["verdict"], "model_calls": result["model_calls"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
