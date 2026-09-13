import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from tooling.feynman_subscription_control_plane_preflight import (
    ControlPlaneError,
    _environment_summary,
    _failure_category,
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


if __name__ == "__main__":
    unittest.main()
