#!/usr/bin/env python3
"""Serve deterministic Responses API SSE for the remote-exec reference.

The first response asks Codex to run one `exec_command`. The command writes a
marker in the selected remote workspace, verifies that the tool process cannot
reach the control-plane host/port, and verifies that secret-like environment
keys were not propagated from the control plane. A later response is returned
only after Codex feeds the matching tool output back with all expected markers.

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

CALL_ID = "call-remote-exec-reference"
FINAL_TEXT = "REMOTE_EXEC_REFERENCE_OK"
WORKSPACE_MARKER = "REMOTE_EXEC_OK"
NETWORK_MARKER = "NETWORK_BLOCKED"
AUTH_ENV_MARKER = "AUTH_ENV_CLEAN"
MAX_BODY_BYTES = 5 * 1024 * 1024
HOST_PATTERN = re.compile(r"(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])")


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


def _tool_command(host: str, port: int) -> str:
    if HOST_PATTERN.fullmatch(host) is None:
        raise ValueError("tool network host contains unsupported characters")
    if not 1 <= port <= 65535:
        raise ValueError("tool network port must be in 1..65535")
    return f"""set -eu
printf '%s\\n' '{WORKSPACE_MARKER}' > remote-tool-proof.txt
python3 - <<'PY'
import os
import re
import sys
pattern = re.compile(r'(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE|AUTH|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)', re.I)
bad = sorted(key for key in os.environ if pattern.search(key))
if bad:
    print('AUTH_ENV_LEAK:' + ','.join(bad))
    raise SystemExit(8)
print({AUTH_ENV_MARKER!r})
PY
python3 - <<'PY'
import socket
import sys
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


def function_call_events(host: str, port: int) -> list[dict[str, Any]]:
    response_id = "resp-remote-tool"
    arguments = json.dumps(
        {"cmd": _tool_command(host, port), "yield_time_ms": 1000},
        separators=(",", ":"),
    )
    return [
        _created(response_id),
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "call_id": CALL_ID,
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


def find_matching_tool_output(body: Any) -> str | None:
    for node in _iter_nodes(body):
        if not isinstance(node, dict):
            continue
        if node.get("type") != "function_call_output" or node.get("call_id") != CALL_ID:
            continue
        output = node.get("output")
        if isinstance(output, str):
            return output
        if output is not None:
            return json.dumps(output, ensure_ascii=False, sort_keys=True)
    return None


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


class ReferenceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], *, state_path: Path, ready_path: Path,
                 tool_network_host: str):
        super().__init__(address, ReferenceHandler)
        self.state_path = state_path
        self.ready_path = ready_path
        self.tool_network_host = tool_network_host
        self.requests: list[dict[str, Any]] = []
        self.validation_error: str | None = None

    def write_state(self) -> None:
        _atomic_json(
            self.state_path,
            {
                "schema_version": 1,
                "requests": self.requests,
                "validation_error": self.validation_error,
                "final_text": FINAL_TEXT,
                "call_id": CALL_ID,
                "scope": "credential-free mock Responses control-plane reference",
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
            self._json(200, {"ok": True})
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

        output = find_matching_tool_output(body)
        record = {
            "index": len(self.server.requests) + 1,
            "body_sha256": hashlib.sha256(raw).hexdigest(),
            "has_matching_tool_output": output is not None,
            "tool_output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest() if output is not None else None,
            "tool_output_contains_workspace_marker": WORKSPACE_MARKER in output if output is not None else False,
            "tool_output_contains_network_marker": NETWORK_MARKER in output if output is not None else False,
            "tool_output_contains_auth_env_marker": AUTH_ENV_MARKER in output if output is not None else False,
        }
        self.server.requests.append(record)

        if len(self.server.requests) == 1:
            self.server.write_state()
            self._sse(function_call_events(self.server.tool_network_host, self.server.server_port))
            return

        required = (WORKSPACE_MARKER, NETWORK_MARKER, AUTH_ENV_MARKER)
        if output is None or not all(marker in output for marker in required):
            self.server.validation_error = "second model request lacks verified remote tool output markers"
            self.server.write_state()
            self._json(409, {"error": self.server.validation_error})
            return

        self.server.write_state()
        self._sse(final_events())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--tool-network-host", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()
    if args.port < 0 or args.port > 65535:
        parser.error("--port must be in 0..65535")
    if HOST_PATTERN.fullmatch(args.tool_network_host) is None:
        parser.error("--tool-network-host contains unsupported characters")

    server = ReferenceServer(
        (args.bind, args.port),
        state_path=args.state.resolve(),
        ready_path=args.ready.resolve(),
        tool_network_host=args.tool_network_host,
    )
    _atomic_json(
        server.ready_path,
        {
            "schema_version": 1,
            "bind": args.bind,
            "port": server.server_port,
            "tool_network_host": args.tool_network_host,
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
