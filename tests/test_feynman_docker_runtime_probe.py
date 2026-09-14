from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import tooling.feynman_docker_runtime_probe as runtime_probe
from tooling.feynman_docker_runtime_probe import (
    MAX_CAPTURE_BYTES, PROBE_IMAGE, _drain, _initialize_response_observed,
    _inspect_container, _new_capture, _validate_docker_host,
    _stage_passed, _base_command, run,
)


class DockerRuntimeProbeTests(unittest.TestCase):
    def test_base_command_can_pin_a_local_docker_endpoint(self):
        command = _base_command(Path("docker"), Path("config"), "run", "probe", "run-id", "npipe:////./pipe/docker_engine")
        self.assertEqual(command[0:5], ["docker", "--config", "config", "--host", "npipe:////./pipe/docker_engine"])

    def test_docker_host_rejects_nonlocal_transport(self):
        with self.assertRaisesRegex(ValueError, "local npipe"):
            _validate_docker_host("tcp://127.0.0.1:2375")

    def test_stage_accepts_exact_marker_without_echo_added_newline(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": b""})()
        with patch("tooling.feynman_docker_runtime_probe._inspect_container", return_value={
                "available": True, "presence": "present", "owned": True,
                "status": "exited", "exit_code": 0, "oom_killed": False}), \
             patch("tooling.feynman_docker_runtime_probe._remove_owned_container",
                   return_value={"status": "removed", "verified": True}):
            from tooling.feynman_docker_runtime_probe import _run_stage, MARKER
            value = _run_stage(
                [sys.executable, "-B", "-c", "import sys; sys.stdout.buffer.write(sys.argv[1].encode())",
                 MARKER.decode()],
                docker=Path("docker"), config=Path("config"), name="fixture",
                run_id="fixture", input_data=None, marker=MARKER, timeout=3)
        self.assertTrue(value["marker_observed"])
        self.assertTrue(_stage_passed("container-start", value))

    def test_initialize_stage_keeps_stdin_open_until_first_response(self):
        script = (
            "import sys,threading,time;"
            "sys.stdin.readline();"
            "done=threading.Event();"
            "threading.Thread(target=lambda:(sys.stdin.read(),done.set()),daemon=True).start();"
            "time.sleep(0.1);"
            "sys.exit(7) if done.is_set() else None;"
            "sys.stdout.write('{\\\"id\\\":1,\\\"result\\\":{}}\\n');"
            "sys.stdout.flush();"
            "done.wait(2)"
        )
        with patch("tooling.feynman_docker_runtime_probe._inspect_container", return_value={
                "available": True, "presence": "present", "owned": True,
                "status": "exited", "exit_code": 0, "oom_killed": False}), \
             patch("tooling.feynman_docker_runtime_probe._remove_owned_container",
                   return_value={"status": "removed", "verified": True}):
            from tooling.feynman_docker_runtime_probe import _run_stage
            value = _run_stage(
                [sys.executable, "-B", "-c", script],
                docker=Path("docker"), config=Path("config"), name="fixture",
                run_id="fixture", input_data=b"request\n", marker=None, timeout=3,
                wait_for_stdout_before_close=True,
            )
        self.assertTrue(value["initialize_response_observed"])
        self.assertTrue(_stage_passed("exec-server-initialize", value))

    def test_inspect_container_requires_the_probe_label(self):
        completed = type("Completed", (), {
            "returncode": 0,
            "stdout": b"exited|0|false|expected-run\n",
        })()
        with patch("tooling.feynman_docker_runtime_probe.subprocess.run", return_value=completed):
            result = _inspect_container(Path("docker"), Path("config"), "owned-name", "expected-run")
        self.assertEqual(result, {
            "available": True, "presence": "present", "owned": True, "status": "exited",
            "exit_code": 0, "oom_killed": False,
        })

    def test_inspect_container_does_not_preserve_foreign_label(self):
        completed = type("Completed", (), {
            "returncode": 0,
            "stdout": b"private-state|0|false|foreign-run\n",
        })()
        with patch("tooling.feynman_docker_runtime_probe.subprocess.run", return_value=completed):
            result = _inspect_container(Path("docker"), Path("config"), "owned-name", "expected-run")
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["owned"])
        self.assertNotIn("private-state", json.dumps(result))
        self.assertNotIn("foreign-run", json.dumps(result))

    def test_initialize_response_requires_result_for_the_expected_id(self):
        valid = b'{"id":1,"result":{"protocolVersion":"x"}}\n'
        error = b'{"id":1,"error":{"code":-32603}}\n'
        self.assertTrue(_initialize_response_observed(valid, truncated=False))
        self.assertFalse(_initialize_response_observed(error, truncated=False))
        self.assertFalse(_initialize_response_observed(valid, truncated=True))
        self.assertFalse(_initialize_response_observed(b'{"id":true,"result":{}}\n', truncated=False))
        self.assertFalse(_initialize_response_observed(
            valid + error, truncated=False))

    def test_drain_preserves_digest_but_bounds_sensitive_sample(self):
        payload = b"x" * (MAX_CAPTURE_BYTES + 17)
        capture = _new_capture()
        _drain(io.BytesIO(payload), capture)
        self.assertEqual(capture["bytes"], len(payload))
        self.assertEqual(len(capture["sample"]), MAX_CAPTURE_BYTES)
        self.assertTrue(capture["truncated"])
        self.assertTrue(capture["drained"])
        self.assertFalse(capture["read_error"])

    def test_stage_rejects_nonzero_inner_container_exit(self):
        capture = _new_capture()
        capture["bytes"] = 1
        capture["drained"] = True
        value = {
            "cli_exit_code": 0, "timed_out": False, "stdin_write_error": False,
            "cli_stop_verified": True,
            "stdout": capture, "stderr": capture,
            "marker_observed": True, "node_version_observed": False,
            "initialize_response_observed": False,
            "container": {"available": True, "owned": True, "status": "exited", "exit_code": 7, "oom_killed": False},
            "cleanup": {"status": "removed", "verified": True},
        }
        self.assertFalse(_stage_passed("entrypoint-echo", value))

    def test_stage_rejects_cleanup_uncertainty(self):
        capture = _new_capture()
        capture["drained"] = True
        value = {
            "cli_exit_code": 0, "timed_out": False, "stdin_write_error": False,
            "cli_stop_verified": True,
            "stdout": capture, "stderr": capture,
            "marker_observed": True, "node_version_observed": False,
            "container_id_observed": False,
            "initialize_response_observed": False,
            "container": {"available": True, "owned": True, "exit_code": 0, "oom_killed": False},
            "cleanup": {"status": "not-observed", "verified": False},
        }
        self.assertFalse(_stage_passed("entrypoint-echo", value))

    def test_cleanup_does_not_verify_when_post_remove_presence_is_unknown(self):
        first = type("Completed", (), {"returncode": 0, "stdout": b""})()
        second = type("Completed", (), {"returncode": 1, "stdout": b""})()
        with patch("tooling.feynman_docker_runtime_probe.subprocess.run",
                   side_effect=[first, second]):
            from tooling.feynman_docker_runtime_probe import _remove_owned_container
            result = _remove_owned_container(
                Path("docker"), Path("config"), "owned-name", "expected-run",
                {"available": True, "owned": True, "status": "exited",
                 "exit_code": 0, "oom_killed": False})
        self.assertEqual(result, {"status": "removed", "verified": False})

    def test_create_stage_requires_created_container_and_deferred_cleanup(self):
        capture = _new_capture()
        capture["bytes"] = 1
        capture["drained"] = True
        value = {
            "cli_exit_code": 0, "timed_out": False, "stdin_write_error": False,
            "cli_stop_verified": True,
            "stdout": capture, "stderr": capture,
            "marker_observed": False, "node_version_observed": False,
            "initialize_response_observed": False,
            "container": {"available": True, "owned": True, "status": "created", "exit_code": 0, "oom_killed": False},
            "cleanup": {"status": "deferred", "verified": False},
        }
        value["container_id_observed"] = True
        self.assertTrue(_stage_passed("container-create", value))

    def test_runtime_probe_rejects_existing_output_before_subprocess(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "report.json"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "new absolute"):
                run(docker=Path("docker"), config=Path(raw),
                    image="sha256:" + "0" * 64, output=output)

    def test_stage_exception_is_persisted_without_raw_error(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            docker = root / "docker.exe"
            docker.write_bytes(b"fixture")
            config = root / "config"
            config.mkdir()
            output = root / "report.json"
            with patch("tooling.feynman_docker_runtime_probe._run_stage",
                       side_effect=subprocess.TimeoutExpired("docker", 30)), \
                 patch("tooling.feynman_docker_runtime_probe._inspect_container",
                       return_value={"available": False, "presence": "unavailable"}), \
                 patch("tooling.feynman_docker_runtime_probe._remove_owned_container",
                       return_value={"status": "not-observed", "verified": False}):
                result = run(docker=docker, config=config, image=PROBE_IMAGE,
                             output=output, timeout=30)
            self.assertEqual(result["verdict"], "docker-runtime-blocked")
            self.assertEqual(result["failure_stage"], "container-create")
            self.assertEqual(result["error_code"], "docker-cli-timeout")
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(persisted, result)
            self.assertNotIn("TimeoutExpired", json.dumps(persisted))

    def test_unreaped_cli_is_recorded_as_incomplete_without_raising(self):
        class NeverReaped:
            pid = 77
            returncode = None

            def __init__(self):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()
                self.wait_calls = 0
                self.kill_called = False

            def poll(self):
                return None

            def wait(self, timeout=None):
                self.wait_calls += 1
                raise subprocess.TimeoutExpired("docker", timeout)

            def kill(self):
                self.kill_called = True

        process = NeverReaped()
        with patch("tooling.feynman_docker_runtime_probe.subprocess.Popen",
                   return_value=process), \
             patch("tooling.feynman_docker_runtime_probe._stop_cli",
                   return_value=True), \
             patch("tooling.feynman_docker_runtime_probe._inspect_container",
                   return_value={"available": False, "presence": "unavailable"}):
            from tooling.feynman_docker_runtime_probe import _run_stage
            value = _run_stage(
                ["docker", "run"], docker=Path("docker"), config=Path("config"),
                name="fixture", run_id="fixture", input_data=None, marker=None,
                timeout=1,
            )
        self.assertTrue(value["timed_out"])
        self.assertFalse(value["cli_stop_verified"])
        self.assertTrue(process.kill_called)
        self.assertGreaterEqual(process.wait_calls, 3)

    def test_main_fallback_uses_fixed_error_code_without_raw_error(self):
        argv = [
            "feynman_docker_runtime_probe", "--docker", "docker.exe",
            "--docker-config", "config", "--image", PROBE_IMAGE,
            "--output", "report.json",
        ]
        with patch.object(runtime_probe, "run",
                          side_effect=OSError("PRIVATE_DOCKER_ERROR")), \
             patch.object(sys, "argv", argv):
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = runtime_probe.main()
        payload = json.loads(captured.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["failure_stage"], "probe-error")
        self.assertEqual(payload["error_code"], "docker-os-error")
        self.assertFalse(payload["report_written"])
        self.assertNotIn("PRIVATE_DOCKER_ERROR", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
