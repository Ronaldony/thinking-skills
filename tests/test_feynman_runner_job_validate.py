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

from tooling.feynman_boundary_profile import validate_profile
from tooling.feynman_runner_job_validate import validate_job


class RunnerJobValidateTests(unittest.TestCase):
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
            "scope": "synthetic strict runner profile",
        }
        validate_profile(self.profile)
        raw = json.dumps(self.profile, sort_keys=True).encode("utf-8")
        self.profile_sha = hashlib.sha256(raw).hexdigest()
        self.job = {
            "schema_version": 2,
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
                "mode": "control-plane-only",
                "control_plane_credential_source": "environment",
                "control_plane_credential_env_key": "OPENAI_API_KEY",
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

    def tearDown(self):
        self.tmp.cleanup()

    def test_matching_job_and_profile_pass(self):
        result = validate_job(deepcopy(self.job), deepcopy(self.profile), self.profile_sha)
        self.assertEqual(result["verdict"], "runner-job-valid")
        self.assertEqual(result["authentication_mode"], "control-plane-only")
        self.assertEqual(result["control_plane_credential_source"], "environment")
        self.assertEqual(result["control_plane_credential_env_key"], "OPENAI_API_KEY")

    def test_legacy_schema_v1_is_rejected(self):
        job = deepcopy(self.job)
        job["schema_version"] = 1
        with self.assertRaises(ValueError):
            validate_job(job, deepcopy(self.profile), self.profile_sha)

    def test_legacy_external_broker_mode_is_rejected(self):
        job = deepcopy(self.job)
        job["authentication"]["mode"] = "external-broker"
        with self.assertRaises(ValueError):
            validate_job(job, deepcopy(self.profile), self.profile_sha)

    def test_unvalidated_credential_source_is_rejected(self):
        job = deepcopy(self.job)
        job["authentication"]["control_plane_credential_source"] = "file"
        with self.assertRaises(ValueError):
            validate_job(job, deepcopy(self.profile), self.profile_sha)

    def test_invalid_control_plane_credential_env_key_is_rejected(self):
        job = deepcopy(self.job)
        job["authentication"]["control_plane_credential_env_key"] = "BAD-KEY"
        with self.assertRaises(ValueError):
            validate_job(job, deepcopy(self.profile), self.profile_sha)

    def test_control_plane_key_in_candidate_env_is_rejected(self):
        job = deepcopy(self.job)
        job["boundary"]["candidate_env_keys"].append("OPENAI_API_KEY")
        profile = deepcopy(self.profile)
        profile["candidate_env_keys"].append("OPENAI_API_KEY")
        with self.assertRaises(ValueError):
            validate_job(job, profile, self.profile_sha)

    def test_unexpected_auth_field_is_rejected(self):
        job = deepcopy(self.job)
        job["authentication"]["credential_value"] = "must-never-appear"
        with self.assertRaises(ValueError):
            validate_job(job, deepcopy(self.profile), self.profile_sha)

    def test_extra_writable_mount_is_rejected(self):
        profile = deepcopy(self.profile)
        profile["read_write_mounts"].append(str((self.base / "extra").resolve()))
        with self.assertRaises(ValueError):
            validate_job(deepcopy(self.job), profile, self.profile_sha)

    def test_missing_candidate_writable_mount_is_rejected(self):
        profile = deepcopy(self.profile)
        profile["read_write_mounts"].remove(self.paths["candidate_dir"])
        with self.assertRaises(ValueError):
            validate_job(deepcopy(self.job), profile, self.profile_sha)

    def test_candidate_auth_env_exposure_is_rejected(self):
        job = deepcopy(self.job)
        job["authentication"]["candidate_tool_auth_env_keys"] = ["OPENAI_API_KEY"]
        with self.assertRaises(ValueError):
            validate_job(job, deepcopy(self.profile), self.profile_sha)

    def test_candidate_credential_file_is_rejected(self):
        job = deepcopy(self.job)
        job["authentication"]["candidate_readable_credential_files"] = ["/run/credentials.json"]
        with self.assertRaises(ValueError):
            validate_job(job, deepcopy(self.profile), self.profile_sha)

    def test_credential_command_argument_is_rejected(self):
        job = deepcopy(self.job)
        job["authentication"]["credential_command_arguments"] = ["--api-key=secret"]
        with self.assertRaises(ValueError):
            validate_job(job, deepcopy(self.profile), self.profile_sha)

    def test_boundary_profile_digest_drift_is_rejected(self):
        job = deepcopy(self.job)
        job["boundary"]["profile_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            validate_job(job, deepcopy(self.profile), self.profile_sha)

    def test_tool_network_drift_is_rejected(self):
        job = deepcopy(self.job)
        job["network"]["tool_network"] = "open"
        with self.assertRaises(ValueError):
            validate_job(job, deepcopy(self.profile), self.profile_sha)

    def test_protected_path_as_candidate_home_is_rejected(self):
        job = deepcopy(self.job)
        job["paths"]["ephemeral_home"] = job["paths"]["evaluator_dir"]
        with self.assertRaises(ValueError):
            validate_job(job, deepcopy(self.profile), self.profile_sha)

    def test_skill_condition_requires_runtime(self):
        job = deepcopy(self.job)
        job["job"]["condition_id"] = "feynman-v05"
        job["skills"]["expected_candidate_skills"] = ["feynman-thinking"]
        with self.assertRaises(ValueError):
            validate_job(job, deepcopy(self.profile), self.profile_sha)


if __name__ == "__main__":
    unittest.main()
