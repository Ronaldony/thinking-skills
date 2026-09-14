from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tooling.feynman_docker_runtime_probe import (
    MAX_CAPTURE_BYTES, _drain, _initialize_response_observed,
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


if __name__ == "__main__":
    unittest.main()
