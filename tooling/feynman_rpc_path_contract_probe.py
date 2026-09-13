#!/usr/bin/env python3
"""Compare direct Linux and native-Windows-proxy RPC path semantics.

This probe uses only a temporary candidate fixture, empty runtime homes, and a
pinned offline Docker image.  It never reads a real CODEX_HOME, credentials, or
model/evaluation input.  Reports retain structural roles and hashes, not raw
RPC payloads or filesystem paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tempfile
import time
from typing import Any


PROBE_IMAGE = "sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6"
EXPECTED_IDS = (1, 2, 3, 4)


def _docker_args(*, image: str, candidate: Path, home: Path,
                 codex_home: Path, temp: Path) -> list[str]:
    mounts = (
        (candidate, "/run/candidate"),
        (home, "/run/home"),
        (codex_home, "/run/codex"),
        (temp, "/run/temp"),
    )
    args = [
        "run", "--rm", "-i", "--network", "none", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--read-only", "--user", "1000:1000",
        "--tmpfs", "/tmp:rw,nosuid,nodev",
    ]
    for source, destination in mounts:
        args.extend(("-v", f"{source}:{destination}:rw"))
    args.extend((image, "env", "-i", "HOME=/run/home", "CODEX_HOME=/run/codex",
                 "PATH=/usr/local/bin:/usr/bin:/bin", "TMPDIR=/tmp",
                 "PYTHONDONTWRITEBYTECODE=1", "codex", "exec-server",
                 "--listen", "stdio"))
    return args


def _requests(*, candidate: Path, direct: bool) -> list[dict[str, Any]]:
    if direct:
        cwd = "file:///run/candidate/sub"
        canonical = "file:///run/candidate/sub"
        metadata = "file:///run/candidate/sub/config.toml"
    else:
        root = candidate.as_posix()
        cwd = f"file:///{root}/sub"
        canonical = f"file:///{root}/sub"
        metadata = f"file:///{root}/sub/config.toml"
    return [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "clientName": "feynman-path-contract-probe",
        }},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "fs/getMetadata", "params": {"path": metadata}},
        {"jsonrpc": "2.0", "id": 3, "method": "fs/readFile", "params": {
            "path": metadata, "offset": 0, "len": 1,
        }},
        {"jsonrpc": "2.0", "id": 4, "method": "process/start", "params": {
            "processId": "feynman-path-contract-readable",
            "argv": ["sh", "-c", "test -r config.toml"],
            "cwd": cwd, "env": {"PATH": "/usr/local/bin:/usr/bin:/bin"},
            "tty": False, "pipeStdin": False, "arg0": None,
        }},
    ]


def _path_role(value: str, candidate: Path) -> str:
    host = candidate.as_posix().rstrip("/")
    normalized = value.replace("\\", "/")
    if normalized.startswith("file://"):
        normalized = normalized[7:]
    if len(normalized) >= 3 and normalized[0] == "/" and normalized[2] == ":":
        normalized = normalized[1:]
    if normalized == "/run/candidate" or normalized.startswith("/run/candidate/"):
        return "candidate/" + normalized.removeprefix("/run/candidate/")
    if normalized == host or normalized.startswith(host + "/"):
        return "candidate/" + normalized.removeprefix(host + "/")
    for root in ("/run/home", "/run/codex", "/run/temp"):
        if normalized == root or normalized.startswith(root + "/"):
            return root.removeprefix("/") + "/..."
    return "outside-declared-mount"


def _shape(value: Any, *, candidate: Path, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {name: _shape(item, candidate=candidate, key=name)
                for name, item in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(item, candidate=candidate, key=key) for item in value]
    if isinstance(value, str):
        if key in {"path", "cwd", "uri", "file", "root"}:
            return {"path_role": _path_role(value, candidate)}
        if key in {"text", "data", "contents", "content", "message"}:
            return {"redacted_string": len(value)}
        return {"string_kind": "empty" if not value else "nonempty"}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return {"value_kind": type(value).__name__}


def _response_summary(stdout: str, *, candidate: Path) -> dict[str, Any]:
    responses: dict[str, Any] = {}
    notifications = 0
    malformed = 0
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(value, dict):
            malformed += 1
            continue
        identifier = value.get("id")
        if type(identifier) in {int, str}:
            responses[str(identifier)] = _shape(value, candidate=candidate)
        else:
            notifications += 1
    return {
        "response_ids": sorted(responses),
        "notifications": notifications,
        "malformed_lines": malformed,
        "responses": responses,
    }


def _parse_line(line: str, *, candidate: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    identifier = value.get("id")
    if type(identifier) in {int, str}:
        return {"kind": "response", "id": str(identifier),
                "status": "error" if isinstance(value.get("error"), dict) else "result",
                "shape": _shape(value, candidate=candidate)}
    params = value.get("params")
    return {
        "kind": "notification", "method": value.get("method"),
        "exit_code": params.get("exitCode") if isinstance(params, dict)
        and type(params.get("exitCode")) is int else None,
        "sandbox_denied": params.get("sandboxDenied") if isinstance(params, dict)
        and type(params.get("sandboxDenied")) is bool else None,
    }


def _run_peer(command: list[str], messages: list[dict[str, Any]], *, candidate: Path,
              timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    assert process.stdin is not None and process.stdout is not None
    received: queue.Queue[str | None] = queue.Queue()

    def read_lines() -> None:
        try:
            for line in process.stdout:
                received.put(line)
        finally:
            received.put(None)

    threading.Thread(target=read_lines, daemon=True).start()
    deadline = started + timeout
    responses: dict[str, Any] = {}
    notifications = 0
    malformed = 0
    response_statuses: dict[str, str] = {}
    process_exit_codes: list[int] = []
    process_sandbox_denied: list[bool] = []
    peer_closed_after_requests = False

    def record(line: str) -> dict[str, Any] | None:
        nonlocal notifications, malformed
        parsed = _parse_line(line, candidate=candidate)
        if parsed is None:
            malformed += 1
        elif parsed["kind"] == "notification":
            notifications += 1
            if parsed.get("method") == "process/exited":
                if type(parsed.get("exit_code")) is int:
                    process_exit_codes.append(parsed["exit_code"])
                if type(parsed.get("sandbox_denied")) is bool:
                    process_sandbox_denied.append(parsed["sandbox_denied"])
        else:
            responses[parsed["id"]] = parsed["shape"]
            response_statuses[parsed["id"]] = parsed["status"]
        return parsed

    def wait_for(*, response_id: str | None = None,
                 notification_method: str | None = None) -> bool:
        nonlocal peer_closed_after_requests
        while time.monotonic() < deadline:
            try:
                line = received.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                return False
            if line is None:
                peer_closed_after_requests = True
                return False
            parsed = record(line)
            if parsed is None:
                continue
            if response_id is not None and parsed.get("id") == response_id:
                return True
            if (notification_method is not None
                    and parsed.get("method") == notification_method):
                return True
        return False

    try:
        for index, message in enumerate(messages):
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()
            if index == 0:
                wait_for(response_id="1")
            elif message.get("id") is not None:
                wait_for(response_id=str(message["id"]))
            if message.get("method") == "process/start":
                wait_for(notification_method="process/exited")
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=max(1, min(10, timeout)))
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=max(1, min(10, timeout)))
    return {
        "response_ids": sorted(responses),
        "notifications": notifications,
        "malformed_lines": malformed,
        "peer_closed_after_requests": peer_closed_after_requests,
        "responses": responses,
        "response_statuses": response_statuses,
        "process_exit_codes": process_exit_codes,
        "process_sandbox_denied": process_sandbox_denied,
        "exit_code": process.returncode,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def _digest(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def run(*, docker: Path, docker_config: Path, image: str,
        proxy: Path, output: Path, timeout: int = 45) -> dict[str, Any]:
    if not docker.is_file() or not proxy.is_file() or not docker_config.is_dir():
        raise ValueError("path contract probe executable/config input is unavailable")
    if image != PROBE_IMAGE or not image.startswith("sha256:") or len(image) != 71:
        raise ValueError("path contract probe requires the pinned remote boundary image")
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("path contract probe output must be a new absolute path")
    with tempfile.TemporaryDirectory(prefix="feynman-path-contract-") as raw:
        root = Path(raw)
        candidate = root / "candidate"
        sub = candidate / "sub"
        home = root / "home"
        codex_home = root / "codex"
        temp = root / "temp"
        for directory in (sub, home, codex_home, temp):
            directory.mkdir(parents=True)
        (sub / "config.toml").write_text('marker = "CONFIG_FIXTURE"\n', encoding="utf-8")
        (sub / "requirements.txt").write_text("fixture-requirement\n", encoding="utf-8")
        (sub / "child.txt").write_text("CHILD_FIXTURE\n", encoding="utf-8")
        docker_args = _docker_args(image=image, candidate=candidate, home=home,
                                   codex_home=codex_home, temp=temp)
        direct_command = [str(docker), "--config", str(docker_config), *docker_args]
        proxy_command = [
            sys.executable, "-B", str(proxy), "--docker", str(docker),
            "--", "--config", str(docker_config), *docker_args,
        ]
        direct = _run_peer(direct_command, _requests(candidate=candidate, direct=True),
                           candidate=candidate, timeout=timeout)
        proxy = _run_peer(proxy_command, _requests(candidate=candidate, direct=False),
                          candidate=candidate, timeout=timeout)
    direct_responses = direct.pop("responses")
    proxy_responses = proxy.pop("responses")
    response_shapes_match = direct_responses == proxy_responses
    request_shape_direct = [_shape(item, candidate=candidate)
                            for item in _requests(candidate=candidate, direct=True)]
    request_shape_proxy = [_shape(item, candidate=candidate)
                           for item in _requests(candidate=candidate, direct=False)]
    request_shapes_match = request_shape_direct == request_shape_proxy
    result = {
        "schema_version": 1,
        "verdict": "rpc-path-contract-equivalent" if (
            direct["exit_code"] == 0 and proxy["exit_code"] == 0
            and direct["response_ids"] == proxy["response_ids"] == [str(x) for x in EXPECTED_IDS]
            and direct["malformed_lines"] == proxy["malformed_lines"] == 0
            and direct["response_statuses"] == proxy["response_statuses"]
            and set(direct["response_statuses"].values()) == {"result"}
            and direct["process_exit_codes"] == proxy["process_exit_codes"] == [0]
            and direct["process_sandbox_denied"] == proxy["process_sandbox_denied"] == [False]
            and request_shapes_match
            and response_shapes_match
        ) else "rpc-path-contract-blocked",
        "image_id": image,
        "direct": direct,
        "proxy": proxy,
        "request_shapes_match": request_shapes_match,
        "direct_request_shape_digest": _digest(request_shape_direct),
        "proxy_request_shape_digest": _digest(request_shape_proxy),
        "response_shapes_match": response_shapes_match,
        "direct_response_shape_digest": _digest(direct_responses),
        "proxy_response_shape_digest": _digest(proxy_responses),
        "scope": "offline Docker exec-server path semantics; no auth, model, or evaluation",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--proxy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()
    try:
        result = run(docker=args.docker, docker_config=args.docker_config,
                     image=args.image, proxy=args.proxy, output=args.output,
                     timeout=args.timeout)
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
        parser.exit(2, "error: RPC path contract probe failed\n")
    print(json.dumps({
        "verdict": result["verdict"],
        "direct_exit_code": result["direct"]["exit_code"],
        "proxy_exit_code": result["proxy"]["exit_code"],
        "request_shapes_match": result["request_shapes_match"],
        "response_shapes_match": result["response_shapes_match"],
        "direct_response_shape_digest": result["direct_response_shape_digest"],
        "proxy_response_shape_digest": result["proxy_response_shape_digest"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "rpc-path-contract-equivalent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
