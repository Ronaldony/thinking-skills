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

from tooling.feynman_remote_exec_environment import (
    build_document,
    expected_docker_args,
    render_toml,
    validate_document,
)


class RemoteExecEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.paths = {
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
                self.paths["candidate_dir"], self.paths["ephemeral_home"],
                self.paths["codex_home"], self.paths["temp_dir"],
            ],
            "read_only_mounts": [],
            "tmpfs_mounts": ["/tmp"],
            "protected_roots_mounted": [],
            "candidate_env_keys": ["HOME", "CODEX_HOME", "PATH", "TMPDIR"],
            "scope": "synthetic stdio remote exec profile",
        }
        raw = json.dumps(self.profile, sort_keys=True).encode("utf-8")
        self.profile_sha = hashlib.sha256(raw).hexdigest()
        self.job = {
            "schema_version": 2,
            "run_id": "reference/run 1",
            "job": {
                "ordinal": 1,
                "case_id": "mechanism-01",
                "condition_id": "baseline",
                "repeat": 1,
                "has_followup": False,
            },
            "versions": {"model": "mock-model", "codex_cli": "codex-test"},
            "paths": deepcopy(self.paths),
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
            "scope": "synthetic runner job",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_document_disables_local_execution_and_uses_stdio_exec_server(self):
        document = build_document(deepcopy(self.job), deepcopy(self.profile), self.profile_sha)
        self.assertFalse(document["include_local"])
        self.assertEqual(document["default"], "candidate")
        environment = document["environments"][0]
        self.assertEqual(environment["program"], "docker")
        args = environment["args"]
        self.assertIn("--network", args)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertEqual(args[-4:], ["codex", "exec-server", "--listen", "stdio"])
        self.assertNotIn(self.paths["evaluator_dir"], " ".join(args))
        self.assertNotIn(self.paths["source_repo"], " ".join(args))
        self.assertNotIn(self.paths["real_home"], " ".join(args))
        self.assertNotIn("OPENAI_API_KEY", " ".join(args))

    def test_all_candidate_owned_roots_are_exact_rw_binds(self):
        args = expected_docker_args(deepcopy(self.job), deepcopy(self.profile))
        joined = "\n".join(args)
        for key in ("candidate_dir", "ephemeral_home", "codex_home", "temp_dir"):
            path = self.paths[key]
            self.assertIn(f"{path}:{path}:rw", joined)

    def test_rendered_toml_round_trips_to_canonical_document(self):
        document = build_document(deepcopy(self.job), deepcopy(self.profile), self.profile_sha)
        parsed = tomllib.loads(render_toml(document))
        result = validate_document(parsed, deepcopy(self.job), deepcopy(self.profile), self.profile_sha)
        self.assertEqual(result["verdict"], "remote-exec-environment-valid")
        self.assertTrue(result["container_name"].startswith("feynman-tool-reference-run-1"))

    def test_local_environment_reenable_is_rejected(self):
        document = build_document(deepcopy(self.job), deepcopy(self.profile), self.profile_sha)
        document["include_local"] = True
        with self.assertRaises(ValueError):
            validate_document(document, deepcopy(self.job), deepcopy(self.profile), self.profile_sha)

    def test_read_only_host_bind_without_source_contract_is_rejected(self):
        profile = deepcopy(self.profile)
        profile["read_only_mounts"] = ["/probe/file"]
        with self.assertRaises(ValueError):
            build_document(deepcopy(self.job), profile, self.profile_sha)

    def test_non_closed_network_profile_is_rejected(self):
        profile = deepcopy(self.profile)
        profile["network_mode"] = "open"
        job = deepcopy(self.job)
        job["boundary"]["network_mode"] = "open"
        job["network"]["tool_network"] = "open"
        with self.assertRaises(ValueError):
            build_document(job, profile, self.profile_sha)

    def test_unknown_candidate_env_key_has_to_be_explicitly_supported(self):
        profile = deepcopy(self.profile)
        profile["candidate_env_keys"].append("LANG")
        job = deepcopy(self.job)
        job["boundary"]["candidate_env_keys"].append("LANG")
        with self.assertRaises(ValueError):
            expected_docker_args(job, profile)


if __name__ == "__main__":
    unittest.main()
