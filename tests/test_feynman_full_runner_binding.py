from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tooling.feynman_full_runner_binding import bind
from tooling.feynman_full_runner_contract import TOOL_NAMES


class FullRunnerBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        (self.candidate / "candidate.py").write_text("value = 1\n", encoding="utf-8")
        (self.candidate / "test_candidate.py").write_text("assert True\n", encoding="utf-8")
        self.profile = self.root / "profile.json"
        self.profile.write_text(json.dumps({
            "schema_version": 1, "backend": "docker", "backend_version": "29.7.2",
            "image": "sha256:" + "1" * 64, "image_id": "sha256:" + "1" * 64,
            "network_mode": "none", "read_only_root": True,
            "no_new_privileges": True, "capabilities": [], "run_as": "1000:1000",
            "read_write_mounts": ["/run/candidate", "/run/home", "/run/codex", "/run/temp"],
            "read_only_mounts": [], "tmpfs_mounts": ["/tmp"],
            "protected_roots_mounted": [],
            "candidate_env_keys": ["HOME", "CODEX_HOME", "PATH", "TMPDIR", "PYTHONDONTWRITEBYTECODE"],
            "scope": "test",
        }), encoding="utf-8")
        self.job = self.root / "job.json"
        paths = {
            "candidate_dir": str(self.candidate),
            "evaluator_dir": str(self.root / "evaluator"),
            "source_repo": str(self.root / "source"),
            "ephemeral_home": str(self.root / "home"),
            "codex_home": str(self.root / "codex"),
            "temp_dir": str(self.root / "temp"),
            "real_home": str(self.root / "real"),
            "control_codex_home": str(self.root / "control"),
        }
        for name in ("evaluator", "source", "home", "codex", "temp", "real", "control"):
            (self.root / name).mkdir()
        import hashlib
        plan_sha = "a" * 64
        prompt_sha = "b" * 64
        profile_sha = hashlib.sha256(self.profile.read_bytes()).hexdigest()
        self.job.write_text(json.dumps({
            "schema_version": 3, "run_id": "binding-test",
            "job": {"ordinal": 1, "case_id": "tools-10", "condition_id": "feynman-v05", "repeat": 1, "has_followup": False},
            "versions": {"model": "gpt-5.6-luna", "codex_cli": "codex-cli 0.154.0"},
            "paths": paths,
            "boundary": {"profile_sha256": profile_sha, "backend": "docker", "backend_version": "29.7.2", "network_mode": "none", "candidate_env_keys": ["HOME", "CODEX_HOME", "PATH", "TMPDIR", "PYTHONDONTWRITEBYTECODE"], "mounts": [{"source": paths["candidate_dir"], "destination": "/run/candidate", "access": "rw"}, {"source": paths["ephemeral_home"], "destination": "/run/home", "access": "rw"}, {"source": paths["codex_home"], "destination": "/run/codex", "access": "rw"}, {"source": paths["temp_dir"], "destination": "/run/temp", "access": "rw"}]},
            "network": {"case_requires_tool_network": False, "tool_network": "blocked", "allowed_tool_destinations": [], "control_plane_separate_from_tool_network": True},
            "authentication": {"mode": "chatgpt-subscription", "control_plane_auth_source": "codex-session", "api_key_auth_allowed": False, "candidate_auth_exposed": False, "candidate_tool_auth_env_keys": [], "candidate_readable_auth_paths": [], "auth_command_arguments": []},
            "skills": {"expected_candidate_skills": ["feynman-thinking"], "runtime_sha256": "c" * 64},
            "digests": {"eval_plan_sha256": plan_sha, "candidate_prompt_sha256": prompt_sha, "boundary_profile_sha256": profile_sha, "runtime_sha256": "c" * 64},
            "scope": "test",
        }), encoding="utf-8")
        self.catalog = self.root / "catalog.json"
        self.docker = self.root / "docker.json"
        self.adapter = self.root / "adapter.mjs"
        self.adapter.write_text("adapter\n", encoding="utf-8")
        self.node = self.root / "node.exe"
        self.docker_bin = self.root / "docker.exe"
        self.node.write_text("node\n", encoding="utf-8")
        self.docker_bin.write_text("docker\n", encoding="utf-8")
        self.docker_config = self.root / "docker-config"
        self.docker_config.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _reports(self, image: str) -> None:
        from tooling.feynman_full_runner_contract import build_full_runner_override
        override = build_full_runner_override(node_bin=self.node, adapter=self.adapter, candidate=self.candidate, docker_bin=self.docker_bin, docker_config=self.docker_config, docker_image_id=image)
        lineage = override.sanitized_lineage()
        self.catalog.write_text(json.dumps({
            "verdict": "full-runner-mcp-contract-ready", "model_calls": 0, "authentication_used": False,
            "lineage": lineage, "catalog": {"server_name": "feynman_full_runner", "tool_names": sorted(TOOL_NAMES)},
            "privacy": {"model_request_started": False, "credential_files_read": False, "tool_payloads_preserved": False},
        }), encoding="utf-8")
        self.docker.write_text(json.dumps({
            "verdict": "full-runner-mcp-docker-preflight-passed", "model_calls": 0, "authentication_used": False,
            "checks": {"initialize_ok": True, "exact_tool_catalog": True, "fixed_read_observed": True, "fixed_write_observed": True, "fixed_test_passed": True, "write_visible_to_followup_read": True},
            "fixed_policy": {"tool_names": list(TOOL_NAMES), "candidate_file": "candidate.py", "test_command": ["python3", "-B", "-I", "/run/candidate/test_candidate.py"], "network_mode": "none", "read_only_root": True, "candidate_mount_access": "ro", "write_target": "candidate.py"},
            "privacy": {"model_request_started": False, "credential_files_read": False, "tool_payloads_preserved": False},
        }), encoding="utf-8")

    @patch("tooling.feynman_full_runner_binding._sha", return_value="d" * 64)
    def test_binds_valid_chain_without_model(self, _sha: object) -> None:
        image = "sha256:" + "2" * 64
        self._reports(image)
        result = bind(runner_job_path=self.job, boundary_profile_path=self.profile, catalog_preflight_path=self.catalog, docker_preflight_path=self.docker, node_bin=self.node, adapter=self.adapter, docker_bin=self.docker_bin, docker_config=self.docker_config, docker_image_id=image, output=self.root / "binding.json")
        self.assertEqual(result["verdict"], "full-runner-mcp-artifact-chain-bound")
        self.assertEqual(result["checks"]["model_calls"], 0)
        self.assertFalse(result["checks"]["authentication_used"])

    def test_rejects_catalog_image_drift(self) -> None:
        image = "sha256:" + "2" * 64
        self._reports("sha256:" + "3" * 64)
        with self.assertRaises(ValueError):
            bind(runner_job_path=self.job, boundary_profile_path=self.profile, catalog_preflight_path=self.catalog, docker_preflight_path=self.docker, node_bin=self.node, adapter=self.adapter, docker_bin=self.docker_bin, docker_config=self.docker_config, docker_image_id=image, output=self.root / "binding.json")


if __name__ == "__main__":
    unittest.main()
