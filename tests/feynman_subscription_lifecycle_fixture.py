"""Offline JSON-RPC peer for the subscription startup lifecycle tests.

This is deliberately not a Codex or Docker replacement.  It only exercises
the diagnostic client's framing, response-ID matching, and bounded failure
classification without reading a CODEX_HOME, using credentials, or starting
an App Server/model process.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def _emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _initialize(identifier: Any, *, duplicate: bool = False) -> None:
    response = {
        "jsonrpc": "2.0",
        "id": identifier,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"experimentalApi": {}},
            "serverInfo": {"name": "offline-lifecycle-fixture", "version": "1.0"},
        },
    }
    _emit(response)
    if duplicate:
        _emit(response)


def _thread_start(identifier: Any, mode: str) -> None:
    if mode == "thread-start-error":
        _emit({
            "jsonrpc": "2.0",
            "id": identifier,
            "error": {
                "code": -32603,
                "message": "synthetic remote environment initialization failure",
            },
        })
        return
    if mode == "wrong-response-id":
        _emit({
            "jsonrpc": "2.0",
            "id": 99,
            "result": {"thread": {"id": "ignored", "ephemeral": True}},
        })
    _emit({
        "jsonrpc": "2.0",
        "id": identifier,
        "result": {
            "approvalPolicy": "never",
            "approvalsReviewer": "user",
            "cwd": "/run/candidate",
            "model": "synthetic-model",
            "modelProvider": "synthetic-provider",
            "sandbox": {"type": "workspaceWrite"},
            "thread": {
                "cliVersion": "synthetic-cli",
                "createdAt": "2026-01-01T00:00:00Z",
                "cwd": "/run/candidate",
                "ephemeral": True,
                "id": "synthetic-ephemeral-thread",
                "modelProvider": "synthetic-provider",
                "preview": False,
                "projectId": None,
                "sessionId": "synthetic-session",
                "source": "cli",
                "status": "idle",
                "turns": [],
                "updatedAt": "2026-01-01T00:00:00Z",
            },
            "instructionSources": ["/run/candidate/AGENTS.md"],
        },
    })


def main() -> int:
    modes = {"healthy", "initialize-timeout", "thread-start-error", "wrong-response-id", "proxy-child", "proxy-child-exit", "stderr-flood", "duplicate-response"}
    mode = sys.argv[1] if len(sys.argv) >= 2 else ""
    if mode not in modes:
        return 2
    for raw in sys.stdin.buffer:
        try:
            message = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return 3
        if not isinstance(message, dict):
            return 3
        method = message.get("method")
        identifier = message.get("id")
        if method == "initialize":
            if mode == "proxy-child-exit":
                return 7
            if mode == "initialize-timeout":
                continue
            if mode == "stderr-flood":
                sys.stderr.write("x" * 1048576)
                sys.stderr.flush()
            _initialize(identifier, duplicate=mode == "duplicate-response")
        elif method == "initialized":
            continue
        elif method == "thread/start":
            _thread_start(identifier, mode)
        elif method == "turn/start":
            # The startup diagnostic must never send this request.
            _emit({
                "jsonrpc": "2.0",
                "id": identifier,
                "error": {"code": -32099, "message": "turn not allowed in lifecycle fixture"},
            })
        else:
            _emit({
                "jsonrpc": "2.0",
                "id": identifier,
                "error": {"code": -32601, "message": "fixture method not found"},
            })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
