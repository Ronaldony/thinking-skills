from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tooling.feynman_docker_runtime_probe import (
    _initialize_response_observed, _inspect_container, _new_capture,
    _stage_passed, run,
)


class DockerRuntimeProbeTests(unittest.TestCase):
    def test_inspect_container_requires_the_probe_label(self):
        completed = type("Completed", (), {
            "returncode": 0,
            "stdout": b"exited|0|false|expected-run\n",
        })()
        with patch("tooling.feynman_docker_runtime_probe.subprocess.run", return_value=completed):
            result = _inspect_container(Path("docker"), Path("config"), "owned-name", "expected-run")
        self.assertEqual(result, {
            "available": True, "owned": True, "status": "exited",
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

    def test_stage_rejects_cleanup_uncertainty(self):
        capture = _new_capture()
        capture["drained"] = True
        value = {
            "cli_exit_code": 0, "timed_out": False, "stdin_write_error": False,
            "cli_stop_verified": True,
            "stdout": capture, "stderr": capture,
            "marker_observed": True, "node_version_observed": False,
            "initialize_response_observed": False,
            "container": {"available": True, "owned": True, "exit_code": 0, "oom_killed": False},
            "cleanup": {"status": "not-observed", "verified": False},
        }
        self.assertFalse(_stage_passed("entrypoint-echo", value))

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
