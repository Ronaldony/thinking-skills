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
import base64
import binascii
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any

try:
    from .feynman_rpc_path_mapping import RpcPathMapper, RpcPathMappingError, map_json_line
except ImportError:
    from feynman_rpc_path_mapping import RpcPathMapper, RpcPathMappingError, map_json_line


PROXY_ERROR_CODE = -32001
PROBE_READ_LIMIT_ENV = "FEYNMAN_PROBE_RPC_READ_LIMIT_BYTES"
PROBE_ALLOWED_METHODS_ENV = "FEYNMAN_PROBE_RPC_ALLOWED_METHODS"
PROBE_ALLOWED_PATH_ENV = "FEYNMAN_PROBE_RPC_ALLOWED_PATH"
PROBE_CONFIG_PATH = "file:///run/candidate/.feynman-diagnostic-absent.toml"


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


def _split_cli(argv: list[str]) -> tuple[str, Path | None, list[str]]:
    try:
        separator = argv.index("--")
    except ValueError as exc:
        raise ValueError("proxy requires `--` before Docker arguments") from exc
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--telemetry-file", type=Path)
    options = parser.parse_args(argv[:separator])
    docker_args = argv[separator + 1 :]
    if not docker_args:
        raise ValueError("proxy requires Docker arguments")
    return options.docker, options.telemetry_file, docker_args


