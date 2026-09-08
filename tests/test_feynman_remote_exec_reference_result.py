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

from tooling.feynman_network_reference import endpoint_identity
from tooling.feynman_remote_exec_environment import build_files as build_remote_environment
from tooling.feynman_remote_exec_reference_result import assemble


class RemoteExecReferenceResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.candidate = self.base / "candidate"
        self.evaluator = self.base / "evaluator"
        self.home = self.base / "home"
        self.codex_home = self.base / "codex-home"
        self.temp_dir = self.base / "temp"
        self.source = self.base / "source"
        self.real_home = self.base / "real-home"
        for path in (
            self.candidate, self.evaluator, self.home, self.codex_home,
            self.temp_dir, self.source, self.real_home,
        ):
            path.mkdir(parents=True)

        self.profile_path = self.base / "profile.json"
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
                str(self.candidate.resolve()), str(self.home.resolve()),
                str(self.codex_home.resolve()), str(self.temp_dir.resolve()),
            ],
            "read_only_mounts": [],
            "tmpfs_mounts": ["/tmp"],
            "protected_roots_mounted": [],
            "candidate_env_keys": ["HOME", "CODEX_HOME", "PATH", "TMPDIR"],
            "scope": "synthetic remote tool result profile",
        }
        self.profile_path.write_text(
            json.dumps(self.profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.profile_sha = hashlib.sha256(self.profile_path.read_bytes()).hexdigest()

        self.job_path = self.base / "runner-job.json"
        self.job = {
            "schema_version": 1,
            "run_id": "synthetic-reference",
            "job": {
                "ordinal": 1,
                "case_id": "mechanism-01",
                "condition_id": "baseline",
                "repeat": 1,
                "has_followup": False,
            },
            "versions": {"model": "mock-model", "codex_cli": "codex-cli synthetic"},
            "paths": {
                "candidate_dir": str(self.candidate.resolve()),
                "evaluator_dir": str(self.evaluator.resolve()),
                "source_repo": str(self.source.resolve()),
                "ephemeral_home": str(self.home.resolve()),
                "codex_home": str(self.codex_home.resolve()),
                "temp_dir": str(self.temp_dir.resolve()),
                "real_home": str(self.real_home.resolve()),
            },
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
        self.job_path.write_text(json.dumps(self.job, indent=2) + "\n", encoding="utf-8")

        self.environment_path = self.base / "environments.toml"
        build_remote_environment(self.job_path, self.profile_path, self.environment_path)

        self.host = "172.17.0.1"
        self.port = 19001
        self.network_path = self.base / "network-reference.json"
        self.network_path.write_text(json.dumps({
            "schema_version": 1,
            "host": self.host,
            "port": self.port,
            "reachable_from_control_plane": True,
            "probe_method": "tcp-connect:v1",
            "endpoint_identity_sha256": endpoint_identity(self.host, self.port),
        }) + "\n", encoding="utf-8")

        self.mock_state_path = self.base / "mock-state.json"
        self.mock_state = {
            "schema_version": 3,
            "scenario": "exec-only",
            "requests": [
                {
                    "index": 1,
                    "body_sha256": "3" * 64,
                    "has_patch_output": False,
                    "patch_output_sha256": None,
                    "has_exec_output": False,
                    "exec_output_sha256": None,
                    "exec_output_contains_patch_marker": False,
                    "exec_output_contains_workspace_marker": False,
                    "exec_output_contains_network_marker": False,
                    "exec_output_contains_auth_env_marker": False,
                },
                {
                    "index": 2,
                    "body_sha256": "4" * 64,
                    "has_patch_output": False,
                    "patch_output_sha256": None,
                    "has_exec_output": True,
                    "exec_output_sha256": "7" * 64,
                    "exec_output_contains_patch_marker": False,
                    "exec_output_contains_workspace_marker": True,
                    "exec_output_contains_network_marker": True,
                    "exec_output_contains_auth_env_marker": True,
                },
            ],
            "validation_error": None,
            "final_text": "REMOTE_EXEC_REFERENCE_OK",
            "patch_call_id": None,
            "exec_call_id": "call-remote-exec-reference",
            "patch_filename": None,
            "scope": "synthetic exec-only mock state",
        }
        self._write_mock_state()

        self.trace_path = self.base / "trace.jsonl"
        self._write_trace(include_patch=False)

        self.proof_path = self.candidate / "remote-tool-proof.txt"
        self.proof_path.write_text("REMOTE_EXEC_OK\n", encoding="utf-8")
        self.patch_proof_path = self.candidate / "remote-patch-proof.txt"

        self.inspect_path = self.base / "inspect.json"
        env_tokens = [
            f"HOME={self.home.resolve()}",
            f"CODEX_HOME={self.codex_home.resolve()}",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            f"TMPDIR={self.temp_dir.resolve()}",
        ]
        mounts = [
            {"Type": "bind", "Destination": str(self.candidate.resolve()), "RW": True},
            {"Type": "bind", "Destination": str(self.home.resolve()), "RW": True},
            {"Type": "bind", "Destination": str(self.codex_home.resolve()), "RW": True},
            {"Type": "bind", "Destination": str(self.temp_dir.resolve()), "RW": True},
            {"Type": "tmpfs", "Destination": "/tmp", "RW": True},
        ]
        self.inspect_path.write_text(json.dumps([{
            "Id": "container-1",
            "Image": self.profile["image_id"],
            "Config": {
                "User": self.profile["run_as"],
                "Cmd": ["env", "-i", *env_tokens, "codex", "exec-server", "--listen", "stdio"],
            },
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "Privileged": False,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges"],
                "Tmpfs": {"/tmp": "rw,nosuid,nodev"},
                "Devices": [],
                "DeviceRequests": [],
            },
            "Mounts": mounts,
        }]) + "\n", encoding="utf-8")

        self.control_version = self.base / "control-version.txt"
        self.tool_version = self.base / "tool-version.txt"
        self.control_version.write_text("codex-cli synthetic\n", encoding="utf-8")
        self.tool_version.write_text("codex-cli synthetic\n", encoding="utf-8")
        self.mock_program = ROOT / "tooling" / "feynman_mock_responses_server.py"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_mock_state(self):
        self.mock_state_path.write_text(json.dumps(self.mock_state) + "\n", encoding="utf-8")

    def _write_trace(self, *, include_patch: bool):
        command = "python3 -c 'print(1)' # target " + self.host + ":" + str(self.port)
        markers = []
        if include_patch:
            markers.append("REMOTE_PATCH_OK")
        markers.extend(["AUTH_ENV_CLEAN", "NETWORK_BLOCKED", "REMOTE_EXEC_OK"])
        events = [
            {"type": "thread.started", "thread_id": "thread-reference"},
            {"type": "item.completed", "item": {
                "id": "cmd-1",
                "type": "command_execution",
                "command": command,
                "aggregated_output": "\n".join(markers) + "\n",
                "exit_code": 0,
                "status": "completed",
            }},
            {"type": "item.completed", "item": {
                "id": "msg-1", "type": "agent_message", "text": "REMOTE_EXEC_REFERENCE_OK"
            }},
        ]
        self.trace_path.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
        )

    def _assemble(self, *, patch: bool = False):
        return assemble(
            boundary_profile_path=self.profile_path,
            runner_job_path=self.job_path,
            remote_environment_path=self.environment_path,
            network_reference_path=self.network_path,
            mock_state_path=self.mock_state_path,
            codex_trace_path=self.trace_path,
            docker_inspect_path=self.inspect_path,
            patch_proof_path=self.patch_proof_path if patch else None,
            candidate_proof_path=self.proof_path,
            mock_server_program_path=self.mock_program,
            control_codex_version_path=self.control_version,
            tool_codex_version_path=self.tool_version,
        )

    def _switch_to_patch_scenario(self):
        self.mock_state = {
            "schema_version": 3,
            "scenario": "patch-then-exec",
            "requests": [
                {
                    "index": 1, "body_sha256": "3" * 64,
                    "has_patch_output": False, "patch_output_sha256": None,
                    "has_exec_output": False, "exec_output_sha256": None,
                    "exec_output_contains_patch_marker": False,
                    "exec_output_contains_workspace_marker": False,
                    "exec_output_contains_network_marker": False,
                    "exec_output_contains_auth_env_marker": False,
                },
                {
                    "index": 2, "body_sha256": "4" * 64,
                    "has_patch_output": True, "patch_output_sha256": "5" * 64,
                    "has_exec_output": False, "exec_output_sha256": None,
                    "exec_output_contains_patch_marker": False,
                    "exec_output_contains_workspace_marker": False,
                    "exec_output_contains_network_marker": False,
                    "exec_output_contains_auth_env_marker": False,
                },
                {
                    "index": 3, "body_sha256": "6" * 64,
                    "has_patch_output": True, "patch_output_sha256": "5" * 64,
                    "has_exec_output": True, "exec_output_sha256": "7" * 64,
                    "exec_output_contains_patch_marker": True,
                    "exec_output_contains_workspace_marker": True,
                    "exec_output_contains_network_marker": True,
                    "exec_output_contains_auth_env_marker": True,
                },
            ],
            "validation_error": None,
            "final_text": "REMOTE_EXEC_REFERENCE_OK",
            "patch_call_id": "call-remote-patch-reference",
            "exec_call_id": "call-remote-exec-reference",
            "patch_filename": "remote-patch-proof.txt",
            "scope": "synthetic patch-then-exec state",
        }
        self._write_mock_state()
        self._write_trace(include_patch=True)
        self.patch_proof_path.write_text("REMOTE_PATCH_OK\n", encoding="utf-8")

    def test_valid_exec_only_evidence_produces_content_bound_reference_result(self):
        result = self._assemble()
        self.assertEqual(result["schema_version"], 3)
        self.assertEqual(result["verdict"], "mock-remote-tool-reference-passed")
        self.assertEqual(result["scenario"], "exec-only")
        self.assertEqual(result["assertions"]["model_requests"], 2)
        self.assertFalse(result["assertions"]["apply_patch_round_trip"])
        self.assertFalse(result["assertions"]["remote_patch_marker"])
        self.assertTrue(result["assertions"]["exec_output_round_trip"])
        self.assertTrue(result["assertions"]["tool_network_blocked"])
        self.assertTrue(result["assertions"]["auth_env_clean"])
        self.assertTrue(result["assertions"]["local_execution_disabled"])
        self.assertIsNone(result["digests"]["patch_proof_sha256"])
        self.assertEqual(result["digests"]["boundary_profile_sha256"], self.profile_sha)

    def test_patch_scenario_remains_supported_with_stronger_evidence(self):
        self._switch_to_patch_scenario()
        result = self._assemble(patch=True)
        self.assertEqual(result["scenario"], "patch-then-exec")
        self.assertEqual(result["assertions"]["model_requests"], 3)
        self.assertTrue(result["assertions"]["apply_patch_round_trip"])
        self.assertTrue(result["assertions"]["remote_patch_marker"])
        self.assertIsNotNone(result["digests"]["patch_proof_sha256"])

    def test_exec_only_rejects_supplied_patch_proof(self):
        self.patch_proof_path.write_text("REMOTE_PATCH_OK\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self._assemble(patch=True)

    def test_tampered_exec_round_trip_is_rejected(self):
        self.mock_state["requests"][1]["exec_output_contains_network_marker"] = False
        self._write_mock_state()
        with self.assertRaises(ValueError):
            self._assemble()

    def test_trace_not_bound_to_network_reference_is_rejected(self):
        text = self.trace_path.read_text(encoding="utf-8").replace(self.host, "127.0.0.9")
        self.trace_path.write_text(text, encoding="utf-8")
        with self.assertRaises(ValueError):
            self._assemble()

    def test_control_tool_codex_version_mismatch_is_rejected(self):
        self.tool_version.write_text("codex-cli other\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self._assemble()

    def test_patch_scenario_requires_patch_proof(self):
        self._switch_to_patch_scenario()
        with self.assertRaises(ValueError):
            self._assemble(patch=False)

    def test_candidate_proof_tampering_is_rejected(self):
        self.proof_path.write_text("LOCAL_FAKE\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self._assemble()


if __name__ == "__main__":
    unittest.main()
