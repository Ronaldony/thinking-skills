from __future__ import annotations

import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from tooling.feynman_subscription_startup_diagnostic import (
    APP_SERVER_LOCAL_ISOLATION_OVERRIDES, StartupDiagnosticError,
    _SAFE_NOTIFICATION_METHODS, _safe_proxy_telemetry, _thread_start_params,
    _thread_summary, _wait_for_thread_start, _proxy_telemetry_ready,
    _write_failure_artifact, _consume_private_stderr, _read_json_lines,
    _instruction_sources_allowed, _wait_for_proxy_telemetry_exit,
)
from tooling.feynman_rpc_path_proxy import _ProxyTelemetry


ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_FIXTURE = ROOT / "tests" / "feynman_subscription_lifecycle_fixture.py"


class SubscriptionStartupDiagnosticTests(unittest.TestCase):
    def test_startup_error_retains_observed_initialize_state(self):
        before = StartupDiagnosticError("thread-start-timeout")
        after = StartupDiagnosticError("thread-start-timeout", initialize_completed=True)
        self.assertFalse(before.initialize_completed)
        self.assertTrue(after.initialize_completed)

    def _lifecycle_process(self, mode: str):
        process = subprocess.Popen(
            [sys.executable, "-B", str(LIFECYCLE_FIXTURE), mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={
                key: os.environ[key]
                for key in ("PATH", "SystemRoot", "WINDIR", "ComSpec", "PATHEXT", "TEMP", "TMP")
                if key in os.environ
            },
            bufsize=0,
        )
        assert process.stdin is not None and process.stdout is not None
        received: queue.Queue[dict | None] = queue.Queue()
        reader = threading.Thread(
            target=_read_json_lines, args=(process.stdout, received), daemon=True
        )
        reader.start()
        return process, received, reader

    def _close_lifecycle_process(self, process, reader):
        assert process.stdin is not None
        process.stdin.close()
        process.wait(timeout=5)
        reader.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        self.assertEqual(process.returncode, 0)

    def test_offline_fixture_healthy_lifecycle_sends_no_turn(self):
        process, received, reader = self._lifecycle_process("healthy")
        try:
            assert process.stdin is not None
            process.stdin.write(_request_for_test(1, "initialize"))
            process.stdin.flush()
            initialize, _ = _wait_for_thread_start(received, 1, 5)
            self.assertIn("result", initialize)
            process.stdin.write(_notification_for_test("initialized"))
            process.stdin.write(_request_for_test(2, "thread/start"))
            process.stdin.flush()
            response, notifications = _wait_for_thread_start(received, 2, 5)
            summary = _thread_summary(response)
            self.assertTrue(summary["thread_started"])
            self.assertEqual(notifications, {})
            self.assertEqual(process.poll(), None)
        finally:
            self._close_lifecycle_process(process, reader)

    def test_offline_fixture_initialize_timeout_is_client_timeout(self):
        process, received, reader = self._lifecycle_process("initialize-timeout")
        try:
            assert process.stdin is not None
            process.stdin.write(_request_for_test(1, "initialize"))
            process.stdin.flush()
            with self.assertRaisesRegex(StartupDiagnosticError, "^thread-start-timeout$"):
                _wait_for_thread_start(received, 1, 0)
        finally:
            self._close_lifecycle_process(process, reader)

    def test_initialize_timeout_has_a_distinct_failure_stage(self):
        received = queue.Queue()
        with self.assertRaisesRegex(StartupDiagnosticError, "^initialize-timeout$"):
            _wait_for_thread_start(received, 1, 0, timeout_stage="initialize-timeout")

    def test_failure_artifact_can_preserve_completed_initialize_stage(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "startup.json"
            _write_failure_artifact(path, "thread-start-timeout", initialize_completed=True)
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(value["checks"]["initialize_completed"])

    def test_offline_fixture_thread_start_error_is_not_initialize_timeout(self):
        process, received, reader = self._lifecycle_process("thread-start-error")
        try:
            assert process.stdin is not None
            process.stdin.write(_request_for_test(1, "initialize"))
            process.stdin.flush()
            initialize, _ = _wait_for_thread_start(received, 1, 5)
            self.assertNotIn("error", initialize)
            process.stdin.write(_notification_for_test("initialized"))
            process.stdin.write(_request_for_test(2, "thread/start"))
            process.stdin.flush()
            response, _ = _wait_for_thread_start(received, 2, 5)
            summary = _thread_summary(response)
            self.assertEqual(summary["error_code"], -32603)
            self.assertEqual(summary["error_category"], "remote-environment-error")
        finally:
            self._close_lifecycle_process(process, reader)

    def test_offline_fixture_ignores_unmatched_response_id(self):
        process, received, reader = self._lifecycle_process("wrong-response-id")
        try:
            assert process.stdin is not None
            process.stdin.write(_request_for_test(1, "initialize"))
            process.stdin.flush()
            _wait_for_thread_start(received, 1, 5)
            process.stdin.write(_notification_for_test("initialized"))
            process.stdin.write(_request_for_test(2, "thread/start"))
            process.stdin.flush()
            response, _ = _wait_for_thread_start(received, 2, 5)
            self.assertEqual(response["id"], 2)
            self.assertEqual(_thread_summary(response)["thread_started"], True)
        finally:
            self._close_lifecycle_process(process, reader)

    def test_probe_isolates_local_project_discovery(self):
        self.assertEqual(
            APP_SERVER_LOCAL_ISOLATION_OVERRIDES,
            ("project_root_markers=[]", "project_doc_max_bytes=0"),
        )

    def test_thread_start_is_ephemeral_and_has_no_turn_or_prompt(self):
        params = _thread_start_params(model="gpt-5.6-luna")
        self.assertEqual(
            set(params), {"model", "approvalPolicy", "sandbox", "ephemeral"}
        )
        self.assertTrue(params["ephemeral"])
        self.assertEqual(params["approvalPolicy"], "never")
        self.assertEqual(params["sandbox"], "workspace-write")
        self.assertNotIn("cwd", params)
        self.assertNotIn("environments", params)
        self.assertNotIn("runtimeWorkspaceRoots", params)
        serialized = json.dumps(params)
        self.assertNotIn("prompt", serialized)
        self.assertNotIn("input", serialized)

    def test_thread_summary_preserves_no_id_or_instruction_path(self):
        summary = _thread_summary({"result": {
            "thread": {"id": "SYNTHETIC_PRIVATE_THREAD", "ephemeral": True},
            "instructionSources": ["/run/candidate/AGENTS.md"],
        }})
        self.assertEqual(summary, {
            "thread_started": True,
            "error_code": None,
            "error_category": None,
            "error_signals": {
                "mentions_environment": False,
                "mentions_exec_server": False,
                "mentions_connection": False,
                "mentions_initialize": False,
                "mentions_exit": False,
                "mentions_closed": False,
                "mentions_timeout": False,
                "mentions_config": False,
                "mentions_path": False,
                "mentions_not_found": False,
            },
            "error_data_kind": "none",
            "ephemeral_thread": True,
            "instruction_sources_present": True,
            "instruction_sources_allowed": True,
            "response_payload_preserved": False,
        })
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(summary))

    def test_instruction_sources_are_limited_to_declared_remote_mounts(self):
        self.assertTrue(_instruction_sources_allowed([
            "/run/candidate/AGENTS.md", "file:///run/codex/skills/feynman-thinking/SKILL.md",
        ]))
        for source in (
                "C:/private/AGENTS.md", "/run/home/AGENTS.md",
                "/run/candidate/../home/AGENTS.md", "relative/AGENTS.md"):
            with self.subTest(source=source):
                self.assertFalse(_instruction_sources_allowed([source]))

    def test_thread_summary_rejects_instruction_source_outside_remote_mounts(self):
        with self.assertRaisesRegex(StartupDiagnosticError, "^instruction-source-not-allowed$"):
            _thread_summary({"result": {
                "thread": {"id": "synthetic", "ephemeral": True},
                "instructionSources": ["/run/home/AGENTS.md"],
            }})

    def test_error_summary_preserves_only_numeric_code(self):
        summary = _thread_summary({"error": {
            "code": -32001,
            "message": "Remote environment exec-server connection initialization failed at SYNTHETIC_PRIVATE_PATH",
            "data": {"private": "SYNTHETIC_PRIVATE_DATA"},
        }})
        self.assertEqual(summary["error_code"], -32001)
        self.assertEqual(summary["error_category"], "remote-path-error")
        self.assertTrue(summary["error_signals"]["mentions_environment"])
        self.assertTrue(summary["error_signals"]["mentions_exec_server"])
        self.assertTrue(summary["error_signals"]["mentions_connection"])
        self.assertTrue(summary["error_signals"]["mentions_initialize"])
        self.assertTrue(summary["error_signals"]["mentions_path"])
        self.assertEqual(summary["error_data_kind"], "object")
        self.assertFalse(summary["thread_started"])
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(summary))

    def test_unknown_notification_method_is_not_preserved(self):
        received = queue.Queue()
        received.put({"method": "SYNTHETIC_PRIVATE_NOTIFICATION", "params": {}})
        received.put({"id": 2, "error": {"code": -32603, "message": "environment failed"}})
        response, notifications = _wait_for_thread_start(received, 2, 10)
        self.assertEqual(response["id"], 2)
        self.assertEqual(notifications, {"unknown": 1})
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(notifications))

    def test_environment_connection_notification_uses_current_schema_name(self):
        received = queue.Queue()
        received.put({"method": "thread/environment/connected", "params": {}})
        received.put({"id": 2, "error": {"code": -32603, "message": "environment failed"}})
        response, notifications = _wait_for_thread_start(received, 2, 10)
        self.assertEqual(response["id"], 2)
        self.assertEqual(notifications, {"thread/environment/connected": 1})
        self.assertIn("thread/environment/connected", _SAFE_NOTIFICATION_METHODS)

    def test_missing_proxy_telemetry_is_fixed_and_payload_free(self):
        with tempfile.TemporaryDirectory() as root:
            missing = Path(root) / "synthetic-private-telemetry.json"
            with self.assertRaisesRegex(
                StartupDiagnosticError, "^startup-proxy-telemetry-missing$"
            ):
                _safe_proxy_telemetry(missing)
            self.assertNotIn(str(missing), "startup-proxy-telemetry-missing")

    def test_durable_thread_is_rejected(self):
        with self.assertRaisesRegex(StartupDiagnosticError, "not-ephemeral"):
                _thread_summary({"result": {"thread": {"id": "x", "ephemeral": False}}})

    def test_thread_summary_requires_instruction_sources_array(self):
        with self.assertRaisesRegex(StartupDiagnosticError, "response-shape"):
            _thread_summary({"result": {"thread": {"id": "x", "ephemeral": True}}})

    def test_proxy_telemetry_requires_complete_correlation(self):
        value = {
            "requests_seen": 2, "requests_forwarded": 2,
            "responses_seen": 1, "responses_forwarded": 1,
            "responses_matched": 1, "responses_unmatched": 0,
            "notifications_seen": 0, "malformed_responses": 0,
            "pending_request_ids": 0, "request_write_failures": 0,
            "request_id_duplicates": 0, "request_mapping_rejections": 0,
            "response_mapping_rejections": 0, "child_exit_code": 0,
        }
        self.assertTrue(_proxy_telemetry_ready(value))
        value["responses_unmatched"] = 1
        self.assertFalse(_proxy_telemetry_ready(value))

    def test_proxy_telemetry_rejects_nonzero_child_exit(self):
        value = {
            "requests_seen": 1, "requests_forwarded": 1,
            "responses_seen": 1, "responses_forwarded": 1,
            "responses_matched": 1, "responses_unmatched": 0,
            "notifications_seen": 0, "malformed_responses": 0,
            "pending_request_ids": 0, "request_write_failures": 0,
            "request_id_duplicates": 0, "request_mapping_rejections": 0,
            "response_mapping_rejections": 0, "child_exit_code": 7,
        }
        self.assertFalse(_proxy_telemetry_ready(value))

    def test_proxy_telemetry_excludes_notifications_from_response_matching(self):
        value = {
            "requests_seen": 1, "requests_forwarded": 1,
            "responses_seen": 2, "responses_forwarded": 2,
            "responses_matched": 1, "responses_unmatched": 0,
            "notifications_seen": 1, "malformed_responses": 0,
            "pending_request_ids": 0, "request_write_failures": 0,
            "request_id_duplicates": 0, "request_mapping_rejections": 0,
            "response_mapping_rejections": 0, "child_exit_code": 0,
        }
        self.assertTrue(_proxy_telemetry_ready(value))

    def test_proxy_telemetry_without_child_exit_is_incomplete(self):
        value = {
            "requests_seen": 1, "requests_forwarded": 1,
            "responses_seen": 1, "responses_forwarded": 1,
            "responses_matched": 1, "responses_unmatched": 0,
            "notifications_seen": 0, "malformed_responses": 0,
            "pending_request_ids": 0, "request_write_failures": 0,
            "request_id_duplicates": 0, "request_mapping_rejections": 0,
            "response_mapping_rejections": 0, "child_exit_code": None,
        }
        self.assertFalse(_proxy_telemetry_ready(value))

    def test_cleanup_wait_accepts_final_proxy_child_exit_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "telemetry.json"
            value = _ProxyTelemetry().snapshot()
            value["child_exit_code"] = 0
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assertTrue(_wait_for_proxy_telemetry_exit(
                path, deadline=time.monotonic() + 1))

    def test_cleanup_wait_times_out_on_partial_proxy_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "telemetry.json"
            path.write_text(json.dumps(_ProxyTelemetry().snapshot()), encoding="utf-8")
            self.assertFalse(_wait_for_proxy_telemetry_exit(
                path, deadline=time.monotonic() + 0.01))

    def test_stderr_sample_is_bounded_but_stream_is_drained_to_eof(self):
        stream = io.BytesIO(b"x" * 300000)
        sample = []
        _consume_private_stderr(stream, sample)
        self.assertEqual(sum(map(len, sample)), 262144)
        self.assertEqual(stream.read(), b"")

    def test_nested_telemetry_allowlist_rejects_arbitrary_labels(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "telemetry.json"
            value = _ProxyTelemetry().snapshot()
            value["request_mapping_rejection_method_reasons"] = {
                "SYNTHETIC_PRIVATE_METHOD": {"unclassified": 1},
            }
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(
                StartupDiagnosticError, "^startup-telemetry-counter-shape$"
            ):
                _safe_proxy_telemetry(path)

    def test_failure_artifact_is_blocked_and_payload_free(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "startup.json"
            _write_failure_artifact(path, "thread-start-timeout")
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value["verdict"], "subscription-startup-thread-blocked")
            self.assertEqual(value["failure_stage"], "thread-start-timeout")
            self.assertFalse(value["checks"]["initialize_completed"])
            self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(value))

    def test_failure_artifact_sanitizes_unexpected_stage(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "startup.json"
            _write_failure_artifact(path, "C:\\private\\token")
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value["failure_stage"], "diagnostic-failure")

    def test_artifact_schema_is_valid_json(self):
        schema = json.loads(Path(
            "evals/feynman-thinking/subscription-startup-diagnostic.schema.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], 3)
        self.assertIn("instruction_sources_allowed",
                      schema["properties"]["checks"]["properties"])
        self.assertEqual(schema["properties"]["checks"]["properties"]
                         ["model_generation_requests_sent"]["const"], 0)
        self.assertIn("request_mapping_rejection_method_reasons",
                      schema["properties"]["proxy_telemetry"]["properties"])
        self.assertIn("request_mapping_rejection_method_reason_fields",
                      schema["properties"]["proxy_telemetry"]["properties"])
        self.assertIn("proxy_telemetry_complete", schema["properties"]["checks"]["properties"])
        self.assertIn("cleanup_verified", schema["properties"]["checks"]["properties"])
        self.assertIn("error_signals", schema["properties"]["checks"]["properties"])
        self.assertIn("error_data_kind", schema["properties"]["checks"]["properties"])
        self.assertEqual(
            schema["properties"]["proxy_telemetry_status"]["enum"],
            ["available", "missing"],
        )
        self.assertEqual(
            schema["properties"]["proxy_telemetry"]["type"],
            ["object", "null"],
        )

def _request_for_test(identifier: int, method: str) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method, "params": {}})
            + "\n").encode("utf-8")


def _notification_for_test(method: str) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "method": method, "params": {}})
            + "\n").encode("utf-8")


if __name__ == "__main__":
    unittest.main()
