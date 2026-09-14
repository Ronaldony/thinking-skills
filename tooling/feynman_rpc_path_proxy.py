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
import ctypes
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

try:
    from .feynman_rpc_path_mapping import (
        REQUEST_PATH_ARRAY_FIELDS, REQUEST_PATH_FIELDS, RpcPathMapper,
        RpcPathMappingError, map_json_line,
    )
except ImportError:
    from feynman_rpc_path_mapping import (
        REQUEST_PATH_ARRAY_FIELDS, REQUEST_PATH_FIELDS, RpcPathMapper,
        RpcPathMappingError, map_json_line,
    )


PROXY_ERROR_CODE = -32001
PROBE_READ_LIMIT_ENV = "FEYNMAN_PROBE_RPC_READ_LIMIT_BYTES"
PROBE_ALLOWED_METHODS_ENV = "FEYNMAN_PROBE_RPC_ALLOWED_METHODS"
PROBE_ALLOWED_PATH_ENV = "FEYNMAN_PROBE_RPC_ALLOWED_PATH"
TELEMETRY_OVERRIDE_ENV = "FEYNMAN_RPC_TELEMETRY_OVERRIDE"
PROBE_CONFIG_PATH = "file:///run/candidate/.feynman-diagnostic-absent.toml"
_SAFE_REJECTION_FIELDS = frozenset({
    "unknown",
    *(field for fields in REQUEST_PATH_FIELDS.values() for field in fields),
    *(field for fields in REQUEST_PATH_ARRAY_FIELDS.values() for field in fields),
})

# Mapping exceptions contain only fixed source-controlled messages.  Convert
# them to bounded labels before telemetry so a rejected path is never retained.
_MAPPING_REJECTION_REASONS = {
    "only local file URIs are supported": "unsupported-file-uri",
    "file URI query and fragment components are unsupported": "unsupported-file-uri-components",
    "host path must be absolute": "host-path-not-absolute",
    "host path must be traversal-free": "host-path-traversal",
    "host path must be absolute and traversal-free": "invalid-host-path",
    "host path is outside declared mounts": "host-path-outside-declared-mount",
    "container path must be absolute": "container-path-not-absolute",
    "container path must be traversal-free": "container-path-traversal",
    "container path must be absolute and traversal-free": "invalid-container-path",
    "container path is outside declared mounts": "container-path-outside-declared-mount",
    "container file URI must use POSIX paths": "invalid-container-file-uri",
    "declared path field must be a string": "invalid-path-field-type",
    "declared path array must be a list": "invalid-path-array-shape",
    "config path groups must contain only paths": "invalid-path-array-shape",
    "relative requirements path is ambiguous": "ambiguous-relative-environment-path",
    "relative requirements path is unsafe": "unsafe-relative-environment-path",
    "candidate mount is not declared": "candidate-mount-not-declared",
    "RPC line is not valid JSON": "malformed-request",
    "RPC message must be a JSON object": "malformed-request",
}

