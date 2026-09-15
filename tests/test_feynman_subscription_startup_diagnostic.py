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
from unittest.mock import patch

from tooling import feynman_subscription_startup_diagnostic as startup_module
from tooling.feynman_subscription_startup_diagnostic import (
    APP_SERVER_LOCAL_ISOLATION_OVERRIDES, StartupDiagnosticError,
    _SAFE_NOTIFICATION_METHODS, _safe_proxy_telemetry, _thread_start_params,
    _thread_summary, _wait_for_thread_start, _proxy_telemetry_ready,
    _write_failure_artifact, _consume_private_stderr, _read_json_lines,
    _instruction_sources_allowed, _wait_for_proxy_telemetry_exit,
    run as run_startup_diagnostic,
)
from tooling.feynman_rpc_path_proxy import _ProxyTelemetry
from tooling.feynman_subscription_smoke_exec import build_codex_exec_command


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

    def test_synthetic_run_records_graceful_process_reap(self):
        class FakeProcess:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO(
                    b'{"id":1,"result":{}}\n'
                    b'{"id":2,"result":{"thread":{"id":"private",'
                    b'"ephemeral":true},"instructionSources":[]}}\n'
                )
                self.stderr = io.BytesIO()
                self.returncode = None
                self.wait_calls = 0

            def wait(self, timeout=None):
                self.wait_calls += 1
                self.returncode = 0
                return 0

            def poll(self):
                return self.returncode

        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            paths = {
                "candidate_dir": str(base / "candidate"),
            }
            fake_job = {"paths": paths, "versions": {"model": "gpt-5.6-luna"}}
            telemetry = _ProxyTelemetry().snapshot()
            telemetry.update({
                "request_methods": {"initialize": 2},
                "requests_seen": 2,
                "requests_forwarded": 2,
                "responses_seen": 2,
                "responses_forwarded": 2,
                "responses_matched": 2,
            })
            telemetry["child_exit_code"] = 0
            process = FakeProcess()
            with patch(
                "tooling.feynman_subscription_startup_diagnostic._regular",
                side_effect=lambda path, label: path,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._directory",
                return_value=base / "candidate",
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._load",
                return_value=fake_job,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.validate_checkpoint",
                return_value={},
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.validate_files",
                return_value={"verdict": "remote-exec-environment-valid"},
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._validate_control_files",
                return_value=(base / "control", base / "environment.toml"),
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.prepare_full_runner_executor_wiring",
                return_value={"all_config_overrides": [], "preparation_fingerprint": "a" * 64},
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._resolve_executable",
                return_value="codex",
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._safe_exec_env",
                return_value={},
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.subprocess.Popen",
                return_value=process,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._wait_for_proxy_telemetry_exit",
                return_value=True,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._safe_proxy_telemetry",
                return_value=telemetry,
            ):
                result = run_startup_diagnostic(
                    runner_job_path=base / "runner.json",
                    boundary_profile_path=base / "profile.json",
                    remote_environment_path=base / "environment.toml",
                    binding_path=base / "binding.json",
                    codex_bin=base / "codex.cmd",
                    node_bin=base / "node.exe",
                    adapter=base / "adapter.mjs",
                    docker_bin=base / "docker.exe",
                    docker_config=base / "docker-config",
                    docker_image_id="sha256:" + "a" * 64,
                    telemetry_path=base / "telemetry.json",
                    output_path=base / "startup.json",
                    timeout_seconds=10,
                )
            self.assertEqual(process.wait_calls, 1)
            self.assertTrue(result["checks"]["process_tree_reaped"])
            self.assertTrue(result["checks"]["cleanup_verified"])
            self.assertEqual(result["verdict"], "subscription-startup-thread-ready")

    def test_expired_post_spawn_deadline_still_runs_cleanup(self):
        class FakeProcess:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()
                self.returncode = None
                self.wait_calls = 0

            def wait(self, timeout=None):
                self.wait_calls += 1
                self.returncode = 0
                return 0

            def poll(self):
                return self.returncode

        class ExpiredClock:
            def __init__(self):
                self.calls = 0

            def __call__(self):
                self.calls += 1
                # The first call creates the ten-second startup deadline and
                # the second is used by wiring preparation.  The next call
                # represents the post-spawn check after the budget expired.
                return 0.0 if self.calls <= 2 else 11.0

        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            fake_job = {
                "paths": {"candidate_dir": str(base / "candidate")},
                "versions": {"model": "gpt-5.6-luna"},
            }
            process = FakeProcess()
            clock = ExpiredClock()
            with patch(
                "tooling.feynman_subscription_startup_diagnostic._regular",
                side_effect=lambda path, label: path,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._directory",
                return_value=base / "candidate",
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._load",
                return_value=fake_job,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.validate_checkpoint",
                return_value={},
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.validate_files",
                return_value={"verdict": "remote-exec-environment-valid"},
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._validate_control_files",
                return_value=(base / "control", base / "environment.toml"),
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.prepare_full_runner_executor_wiring",
                return_value={"all_config_overrides": [], "preparation_fingerprint": "a" * 64},
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._resolve_executable",
                return_value="codex",
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._safe_exec_env",
                return_value={},
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.subprocess.Popen",
                return_value=process,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._wait_for_proxy_telemetry_exit",
                return_value=True,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.time.monotonic",
                side_effect=clock,
            ):
                with self.assertRaisesRegex(StartupDiagnosticError, "^startup-timeout$"):
                    run_startup_diagnostic(
                        runner_job_path=base / "runner.json",
                        boundary_profile_path=base / "profile.json",
                        remote_environment_path=base / "environment.toml",
                        binding_path=base / "binding.json",
                        codex_bin=base / "codex.cmd",
                        node_bin=base / "node.exe",
                        adapter=base / "adapter.mjs",
                        docker_bin=base / "docker.exe",
                        docker_config=base / "docker-config",
                        docker_image_id="sha256:" + "a" * 64,
                        telemetry_path=base / "telemetry.json",
                        output_path=base / "startup.json",
                        timeout_seconds=10,
                    )
            self.assertEqual(process.wait_calls, 1)
            self.assertEqual(process.returncode, 0)

    def test_prepared_wiring_is_consumed_without_a_second_probe(self):
        class FakeProcess:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO(
                    b'{"id":1,"result":{}}\n'
                    b'{"id":2,"result":{"thread":{"id":"private",'
                    b'"ephemeral":true},"instructionSources":[]}}\n'
                )
                self.stderr = io.BytesIO()
                self.returncode = None

            def wait(self, timeout=None):
                self.returncode = 0
                return 0

            def poll(self):
                return self.returncode

        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            fake_job = {
                "paths": {"candidate_dir": str(base / "candidate")},
                "versions": {"model": "gpt-5.6-luna"},
            }
            command = build_codex_exec_command(
                executable="codex", model="gpt-5.6-luna",
                candidate_dir=base / "candidate", config_overrides=(),
            )
            prepared = {
                "all_config_overrides": (),
                "command": command,
                "preparation_fingerprint": "a" * 64,
            }
            process = FakeProcess()
            telemetry = _ProxyTelemetry().snapshot()
            telemetry.update({
                "request_methods": {"initialize": 1, "thread/start": 1},
                "requests_seen": 2,
                "requests_forwarded": 2,
                "responses_seen": 2,
                "responses_forwarded": 2,
                "responses_matched": 2,
                "child_exit_code": 0,
            })
            with patch(
                "tooling.feynman_subscription_startup_diagnostic._regular",
                side_effect=lambda path, label: path,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._directory",
                return_value=base / "candidate",
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._load",
                return_value=fake_job,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.validate_checkpoint",
                return_value={},
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.validate_files",
                return_value={"verdict": "remote-exec-environment-valid"},
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._validate_control_files",
                return_value=(base / "control", base / "environment.toml"),
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.prepare_full_runner_executor_wiring",
            ) as prepare, patch(
                "tooling.feynman_subscription_startup_diagnostic._wiring_fingerprint",
                return_value="a" * 64,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._resolve_executable",
                return_value="codex",
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._safe_exec_env",
                return_value={},
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.subprocess.Popen",
                return_value=process,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._wait_for_proxy_telemetry_exit",
                return_value=True,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._safe_proxy_telemetry",
                return_value=telemetry,
            ):
                result = run_startup_diagnostic(
                    runner_job_path=base / "runner.json",
                    boundary_profile_path=base / "profile.json",
                    remote_environment_path=base / "environment.toml",
                    binding_path=base / "binding.json",
                    codex_bin=base / "codex.cmd",
                    node_bin=base / "node.exe",
                    adapter=base / "adapter.mjs",
                    docker_bin=base / "docker.exe",
                    docker_config=base / "docker-config",
                    docker_image_id="sha256:" + "a" * 64,
                    telemetry_path=base / "telemetry.json",
                    output_path=base / "startup.json",
                    timeout_seconds=10,
                    prepared_wiring=prepared,
                )
            prepare.assert_not_called()
            self.assertEqual(result["preparation_fingerprint"], "a" * 64)

    def test_direct_run_validation_blocks_before_app_server(self):
        process = unittest.mock.Mock()
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            with patch(
                "tooling.feynman_subscription_startup_diagnostic._regular",
                side_effect=lambda path, label: path,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic._directory",
                return_value=base,
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.from_run_inputs",
                return_value={"schema_version": 1},
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.validate_checkpoint",
                side_effect=ValueError("synthetic checkpoint rejection"),
            ), patch(
                "tooling.feynman_subscription_startup_diagnostic.subprocess.Popen",
                return_value=process,
            ) as popen:
                with self.assertRaisesRegex(
                    StartupDiagnosticError, "^startup-input-validation-failed$"
                ):
                    run_startup_diagnostic(
                        runner_job_path=base / "runner.json",
                        boundary_profile_path=base / "profile.json",
                        remote_environment_path=base / "environment.toml",
                        binding_path=base / "binding.json",
                        codex_bin=base / "codex.cmd",
                        node_bin=base / "node.exe",
                        adapter=base / "adapter.mjs",
                        docker_bin=base / "docker.exe",
                        docker_config=base / "docker-config",
                        docker_image_id="sha256:" + "a" * 64,
                        telemetry_path=base / "telemetry.json",
                        output_path=base / "startup.json",
                        timeout_seconds=10,
                    )
            popen.assert_not_called()

    def test_individual_cli_validates_checkpoint_before_run(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            args = [
                "startup-diagnostic.py",
                "--runner-job", str(base / "runner.json"),
                "--boundary-profile", str(base / "profile.json"),
                "--remote-environment", str(base / "environment.toml"),
                "--binding", str(base / "binding.json"),
                "--codex-bin", str(base / "codex.cmd"),
                "--node-bin", str(base / "node.exe"),
                "--adapter", str(base / "adapter.mjs"),
                "--docker-bin", str(base / "docker.exe"),
                "--docker-config", str(base / "docker-config"),
                "--docker-image-id", "sha256:" + "a" * 64,
                "--telemetry", str(base / "telemetry.json"),
                "--output", str(base / "startup.json"),
            ]
            fake_result = {
                "verdict": "subscription-startup-thread-ready",
                "checks": {
                    "thread_started": True, "error_code": None,
                    "error_category": None, "turn_requests_sent": 0,
                    "model_generation_requests_sent": 0,
                },
                "proxy_telemetry_status": "available",
                "proxy_telemetry": {},
            }
            with patch.object(sys, "argv", args), patch.object(
                startup_module, "validate_checkpoint", return_value={}
            ) as validate, patch.object(
                startup_module, "run", return_value=fake_result
            ) as run_mock, patch.object(startup_module, "_write_failure_artifact"):
                self.assertEqual(startup_module.main(), 0)
            validate.assert_called_once()
            run_mock.assert_called_once()

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
            **_ProxyTelemetry().snapshot(),
            "request_methods": {"initialize": 2},
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

    def test_proxy_telemetry_requires_drained_child_stderr_when_present(self):
        value = {
            **_ProxyTelemetry().snapshot(),
            "request_methods": {"initialize": 1},
            "requests_seen": 1, "requests_forwarded": 1,
            "responses_seen": 1, "responses_forwarded": 1,
            "responses_matched": 1, "responses_unmatched": 0,
            "notifications_seen": 0, "malformed_responses": 0,
            "pending_request_ids": 0, "request_write_failures": 0,
            "request_id_duplicates": 0, "request_mapping_rejections": 0,
            "response_mapping_rejections": 0, "child_exit_code": 0,
            "child_stderr_bytes": 3, "child_stderr_nonempty": True,
            "child_stderr_truncated": False, "child_stderr_read_error": False,
            "child_stderr_drained": True,
        }
        self.assertTrue(_proxy_telemetry_ready(value))
        value["child_stderr_drained"] = False
        self.assertFalse(_proxy_telemetry_ready(value))
        value["child_stderr_drained"] = True
        value["child_stderr_read_error"] = True
        self.assertFalse(_proxy_telemetry_ready(value))

    def test_empty_proxy_telemetry_is_not_ready(self):
        value = {
            **_ProxyTelemetry().snapshot(),
            "requests_seen": 0, "requests_forwarded": 0,
            "responses_seen": 0, "responses_forwarded": 0,
            "responses_matched": 0, "responses_unmatched": 0,
            "notifications_seen": 0, "malformed_responses": 0,
            "pending_request_ids": 0, "request_write_failures": 0,
            "request_id_duplicates": 0, "request_mapping_rejections": 0,
            "response_mapping_rejections": 0, "child_exit_code": 0,
        }
        self.assertFalse(_proxy_telemetry_ready(value))

    def test_proxy_telemetry_rejects_non_numeric_error_code_label(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "telemetry.json"
            value = _ProxyTelemetry().snapshot()
            value["response_error_codes"] = {"SYNTHETIC_PRIVATE_CODE": 1}
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(
                StartupDiagnosticError, "^startup-telemetry-error-code-shape$"
            ):
                _safe_proxy_telemetry(path)

    def test_proxy_telemetry_rejects_nonzero_child_exit(self):
        value = {
            **_ProxyTelemetry().snapshot(),
            "request_methods": {"initialize": 1},
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
            **_ProxyTelemetry().snapshot(),
            "request_methods": {"initialize": 1},
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
            **_ProxyTelemetry().snapshot(),
            "request_methods": {"initialize": 1},
            "requests_seen": 1, "requests_forwarded": 1,
            "responses_seen": 1, "responses_forwarded": 1,
            "responses_matched": 1, "responses_unmatched": 0,
            "notifications_seen": 0, "malformed_responses": 0,
            "pending_request_ids": 0, "request_write_failures": 0,
            "request_id_duplicates": 0, "request_mapping_rejections": 0,
            "response_mapping_rejections": 0, "child_exit_code": None,
        }
        self.assertFalse(_proxy_telemetry_ready(value))

    def test_proxy_telemetry_rejects_inconsistent_request_accounting(self):
        value = {
            **_ProxyTelemetry().snapshot(),
            "request_methods": {"initialize": 2},
            "requests_seen": 1,
            "requests_forwarded": 1,
            "responses_seen": 1,
            "responses_forwarded": 1,
            "responses_matched": 1,
            "child_exit_code": 0,
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
        self.assertNotIn("preparation_fingerprint", schema["required"])
        self.assertEqual(
            schema["allOf"][0]["then"]["required"],
            ["preparation_fingerprint"],
        )
        self.assertEqual(
            schema["properties"]["preparation_fingerprint"]["pattern"],
            "^[0-9a-f]{64}$",
        )
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
