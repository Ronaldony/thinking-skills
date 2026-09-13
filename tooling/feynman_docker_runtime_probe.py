#!/usr/bin/env python3
"""Find the first stage where a pinned Docker image fails to run.

The probe records only bounded process/container status metadata.  It never
reads a real Codex home, credentials, model input, or command output beyond a
fixed marker check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid


PROBE_IMAGE = "sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6"
MARKER = "FEYNMAN_RUNTIME_PROBE_OK"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stop_cli(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=5,
            )
        else:
            process.terminate()
    except (OSError, subprocess.SubprocessError):
        pass


def _inspect_container(docker: Path, config: Path, name: str) -> dict[str, object]:
    try:
        result = subprocess.run(
            [str(docker), "--config", str(config), "inspect", name,
             "--format", "{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return {"available": False}
    raw = result.stdout.decode("ascii", errors="ignore").strip()
    fields = raw.split("|")
    if result.returncode != 0 or len(fields) != 3:
        return {"available": False, "inspect_exit_code": result.returncode}
    status, exit_code, oom_killed = fields
    parsed_exit: int | None
    try:
        parsed_exit = int(exit_code)
    except ValueError:
        parsed_exit = None
    return {
        "available": True,
        "status": status if status in {"created", "running", "paused", "restarting", "removing", "exited", "dead"} else "unknown",
        "exit_code": parsed_exit,
        "oom_killed": oom_killed == "true",
    }


def _remove_container(docker: Path, config: Path, name: str) -> int | None:
    try:
        return subprocess.run(
            [str(docker), "--config", str(config), "rm", "-f", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=5,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        return None


def _run_stage(command: list[str], *, docker: Path, config: Path, name: str,
               input_data: bytes | None, marker: bytes | None,
               timeout: int) -> dict[str, object]:
    started = time.monotonic()
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(input=input_data, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        container = _inspect_container(docker, config, name)
        _stop_cli(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
        if not stdout and isinstance(exc.output, bytes):
            stdout = exc.output
        if not stderr and isinstance(exc.stderr, bytes):
            stderr = exc.stderr
    else:
        container = {"available": False}
    cleanup_exit_code = _remove_container(docker, config, name)
    marker_observed = marker is not None and stdout == marker
    version_observed = bool(re.fullmatch(rb"v\d+(?:\.\d+){1,2}\r?\n?", stdout))
    return {
        "cli_exit_code": process.returncode,
        "timed_out": timed_out,
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "stdout_digest": _digest(stdout),
        "stderr_digest": _digest(stderr),
        "marker_observed": marker_observed,
        "node_version_observed": version_observed,
        "container": container,
        "cleanup_exit_code": cleanup_exit_code,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def _base_command(docker: Path, config: Path, name: str, image: str) -> list[str]:
    return [
        str(docker), "--config", str(config), "run", "--rm", "--name", name,
        "--network", "none", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--read-only", "--user", "1000:1000",
        "--tmpfs", "/tmp:rw,nosuid,nodev",
    ]


def run(*, docker: Path, config: Path, image: str, output: Path,
        timeout: int = 8) -> dict[str, object]:
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("Docker runtime probe output must be a new absolute path")
    if not docker.is_file() or not config.is_dir():
        raise ValueError("Docker runtime probe executable/config input is unavailable")
    if image != PROBE_IMAGE:
        raise ValueError("Docker runtime probe requires the pinned image")
    with tempfile.TemporaryDirectory(prefix="feynman-runtime-"):
        run_id = uuid.uuid4().hex[:12]
        stages = [
            ("entrypoint-echo", _base_command(docker, config, f"feynman-runtime-{run_id}-echo", image)
             + ["--entrypoint", "/bin/echo", image, MARKER], MARKER.encode() + b"\n"),
            ("default-node-version", _base_command(docker, config, f"feynman-runtime-{run_id}-node", image)
             + [image, "node", "--version"], None),
            ("exec-server-initialize", _base_command(docker, config, f"feynman-runtime-{run_id}-server", image)
             + [image, "env", "-i", "HOME=/tmp", "CODEX_HOME=/tmp", "PATH=/usr/local/bin:/usr/bin:/bin",
                "TMPDIR=/tmp", "PYTHONDONTWRITEBYTECODE=1", "codex", "exec-server", "--listen", "stdio"],
             b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientName":"feynman-runtime-probe"}}\n'),
        ]
        results: list[dict[str, object]] = []
        stopped_after: str | None = None
        for stage, command, input_data in stages:
            name = command[command.index("--name") + 1]
            result = _run_stage(
                command, docker=docker, config=config, name=name,
                input_data=input_data, marker=MARKER.encode() + b"\n"
                if stage == "entrypoint-echo" else None, timeout=timeout,
            )
            result["stage"] = stage
            results.append(result)
            passed = (
                result["cli_exit_code"] == 0 and not result["timed_out"]
                and result["cleanup_exit_code"] in {0, 1}
                and (result["marker_observed"] if stage == "entrypoint-echo"
                     else result["node_version_observed"] if stage == "default-node-version"
                     else result["stdout_bytes"] > 0)
            )
            if not passed:
                stopped_after = stage
                break
        result = {
            "schema_version": 1,
            "verdict": "docker-runtime-ready" if stopped_after is None else "docker-runtime-blocked",
            "failure_stage": stopped_after,
            "image_id": image,
            "stages": results,
            "scope": "offline pinned Docker image process lifecycle; no auth, model, or evaluation",
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()
    try:
        result = run(docker=args.docker, config=args.docker_config,
                     image=args.image, output=args.output, timeout=args.timeout)
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
        parser.exit(2, "error: Docker runtime probe failed\n")
    print(json.dumps({
        "verdict": result["verdict"],
        "failure_stage": result["failure_stage"],
        "stage_count": len(result["stages"]),
    }, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "docker-runtime-ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
