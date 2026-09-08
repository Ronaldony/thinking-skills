from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_condition_workspace import prepare_condition
from tooling.feynman_eval_plan import build_plan, write_plan
from tooling.feynman_runner_job import build_job


class RunnerJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.profile_path = self.base / "profile.json"
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
                "/isolated/candidate", "/isolated/home", "/isolated/codex-home", "/isolated/tmp"
            ],
            "read_only_mounts": ["/probe/feynman_boundary_probe.py"],
            "tmpfs_mounts": ["/tmp"],
            "protected_roots_mounted": [],
            "candidate_env_keys": ["HOME", "CODEX_HOME", "PATH", "TMPDIR"],
            "scope": "synthetic model-runner profile",
        }
        self._write_profile()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_profile(self):
        self.profile_path.write_text(json.dumps(self.profile, sort_keys=True), encoding="utf-8")

    def _prepare(self, condition: str):
        plan = build_plan(
            ROOT,
            case_ids=["mechanism-01"],
            condition_ids=[condition],
            repeats=1,
            seed=0,
        )
        plan_path = self.base / f"plan-{condition}.json"
        write_plan(plan, plan_path)
        candidate = self.base / f"candidate-{condition}"
        evaluator = self.base / f"evaluator-{condition}"
        prepare_condition(ROOT, "mechanism-01", condition, candidate, evaluator)
        return plan, plan_path, candidate, evaluator

    def _build(self, condition: str):
        plan, plan_path, candidate, evaluator = self._prepare(condition)
        result = build_job(
            plan_path=plan_path,
            ordinal=plan["jobs"][0]["ordinal"],
            evaluator_case_path=evaluator / "case.json",
            boundary_profile_path=self.profile_path,
            run_id=f"run-{condition}",
            model="test-model",
            codex_cli="codex test",
            candidate_dir=candidate,
            evaluator_dir=evaluator,
            source_repo=ROOT,
            ephemeral_home=self.base / f"home-{condition}",
            codex_home=self.base / f"codex-{condition}",
            temp_dir=self.base / f"temp-{condition}",
            real_home=self.base / "real-user-home",
        )
        return result, plan, plan_path, candidate, evaluator

    def test_baseline_job_contains_no_skill_or_credentials(self):
        result, _, _, _, _ = self._build("baseline")
        self.assertEqual(result["job"]["condition_id"], "baseline")
        self.assertEqual(result["skills"]["expected_candidate_skills"], [])
        self.assertIsNone(result["skills"]["runtime_sha256"])
        self.assertEqual(result["network"]["tool_network"], "blocked")
        self.assertEqual(result["authentication"], {
            "mode": "external-broker",
            "candidate_tool_auth_env_keys": [],
            "candidate_readable_credential_files": [],
            "credential_command_arguments": [],
        })

    def test_v05_job_binds_runtime_digest(self):
        result, _, _, _, _ = self._build("feynman-v05")
        self.assertEqual(result["skills"]["expected_candidate_skills"], ["feynman-thinking"])
        self.assertEqual(
            result["skills"]["runtime_sha256"],
            result["digests"]["runtime_sha256"],
        )
        self.assertIsInstance(result["skills"]["runtime_sha256"], str)
        self.assertEqual(len(result["skills"]["runtime_sha256"]), 64)

    def test_closed_network_rejects_allowed_destinations(self):
        plan, plan_path, candidate, evaluator = self._prepare("baseline")
        with self.assertRaises(ValueError):
            build_job(
                plan_path=plan_path,
                ordinal=plan["jobs"][0]["ordinal"],
                evaluator_case_path=evaluator / "case.json",
                boundary_profile_path=self.profile_path,
                run_id="run-network-drift",
                model="test-model",
                codex_cli="codex test",
                candidate_dir=candidate,
                evaluator_dir=evaluator,
                source_repo=ROOT,
                ephemeral_home=self.base / "home-network",
                codex_home=self.base / "codex-network",
                temp_dir=self.base / "temp-network",
                real_home=self.base / "real-user-home",
                allowed_tool_destinations=["example.invalid"],
            )

    def test_network_required_case_rejects_none_profile(self):
        plan, plan_path, candidate, evaluator = self._prepare("baseline")
        with self.assertRaises(ValueError):
            build_job(
                plan_path=plan_path,
                ordinal=plan["jobs"][0]["ordinal"],
                evaluator_case_path=evaluator / "case.json",
                boundary_profile_path=self.profile_path,
                run_id="run-needs-network",
                model="test-model",
                codex_cli="codex test",
                candidate_dir=candidate,
                evaluator_dir=evaluator,
                source_repo=ROOT,
                ephemeral_home=self.base / "home-needs-network",
                codex_home=self.base / "codex-needs-network",
                temp_dir=self.base / "temp-needs-network",
                real_home=self.base / "real-user-home",
                case_requires_tool_network=True,
                allowed_tool_destinations=["fixture.example.invalid"],
            )

    def test_protected_and_candidate_paths_cannot_overlap(self):
        plan, plan_path, candidate, evaluator = self._prepare("baseline")
        with self.assertRaises(ValueError):
            build_job(
                plan_path=plan_path,
                ordinal=plan["jobs"][0]["ordinal"],
                evaluator_case_path=evaluator / "case.json",
                boundary_profile_path=self.profile_path,
                run_id="run-overlap",
                model="test-model",
                codex_cli="codex test",
                candidate_dir=candidate,
                evaluator_dir=evaluator,
                source_repo=ROOT,
                ephemeral_home=evaluator / "nested-home",
                codex_home=self.base / "codex-overlap",
                temp_dir=self.base / "temp-overlap",
                real_home=self.base / "real-user-home",
            )

    def test_tampered_evaluator_prompt_digest_is_rejected(self):
        plan, plan_path, candidate, evaluator = self._prepare("baseline")
        case_path = evaluator / "case.json"
        case = json.loads(case_path.read_text(encoding="utf-8"))
        case["candidate_prompt_sha256"] = "f" * 64
        case_path.write_text(json.dumps(case), encoding="utf-8")
        with self.assertRaises(ValueError):
            build_job(
                plan_path=plan_path,
                ordinal=plan["jobs"][0]["ordinal"],
                evaluator_case_path=case_path,
                boundary_profile_path=self.profile_path,
                run_id="run-tampered",
                model="test-model",
                codex_cli="codex test",
                candidate_dir=candidate,
                evaluator_dir=evaluator,
                source_repo=ROOT,
                ephemeral_home=self.base / "home-tampered",
                codex_home=self.base / "codex-tampered",
                temp_dir=self.base / "temp-tampered",
                real_home=self.base / "real-user-home",
            )

    def test_no_skill_condition_rejects_runtime_manifest(self):
        plan, plan_path, candidate, evaluator = self._prepare("baseline")
        case_path = evaluator / "case.json"
        case = json.loads(case_path.read_text(encoding="utf-8"))
        case["runtime_manifest"] = {"runtime_sha256": "a" * 64}
        case_path.write_text(json.dumps(case), encoding="utf-8")
        with self.assertRaises(ValueError):
            build_job(
                plan_path=plan_path,
                ordinal=plan["jobs"][0]["ordinal"],
                evaluator_case_path=case_path,
                boundary_profile_path=self.profile_path,
                run_id="run-runtime-drift",
                model="test-model",
                codex_cli="codex test",
                candidate_dir=candidate,
                evaluator_dir=evaluator,
                source_repo=ROOT,
                ephemeral_home=self.base / "home-runtime",
                codex_home=self.base / "codex-runtime",
                temp_dir=self.base / "temp-runtime",
                real_home=self.base / "real-user-home",
            )


if __name__ == "__main__":
    unittest.main()