class _ProxyTelemetry:
    """Thread-safe, payload-free proxy activity counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._request_methods: Counter[str] = Counter()
        self._response_error_codes: Counter[str] = Counter()
        self._values: Counter[str] = Counter()
        self._child_exit_code: int | None = None

    def request_seen(self, method: str | None) -> None:
        with self._lock:
            self._values["requests_seen"] += 1
            self._request_methods[method if isinstance(method, str) else "unknown"] += 1

    def request_forwarded(self) -> None:
        with self._lock:
            self._values["requests_forwarded"] += 1

    def request_rejected(self, *, malformed: bool) -> None:
        with self._lock:
            self._values["request_mapping_rejections"] += 1
            if malformed:
                self._values["malformed_requests"] += 1

    def response_seen(self, error_code: Any = None, *, malformed: bool = False) -> None:
        with self._lock:
            self._values["responses_seen"] += 1
            if isinstance(error_code, int) and not isinstance(error_code, bool):
                self._response_error_codes[str(error_code)] += 1
            if malformed:
                self._values["malformed_responses"] += 1

    def response_forwarded(self) -> None:
        with self._lock:
            self._values["responses_forwarded"] += 1

    def response_rejected(self) -> None:
        with self._lock:
            self._values["response_mapping_rejections"] += 1

    def probe_policy_rejected(self) -> None:
        with self._lock:
            self._values["probe_policy_rejections"] += 1

    def probe_read_limit_applied(self) -> None:
        with self._lock:
            self._values["probe_read_limit_applied"] += 1

    def probe_response_rejected(self, decoded_bytes: int | None = None) -> None:
        with self._lock:
            self._values["probe_response_rejections"] += 1
            if decoded_bytes is not None:
                self._values["probe_rejected_read_max_bytes"] = max(
                    self._values["probe_rejected_read_max_bytes"], decoded_bytes)

    def child_exit(self, value: int | None) -> None:
        with self._lock:
            self._child_exit_code = value

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            values = dict(self._values)
            return {
                "schema_version": 1,
                "request_methods": dict(sorted(self._request_methods.items())),
                "response_error_codes": dict(sorted(self._response_error_codes.items())),
                "requests_seen": values.get("requests_seen", 0),
                "requests_forwarded": values.get("requests_forwarded", 0),
                "request_mapping_rejections": values.get("request_mapping_rejections", 0),
                "malformed_requests": values.get("malformed_requests", 0),
                "responses_seen": values.get("responses_seen", 0),
                "responses_forwarded": values.get("responses_forwarded", 0),
                "response_mapping_rejections": values.get("response_mapping_rejections", 0),
                "malformed_responses": values.get("malformed_responses", 0),
                "probe_policy_rejections": values.get("probe_policy_rejections", 0),
                "probe_read_limit_applied": values.get("probe_read_limit_applied", 0),
                "probe_response_rejections": values.get("probe_response_rejections", 0),
                "probe_rejected_read_max_bytes": values.get("probe_rejected_read_max_bytes", 0),
                "child_exit_code": self._child_exit_code,
            }


def _json_object(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_telemetry(path: Path | None, telemetry: _ProxyTelemetry) -> None:
    if path is None:
        return
    if path.is_symlink():
        raise OSError("refusing to write telemetry through symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(telemetry.snapshot(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _probe_policy_from_env() -> tuple[int | None, frozenset[str] | None, str | None]:
    """Read only fixed probe controls; never serialize the process environment."""
    raw_limit = os.environ.get(PROBE_READ_LIMIT_ENV)
    raw_methods = os.environ.get(PROBE_ALLOWED_METHODS_ENV)
    allowed_path = os.environ.get(PROBE_ALLOWED_PATH_ENV)
    if raw_limit is None and raw_methods is None and allowed_path is None:
        return None, None, None
    if (raw_limit != "1"
            or raw_methods != "environmentConfig/read,fs/getMetadata,fs/readFile"
            or allowed_path != "/run/candidate/candidate.py"):
        raise ValueError("invalid fixed probe RPC policy")
    return 1, frozenset({
        "initialize", "initialized", "environmentConfig/read", "fs/getMetadata", "fs/readFile",
    }), allowed_path


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


def _read_response_size(message: dict[str, Any]) -> int | None:
    """Unknown request fields may be ignored by the server. Verify actual bytes.

    Do not truncate silently: that would conceal an unsupported server-side
    range contract. Reject oversized/malformed results before client exposure.
    """
    result = message.get("result")
    if not isinstance(result, dict) or set(result) != {"dataBase64"}:
        return None
    encoded = result["dataBase64"]
    if not isinstance(encoded, str):
        return None
    try:
        return len(base64.b64decode(encoded, validate=True))
    except (ValueError, binascii.Error):
        return None


def _read_response_within_limit(message: dict[str, Any], limit: int) -> bool:
    size = _read_response_size(message)
    return size is not None and size <= limit


def _write_stdout(lock: threading.Lock, payload: bytes) -> None:
    with lock:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()


def _map_request_payload(
    mapper: RpcPathMapper,
    raw: bytes,
    *,
    read_limit: int | None = None,
    allowed_methods: frozenset[str] | None = None,
    allowed_path: str | None = None,
) -> tuple[bytes | None, bytes | None]:
    """Return either a child request or a fixed error for the control client."""
    try:
        message = _json_object(raw)
        if allowed_methods is not None:
            if message is None or message.get("method") not in allowed_methods:
                return None, _fixed_error(message.get("id") if message else None)
        if message and message.get("method") == "fs/readFile":
            params = dict(message.get("params")) if isinstance(message.get("params"), dict) else {}
            if allowed_path is not None:
                path = params.get("path")
                # This check occurs after path mapping below as well; the
                # host-side value is never echoed in an error response.
                if path is not None and not isinstance(path, str):
                    return None, _fixed_error(message.get("id"))
            if read_limit is not None:
                params["offset"] = 0
                params["len"] = read_limit
                message = dict(message)
                message["params"] = params
                raw = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        line = raw.decode("utf-8")
        mapped = map_json_line(mapper, line)
        if allowed_path is not None and message and message.get("method") == "environmentConfig/read":
            params = json.loads(mapped).get("params", {})
            # Config RPCs can read whole files, so they are NOT metadata-only.
            # Only the diagnostic absent-file sentinel is allowed. Its absence
            # must also be checked before a guarded session is started.
            if params.get("cwd") not in {"/run/candidate", "file:///run/candidate"}:
                return None, _fixed_error(message.get("id"))
            for field in ("configPaths", "requirementsPaths"):
                groups = params.get(field, [])
                if not isinstance(groups, list) or any(
                    not isinstance(group, list) or any(path != PROBE_CONFIG_PATH for path in group)
                    for group in groups
                ):
                    return None, _fixed_error(message.get("id"))
        if allowed_path is not None and message and message.get("method") in {"fs/getMetadata", "fs/readFile"}:
            mapped_message = json.loads(mapped)
            mapped_path = mapped_message.get("params", {}).get("path") if isinstance(mapped_message, dict) else None
            metadata_root = allowed_path.rsplit("/", 1)[0]
            allowed_metadata_paths = {metadata_root, "file://" + metadata_root}
            is_metadata_path = isinstance(mapped_path, str) and (
                mapped_path in allowed_metadata_paths
                or mapped_path.startswith(metadata_root + "/")
                or mapped_path.startswith("file://" + metadata_root + "/")
            )
            is_read_path = mapped_path in {allowed_path, "file://" + allowed_path}
            if (message.get("method") == "fs/readFile" and not is_read_path) or (
                    message.get("method") == "fs/getMetadata" and not is_metadata_path):
                return None, _fixed_error(message.get("id"))
        return (mapped + "\n").encode("utf-8"), None
    except (UnicodeDecodeError, RpcPathMappingError, ValueError):
        return None, _fixed_error(_request_id(raw.decode("utf-8", errors="replace")))


def run_proxy(
    docker: str,
    docker_args: list[str],
    telemetry_path: Path | None = None,
    *,
    read_limit: int | None = None,
    allowed_methods: frozenset[str] | None = None,
    allowed_path: str | None = None,
) -> int:
    mapper = RpcPathMapper.from_mounts(_docker_mounts(docker_args))
    telemetry = _ProxyTelemetry()
    child = subprocess.Popen(
        [docker, *docker_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    assert child.stdin is not None
    assert child.stdout is not None
    output_lock = threading.Lock()
    stop = threading.Event()
    pending_lock = threading.Lock()
    pending_methods: dict[str | int, str] = {}

    def forward_requests() -> None:
        try:
            for raw in sys.stdin.buffer:
                if stop.is_set():
                    break
                request = _json_object(raw)
                telemetry.request_seen(request.get("method") if request else None)
                if request and request.get("method") == "fs/readFile" and read_limit is not None:
                    telemetry.probe_read_limit_applied()
                if allowed_methods is not None and (request is None or request.get("method") not in allowed_methods):
                    telemetry.probe_policy_rejected()
                payload, rejection = _map_request_payload(
                    mapper, raw, read_limit=read_limit,
                    allowed_methods=allowed_methods, allowed_path=allowed_path,
                )
                if rejection is not None:
                    telemetry.request_rejected(malformed=request is None)
                    _write_stdout(output_lock, rejection)
                    continue
                assert payload is not None
                if request and type(request.get("id")) in {str, int}:
                    with pending_lock:
                        pending_methods[request["id"]] = request.get("method")
                telemetry.request_forwarded()
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
                response = _json_object(raw)
                error_code = None
                if response and isinstance(response.get("error"), dict):
                    error_code = response["error"].get("code")
                telemetry.response_seen(error_code, malformed=response is None)
                request_method = None
                if response and type(response.get("id")) in {str, int}:
                    with pending_lock:
                        request_method = pending_methods.pop(response["id"], None)
                if (read_limit is not None and request_method == "fs/readFile"
                        and response is not None and "error" not in response
                        and not _read_response_within_limit(response, read_limit)):
                    telemetry.probe_response_rejected(_read_response_size(response))
                    _write_stdout(output_lock, _fixed_error(response.get("id")))
                    continue
                try:
                    line = raw.decode("utf-8")
                    mapped = map_json_line(mapper, line, response=True)
                    payload = (mapped + "\n").encode("utf-8")
                except (UnicodeDecodeError, RpcPathMappingError, ValueError):
                    telemetry.response_rejected()
                    stop.set()
                    child.terminate()
                    break
                _write_stdout(output_lock, payload)
                telemetry.response_forwarded()
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
    exit_code = child.wait()
    telemetry.child_exit(exit_code)
    _write_telemetry(telemetry_path, telemetry)
    return exit_code


def main() -> int:
    try:
        docker, telemetry_path, docker_args = _split_cli(sys.argv[1:])
        read_limit, allowed_methods, allowed_path = _probe_policy_from_env()
        return run_proxy(
            docker, docker_args, telemetry_path,
            read_limit=read_limit, allowed_methods=allowed_methods, allowed_path=allowed_path,
        )
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        # Keep failures fixed-label and avoid echoing command/path payloads.
        print(f"feynman RPC proxy failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
