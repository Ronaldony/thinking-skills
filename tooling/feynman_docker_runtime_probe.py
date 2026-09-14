#!/usr/bin/env python3
"""Find the first stage where a pinned Docker image fails to run.

The probe owns only containers bearing its unique label. It retains no raw
stdout/stderr, credentials, model input, or candidate data. Process output is
continuously drained with a bounded in-memory sample so diagnostic plumbing
cannot create a pipe deadlock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid
from typing import BinaryIO, TypedDict


PROBE_IMAGE = "sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6"
MARKER = b"FEYNMAN_RUNTIME_PROBE_OK\n"
LABEL_KEY = "com.openai.feynman.runtime-probe"
MAX_CAPTURE_BYTES = 262144
RUNTIME_REPORT_SCHEMA_VERSION = 3
SAFE_CONTAINER_STATES = frozenset({
    "created", "running", "paused", "restarting", "removing", "exited", "dead",
})


def _validate_docker_host(value: str | None) -> str | None:
    if value is None:
        return None
    if not value or not value.startswith(("npipe://", "unix://")):
        raise ValueError("Docker host must be a local npipe or unix endpoint")
    return value


class _Capture(TypedDict):
    bytes: int
    digest: str
    sample: bytes
    truncated: bool
    read_error: bool
    drained: bool


def _new_capture() -> _Capture:
    return {
        "bytes": 0,
        "digest": hashlib.sha256(b"").hexdigest(),
        "sample": b"",
        "truncated": False,
        "read_error": False,
        "drained": False,
    }


def _drain(stream: BinaryIO, capture: _Capture) -> None:
    digest = hashlib.sha256()
    sample = bytearray()
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            capture["bytes"] += len(chunk)
            digest.update(chunk)
            remaining = MAX_CAPTURE_BYTES - len(sample)
            if remaining > 0:
                sample.extend(chunk[:remaining])
            if len(chunk) > remaining:
                capture["truncated"] = True
    except OSError:
        capture["read_error"] = True
    finally:
        capture["digest"] = digest.hexdigest()
        capture["sample"] = bytes(sample)
        capture["drained"] = True


def _stop_cli(process: subprocess.Popen[bytes]) -> bool:
    if process.poll() is not None:
        return True
    try:
        if os.name == "nt":
            return subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=5,
            ).returncode == 0
        process.terminate()
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _inspect_container(docker: Path, config: Path, name: str,
                       run_id: str, docker_host: str | None = None) -> dict[str, object]:
    """Return only a fixed status projection and whether this probe owns it."""
    try:
        result = subprocess.run(
            [str(docker), "--config", str(config), *( ["--host", docker_host] if docker_host else [] ), "inspect", name,
             "--format", "{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|{{index .Config.Labels \"com.openai.feynman.runtime-probe\"}}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return {"available": False, "presence": "unavailable", "inspect_error": True}
    fields = result.stdout.decode("ascii", errors="ignore").strip().split("|")
    if result.returncode != 0 or len(fields) != 4:
        return {"available": False, "presence": "unavailable", "inspect_exit_code": result.returncode}
    status, exit_code, oom_killed, observed_run_id = fields
    try:
        parsed_exit: int | None = int(exit_code)
    except ValueError:
        parsed_exit = None
    return {
        "available": True,
        "presence": "present",
        "owned": observed_run_id == run_id,
        "status": status if status in SAFE_CONTAINER_STATES else "unknown",
        "exit_code": parsed_exit,
        "oom_killed": oom_killed == "true",
    }


def _container_absent(docker: Path, config: Path, name: str,
                      docker_host: str | None = None) -> bool:
    """Confirm absence with a successful list operation; inspect errors are unknown."""
    try:
        result = subprocess.run(
            [str(docker), "--config", str(config), *( ["--host", docker_host] if docker_host else [] ), "ps", "-a",
             "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and not result.stdout.strip()


def _remove_owned_container(docker: Path, config: Path, name: str,
                            run_id: str, observation: dict[str, object],
                            docker_host: str | None = None) -> dict[str, object]:
    if observation.get("available") is not True:
        return {"status": "not-observed", "verified": False}
    if observation.get("owned") is not True:
        return {"status": "not-owned", "verified": False}
    try:
        removed = subprocess.run(
            [str(docker), "--config", str(config), *( ["--host", docker_host] if docker_host else [] ), "rm", "-f", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=5,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return {"status": "remove-error", "verified": False}
    absent = _container_absent(docker, config, name, docker_host)
    return {
        "status": "removed" if removed else "remove-failed",
        "verified": removed and absent,
    }


def _initialize_response_observed(sample: bytes, *, truncated: bool) -> bool:
    if truncated:
        return False
    observed = 0
    valid = False
    invalid = False
    for line in sample.splitlines():
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or type(value.get("id")) is not int or value.get("id") != 1:
            continue
        observed += 1
        if isinstance(value.get("result"), dict) and "error" not in value:
            valid = True
        else:
            invalid = True
    return observed == 1 and valid and not invalid


def _run_stage(command: list[str], *, docker: Path, config: Path, name: str,
               run_id: str, input_data: bytes | None, marker: bytes | None,
               timeout: int, cleanup_after: bool = True,
               docker_host: str | None = None) -> dict[str, object]:
    started = time.monotonic()
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    stdout_capture = _new_capture()
    stderr_capture = _new_capture()
    stdout_reader = threading.Thread(target=_drain, args=(process.stdout, stdout_capture), daemon=True)
    stderr_reader = threading.Thread(target=_drain, args=(process.stderr, stderr_capture), daemon=True)
    stdout_reader.start()
    stderr_reader.start()
    stdin_write_error = False
    try:
        if input_data is not None:
            process.stdin.write(input_data)
            process.stdin.flush()
        process.stdin.close()
    except OSError:
        stdin_write_error = True

    timed_out = False
    cli_stop_verified = True
    try:
        process.wait(timeout=timeout)
        observation = _inspect_container(docker, config, name, run_id, docker_host)
    except subprocess.TimeoutExpired:
        timed_out = True
        observation = _inspect_container(docker, config, name, run_id, docker_host)
        cli_stop_verified = _stop_cli(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            cli_stop_verified = False
    stdout_reader.join(timeout=5)
    stderr_reader.join(timeout=5)
    try:
        process.stdout.close()
        process.stderr.close()
    except OSError:
        pass
    cleanup = (
        _remove_owned_container(docker, config, name, run_id, observation, docker_host)
        if cleanup_after else {"status": "deferred", "verified": False}
    )
    marker_observed = marker is not None and not stdout_capture["truncated"] and stdout_capture["sample"] == marker
    node_version_observed = (
        not stdout_capture["truncated"]
        and bool(re.fullmatch(rb"v\d+(?:\.\d+){1,2}\r?\n?", stdout_capture["sample"]))
    )
    initialize_observed = _initialize_response_observed(
        stdout_capture["sample"], truncated=stdout_capture["truncated"])
    return {
        "cli_exit_code": process.returncode,
        "timed_out": timed_out,
        "cli_stop_verified": cli_stop_verified,
        "stdin_write_error": stdin_write_error,
        "stdout": {key: value for key, value in stdout_capture.items() if key != "sample"},
        "stderr": {key: value for key, value in stderr_capture.items() if key != "sample"},
        "marker_observed": marker_observed,
        "node_version_observed": node_version_observed,
        "initialize_response_observed": initialize_observed,
        "container_id_observed": bool(
            re.fullmatch(rb"[0-9a-f]{12,64}\r?\n?", stdout_capture["sample"])),
        "container": observation,
        "cleanup": cleanup,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def _base_command(docker: Path, config: Path, action: str, name: str,
                  run_id: str, docker_host: str | None = None) -> list[str]:
    return [
        str(docker), "--config", str(config),
        *( ["--host", docker_host] if docker_host else [] ), action, "--name", name,
        "--label", f"{LABEL_KEY}={run_id}", "--network", "none",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--user", "1000:1000", "--tmpfs", "/tmp:rw,nosuid,nodev",
    ]


def _stage_passed(stage: str, value: dict[str, object]) -> bool:
    stdout = value["stdout"]
    stderr = value["stderr"]
    container = value["container"]
    cleanup = value["cleanup"]
    assert isinstance(stdout, dict) and isinstance(stderr, dict)
    assert isinstance(container, dict) and isinstance(cleanup, dict)
    observed = (
        value["container_id_observed"] if stage == "container-create"
        else value["marker_observed"] if stage in {"container-start", "entrypoint-echo"}
        else value["node_version_observed"] if stage == "default-node-version"
        else value["initialize_response_observed"]
    )
    cleanup_ok = (
        cleanup.get("status") == "deferred" if stage == "container-create"
        else cleanup.get("status") == "removed" and cleanup.get("verified") is True
    )
    container_ok = (
        container.get("available") is True and container.get("owned") is True
        and container.get("exit_code") == 0 and container.get("oom_killed") is False
        and (container.get("status") == "created" if stage == "container-create"
             else container.get("status") == "exited")
    )
    return bool(
        value["cli_exit_code"] == 0 and not value["timed_out"]
        and not value["stdin_write_error"] and value["cli_stop_verified"]
        and stdout["drained"] and stderr["drained"]
        and not stdout["read_error"] and not stderr["read_error"]
        and container_ok and cleanup_ok
        and observed
    )


def run(*, docker: Path, config: Path, image: str, output: Path,
        timeout: int = 30, docker_host: str | None = None) -> dict[str, object]:
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("Docker runtime probe output must be a new absolute path")
    if not docker.is_file() or not config.is_dir():
        raise ValueError("Docker runtime probe executable/config input is unavailable")
    if image != PROBE_IMAGE:
        raise ValueError("Docker runtime probe requires the pinned image")
    if timeout < 1:
        raise ValueError("Docker runtime probe timeout must be positive")
    docker_host = _validate_docker_host(docker_host)
    run_id = uuid.uuid4().hex[:12]
    create_name = f"feynman-runtime-{run_id}-create"
    create = _run_stage(
        _base_command(docker, config, "create", create_name, run_id, docker_host)
        + ["--entrypoint", "/bin/echo", image, MARKER.decode().rstrip("\r\n")],
        docker=docker, config=config, name=create_name, run_id=run_id,
        input_data=None, marker=None, timeout=timeout, cleanup_after=False,
        docker_host=docker_host,
    )
    create["stage"] = "container-create"
    results: list[dict[str, object]] = [create]
    if not _stage_passed("container-create", create):
        create["cleanup"] = _remove_owned_container(
            docker, config, create_name, run_id, create["container"], docker_host)
        stopped_after: str | None = "container-create"
    else:
        start = _run_stage(
            [str(docker), "--config", str(config),
             *( ["--host", docker_host] if docker_host else [] ), "start", "-a", create_name],
            docker=docker, config=config, name=create_name, run_id=run_id,
            input_data=None, marker=MARKER, timeout=timeout, docker_host=docker_host,
        )
        start["stage"] = "container-start"
        results.append(start)
        stopped_after = None if _stage_passed("container-start", start) else "container-start"
    stage_specs = [
        ("default-node-version", lambda name: _base_command(docker, config, "run", name, run_id, docker_host)
         + [image, "node", "--version"], None, None),
        ("exec-server-initialize", lambda name: _base_command(docker, config, "run", name, run_id, docker_host)
         + ["-i", image, "env", "-i", "HOME=/tmp", "CODEX_HOME=/tmp",
            "PATH=/usr/local/bin:/usr/bin:/bin", "TMPDIR=/tmp",
            "PYTHONDONTWRITEBYTECODE=1", "codex", "exec-server", "--listen", "stdio"],
         b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientName":"feynman-runtime-probe"}}\n', None),
    ]
    if stopped_after is None:
        for stage, command_factory, input_data, marker in stage_specs:
            name = f"feynman-runtime-{run_id}-{len(results) + 1}"
            value = _run_stage(
                command_factory(name), docker=docker, config=config, name=name,
                run_id=run_id, input_data=input_data, marker=marker, timeout=timeout,
                docker_host=docker_host,
            )
            value["stage"] = stage
            results.append(value)
            if not _stage_passed(stage, value):
                stopped_after = stage
                break
    result = {
        "schema_version": RUNTIME_REPORT_SCHEMA_VERSION,
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
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--docker-host")
    args = parser.parse_args()
    try:
        result = run(docker=args.docker, config=args.docker_config,
                     image=args.image, output=args.output, timeout=args.timeout,
                     docker_host=args.docker_host)
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
