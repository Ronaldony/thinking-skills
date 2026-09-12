#!/usr/bin/env python3
"""Run a model-free native Windows-to-Linux exec-server preflight.

The probe validates the canonical remote-environment document, starts its
field-specific proxy with an ephemeral Docker container, and exercises the
documented exec-server lifecycle. It never sends a model prompt, reads auth
files, persists filesystem/process payloads, or inherits API-key variables.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import queue
import subprocess
import sys
import threading
import time
import tomllib
from typing import Any, Mapping
from urllib.parse import quote
from uuid import uuid4

try:
    from .feynman_remote_exec_environment import validate_files
    from .feynman_runner_job_validate import _load as load_job
except ImportError:
    from feynman_remote_exec_environment import validate_files
    from feynman_runner_job_validate import _load as load_job


RETIRED_API_ENV_KEYS = {"OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"}
WINDOWS_SYSTEM_ENV_KEYS = ("SystemRoot", "ComSpec", "PATHEXT", "WINDIR")
SKILL_RELATIVE_PATH = ".agents/skills/feynman-thinking/SKILL.md"


def _file_uri(path: str) -> str:
    windows = PureWindowsPath(path)
    if windows.is_absolute():
        value = "/" + windows.as_posix()
    else:
        value = Path(path).resolve(strict=False).as_posix()
    return "file://" + quote(value, safe="/:@-._~")


def _safe_probe_env(docker_config: Path) -> dict[str, str]:
    for key in RETIRED_API_ENV_KEYS:
        if key in os.environ:
            raise ValueError("retired API authentication environment is set")
    path_value = os.environ.get("PATH", "")
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            docker_dir = Path(local_app_data) / "Programs" / "DockerDesktop" / "resources" / "bin"
            if docker_dir.is_dir() and str(docker_dir) not in path_value.split(os.pathsep):
                path_value = str(docker_dir) + os.pathsep + path_value
    if not path_value:
        raise ValueError("probe has no executable PATH")
    result = {"PATH": path_value, "DOCKER_CONFIG": str(docker_config)}
    if os.name == "nt":
        for key in WINDOWS_SYSTEM_ENV_KEYS:
            value = os.environ.get(key)
            if value:
                result[key] = value
    return result


def _ephemeral_command(document: Mapping[str, Any], run_id: str) -> list[str]:
    environments = document.get("environments")
    if not isinstance(environments, list) or len(environments) != 1:
        raise ValueError("remote environment must contain one environment")
    environment = environments[0]
    if not isinstance(environment, Mapping):
        raise ValueError("remote environment entry is invalid")
    program = environment.get("program")
    args = environment.get("args")
    if not isinstance(program, str) or not isinstance(args, list) or not all(isinstance(x, str) for x in args):
        raise ValueError("remote environment launch command is invalid")
    try:
        separator = args.index("--")
    except ValueError as exc:
        raise ValueError("remote environment does not use the RPC proxy separator") from exc
    docker_args = list(args[separator + 1 :])
    if not docker_args or docker_args[0] != "run":
        raise ValueError("remote environment does not launch Docker run")
    if "--rm" not in docker_args:
        docker_args.insert(1, "--rm")
    try:
        name_index = docker_args.index("--name") + 1
    except ValueError as exc:
        raise ValueError("remote environment Docker command has no container name") from exc
    docker_args[name_index] = ("feynman-rpc-preflight-" + run_id + "-" + uuid4().hex[:12])[:120]
    return [program, *args[: separator + 1], *docker_args]


def _request(identifier: int, method: str, params: Mapping[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}, separators=(",", ":")) + "\n").encode("utf-8")


def _notification(method: str, params: Mapping[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, separators=(",", ":")) + "\n").encode("utf-8")


def _summary(raw: bytes) -> dict[str, Any]:
    message = json.loads(raw)
    if not isinstance(message, dict):
        raise ValueError("exec-server response is not an object")
    result = message.get("result")
    error = message.get("error")
    params = message.get("params")
    return {
        "id": message.get("id"),
        "method": message.get("method"),
        "result_keys": sorted(result) if isinstance(result, dict) else [],
        "error_code": error.get("code") if isinstance(error, dict) else None,
        "exit_code": params.get("exitCode") if isinstance(params, dict) else None,
        "sandbox_denied": params.get("sandboxDenied") if isinstance(params, dict) else None,
    }


def _wait_for(
    received: queue.Queue[bytes],
    request_id: int | None = None,
    notification: str | None = None,
    timeout: float = 20,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    deadline = time.monotonic() + timeout
    observed: list[dict[str, Any]] = []
    host_path_echo = False
    while time.monotonic() < deadline:
        try:
            raw = received.get(timeout=max(0.1, deadline - time.monotonic()))
        except queue.Empty:
            break
        summary = _summary(raw)
        host_path_echo = host_path_echo or b":/DevWorks/" in raw or b":\\DevWorks\\" in raw
        if request_id is not None and summary["id"] == request_id:
            return summary, observed, host_path_echo
        if notification is not None and summary["method"] == notification:
            return summary, observed, host_path_echo
        observed.append(summary)
    raise TimeoutError("exec-server response timed out")


def run_preflight(
    *, job_path: Path, profile_path: Path, remote_environment_path: Path,
    docker_config: Path, output_path: Path | None = None, timeout_seconds: int = 45,
) -> dict[str, Any]:
    if type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 120:
        raise ValueError("timeout_seconds must be an integer in 30..120")
    validation = validate_files(job_path, profile_path, remote_environment_path)
    if validation.get("verdict") != "remote-exec-environment-valid":
        raise ValueError("remote environment validation did not pass")
    job = load_job(job_path.resolve())
    paths = job.get("paths")
    if not isinstance(paths, Mapping) or not isinstance(paths.get("candidate_dir"), str):
        raise ValueError("runner job has no candidate directory")
    candidate_uri = _file_uri(paths["candidate_dir"])
    document = tomllib.loads(remote_environment_path.read_text(encoding="utf-8"))
    command = _ephemeral_command(document, str(job.get("run_id", "run")))
    environment = _safe_probe_env(docker_config.resolve())
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, cwd=Path.cwd(), bufsize=0,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    received: queue.Queue[bytes] = queue.Queue()
    threading.Thread(target=lambda: [received.put(line) for line in process.stdout], daemon=True).start()
    host_echo = False
    try:
        process.stdin.write(_request(1, "initialize", {"clientName": "feynman-model-free-preflight"}))
        process.stdin.flush()
        initialized, _, echoed = _wait_for(received, request_id=1, timeout=timeout_seconds)
        host_echo = host_echo or echoed
        if initialized["error_code"] is not None or set(initialized["result_keys"]) != {"environmentInfo", "sessionId"}:
            raise ValueError("exec-server initialize did not return the expected metadata")
        process.stdin.write(_notification("initialized", {}))
        process.stdin.write(_request(2, "fs/readFile", {"path": candidate_uri + "/task.txt", "offset": 0, "len": 1}))
        process.stdin.flush()
        task_read, _, echoed = _wait_for(received, request_id=2, timeout=timeout_seconds)
        host_echo = host_echo or echoed
        if task_read["error_code"] is not None or task_read["result_keys"] != ["dataBase64"]:
            raise ValueError("candidate task read did not return dataBase64")
        process.stdin.write(_request(3, "fs/readFile", {"path": candidate_uri + "/" + SKILL_RELATIVE_PATH, "offset": 0, "len": 1}))
        process.stdin.flush()
        skill_read, _, echoed = _wait_for(received, request_id=3, timeout=timeout_seconds)
        host_echo = host_echo or echoed
        if skill_read["error_code"] is not None or skill_read["result_keys"] != ["dataBase64"]:
            raise ValueError("candidate skill read did not return dataBase64")
        process.stdin.write(_request(4, "process/start", {
            "processId": "feynman-preflight-skill-readable",
            "argv": ["sh", "-c", "test -r .agents/skills/feynman-thinking/SKILL.md"],
            "cwd": candidate_uri,
            "env": {"PATH": "/usr/local/bin:/usr/bin:/bin"},
            "tty": False,
            "pipeStdin": False,
            "arg0": None,
        }))
        process.stdin.flush()
        started, _, echoed = _wait_for(received, request_id=4, timeout=timeout_seconds)
        host_echo = host_echo or echoed
        if started["error_code"] is not None or "processId" not in started["result_keys"]:
            raise ValueError("preflight process did not start")
        exited, _, echoed = _wait_for(received, notification="process/exited", timeout=timeout_seconds)
        host_echo = host_echo or echoed
        if exited["exit_code"] != 0 or exited["sandbox_denied"] is not False:
            raise ValueError("preflight process did not exit cleanly")
        if host_echo:
            raise ValueError("exec-server response echoed a host path")
        result = {
            "schema_version": 1,
            "verdict": "native-rpc-preflight-passed",
            "run_id": job.get("run_id"),
            "checks": {
                "remote_environment_valid": True,
                "initialize_metadata": True,
                "candidate_task_read": True,
                "feynman_skill_read": True,
                "skill_readability_process": True,
                "process_exit_code": 0,
                "process_sandbox_denied": False,
                "host_path_echo": False,
            },
            "privacy": {
                "model_request_started": False,
                "payload_contents_preserved": False,
                "credential_files_read": False,
                "api_key_environment_inherited": False,
                "raw_stderr_preserved": False,
            },
            "scope": "model-free Windows host to Linux exec-server path/read/spawn preflight",
        }
        if output_path is not None:
            if output_path.exists() or output_path.is_symlink():
                raise FileExistsError("preflight output path already exists")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--remote-environment", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    args = parser.parse_args()
    try:
        result = run_preflight(
            job_path=args.job, profile_path=args.boundary_profile,
            remote_environment_path=args.remote_environment, docker_config=args.docker_config,
            output_path=args.output, timeout_seconds=args.timeout_seconds,
        )
    except (ValueError, OSError, TimeoutError, json.JSONDecodeError, tomllib.TOMLDecodeError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"error: model-free RPC preflight failed: {type(exc).__name__}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
