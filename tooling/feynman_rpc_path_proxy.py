#!/usr/bin/env python3
"""Proxy a Codex stdio exec-server across a Windows/Linux path namespace.

The control-plane Codex process speaks JSON-RPC over this process's stdio. The
proxy starts the declared Docker exec-server, maps only the path fields listed
by :mod:`feynman_rpc_path_mapping`, and forwards all other JSON values without
rewriting. Mapping failures return a fixed JSON-RPC error and never include the
rejected path in output.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from typing import Any

try:
    from .feynman_rpc_path_mapping import RpcPathMapper, RpcPathMappingError, map_json_line
except ImportError:
    from feynman_rpc_path_mapping import RpcPathMapper, RpcPathMappingError, map_json_line


PROXY_ERROR_CODE = -32001


def _docker_mounts(docker_args: list[str]) -> list[dict[str, str]]:
    mounts: list[dict[str, str]] = []
    index = 0
    while index < len(docker_args):
        token = docker_args[index]
        if token in {"-v", "--volume"}:
            if index + 1 >= len(docker_args):
                raise ValueError("Docker volume option has no value")
            value = docker_args[index + 1]
            try:
                source, destination, access = value.rsplit(":", 2)
            except ValueError as exc:
                raise ValueError("Docker volume option is not source:destination:access") from exc
            if access not in {"ro", "rw"}:
                raise ValueError("Docker volume access is not ro or rw")
            mounts.append({"source": source, "destination": destination, "access": access})
            index += 2
            continue
        index += 1
    if not mounts:
        raise ValueError("Docker command has no bind mounts")
    return mounts


def _split_cli(argv: list[str]) -> tuple[str, list[str]]:
    try:
        separator = argv.index("--")
    except ValueError as exc:
        raise ValueError("proxy requires `--` before Docker arguments") from exc
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker")
    options = parser.parse_args(argv[:separator])
    docker_args = argv[separator + 1 :]
    if not docker_args:
        raise ValueError("proxy requires Docker arguments")
    return options.docker, docker_args


def _fixed_error(request_id: Any = None) -> bytes:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "error": {"code": PROXY_ERROR_CODE, "message": "RPC path mapping rejected"},
    }
    if request_id is not None:
        response["id"] = request_id
    return (json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8")


def _request_id(line: str) -> Any:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value.get("id") if isinstance(value, dict) else None


def _write_stdout(lock: threading.Lock, payload: bytes) -> None:
    with lock:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()


def _map_request_payload(mapper: RpcPathMapper, raw: bytes) -> tuple[bytes | None, bytes | None]:
    """Return either a child request or a fixed error for the control client."""
    try:
        line = raw.decode("utf-8")
        mapped = map_json_line(mapper, line)
        return (mapped + "\n").encode("utf-8"), None
    except (UnicodeDecodeError, RpcPathMappingError, ValueError):
        return None, _fixed_error(_request_id(raw.decode("utf-8", errors="replace")))


def run_proxy(docker: str, docker_args: list[str]) -> int:
    mapper = RpcPathMapper.from_mounts(_docker_mounts(docker_args))
    child = subprocess.Popen(
        [docker, *docker_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,
        bufsize=0,
    )
    assert child.stdin is not None
    assert child.stdout is not None
    output_lock = threading.Lock()
    stop = threading.Event()

    def forward_requests() -> None:
        try:
            for raw in sys.stdin.buffer:
                if stop.is_set():
                    break
                payload, rejection = _map_request_payload(mapper, raw)
                if rejection is not None:
                    _write_stdout(output_lock, rejection)
                    continue
                assert payload is not None
                child.stdin.write(payload)
                child.stdin.flush()
        finally:
            try:
                child.stdin.close()
            except OSError:
                pass

    def forward_responses() -> None:
        try:
            for raw in child.stdout:
                if stop.is_set():
                    break
                try:
                    line = raw.decode("utf-8")
                    mapped = map_json_line(mapper, line, response=True)
                    payload = (mapped + "\n").encode("utf-8")
                except (UnicodeDecodeError, RpcPathMappingError, ValueError):
                    stop.set()
                    child.terminate()
                    break
                _write_stdout(output_lock, payload)
        finally:
            stop.set()

    request_thread = threading.Thread(target=forward_requests, name="rpc-proxy-stdin")
    response_thread = threading.Thread(target=forward_responses, name="rpc-proxy-stdout")
    request_thread.start()
    response_thread.start()
    response_thread.join()
    stop.set()
    if child.poll() is None:
        child.terminate()
    request_thread.join(timeout=5)
    return child.wait()


def main() -> int:
    try:
        docker, docker_args = _split_cli(sys.argv[1:])
        return run_proxy(docker, docker_args)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        # Keep failures fixed-label and avoid echoing command/path payloads.
        print(f"feynman RPC proxy failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
