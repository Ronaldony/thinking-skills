#!/usr/bin/env python3
"""Serve deterministic Responses API SSE for remote-tool references.

Two scenarios are supported:

- ``exec-only``: prove that a host-side Codex control plane can route an
  ``exec_command`` into the selected remote exec-server, while the tool boundary
  has no network and no auth-like environment variables.
- ``patch-then-exec``: additionally request ``apply_patch`` first, then require
  the remote command to read the patched marker.

For synthetic authentication references an optional expected bearer SHA-256 may
be supplied. The server then verifies that every Responses request carries the
matching bearer while recording only its digest, never the raw Authorization
header or token. The expected digest can also be embedded into the remote tool
command so the tool process proves that no environment value equals the control-
plane credential.

This is a test model server. It never calls an external model service and never
needs a real credential.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

SCENARIO_EXEC_ONLY = "exec-only"
SCENARIO_PATCH_THEN_EXEC = "patch-then-exec"
SCENARIOS = {SCENARIO_EXEC_ONLY, SCENARIO_PATCH_THEN_EXEC}
PATCH_CALL_ID = "call-remote-patch-reference"
EXEC_CALL_ID = "call-remote-exec-reference"
FINAL_TEXT = "REMOTE_EXEC_REFERENCE_OK"
PATCH_FILENAME = "remote-patch-proof.txt"
PATCH_MARKER = "REMOTE_PATCH_OK"
WORKSPACE_MARKER = "REMOTE_EXEC_OK"
NETWORK_MARKER = "NETWORK_BLOCKED"
AUTH_ENV_MARKER = "AUTH_ENV_CLEAN"
AUTH_VALUE_MARKER = "AUTH_VALUE_CLEAN"
MAX_BODY_BYTES = 5 * 1024 * 1024
HOST_PATTERN = re.compile(r"(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _sse(events: list[dict[str, Any]]) -> bytes:
    chunks: list[str] = []
    for event in events:
        kind = event["type"]
        chunks.append(f"event: {kind}\n")
        chunks.append("data: " + json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n\n")
    return "".join(chunks).encode("utf-8")


def _created(response_id: str) -> dict[str, Any]:
    return {"type": "response.created", "response": {"id": response_id}}


def _completed(response_id: str) -> dict[str, Any]:
    return {
        "type": "response.completed",
        "response": {
            "id": response_id,
            "usage": {
                "input_tokens": 0,
                "input_tokens_details": None,
                "output_tokens": 0,
                "output_tokens_details": None,
                "total_tokens": 0,
            },
        },
    }


def _patch_text() -> str:
    return (
        "*** Begin Patch\n"
        f"*** Add File: {PATCH_FILENAME}\n"
        f"+{PATCH_MARKER}\n"
        "*** End Patch\n"
    )


def apply_patch_events() -> list[dict[str, Any]]:
    response_id = "resp-remote-patch"
    return [
        _created(response_id),
        {
            "type": "response.output_item.done",
            "item": {
                "type": "custom_tool_call",
                "call_id": PATCH_CALL_ID,
                "name": "apply_patch",
                "input": _patch_text(),
            },
        },
        _completed(response_id),
    ]


def _tool_command(
    host: str,
    port: int,
    *,
    require_patch: bool = False,
    expected_bearer_sha256: str | None = None,
) -> str:
    if HOST_PATTERN.fullmatch(host) is None:
        raise ValueError("tool network host contains unsupported characters")
    if not 1 <= port <= 65535:
        raise ValueError("tool network port must be in 1..65535")
    if expected_bearer_sha256 is not None and SHA256_PATTERN.fullmatch(expected_bearer_sha256) is None:
        raise ValueError("expected bearer digest must be lowercase SHA-256")

    patch_lines = ""
    if require_patch:
        patch_lines = (
            f'PATCH_VALUE="$(cat {PATCH_FILENAME})"\n'
            f"test \"$PATCH_VALUE\" = '{PATCH_MARKER}'\n"
            "printf '%s\\n' \"$PATCH_VALUE\"\n"
        )

    value_check = ""
    if expected_bearer_sha256 is not None:
        value_check = f"""python3 - <<'PY'
import hashlib
import os
expected = {expected_bearer_sha256!r}
leaks = []
for key, value in os.environ.items():
    digest = hashlib.sha256(value.encode('utf-8', errors='surrogateescape')).hexdigest()
    if digest == expected:
        leaks.append(key)
if leaks:
    print('AUTH_VALUE_LEAK:' + ','.join(sorted(leaks)))
    raise SystemExit(10)
print({AUTH_VALUE_MARKER!r})
PY
"""

    return f"""set -eu
{patch_lines}printf '%s\\n' '{WORKSPACE_MARKER}' > remote-tool-proof.txt
python3 - <<'PY'
import os
import re
pattern = re.compile(r'(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE|AUTH|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)', re.I)
bad = sorted(key for key in os.environ if pattern.search(key))
if bad:
    print('AUTH_ENV_LEAK:' + ','.join(bad))
    raise SystemExit(8)
