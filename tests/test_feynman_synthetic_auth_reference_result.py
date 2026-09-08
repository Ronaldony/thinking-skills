from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_synthetic_auth_reference_result import assemble


class SyntheticAuthReferenceResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.secret = b"synthetic-auth-reference-secret"
        self.secret_path = self.base / "secret.txt"
        self.secret_path.write_bytes(self.secret + b"\n")
        self.secret_sha = hashlib.sha256(self.secret).hexdigest()

        self.mock_path = self.base / "mock-state.json"
        self.mock = {
            "schema_version": 4,
            "scenario": "exec-only",
            "validation_error": None,
            "expected_bearer_sha256": self.secret_sha,
            "requests": [
                {
                    "index": 1,
                    "body_sha256": "1" * 64,
                    "authorization_bearer_present": True,
                    "authorization_bearer_sha256": self.secret_sha,
                    "authorization_matches_expected": True,
                    "has_exec_output": False,
                    "exec_output_contains_auth_env_marker": False,
                    "exec_output_contains_auth_value_marker": False,
                },
                {
                    "index": 2,
                    "body_sha256": "2" * 64,
                    "authorization_bearer_present": True,
                    "authorization_bearer_sha256": self.secret_sha,
                    "authorization_matches_expected": True,
                    "has_exec_output": True,
                    "exec_output_contains_auth_env_marker": True,
                    "exec_output_contains_auth_value_marker": True,
                },
            ],
        }
        self._write_mock()

        self.remote_path = self.base / "remote-result.json"
        self.remote = {
            "schema_version": 3,
            "verdict": "mock-remote-tool-reference-passed",
            "scenario": "exec-only",
            "digests": {
                "mock_state_sha256": self._sha(self.mock_path),
                "codex_trace_sha256": "3" * 64,
                "boundary_profile_sha256": "4" * 64,
                "runner_job_sha256": "5" * 64,
            },
            "assertions": {
                "exec_output_round_trip": True,
                "workspace_marker": True,
                "tool_network_blocked": True,
                "auth_env_clean": True,
                "command_execution_observed": True,
                "final_agent_message_observed": True,
                "docker_inspect_matches_profile": True,
                "control_plane_endpoint_reference_valid": True,
                "local_execution_disabled": True,
            },
        }
        self._write_remote()

        self.scan_path = self.base / "leak-scan.json"
        self.scan = {
            "schema_version": 1,
            "verdict": "credential-exact-bytes-not-found",
            "secret_sha256": self.secret_sha,
            "exact_secret_found": False,
            "symlinks_allowed": False,
            "scanned_file_count": 2,
            "scanned_total_bytes": 123,
            "roots": ["/candidate"],
            "explicit_files": ["/trace.jsonl"],
            "files": [
                {"path": "/candidate/a", "source": "root", "size_bytes": 10, "sha256": "6" * 64},
                {"path": "/trace.jsonl", "source": "explicit", "size_bytes": 113, "sha256": "7" * 64},
            ],
        }
        self._write_scan()

    def tearDown(self):
        self.tmp.cleanup()

    def _sha(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_mock(self):
        self.mock_path.write_text(json.dumps(self.mock) + "\n", encoding="utf-8")

    def _write_remote(self):
        self.remote_path.write_text(json.dumps(self.remote) + "\n", encoding="utf-8")

    def _write_scan(self):
        self.scan_path.write_text(json.dumps(self.scan) + "\n", encoding="utf-8")

    def _assemble(self):
        return assemble(
            secret_file=self.secret_path,
            remote_reference_result_path=self.remote_path,
            mock_state_path=self.mock_path,
            leak_scan_path=self.scan_path,
        )

    def test_valid_synthetic_auth_reference_passes(self):
        result = self._assemble()
        self.assertEqual(result["verdict"], "synthetic-control-plane-auth-reference-passed")
        self.assertEqual(result["secret_sha256"], self.secret_sha)
        self.assertTrue(result["assertions"]["all_model_requests_used_expected_synthetic_bearer"])
        self.assertTrue(result["assertions"]["remote_tool_matching_credential_env_value_absent"])
        self.assertTrue(result["assertions"]["exact_secret_bytes_absent_from_scanned_artifacts"])

    def test_bearer_mismatch_is_rejected(self):
        self.mock["requests"][0]["authorization_bearer_sha256"] = "8" * 64
        self._write_mock()
        self.remote["digests"]["mock_state_sha256"] = self._sha(self.mock_path)
        self._write_remote()
        with self.assertRaises(ValueError):
            self._assemble()

    def test_missing_bearer_on_one_request_is_rejected(self):
        self.mock["requests"][1]["authorization_bearer_present"] = False
        self._write_mock()
        self.remote["digests"]["mock_state_sha256"] = self._sha(self.mock_path)
        self._write_remote()
        with self.assertRaises(ValueError):
            self._assemble()

    def test_auth_value_marker_missing_is_rejected(self):
        self.mock["requests"][1]["exec_output_contains_auth_value_marker"] = False
        self._write_mock()
        self.remote["digests"]["mock_state_sha256"] = self._sha(self.mock_path)
        self._write_remote()
        with self.assertRaises(ValueError):
            self._assemble()

    def test_leak_scan_for_different_secret_is_rejected(self):
        self.scan["secret_sha256"] = "9" * 64
        self._write_scan()
        with self.assertRaises(ValueError):
            self._assemble()

    def test_remote_reference_bound_to_different_mock_state_is_rejected(self):
        self.remote["digests"]["mock_state_sha256"] = "a" * 64
        self._write_remote()
        with self.assertRaises(ValueError):
            self._assemble()

    def test_failed_remote_assertion_is_rejected(self):
        self.remote["assertions"]["tool_network_blocked"] = False
        self._write_remote()
        with self.assertRaises(ValueError):
            self._assemble()

    def test_mock_state_schema_v3_is_rejected(self):
        self.mock["schema_version"] = 3
        self._write_mock()
        self.remote["digests"]["mock_state_sha256"] = self._sha(self.mock_path)
        self._write_remote()
        with self.assertRaises(ValueError):
            self._assemble()

    def test_empty_scan_manifest_is_rejected(self):
        self.scan["scanned_file_count"] = 0
        self.scan["scanned_total_bytes"] = 0
        self.scan["files"] = []
        self._write_scan()
        with self.assertRaises(ValueError):
            self._assemble()


if __name__ == "__main__":
    unittest.main()