_SAFE_REQUEST_METHODS = frozenset({
    "initialize", "initialized", "thread/start", "environment/info",
    *REQUEST_PATH_FIELDS,
})


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
        self._request_mapping_rejection_methods: Counter[str] = Counter()
        self._request_mapping_rejection_reasons: Counter[str] = Counter()
        self._request_mapping_rejection_method_reasons: dict[str, Counter[str]] = {}
        self._request_mapping_rejection_method_reason_fields: dict[str, dict[str, Counter[str]]] = {}
        self._response_error_codes: Counter[str] = Counter()
        self._values: Counter[str] = Counter()
        self._child_exit_code: int | None = None

    @staticmethod
    def _safe_method(method: str | None) -> str:
        return method if method in _SAFE_REQUEST_METHODS else "unknown"

    def request_seen(self, method: str | None) -> None:
        with self._lock:
            self._values["requests_seen"] += 1
            self._request_methods[self._safe_method(method)] += 1

    def request_forwarded(self) -> None:
        with self._lock:
            self._values["requests_forwarded"] += 1

    def request_write_failed(self) -> None:
        with self._lock:
            self._values["request_write_failures"] += 1

    def request_id_duplicate(self) -> None:
        with self._lock:
            self._values["request_id_duplicates"] += 1

    def request_rejected(self, *, malformed: bool, method: str | None = None,
                         reason: str | None = None, path_field: str | None = None) -> None:
        with self._lock:
            # A rejected method is useful only as a member of the finite
            # declared path-method contract.  Do not turn an arbitrary peer
            # string into diagnostic data.
            method_key = method if method in REQUEST_PATH_FIELDS else "unknown"
            reason_key = reason if reason in _SAFE_REJECTION_REASONS else "unclassified"
            field_key = path_field if path_field in _SAFE_REJECTION_FIELDS else "unknown"
            self._values["request_mapping_rejections"] += 1
            self._request_mapping_rejection_methods[method_key] += 1
            self._request_mapping_rejection_reasons[reason_key] += 1
            self._request_mapping_rejection_method_reasons.setdefault(
                method_key, Counter())[reason_key] += 1
            self._request_mapping_rejection_method_reason_fields.setdefault(
                method_key, {}).setdefault(reason_key, Counter())[field_key] += 1
            if malformed:
                self._values["malformed_requests"] += 1

    def response_seen(self, error_code: Any = None, *, malformed: bool = False,
                      matched: bool | None = None, notification: bool = False) -> None:
        with self._lock:
            self._values["responses_seen"] += 1
            if isinstance(error_code, int) and not isinstance(error_code, bool):
                self._response_error_codes[str(error_code)] += 1
            if malformed:
                self._values["malformed_responses"] += 1
            if notification:
                self._values["notifications_seen"] += 1
            elif matched is True:
                self._values["responses_matched"] += 1
            elif matched is False:
                self._values["responses_unmatched"] += 1

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

    def pending_request_ids(self, count: int) -> None:
        with self._lock:
            self._values["pending_request_ids"] = max(0, count)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            values = dict(self._values)
            return {
                "schema_version": 3,
                "request_methods": dict(sorted(self._request_methods.items())),
                "response_error_codes": dict(sorted(self._response_error_codes.items())),
                "requests_seen": values.get("requests_seen", 0),
                "requests_forwarded": values.get("requests_forwarded", 0),
                "request_write_failures": values.get("request_write_failures", 0),
                "request_id_duplicates": values.get("request_id_duplicates", 0),
                "request_mapping_rejections": values.get("request_mapping_rejections", 0),
                "request_mapping_rejection_methods": dict(sorted(self._request_mapping_rejection_methods.items())),
                "request_mapping_rejection_reasons": dict(sorted(self._request_mapping_rejection_reasons.items())),
                "request_mapping_rejection_method_reasons": {
                    method: dict(sorted(reasons.items()))
                    for method, reasons in sorted(
                        self._request_mapping_rejection_method_reasons.items())
                },
                "request_mapping_rejection_method_reason_fields": {
                    method: {
                        reason: dict(sorted(fields.items()))
                        for reason, fields in sorted(reasons.items())
                    }
                    for method, reasons in sorted(
                        self._request_mapping_rejection_method_reason_fields.items())
                },
                "malformed_requests": values.get("malformed_requests", 0),
                "responses_seen": values.get("responses_seen", 0),
                "responses_forwarded": values.get("responses_forwarded", 0),
                "responses_matched": values.get("responses_matched", 0),
                "responses_unmatched": values.get("responses_unmatched", 0),
                "notifications_seen": values.get("notifications_seen", 0),
                "pending_request_ids": values.get("pending_request_ids", 0),
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


def _parent_stdin_lines(stop: threading.Event):
    """Yield complete parent lines without blocking shutdown on Windows pipes."""
    fd = sys.stdin.fileno()
    buffered = bytearray()
    while not stop.is_set():
        if os.name == "nt":
            available = ctypes.c_ulong(0)
            try:
                ok = ctypes.windll.kernel32.PeekNamedPipe(
                    ctypes.c_void_p(msvcrt.get_osfhandle(fd)),
                    None, 0, None, ctypes.byref(available), None)
            except (AttributeError, OSError, ValueError):
                ok = False
            if not ok:
                break
            if available.value == 0:
                time.sleep(0.05)
                continue
            try:
                chunk = os.read(fd, min(available.value, 65536))
            except OSError:
                break
        else:
            try:
                ready, _, _ = select.select([fd], [], [], 0.25)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
        if not chunk:
            break
        buffered.extend(chunk)
        while True:
            try:
                end = buffered.index(10)
            except ValueError:
                break
            yield bytes(buffered[:end + 1])
            del buffered[:end + 1]


if os.name == "nt":
    import msvcrt


def _write_telemetry(path: Path | None, telemetry: _ProxyTelemetry) -> None:
    if path is None:
        return
    if path.is_symlink():
        raise OSError("refusing to write telemetry through symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(telemetry.snapshot(), ensure_ascii=False, indent=2) + "\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _effective_telemetry_path(configured: Path | None) -> Path | None:
    """Use a caller-owned diagnostic telemetry path when explicitly supplied.

    The remote-environment document has a stable telemetry destination for a
    real evaluator run.  Model-free control-plane probes must not overwrite
    that artifact, so they can pass one fresh absolute path through a private
    host-only environment variable.  The container receives ``env -i`` and
    cannot observe this setting.
    """
    override = os.environ.get(TELEMETRY_OVERRIDE_ENV)
    if override is None:
        return configured
    candidate = Path(override).expanduser()
    if not candidate.is_absolute() or candidate.is_symlink() or candidate.exists():
        raise ValueError("invalid telemetry override path")
    return candidate


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


_SAFE_REJECTION_REASONS = frozenset({
    *_MAPPING_REJECTION_REASONS.values(),
    "probe-method-not-allowed",
    "probe-read-path-type",
    "probe-config-policy",
    "probe-filesystem-path-policy",
    "invalid-request-structure",
    "unclassified",
})

SAFE_TELEMETRY_METHODS = frozenset({*_SAFE_REQUEST_METHODS, "unknown"})
SAFE_REJECTION_METHODS = frozenset({*REQUEST_PATH_FIELDS, "unknown"})
SAFE_TELEMETRY_REASONS = _SAFE_REJECTION_REASONS
SAFE_REJECTION_FIELDS = _SAFE_REJECTION_FIELDS


def _map_request_payload_with_reason(
    mapper: RpcPathMapper,
    raw: bytes,
    *,
    read_limit: int | None = None,
    allowed_methods: frozenset[str] | None = None,
    allowed_path: str | None = None,
) -> tuple[bytes | None, bytes | None, str | None, str | None]:
    """Return a child request or fixed error plus payload-free context."""
    try:
        message = _json_object(raw)
        if allowed_methods is not None:
            if message is None or message.get("method") not in allowed_methods:
                return None, _fixed_error(message.get("id") if message else None), "probe-method-not-allowed", None
        if message and message.get("method") == "fs/readFile":
            params = dict(message.get("params")) if isinstance(message.get("params"), dict) else {}
            if allowed_path is not None:
                path = params.get("path")
                # This check occurs after path mapping below as well; the
                # host-side value is never echoed in an error response.
                if path is not None and not isinstance(path, str):
                    return None, _fixed_error(message.get("id")), "probe-read-path-type", "path"
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
                return None, _fixed_error(message.get("id")), "probe-config-policy", "cwd"
            for field in ("configPaths", "requirementsPaths"):
                groups = params.get(field, [])
                if not isinstance(groups, list) or any(
                    not isinstance(group, list) or any(path != PROBE_CONFIG_PATH for path in group)
                    for group in groups
                ):
                    return None, _fixed_error(message.get("id")), "probe-config-policy", field
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
                return None, _fixed_error(message.get("id")), "probe-filesystem-path-policy", "path"
        return (mapped + "\n").encode("utf-8"), None, None, None
    except RpcPathMappingError as exc:
        reason = _MAPPING_REJECTION_REASONS.get(str(exc), "unclassified")
        return (None, _fixed_error(_request_id(raw.decode("utf-8", errors="replace"))),
                reason, exc.path_field)
    except UnicodeDecodeError:
        return None, _fixed_error(None), "malformed-request", None
    except ValueError:
        return (None, _fixed_error(_request_id(raw.decode("utf-8", errors="replace"))),
                "invalid-request-structure", None)


def _map_request_payload(
    mapper: RpcPathMapper,
    raw: bytes,
    *,
    read_limit: int | None = None,
    allowed_methods: frozenset[str] | None = None,
    allowed_path: str | None = None,
) -> tuple[bytes | None, bytes | None]:
    """Compatibility wrapper returning only child payload or fixed error."""
    payload, rejection, _, _ = _map_request_payload_with_reason(
        mapper, raw, read_limit=read_limit,
        allowed_methods=allowed_methods, allowed_path=allowed_path,
    )
    return payload, rejection


def _stop_proxy_child(child: subprocess.Popen[bytes], deadline: float) -> bool:
    """Terminate the exact proxy child within a caller-owned deadline."""
    if child.poll() is not None:
        return True
    remaining = max(0.1, deadline - time.monotonic())
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=remaining,
            )
        else:
            child.terminate()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        child.wait(timeout=max(0.1, deadline - time.monotonic()))
        return True
    except subprocess.TimeoutExpired:
        try:
            child.kill()
        except OSError:
            pass
        try:
            child.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return False
        return True


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
    telemetry_path = _effective_telemetry_path(telemetry_path)
    telemetry = _ProxyTelemetry()
    telemetry_file_lock = threading.Lock()
    telemetry_write_wakeup = threading.Event()
    telemetry_write_stop = threading.Event()
    telemetry_write_failed = [False]

    def persist_telemetry() -> None:
        if telemetry_path is None:
            return
        # Forwarding workers only publish that a newer snapshot exists.  The
        # single writer below owns filesystem I/O so fsync/replace latency
        # cannot stall an RPC pipe or make protocol timing nondeterministic.
        telemetry_write_wakeup.set()

    def write_telemetry_snapshots() -> None:
        while True:
            telemetry_write_wakeup.wait()
            telemetry_write_wakeup.clear()
            try:
                with telemetry_file_lock:
                    _write_telemetry(telemetry_path, telemetry)
            except (OSError, ValueError):
                # Keep the failure sticky.  A later successful write cannot
                # turn an execution with incomplete evidence into a green
                # proxy result; the final child exit is forced nonzero.
                telemetry_write_failed[0] = True
            if telemetry_write_stop.is_set() and not telemetry_write_wakeup.is_set():
                return

    # Materialize a safe initial snapshot before any child launch.  Later
    # snapshots make partial lifecycle evidence durable even when App Server
    # tears down the proxy before EOF.
    if telemetry_path is not None:
        with telemetry_file_lock:
            _write_telemetry(telemetry_path, telemetry)
    child = subprocess.Popen(
        [docker, *docker_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    assert child.stdin is not None
    assert child.stdout is not None
    telemetry_writer = None
    if telemetry_path is not None:
        telemetry_writer = threading.Thread(
            target=write_telemetry_snapshots, name="rpc-proxy-telemetry-writer", daemon=True)
        telemetry_writer.start()
    output_lock = threading.Lock()
    stop = threading.Event()
    pending_lock = threading.Lock()
    pending_methods: dict[str | int, str] = {}

    def forward_requests() -> None:
        try:
            for raw in _parent_stdin_lines(stop):
                request = _json_object(raw)
                telemetry.request_seen(request.get("method") if request else None)
                persist_telemetry()
                if request and request.get("method") == "fs/readFile" and read_limit is not None:
                    telemetry.probe_read_limit_applied()
                if allowed_methods is not None and (request is None or request.get("method") not in allowed_methods):
                    telemetry.probe_policy_rejected()
                payload, rejection, rejection_reason, rejection_field = _map_request_payload_with_reason(
                    mapper, raw, read_limit=read_limit,
                    allowed_methods=allowed_methods, allowed_path=allowed_path,
                )
                if rejection is not None:
                    telemetry.request_rejected(
                        malformed=request is None,
                        method=request.get("method") if request else None,
                        reason=rejection_reason,
                        path_field=rejection_field,
                    )
                    persist_telemetry()
                    _write_stdout(output_lock, rejection)
                    continue
                assert payload is not None
                if request and type(request.get("id")) in {str, int}:
                    with pending_lock:
                        if request["id"] in pending_methods:
                            telemetry.request_id_duplicate()
                        pending_methods[request["id"]] = request.get("method")
                        telemetry.pending_request_ids(len(pending_methods))
                try:
                    child.stdin.write(payload)
                    child.stdin.flush()
                except (BrokenPipeError, OSError):
                    telemetry.request_write_failed()
                    persist_telemetry()
                    stop.set()
                    break
                telemetry.request_forwarded()
                persist_telemetry()
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
                request_method = None
                has_id = response is not None and type(response.get("id")) in {str, int}
                if response and type(response.get("id")) in {str, int}:
                    with pending_lock:
                        request_method = pending_methods.pop(response["id"], None)
                        telemetry.pending_request_ids(len(pending_methods))
                telemetry.response_seen(
                    error_code,
                    malformed=response is None,
                    matched=(request_method is not None) if has_id else None,
                    notification=(response is not None and not has_id),
                )
                persist_telemetry()
                if (read_limit is not None and request_method == "fs/readFile"
                        and response is not None and "error" not in response
                        and not _read_response_within_limit(response, read_limit)):
                    telemetry.probe_response_rejected(_read_response_size(response))
                    persist_telemetry()
                    _write_stdout(output_lock, _fixed_error(response.get("id")))
                    continue
                try:
                    line = raw.decode("utf-8")
                    mapped = map_json_line(
                        mapper, line, response=True, request_method=request_method)
                    payload = (mapped + "\n").encode("utf-8")
                except (UnicodeDecodeError, RpcPathMappingError, ValueError):
                    telemetry.response_rejected()
                    persist_telemetry()
                    stop.set()
                    child.terminate()
                    break
                _write_stdout(output_lock, payload)
                telemetry.response_forwarded()
                persist_telemetry()
        finally:
            stop.set()

    request_thread = threading.Thread(
        target=forward_requests, name="rpc-proxy-stdin", daemon=True)
    response_thread = threading.Thread(
        target=forward_responses, name="rpc-proxy-stdout", daemon=True)
    request_thread.start()
    response_thread.start()
    # Keep the proxy alive while its parent still owns stdin.  Once the parent
    # closes stdin, the request thread closes child.stdin and the child is
    # allowed to drain its final responses.  Bounded cleanup is used only
    # after a worker ends unexpectedly or the child ignores EOF.
    while request_thread.is_alive() and response_thread.is_alive():
        request_thread.join(timeout=0.25)
    cleanup_deadline: float | None = None
    if response_thread.is_alive():
        cleanup_deadline = time.monotonic() + 15
        response_thread.join(timeout=max(0.1, cleanup_deadline - time.monotonic()))
        if response_thread.is_alive():
            stop.set()
    else:
        stop.set()
        cleanup_deadline = time.monotonic() + 15
    if child.poll() is None:
        if cleanup_deadline is None:
            cleanup_deadline = time.monotonic() + 15
        _stop_proxy_child(child, cleanup_deadline)
    if response_thread.is_alive():
        response_thread.join(timeout=max(0.1, (cleanup_deadline or time.monotonic()) - time.monotonic()))
    if request_thread.is_alive() and response_thread.is_alive():
        request_thread.join(timeout=max(0.1, (cleanup_deadline or time.monotonic()) - time.monotonic()))
    exit_code = child.poll()
    if exit_code is None:
        exit_code = 1
    with pending_lock:
        telemetry.pending_request_ids(len(pending_methods))
    if telemetry_write_failed[0]:
        exit_code = 1
    telemetry.child_exit(exit_code)
    persist_telemetry()
    if telemetry_writer is not None:
        telemetry_write_stop.set()
        telemetry_write_wakeup.set()
        telemetry_writer.join(timeout=15)
        if telemetry_writer.is_alive():
            telemetry_write_failed[0] = True
            exit_code = 1
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
    # run_proxy has completed bounded child/thread cleanup before returning.
    # os._exit prevents a daemon parent-stdin reader from keeping this
    # standalone bridge alive on Windows after the child has already ended.
    exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