print({AUTH_ENV_MARKER!r})
PY
{value_check}python3 - <<'PY'
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(0.5)
try:
    sock.connect(({host!r}, {port}))
except OSError:
    print({NETWORK_MARKER!r})
    raise SystemExit(0)
print('NETWORK_UNEXPECTED')
raise SystemExit(9)
PY
cat remote-tool-proof.txt
"""


def exec_command_events(
    host: str,
    port: int,
    *,
    require_patch: bool = False,
    expected_bearer_sha256: str | None = None,
) -> list[dict[str, Any]]:
    response_id = "resp-remote-exec"
    arguments = json.dumps(
        {
            "cmd": _tool_command(
                host,
                port,
                require_patch=require_patch,
                expected_bearer_sha256=expected_bearer_sha256,
            ),
            "yield_time_ms": 1000,
        },
        separators=(",", ":"),
    )
    return [
        _created(response_id),
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "call_id": EXEC_CALL_ID,
                "name": "exec_command",
                "arguments": arguments,
            },
        },
        _completed(response_id),
    ]


def final_events() -> list[dict[str, Any]]:
    response_id = "resp-remote-final"
    return [
        _created(response_id),
        {
            "type": "response.output_item.done",
            "item": {
                "type": "message",
                "role": "assistant",
                "id": "msg-remote-final",
                "content": [{"type": "output_text", "text": FINAL_TEXT}],
            },
        },
        _completed(response_id),
    ]


def _iter_nodes(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _iter_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_nodes(child)


def find_call_output(body: Any, *, call_id: str, output_type: str) -> str | None:
    for node in _iter_nodes(body):
        if not isinstance(node, dict):
            continue
        if node.get("type") != output_type or node.get("call_id") != call_id:
            continue
        output = node.get("output")
        if isinstance(output, str):
            return output
        if output is not None:
            return json.dumps(output, ensure_ascii=False, sort_keys=True)
    return None


def find_patch_output(body: Any) -> str | None:
    return find_call_output(body, call_id=PATCH_CALL_ID, output_type="custom_tool_call_output")


def find_exec_output(body: Any) -> str | None:
    return find_call_output(body, call_id=EXEC_CALL_ID, output_type="function_call_output")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(name, path)
    except Exception:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def _bearer_digest(header: str | None) -> tuple[bool, str | None]:
    if header is None or not header.startswith("Bearer "):
        return False, None
    token = header[len("Bearer "):]
    if not token:
        return False, None
    return True, hashlib.sha256(token.encode("utf-8", errors="surrogateescape")).hexdigest()


class ReferenceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        state_path: Path,
        ready_path: Path,
        tool_network_host: str,
        scenario: str,
        expected_bearer_sha256: str | None = None,
    ):
        if scenario not in SCENARIOS:
            raise ValueError(f"unsupported reference scenario: {scenario}")
        if expected_bearer_sha256 is not None and SHA256_PATTERN.fullmatch(expected_bearer_sha256) is None:
            raise ValueError("expected bearer digest must be lowercase SHA-256")
        super().__init__(address, ReferenceHandler)
        self.state_path = state_path
        self.ready_path = ready_path
        self.tool_network_host = tool_network_host
        self.scenario = scenario
        self.expected_bearer_sha256 = expected_bearer_sha256
        self.requests: list[dict[str, Any]] = []
        self.validation_error: str | None = None

    def write_state(self) -> None:
        _atomic_json(
            self.state_path,
            {
                "schema_version": 4,
                "scenario": self.scenario,
                "requests": self.requests,
                "validation_error": self.validation_error,
                "expected_bearer_sha256": self.expected_bearer_sha256,
                "final_text": FINAL_TEXT,
                "patch_call_id": PATCH_CALL_ID if self.scenario == SCENARIO_PATCH_THEN_EXEC else None,
                "exec_call_id": EXEC_CALL_ID,
                "patch_filename": PATCH_FILENAME if self.scenario == SCENARIO_PATCH_THEN_EXEC else None,
                "scope": (
                    "mock Responses control-plane reference; raw authorization values are never recorded; "
                    f"scenario={self.scenario}"
                ),
            },
        )


class ReferenceHandler(BaseHTTPRequestHandler):
    server: ReferenceServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json(self, status: int, value: dict[str, Any]) -> None:
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)

    def _sse(self, events: list[dict[str, Any]]) -> None:
        raw = _sse(events)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/healthz":
            self._json(200, {"ok": True, "scenario": self.server.scenario})
            return
        if self.path in {"/v1/models", "/models"}:
            self._json(200, {"object": "list", "data": []})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.rstrip("/") not in {"/v1/responses", "/responses"}:
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "invalid content length"})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(413, {"error": "invalid request body size"})
            return
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return

        bearer_present, bearer_sha = _bearer_digest(self.headers.get("Authorization"))
        expected_bearer = self.server.expected_bearer_sha256
        bearer_matches = expected_bearer is None or bearer_sha == expected_bearer
        patch_output = find_patch_output(body)
        exec_output = find_exec_output(body)
        record = {
            "index": len(self.server.requests) + 1,
            "body_sha256": hashlib.sha256(raw).hexdigest(),
            "authorization_bearer_present": bearer_present,
            "authorization_bearer_sha256": bearer_sha,
            "authorization_matches_expected": bearer_matches,
            "has_patch_output": patch_output is not None,
            "patch_output_sha256": (
                hashlib.sha256(patch_output.encode("utf-8")).hexdigest()
                if patch_output is not None else None
            ),
            "has_exec_output": exec_output is not None,
            "exec_output_sha256": (
                hashlib.sha256(exec_output.encode("utf-8")).hexdigest()
                if exec_output is not None else None
            ),
            "exec_output_contains_patch_marker": (
                PATCH_MARKER in exec_output if exec_output is not None else False
            ),
            "exec_output_contains_workspace_marker": (
                WORKSPACE_MARKER in exec_output if exec_output is not None else False
            ),
            "exec_output_contains_network_marker": (
                NETWORK_MARKER in exec_output if exec_output is not None else False
            ),
            "exec_output_contains_auth_env_marker": (
                AUTH_ENV_MARKER in exec_output if exec_output is not None else False
            ),
            "exec_output_contains_auth_value_marker": (
                AUTH_VALUE_MARKER in exec_output if exec_output is not None else False
            ),
        }
        self.server.requests.append(record)

        if expected_bearer is not None and not bearer_matches:
            self.server.validation_error = "Responses request bearer is missing or does not match expected SHA-256"
            self.server.write_state()
            self._json(401, {"error": self.server.validation_error})
            return

        request_no = len(self.server.requests)
        auth_value_required = expected_bearer is not None

        if self.server.scenario == SCENARIO_EXEC_ONLY:
            if request_no == 1:
                self.server.write_state()
                self._sse(
                    exec_command_events(
                        self.server.tool_network_host,
                        self.server.server_port,
                        expected_bearer_sha256=expected_bearer,
                    )
                )
                return
            if request_no == 2:
                required = [WORKSPACE_MARKER, NETWORK_MARKER, AUTH_ENV_MARKER]
                if auth_value_required:
                    required.append(AUTH_VALUE_MARKER)
                if exec_output is None or not all(marker in exec_output for marker in required):
                    self.server.validation_error = (
                        "second model request lacks verified exec-only remote output markers"
                    )
                    self.server.write_state()
                    self._json(409, {"error": self.server.validation_error})
                    return
                self.server.write_state()
                self._sse(final_events())
                return
            self.server.validation_error = "exec-only reference received more than two model requests"
            self.server.write_state()
            self._json(409, {"error": self.server.validation_error})
            return

        if request_no == 1:
            self.server.write_state()
            self._sse(apply_patch_events())
            return
        if request_no == 2:
            if patch_output is None:
                self.server.validation_error = (
                    "second model request lacks matching remote apply_patch output"
                )
                self.server.write_state()
                self._json(409, {"error": self.server.validation_error})
                return
            self.server.write_state()
            self._sse(
                exec_command_events(
                    self.server.tool_network_host,
                    self.server.server_port,
                    require_patch=True,
                    expected_bearer_sha256=expected_bearer,
                )
            )
            return
        if request_no == 3:
            required = [PATCH_MARKER, WORKSPACE_MARKER, NETWORK_MARKER, AUTH_ENV_MARKER]
            if auth_value_required:
                required.append(AUTH_VALUE_MARKER)
            if exec_output is None or not all(marker in exec_output for marker in required):
                self.server.validation_error = (
                    "third model request lacks verified patch-then-exec output markers"
                )
                self.server.write_state()
                self._json(409, {"error": self.server.validation_error})
                return
            self.server.write_state()
            self._sse(final_events())
            return
        self.server.validation_error = "patch-then-exec reference received more than three model requests"
        self.server.write_state()
        self._json(409, {"error": self.server.validation_error})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--tool-network-host", required=True)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default=SCENARIO_EXEC_ONLY)
    parser.add_argument("--expected-bearer-sha256")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()
    if args.port < 0 or args.port > 65535:
        parser.error("--port must be in 0..65535")
    if HOST_PATTERN.fullmatch(args.tool_network_host) is None:
        parser.error("--tool-network-host contains unsupported characters")
    if args.expected_bearer_sha256 is not None and SHA256_PATTERN.fullmatch(args.expected_bearer_sha256) is None:
        parser.error("--expected-bearer-sha256 must be lowercase SHA-256")

    server = ReferenceServer(
        (args.bind, args.port),
        state_path=args.state.resolve(),
        ready_path=args.ready.resolve(),
        tool_network_host=args.tool_network_host,
        scenario=args.scenario,
        expected_bearer_sha256=args.expected_bearer_sha256,
    )
    _atomic_json(
        server.ready_path,
        {
            "schema_version": 2,
            "bind": args.bind,
            "port": server.server_port,
            "tool_network_host": args.tool_network_host,
            "scenario": args.scenario,
            "expected_bearer_sha256": args.expected_bearer_sha256,
        },
    )
    server.write_state()
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
