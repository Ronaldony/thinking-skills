from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tooling.feynman_runner_job_link import bind
from test_feynman_runner_attestation import attestation, boundary_report


class RunnerJobLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.paths = {
            "candidate_dir": str((self.base / "candidate").resolve()),
            "evaluator_dir": str((self.base / "evaluator").resolve()),
            "source_repo": str((self.base / "source").resolve()),
            "ephemeral_home": str((self.base / "home").resolve()),
            "codex_home": str((self.base / "codex").resolve()),
            "temp_dir": str((self.base / "temp").resolve()),
            "real_home": str((self.base / "real-home").resolve()),
        }
        self.profile_path = self.base / "boundary-profile.json"
        self.profile = {
            "schema_version": 1,
            "backend": "docker",
            "backend_version": "28.0.4",
            "image": "python:3.12-slim",
            "image_id": "sha256:" + "6" * 64,
            "network_mode": "none",
            "read_only_root": True,
            "no_new_privileges": True,
            "capabilities": [],
            "run_as": "1000:1000",
            "read_write_mounts": [
                self.paths["candidate_dir"], self.paths["ephemeral_home"],
                self.paths["codex_home"], self.paths["temp_dir"],
            ],
            "read_only_mounts": ["/probe/feynman_boundary_probe.py"],
            "tmpfs_mounts": ["/tmp"],
            "protected_roots_mounted": [],
            "candidate_env_keys": ["HOME", "CODEX_HOME", "PATH", "TMPDIR"],
            "scope": "synthetic runner-job linkage profile",
        }
        self.profile_path.write_text(json.dumps(self.profile, sort_keys=True), encoding="utf-8")
        self.profile_sha = hashlib.sha256(self.profile_path.read_bytes()).hexdigest()

        self.job_path = self.base / "runner-job.json"
        self.job = {
            "schema_version": 1,
            "run_id": "run-1",
            "job": {
                "ordinal": 1,
                "case_id": "mechanism-01",
                "condition_id": "baseline",
                "repeat": 1,
                "has_followup": False,
            },
            "versions": {"model": "test-model", "codex_cli": "codex-test"},
            "paths": deepcopy(self.paths),
            "boundary": {
                "profile_sha256": self.profile_sha,
                "backend": "docker",
                "backend_version": "28.0.4",
                "network_mode": "none",
                "candidate_env_keys": ["HOME", "CODEX_HOME", "PATH", "TMPDIR"],
            },
            "network": {
                "case_requires_tool_network": False,
                "tool_network": "blocked",
                "allowed_tool_destinations": [],
                "control_plane_separate_from_tool_network": True,
            },
            "authentication": {
                "mode": "external-broker",
                "candidate_tool_auth_env_keys": [],
                "candidate_readable_credential_files": [],
                "credential_command_arguments": [],
            },
            "skills": {"expected_candidate_skills": [], "runtime_sha256": None},
            "digests": {
                "eval_plan_sha256": "1" * 64,
                "candidate_prompt_sha256": "2" * 64,
                "boundary_profile_sha256": self.profile_sha,
                "runtime_sha256": None,
            },
            "scope": "synthetic runner job",
        }
        self._write_job()

        self.attestation_path = self.base / "attestation.json"
        self.attestation = attestation("baseline")
        self.attestation.update({"run_id": "run-1", "case_id": "mechanism-01"})
        self.attestation["boundary"].update({
            "backend": "docker",
            "backend_version": "28.0.4",
            "profile_sha256": self.profile_sha,
        })
        self.attestation["paths"] = deepcopy(self.paths)
        self.attestation["filesystem"].update({
            "candidate_readable_data_roots": [
                self.paths["candidate_dir"], self.paths["ephemeral_home"],
                self.paths["codex_home"], self.paths["temp_dir"],
            ],
            "candidate_writable_roots": [
                self.paths["candidate_dir"], self.paths["ephemeral_home"],
                self.paths["codex_home"], self.paths["temp_dir"],
            ],
            "forbidden_read_roots": [
                self.paths["evaluator_dir"], self.paths["source_repo"], self.paths["real_home"],
            ],
            "forbidden_write_roots": [
                self.paths["evaluator_dir"], self.paths["source_repo"], self.paths["real_home"],
            ],
        })
        self.attestation["environment"]["candidate_env_keys"] = ["HOME", "CODEX_HOME", "PATH", "TMPDIR"]
        self.attestation["versions"] = deepcopy(self.job["versions"])
        self.attestation["digests"].update({
            "eval_plan_sha256": self.job["digests"]["eval_plan_sha256"],
            "candidate_prompt_sha256": self.job["digests"]["candidate_prompt_sha256"],
            "runtime_sha256": None,
        })

        self.report_path = self.base / "probe-report.json"
        self.report = boundary_report(self.attestation)
        self.report_path.write_text(json.dumps(self.report), encoding="utf-8")
        self.attestation["digests"]["probe_report_sha256"] = hashlib.sha256(
            self.report_path.read_bytes()
        ).hexdigest()
        self._write_attestation()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_job(self):
        self.job_path.write_text(json.dumps(self.job), encoding="utf-8")

    def _write_attestation(self):
        self.attestation_path.write_text(json.dumps(self.attestation), encoding="utf-8")

    def _bind(self):
        return bind(
            runner_job_path=self.job_path,
            boundary_profile_path=self.profile_path,
            probe_report_path=self.report_path,
            attestation_path=self.attestation_path,
        )

    def test_matching_job_and_attestation_bind(self):
        result = self._bind()
        self.assertEqual(result["verdict"], "runner-job-attestation-bound")
        self.assertEqual(result["boundary_profile_sha256"], self.profile_sha)
        self.assertEqual(result["model"], "test-model")

    def test_model_version_drift_is_rejected(self):
        self.attestation["versions"]["model"] = "different-model"
        self._write_attestation()
        with self.assertRaises(ValueError):
            self._bind()

    def test_candidate_path_drift_is_rejected(self):
        drift = str((self.base / "different-candidate").resolve())
        self.attestation["paths"]["candidate_dir"] = drift
        self.attestation["filesystem"]["candidate_readable_data_roots"][0] = drift
        self.attestation["filesystem"]["candidate_writable_roots"][0] = drift
        self._write_attestation()
        with self.assertRaises(ValueError):
            self._bind()

    def test_prompt_digest_drift_is_rejected(self):
        self.attestation["digests"]["candidate_prompt_sha256"] = "f" * 64
        self._write_attestation()
        with self.assertRaises(ValueError):
            self._bind()

    def test_network_policy_drift_is_rejected(self):
        self.attestation["network"]["control_plane_separate_from_tool_network"] = False
        self._write_attestation()
        with self.assertRaises(ValueError):
            self._bind()

    def test_tampered_probe_report_is_rejected(self):
        self.report["observed_env_keys"] = ["HOME"]
        self.report_path.write_text(json.dumps(self.report), encoding="utf-8")
        with self.assertRaises(ValueError):
            self._bind()

    def test_runner_job_profile_digest_drift_is_rejected(self):
        self.job["boundary"]["profile_sha256"] = "f" * 64
        self._write_job()
        with self.assertRaises(ValueError):
            self._bind()


if __name__ == "__main__":
    unittest.main()
