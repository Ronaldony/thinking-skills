from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_path_mapping import native_mounts
from tooling.feynman_docker_reference_inspect import verify_reference
from tooling.feynman_remote_exec_environment import build_document, expected_docker_args
from tooling.feynman_runner_job import build_job
from tooling.feynman_runner_job_validate import validate_job


class NativeWindowsPathMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name).resolve()
        if os.name == "nt":
            self.paths = {
                "candidate_dir": r"C:\feynman\candidate",
                "evaluator_dir": r"C:\feynman\evaluator",
                "source_repo": r"C:\feynman\source",
                "ephemeral_home": r"C:\feynman\home",
                "codex_home": r"C:\feynman\codex",
                "temp_dir": r"C:\feynman\temp",
                "real_home": r"C:\feynman\real-home",
                "control_codex_home": r"C:\feynman\real-home\.codex",
            }
        else:
            self.paths = {
                key: str((base / value).resolve())
                for key, value in {
                    "candidate_dir": "candidate",
                    "evaluator_dir": "evaluator",
                    "source_repo": "source",
                    "ephemeral_home": "home",
                    "codex_home": "codex",
                    "temp_dir": "temp",
                    "real_home": "real-home",
                    "control_codex_home": "real-home/control",
                }.items()
            }
        self.profile = {
            "schema_version": 1,
            "backend": "docker",
            "backend_version": "29.7.2",
            "image": "feynman-codex-remote:local",
            "image_id": "sha256:" + "8" * 64,
            "network_mode": "none",
            "read_only_root": True,
            "no_new_privileges": True,
            "capabilities": [],
            "run_as": "1000:1000",
            "read_write_mounts": ["/run/candidate", "/run/home", "/run/codex", "/run/temp"],
            "read_only_mounts": [],
            "tmpfs_mounts": ["/tmp"],
            "protected_roots_mounted": [],
            "candidate_env_keys": ["HOME", "CODEX_HOME", "PATH", "TMPDIR"],
            "scope": "native Windows path-mapping test profile",
        }
        self.job = {
            "schema_version": 3,
            "run_id": "native-windows/1",
            "job": {"ordinal": 1, "case_id": "mechanism-01", "condition_id": "baseline", "repeat": 1, "has_followup": False},
            "versions": {"model": "mock-model", "codex_cli": "codex-test"},
            "paths": dict(self.paths),
            "boundary": {
                "profile_sha256": "a" * 64,
                "backend": "docker",
                "backend_version": "29.7.2",
                "network_mode": "none",
                "candidate_env_keys": ["HOME", "CODEX_HOME", "PATH", "TMPDIR"],
                "mounts": native_mounts(self.paths),
            },
            "network": {"case_requires_tool_network": False, "tool_network": "blocked", "allowed_tool_destinations": [], "control_plane_separate_from_tool_network": True},
            "authentication": {"mode": "chatgpt-subscription", "control_plane_auth_source": "codex-session", "api_key_auth_allowed": False, "candidate_auth_exposed": False, "candidate_tool_auth_env_keys": [], "candidate_readable_auth_paths": [], "auth_command_arguments": []},
            "skills": {"expected_candidate_skills": [], "runtime_sha256": None},
            "digests": {"eval_plan_sha256": "b" * 64, "candidate_prompt_sha256": "c" * 64, "boundary_profile_sha256": "a" * 64, "runtime_sha256": None},
            "scope": "native Windows path-mapping test job",
        }
        self.profile_sha = hashlib.sha256(json.dumps(self.profile, sort_keys=True).encode()).hexdigest()
        self.job["boundary"]["profile_sha256"] = self.profile_sha
        self.job["digests"]["boundary_profile_sha256"] = self.profile_sha

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_native_mounts_keep_host_and_container_namespaces_separate(self) -> None:
        mounts = native_mounts(self.paths)
        self.assertEqual([mount["destination"] for mount in mounts], ["/run/candidate", "/run/home", "/run/codex", "/run/temp"])
        self.assertEqual([mount["source"] for mount in mounts], [self.paths[key] for key in ("candidate_dir", "ephemeral_home", "codex_home", "temp_dir")])

    def test_runner_validation_accepts_explicit_native_mapping(self) -> None:
        result = validate_job(self.job, self.profile, self.profile_sha)
        self.assertEqual(result["verdict"], "runner-job-valid")
        self.assertEqual(result["mounts"], self.job["boundary"]["mounts"])

    def test_runner_job_builder_emits_native_mapping_for_canonical_profile(self) -> None:
        base = Path(self.temp.name)
        plan_path = base / "plan.json"
        case_path = base / "case.json"
        profile_path = base / "profile.json"
        plan_path.write_text(json.dumps({
            "jobs": [{
                "ordinal": 1,
                "case_id": "mechanism-01",
                "condition": "baseline",
                "repeat": 1,
                "has_followup": False,
                "candidate_prompt_sha256": "c" * 64,
                "required_source_commit": "source-commit",
            }]
        }), encoding="utf-8")
        case_path.write_text(json.dumps({
            "case_id": "mechanism-01",
            "condition_id": "baseline",
            "candidate_prompt_sha256": "c" * 64,
            "required_source_commit": "source-commit",
            "expected_skills": [],
            "runtime_manifest": None,
        }), encoding="utf-8")
        profile_path.write_text(json.dumps(self.profile), encoding="utf-8")
        job = build_job(
            plan_path=plan_path,
            ordinal=1,
            evaluator_case_path=case_path,
            boundary_profile_path=profile_path,
            run_id="native-builder-1",
            model="mock-model",
            codex_cli="codex-test",
            candidate_dir=Path(self.paths["candidate_dir"]),
            evaluator_dir=Path(self.paths["evaluator_dir"]),
            source_repo=Path(self.paths["source_repo"]),
            ephemeral_home=Path(self.paths["ephemeral_home"]),
            codex_home=Path(self.paths["codex_home"]),
            temp_dir=Path(self.paths["temp_dir"]),
            real_home=Path(self.paths["real_home"]),
            control_codex_home=Path(self.paths["control_codex_home"]),
        )
        self.assertEqual(job["boundary"]["mounts"], native_mounts(self.paths))

    def test_docker_args_use_container_workdir_and_env(self) -> None:
        args = expected_docker_args(self.job, self.profile)
        joined = "\n".join(args)
        for key, destination in (("candidate_dir", "/run/candidate"), ("ephemeral_home", "/run/home"), ("codex_home", "/run/codex"), ("temp_dir", "/run/temp")):
            self.assertIn(f"{self.paths[key]}:{destination}:rw", joined)
        self.assertIn("--workdir\n/run/candidate", joined)
        self.assertIn("HOME=/run/home", joined)
        self.assertIn("CODEX_HOME=/run/codex", joined)
        self.assertIn("TMPDIR=/run/temp", joined)
        self.assertNotIn(f"--workdir\n{self.paths['candidate_dir']}", joined)

    def test_document_stays_local_execution_disabled(self) -> None:
        document = build_document(self.job, self.profile, self.profile_sha)
        self.assertFalse(document["include_local"])
        self.assertEqual(document["environments"][0]["program"], "docker")

    def test_docker_inspect_binds_sources_to_the_job_mapping(self) -> None:
        mounts = [
            {"Type": "bind", "Source": mount["source"], "Destination": mount["destination"], "RW": True}
            for mount in self.job["boundary"]["mounts"]
        ]
        mounts.append({"Type": "tmpfs", "Source": "", "Destination": "/tmp", "RW": True})
        payload = [{
            "Id": "container-native",
            "Image": self.profile["image_id"],
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
            "Config": {
                "User": "1000:1000",
                "Cmd": ["env", "-i", "HOME=/run/home", "CODEX_HOME=/run/codex", "PATH=/usr/local/bin:/usr/bin:/bin", "TMPDIR=/run/temp", "codex"],
            },
            "Mounts": mounts,
        }]
        result = verify_reference(self.profile, payload, expected_mounts=self.job["boundary"]["mounts"])
        self.assertEqual(result["verdict"], "docker-inspect-matches-profile")
        payload[0]["Mounts"][0]["Source"] = payload[0]["Mounts"][1]["Source"]
        with self.assertRaises(ValueError):
            verify_reference(self.profile, payload, expected_mounts=self.job["boundary"]["mounts"])


if __name__ == "__main__":
    unittest.main()
