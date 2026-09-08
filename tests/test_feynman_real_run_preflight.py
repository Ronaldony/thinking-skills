from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_condition_workspace import prepare_condition
from tooling.feynman_eval_plan import build_plan, write_plan
from tooling.feynman_real_model_control_config import build_files as build_control_config
from tooling.feynman_real_run_preflight import preflight_files
from tooling.feynman_remote_exec_environment import build_files as build_remote_environment
from tooling.feynman_runner_job import build_job


class RealRunPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.plan_path = self.base / "plan.json"
        self.plan = build_plan(
            ROOT, case_ids=["mechanism-01"], condition_ids=["baseline"], repeats=1, seed=0
        )
        write_plan(self.plan, self.plan_path)
        self.planned = self.plan["jobs"][0]

        self.candidate = self.base / "candidate"
        self.evaluator = self.base / "evaluator"
        prepare_condition(ROOT, "mechanism-01", "baseline", self.candidate, self.evaluator)

        self.home = self.base / "candidate-home"
        self.codex_home = self.base / "tool-codex-home"
        self.temp_dir = self.base / "tool-temp"
        self.source = self.base / "source"
        self.real_home = self.base / "real-home"
        for path in (self.home, self.codex_home, self.temp_dir, self.source, self.real_home):
            path.mkdir(parents=True)

        self.profile_path = self.base / "boundary-profile.json"
        self.profile = {
            "schema_version": 1,
            "backend": "docker",
            "backend_version": "28.0.4",
            "image": "feynman-real-run:local",
            "image_id": "sha256:" + "9" * 64,
            "network_mode": "none",
            "read_only_root": True,
            "no_new_privileges": True,
            "capabilities": [],
            "run_as": "1000:1000",
            "read_write_mounts": [
                str(self.candidate.resolve()),
                str(self.home.resolve()),
                str(self.codex_home.resolve()),
                str(self.temp_dir.resolve()),
            ],
            "read_only_mounts": [],
            "tmpfs_mounts": ["/tmp"],
            "protected_roots_mounted": [],
            "candidate_env_keys": [
                "HOME", "CODEX_HOME", "PATH", "TMPDIR", "PYTHONDONTWRITEBYTECODE"
            ],
            "scope": "synthetic real-run readiness profile",
        }
        self.profile_path.write_text(
            json.dumps(self.profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        self.job_path = self.base / "runner-job.json"
        self.job = build_job(
            plan_path=self.plan_path,
            ordinal=self.planned["ordinal"],
            evaluator_case_path=self.evaluator / "case.json",
            boundary_profile_path=self.profile_path,
            run_id="real-readiness-test",
            model="gpt-real-readiness-test",
            codex_cli="codex-cli synthetic",
            candidate_dir=self.candidate,
            evaluator_dir=self.evaluator,
            source_repo=self.source,
            ephemeral_home=self.home,
            codex_home=self.codex_home,
            temp_dir=self.temp_dir,
            real_home=self.real_home,
            control_plane_credential_env_key="OPENAI_API_KEY",
        )
        self._write_job()

        self.environment_path = self.base / "environments.toml"
        build_remote_environment(self.job_path, self.profile_path, self.environment_path)
        self.control_config_path = self.base / "control-config.toml"
        build_control_config(self.job_path, self.profile_path, self.control_config_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_job(self):
        self.job_path.write_text(json.dumps(self.job, indent=2) + "\n", encoding="utf-8")

    def _preflight(self):
        return preflight_files(
            plan_path=self.plan_path,
            ordinal=self.planned["ordinal"],
            evaluator_case_path=self.evaluator / "case.json",
            runner_job_path=self.job_path,
            boundary_profile_path=self.profile_path,
            remote_environment_path=self.environment_path,
            control_config_path=self.control_config_path,
        )

    def test_valid_files_are_ready_only_for_control_plane_auth(self):
        result = self._preflight()
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["verdict"], "ready-for-control-plane-auth")
        self.assertFalse(result["authentication"]["credential_value_read_by_preflight"])
        self.assertFalse(result["authentication"]["candidate_auth_exposed"])
        self.assertEqual(result["authentication"]["credential_env_key_name"], "OPENAI_API_KEY")
        self.assertEqual(
            result["required_external_input"]["kind"],
            "control-plane-environment-credential",
        )
        self.assertTrue(result["preflight"]["candidate_task_bytes_match"])
        self.assertIn("actual external model-service request/response trace", result["next_required_evidence"])

    def test_preflight_does_not_read_or_serialize_credential_value(self):
        secret = "SYNTHETIC_SECRET_MUST_NOT_APPEAR_7e9f"
        with patch.dict(os.environ, {"OPENAI_API_KEY": secret}, clear=False):
            result = self._preflight()
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn(secret, rendered)
        self.assertEqual(result["authentication"]["credential_env_key_name"], "OPENAI_API_KEY")

    def test_candidate_task_tampering_is_rejected(self):
        (self.candidate / "task.txt").write_text("tampered prompt\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self._preflight()

    def test_runner_job_frozen_ordinal_drift_is_rejected(self):
        self.job["job"]["ordinal"] = self.planned["ordinal"] + 1
        self._write_job()
        with self.assertRaises(ValueError):
            self._preflight()

    def test_runner_job_plan_digest_drift_is_rejected(self):
        self.job["digests"]["eval_plan_sha256"] = "a" * 64
        self._write_job()
        with self.assertRaises(ValueError):
            self._preflight()

    def test_remote_environment_drift_is_rejected(self):
        text = self.environment_path.read_text(encoding="utf-8")
        self.environment_path.write_text(text.replace("include_local = false", "include_local = true"), encoding="utf-8")
        with self.assertRaises(ValueError):
            self._preflight()

    def test_control_config_drift_is_rejected(self):
        text = self.control_config_path.read_text(encoding="utf-8")
        self.control_config_path.write_text(text.replace("approval_policy = \"never\"", "approval_policy = \"on-request\""), encoding="utf-8")
        with self.assertRaises(ValueError):
            self._preflight()

    def test_evaluator_condition_drift_is_rejected(self):
        case_path = self.evaluator / "case.json"
        case = json.loads(case_path.read_text(encoding="utf-8"))
        case["condition_id"] = "generic"
        case_path.write_text(json.dumps(case), encoding="utf-8")
        with self.assertRaises(ValueError):
            self._preflight()

    def test_readiness_schema_has_no_credential_value_field(self):
        schema_path = ROOT / "evals" / "feynman-thinking" / "real-run-readiness.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["verdict"]["const"], "ready-for-control-plane-auth")
        raw = schema_path.read_text(encoding="utf-8")
        self.assertNotIn('"credential_value"', raw)
        self.assertFalse(schema["properties"]["authentication"]["properties"]["credential_value_read_by_preflight"]["const"])


if __name__ == "__main__":
    unittest.main()
