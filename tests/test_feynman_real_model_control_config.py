from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_real_model_control_config import (
    PROVIDER_BASE_URL,
    PROVIDER_ENV_KEY,
    build_document,
    render_toml,
    validate_document,
)


class RealModelControlConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        paths = {
            "candidate_dir": str((base / "candidate").resolve()),
            "evaluator_dir": str((base / "evaluator").resolve()),
            "source_repo": str((base / "source").resolve()),
            "ephemeral_home": str((base / "home").resolve()),
            "codex_home": str((base / "codex").resolve()),
            "temp_dir": str((base / "temp").resolve()),
            "real_home": str((base / "real-home").resolve()),
        }
        self.profile = {
            "schema_version": 1,
            "backend": "docker",
            "backend_version": "28.0.4",
            "image": "feynman-codex-remote:local",
            "image_id": "sha256:" + "8" * 64,
            "network_mode": "none",
            "read_only_root": True,
            "no_new_privileges": True,
            "capabilities": [],
            "run_as": "1000:1000",
            "read_write_mounts": [
                paths["candidate_dir"], paths["ephemeral_home"],
                paths["codex_home"], paths["temp_dir"],
            ],
            "read_only_mounts": [],
            "tmpfs_mounts": ["/tmp"],
            "protected_roots_mounted": [],
            "candidate_env_keys": ["HOME", "CODEX_HOME", "PATH", "TMPDIR"],
            "scope": "synthetic real-model profile",
        }
        self.profile_sha = hashlib.sha256(
            json.dumps(self.profile, sort_keys=True).encode("utf-8")
        ).hexdigest()
        self.job = {
            "schema_version": 2,
            "run_id": "real-smoke",
            "job": {
                "ordinal": 1,
                "case_id": "mechanism-01",
                "condition_id": "baseline",
                "repeat": 1,
                "has_followup": False,
            },
            "versions": {"model": "real-model-id", "codex_cli": "codex-cli 0.153.4"},
            "paths": paths,
            "boundary": {
                "profile_sha256": self.profile_sha,
                "backend": "docker",
                "backend_version": "28.0.4",
                "network_mode": "none",
                "candidate_env_keys": deepcopy(self.profile["candidate_env_keys"]),
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
            "scope": "synthetic real smoke job",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_model_config_is_control_only_and_tool_env_is_fail_closed(self):
        document = build_document(deepcopy(self.job), deepcopy(self.profile), self.profile_sha)
        provider = document["model_providers"]["openai-api"]
        self.assertEqual(provider["base_url"], PROVIDER_BASE_URL)
        self.assertEqual(provider["env_key"], PROVIDER_ENV_KEY)
        self.assertEqual(document["shell_environment_policy"]["inherit"], "none")
        self.assertNotIn(PROVIDER_ENV_KEY, document["shell_environment_policy"]["set"])
        self.assertEqual(document["model"], "real-model-id")

    def test_rendered_config_contains_key_name_but_no_credential_value(self):
        document = build_document(deepcopy(self.job), deepcopy(self.profile), self.profile_sha)
        text = render_toml(document)
        self.assertIn('env_key = "OPENAI_API_KEY"', text)
        self.assertNotIn("sk-", text)
        parsed = tomllib.loads(text)
        result = validate_document(parsed, deepcopy(self.job), deepcopy(self.profile), self.profile_sha)
        self.assertFalse(result["credential_value_stored"])
        self.assertEqual(result["authentication_mode"], "control-plane-only")
        self.assertEqual(result["credential_source"], "environment")

    def test_custom_control_plane_env_key_is_propagated_from_runner_job(self):
        job = deepcopy(self.job)
        job["authentication"]["control_plane_credential_env_key"] = "MODEL_SERVICE_TOKEN"
        document = build_document(job, deepcopy(self.profile), self.profile_sha)
        self.assertEqual(
            document["model_providers"]["openai-api"]["env_key"],
            "MODEL_SERVICE_TOKEN",
        )
        self.assertNotIn("MODEL_SERVICE_TOKEN", document["shell_environment_policy"]["set"])
        result = validate_document(document, job, deepcopy(self.profile), self.profile_sha)
        self.assertEqual(result["credential_env_key_name"], "MODEL_SERVICE_TOKEN")

    def test_mock_model_id_is_rejected(self):
        job = deepcopy(self.job)
        job["versions"]["model"] = "mock-model"
        with self.assertRaises(ValueError):
            build_document(job, deepcopy(self.profile), self.profile_sha)

    def test_tampered_provider_endpoint_is_rejected(self):
        document = build_document(deepcopy(self.job), deepcopy(self.profile), self.profile_sha)
        document["model_providers"]["openai-api"]["base_url"] = "https://example.invalid/v1"
        with self.assertRaises(ValueError):
            validate_document(document, deepcopy(self.job), deepcopy(self.profile), self.profile_sha)

    def test_tool_shell_inherit_all_is_rejected(self):
        document = build_document(deepcopy(self.job), deepcopy(self.profile), self.profile_sha)
        document["shell_environment_policy"]["inherit"] = "all"
        with self.assertRaises(ValueError):
            validate_document(document, deepcopy(self.job), deepcopy(self.profile), self.profile_sha)

    def test_job_with_candidate_auth_env_is_rejected_before_config(self):
        job = deepcopy(self.job)
        job["authentication"]["candidate_tool_auth_env_keys"] = ["OPENAI_API_KEY"]
        with self.assertRaises(ValueError):
            build_document(job, deepcopy(self.profile), self.profile_sha)

    def test_job_exposing_control_plane_key_in_candidate_env_is_rejected(self):
        job = deepcopy(self.job)
        profile = deepcopy(self.profile)
        job["boundary"]["candidate_env_keys"].append("OPENAI_API_KEY")
        profile["candidate_env_keys"].append("OPENAI_API_KEY")
        with self.assertRaises(ValueError):
            build_document(job, profile, self.profile_sha)


if __name__ == "__main__":
    unittest.main()
