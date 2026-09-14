import unittest
import tempfile
import io
from pathlib import Path
from unittest.mock import patch

from tooling import feynman_subscription_control_plane_preflight as control_module
from tooling.feynman_subscription_control_plane_preflight import (
    ControlPlaneError,
    _environment_summary,
    _failure_category,
    _stop_diagnostic_process,
)
from tooling.feynman_rpc_path_proxy import _effective_telemetry_path, TELEMETRY_OVERRIDE_ENV


class ControlPlanePreflightTests(unittest.TestCase):
    def test_environment_summary_preserves_only_presence_metadata(self):
        summary = _environment_summary({
            "id": 2,
            "result": {"shell": {"name": "sh", "path": "/bin/sh"},
                       "cwd": "file:///run/candidate"},
        })
        self.assertEqual(summary, {
            "remote_environment_connected": True,
            "shell_metadata_present": True,
            "default_cwd_present": True,
            "response_payload_preserved": False,
        })

    def test_environment_summary_rejects_error_or_missing_shell(self):
        with self.assertRaises(ControlPlaneError):
            _environment_summary({"id": 2, "error": {"code": -1}})
        with self.assertRaises(ControlPlaneError):
            _environment_summary({"id": 2, "result": {"cwd": None}})

    def test_failure_category_is_fixed_and_does_not_return_stderr(self):
        self.assertEqual(_failure_category("failed to load environments.toml"),
                         "remote-environment-error")
        self.assertEqual(_failure_category("unrelated detail"), "unclassified")

    def test_telemetry_override_replaces_configured_destination_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fresh = root / "fresh.json"
            configured = root / "configured.json"
            configured.write_text("existing synthetic telemetry", encoding="utf-8")
            with patch.dict("os.environ", {TELEMETRY_OVERRIDE_ENV: str(fresh)}, clear=False):
                self.assertEqual(_effective_telemetry_path(configured), fresh)
                fresh.touch()
                with self.assertRaisesRegex(ValueError, "invalid telemetry override path"):
                    _effective_telemetry_path(configured)
            self.assertEqual(configured.read_text(encoding="utf-8"),
                             "existing synthetic telemetry")

    def test_already_exited_parent_is_not_tree_reap_evidence(self):
        class AlreadyExited:
            pid = 1234

            def poll(self):
                return 0

        self.assertFalse(_stop_diagnostic_process(AlreadyExited()))

    def test_control_deadline_includes_spawn_cost(self):
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

        class Clock:
            def __init__(self):
                self.now = 0.0

            def __call__(self):
                return self.now

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            process = FakeProcess()
            clock = Clock()
            observed_timeouts = []

            def spawn(*args, **kwargs):
                # Simulate a slow Popen/reader startup without starting an
                # external process.  The pre-spawn deadline must remain the
                # same budget and therefore be exhausted here.
                clock.now = 61.0
                return process

            def wait_response(received, identifier, timeout_seconds):
                observed_timeouts.append(timeout_seconds)
                raise ControlPlaneError("control-plane-timeout")

            with patch.object(control_module.subprocess, "Popen", side_effect=spawn), \
                    patch.object(control_module, "_wait_response", side_effect=wait_response), \
                    patch.object(control_module.time, "monotonic", side_effect=clock):
                with self.assertRaisesRegex(ControlPlaneError, "^control-plane-timeout$"):
                    control_module.run(
                        codex_bin="codex.cmd",
                        control_home=root,
                        temp_dir=root,
                        proxy_telemetry=root / "telemetry.json",
                        config_overrides=(),
                        timeout_seconds=5,
                    )
            self.assertEqual(process.wait_calls, 1)
            self.assertEqual(len(observed_timeouts), 1)
            self.assertEqual(observed_timeouts[0], 0.0)


if __name__ == "__main__":
    unittest.main()
