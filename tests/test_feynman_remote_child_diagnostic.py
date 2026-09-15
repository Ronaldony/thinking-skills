from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import jsonschema

from tooling import feynman_remote_child_diagnostic as diagnostic


class RemoteChildDiagnosticTests(unittest.TestCase):
    def test_initialize_contract_is_valid_jsonrpc_and_client_name_only(self):
        message = json.loads(diagnostic.INITIALIZE_REQUEST)
        self.assertEqual(message, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"clientName": "feynman-remote-child-diagnostic"},
        })
        self.assertNotIn("clientInfo", message["params"])

    def test_response_observation_rejects_error_duplicate_and_payload_storage(self):
        observation = diagnostic._initialize_observation()
        event = __import__("threading").Event()
        diagnostic._observe_initialize_line(
            b'{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"secret"}}\n',
            observation, event,
        )
        diagnostic._observe_initialize_line(
            b'{"jsonrpc":"2.0","id":1,"result":{}}\n', observation, event,
        )
        serialized = json.dumps(observation)
        self.assertEqual(observation["initialize_error_codes"], {"-32602": 1})
        self.assertEqual(observation["initialize_successes"], 1)
        self.assertNotIn("secret", serialized)
        self.assertTrue(event.is_set())

    def test_drain_bounds_sample_and_still_drains(self):
        capture = diagnostic._new_capture()
        diagnostic._drain(io.BytesIO(b"x" * (diagnostic.MAX_CAPTURE_BYTES + 13)), capture)
        self.assertEqual(capture["bytes"], diagnostic.MAX_CAPTURE_BYTES + 13)
        self.assertEqual(len(capture["sample"]), diagnostic.MAX_CAPTURE_BYTES)
        self.assertTrue(capture["truncated"])
        self.assertTrue(capture["drained"])

    def test_process_drains_stderr_flood_while_waiting_for_json_response(self):
        script = (
            "import sys;"
            "sys.stderr.write('x' * 300000); sys.stderr.flush();"
            "sys.stdout.write('{\\\"jsonrpc\\\":\\\"2.0\\\",\\\"id\\\":1,\\\"result\\\":{}}\\n');"
            "sys.stdout.flush(); sys.stdin.read()"
        )
        observation = diagnostic._initialize_observation()
        response_event = threading.Event()
        with tempfile.TemporaryDirectory() as raw:
            env = diagnostic._safe_environment(Path(raw))
            process, _ = diagnostic._run_process(
                [sys.executable, "-B", "-c", script], env=env, timeout=3,
                input_data=diagnostic.INITIALIZE_REQUEST,
                on_stdout_line=lambda line: diagnostic._observe_initialize_line(
                    line, observation, response_event),
                response_event=response_event, wait_for_response=True,
            )
        self.assertEqual(process["exit_code"], 0)
        self.assertGreaterEqual(process["stderr_bytes"], 300000)
        self.assertTrue(process["stderr_drained"])
        self.assertEqual(observation["initialize_successes"], 1)

    def test_rpc_pass_requires_successful_response_and_cleanup(self):
        process = {
            "process_started": True, "exit_code": 0, "timed_out": False,
            "stdin_write_failed": False, "stdout_drained": True, "stderr_drained": True,
            "stdout_read_error": False, "stderr_read_error": False,
        }
        response = diagnostic._initialize_observation()
        response["expected_id_responses"] = 1
        response["initialize_successes"] = 1
        cleanup = {"verified": True}
        self.assertTrue(diagnostic._rpc_passed(process, response, cleanup))
        response["initialize_successes"] = 0
        response["initialize_error_codes"] = {"-32602": 1}
        self.assertFalse(diagnostic._rpc_passed(process, response, cleanup))

    def test_rpc_variant_result_marks_success_path_as_not_skipped(self):
        process = {
            "process_started": True, "exit_code": 0, "timed_out": False,
            "stdin_write_failed": False, "stdout_bytes": 1, "stderr_bytes": 0,
            "stdout_drained": True, "stderr_drained": True,
            "stdout_read_error": False, "stderr_read_error": False,
            "stdout_truncated": False, "stderr_truncated": False,
            "stderr_nonempty": False, "launch_error": None,
        }
        response = diagnostic._initialize_observation()
        response["expected_id_responses"] = 1
        response["initialize_successes"] = 1
        cleanup = {"status": "absent", "verified": True}
        with patch.object(diagnostic, "_run_process", return_value=(process, b"")), \
                patch.object(diagnostic, "_cleanup_container", return_value=cleanup):
            result = diagnostic._run_rpc_variant(
                label="direct", docker=Path("docker"), config=Path("config"),
                proxy=None, docker_args=["run"], name="name", telemetry_path=None,
                timeout=1,
            )
        self.assertFalse(result["skipped"])

    def test_telemetry_summary_is_fail_closed_and_payload_free(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "telemetry.json"
            path.write_text(json.dumps({"secret": "DO_NOT_RETAIN"}), encoding="utf-8")
            value = diagnostic._telemetry_summary(path)
            self.assertFalse(value["available"])
            self.assertNotIn("DO_NOT_RETAIN", json.dumps(value))

    def test_valid_v3_telemetry_is_revalidated_before_summary(self):
        from tooling.feynman_rpc_path_proxy import _ProxyTelemetry

        telemetry = _ProxyTelemetry()
        telemetry.request_seen("initialize")
        telemetry.request_forwarded()
        telemetry.response_seen(matched=True)
        telemetry.response_forwarded()
        telemetry.pending_request_ids(0)
        telemetry.child_exit(0)
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "telemetry.json"
            path.write_text(json.dumps(telemetry.snapshot()), encoding="utf-8")
            value = diagnostic._telemetry_summary(path)
        self.assertTrue(value["available"])
        self.assertTrue(value["schema_valid"])
        self.assertTrue(value["complete"])
        self.assertTrue(value["mapping_clean"])
        self.assertTrue(value["correlated"])

    def test_container_presence_distinguishes_empty_occupied_and_unavailable(self):
        empty = type("Completed", (), {"returncode": 0, "stdout": b""})()
        occupied = type("Completed", (), {"returncode": 0, "stdout": b"owned-name\n"})()
        failed = type("Completed", (), {"returncode": 1, "stdout": b""})()
        with patch("tooling.feynman_remote_child_diagnostic.subprocess.run", return_value=empty):
            self.assertEqual(
                diagnostic._container_presence(Path("docker"), Path("config"), "n"),
                {"status": "available", "absent": True},
            )
        with patch("tooling.feynman_remote_child_diagnostic.subprocess.run", return_value=occupied):
            self.assertEqual(
                diagnostic._container_presence(Path("docker"), Path("config"), "n"),
                {"status": "occupied", "absent": False},
            )
        with patch("tooling.feynman_remote_child_diagnostic.subprocess.run", return_value=failed):
            self.assertEqual(
                diagnostic._container_presence(Path("docker"), Path("config"), "n"),
                {"status": "unavailable", "absent": False},
            )

    def test_canonical_args_use_the_four_posix_mount_destinations(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = {
                key: str(root / name)
                for key, name in (
                    ("candidate_dir", "candidate"), ("ephemeral_home", "home"),
                    ("codex_home", "codex"), ("temp_dir", "temp"),
                )
            }
            for path in paths.values():
                Path(path).mkdir()
            args = diagnostic._canonical_docker_args(paths, diagnostic.PROBE_IMAGE, "fixture")
            joined = " ".join(args)
            for key, destination in zip(diagnostic.MOUNT_KEYS, diagnostic.MOUNT_DESTINATIONS):
                self.assertIn(f"{paths[key]}:{destination}:rw", joined)
            self.assertIn("codex exec-server --listen stdio", joined)

    def test_cleanup_name_is_the_name_emitted_by_the_canonical_generator(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = {
                key: str(root / name)
                for key, name in (
                    ("candidate_dir", "candidate"), ("ephemeral_home", "home"),
                    ("codex_home", "codex"), ("temp_dir", "temp"),
                )
            }
            for path in paths.values():
                Path(path).mkdir()
            args = diagnostic._canonical_docker_args(paths, diagnostic.PROBE_IMAGE, "remote-child-test")
            name = diagnostic._name_from_args(args)
            self.assertEqual(name, "feynman-tool-remote-child-test")

    def test_schema_validates_blocked_report_shape_from_mocked_stages(self):
        schema = json.loads(Path(
            "evals/feynman-thinking/remote-child-differential.schema.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertIn("proxy-child-stderr-discarded-by-current-proxy", json.dumps(schema))

    def test_input_validation_rejects_nonempty_docker_config_before_process(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            docker = root / "docker.exe"
            docker.write_bytes(b"fixture")
            config = root / "config"
            config.mkdir()
            (config / "config.json").write_text("{}", encoding="utf-8")
            proxy = root / "proxy.py"
            proxy.write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "empty disposable"):
                diagnostic._validate_inputs(
                    docker=docker, docker_config=config, proxy=proxy,
                    fixture_root=root / "new-fixture", output=root / "report.json",
                    image=diagnostic.PROBE_IMAGE, timeout=3,
                )

    def test_run_does_not_start_direct_or_proxy_when_lifecycle_is_blocked(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            docker = root / "docker.exe"
            docker.write_bytes(b"fixture")
            config = root / "config"
            config.mkdir()
            proxy = root / "proxy.py"
            proxy.write_bytes(b"fixture")
            output = root / "report.json"
            calls: list[list[str]] = []

            def fake_run(command, **kwargs):
                calls.append(command)
                process = {
                    "process_started": True, "exit_code": 1, "timed_out": False,
                    "stdin_write_failed": False, "stdout_bytes": 0, "stderr_bytes": 0,
                    "stdout_drained": True, "stderr_drained": True,
                    "stdout_read_error": False, "stderr_read_error": False,
                    "stdout_truncated": False, "stderr_truncated": False,
                    "stderr_nonempty": False, "launch_error": None,
                }
                return process, b""

            with patch.object(diagnostic, "_run_process", side_effect=fake_run), \
                    patch.object(diagnostic, "_container_absent", return_value=True), \
                    patch.object(diagnostic, "_inspect_named_container", return_value={
                        "available": False, "owned": False, "status": "unavailable", "exit_code": None,
                    }):
                result = diagnostic.run(
                    docker=docker, docker_config=config, proxy=proxy,
                    fixture_root=root / "fixture", output=output, timeout=3,
                )
            self.assertEqual(result["failure_stage"], "docker-access")
            self.assertFalse(result["stages"]["direct-exec-server-initialize"]["passed"])
            self.assertFalse(result["stages"]["proxy-exec-server-initialize"]["passed"])
            self.assertEqual(len(calls), 1)
            schema = json.loads(Path(
                "evals/feynman-thinking/remote-child-differential.schema.json"
            ).read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(result)


if __name__ == "__main__":
    unittest.main()
