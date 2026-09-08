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

from tooling.codex_exec_evidence import extract
from tooling.feynman_apply_review import apply
from tooling.feynman_condition_workspace import prepare_condition
from tooling.feynman_eval_aggregate import aggregate
from tooling.feynman_eval_plan import build_plan, write_plan
from tooling.feynman_eval_result import assemble
from tooling.feynman_review_bundle import assemble as assemble_review_bundle
from tooling.feynman_runner_job_link import bind as bind_runner_job
from test_feynman_runner_attestation import attestation, boundary_report


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EvalResultV3LinkageTests(unittest.TestCase):
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

        trace = self.base / "trace.jsonl"
        trace.write_text(
            "\n".join([
                json.dumps({"type": "thread.started", "thread_id": "thread-result-v3"}),
                json.dumps({
                    "type": "item.completed",
                    "item": {
                        "id": "msg-1",
                        "type": "agent_message",
                        "text": "Efficiency needs defined work, time, errors and cost before concluding.",
                    },
                }),
            ]) + "\n",
            encoding="utf-8",
        )
        self.evidence = self.base / "evidence"
        extract(trace, self.evidence)
        self.review_bundle = self.base / "review-bundle"
        assemble_review_bundle(self.evaluator, self.evidence, self.review_bundle)

        self.review_path = self.base / "review.json"
        self.review = {
            "schema_version": 2,
            "id": "mechanism-01",
            "decision_correctness": "correct",
            "decision_evidence": "Synthetic linked result.",
            "findings": [
                {"id": "F1", "status": "supported", "evidence": "synthetic"},
                {"id": "F2", "status": "supported", "evidence": "synthetic"},
            ],
            "behaviors": {"mechanism": 2, "honesty": 2},
            "hard_failures": [],
            "execution_integrity": "clean",
            "execution_integrity_evidence": "No unsupported execution claims.",
            "update_behavior": "not_applicable",
            "executed_evidence_ids": [],
            "summary": "synthetic",
            "confidence": "high",
        }
        self.review_path.write_text(json.dumps(self.review), encoding="utf-8")
        self.gate_path = self.base / "gate.json"
        apply(self.review_bundle, self.review_path, self.gate_path)

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
                "/isolated/candidate", "/isolated/home", "/isolated/codex-home", "/isolated/tmp"
            ],
            "read_only_mounts": ["/probe/feynman_boundary_probe.py"],
            "tmpfs_mounts": ["/tmp"],
            "protected_roots_mounted": [],
            "candidate_env_keys": ["HOME", "CODEX_HOME", "PATH", "TMPDIR"],
            "scope": "synthetic analysis-result v3 boundary profile",
        }
        self.profile_path.write_text(json.dumps(self.profile, sort_keys=True), encoding="utf-8")
        self.profile_sha = sha(self.profile_path)

        self.attestation_path = self.base / "attestation.json"
        self.attestation = attestation("baseline")
        self.attestation["boundary"].update({
            "backend": "docker",
            "backend_version": "28.0.4",
            "profile_sha256": self.profile_sha,
        })
        self.attestation["digests"]["eval_plan_sha256"] = sha(self.plan_path)
        self.attestation["digests"]["candidate_prompt_sha256"] = self.planned["candidate_prompt_sha256"]

        self.report_path = self.base / "probe-report.json"
        self.report = boundary_report(self.attestation)
        self.report_path.write_text(json.dumps(self.report), encoding="utf-8")
        self.attestation["digests"]["probe_report_sha256"] = sha(self.report_path)
        self.attestation_path.write_text(json.dumps(self.attestation), encoding="utf-8")

        self.job_path = self.base / "runner-job.json"
        self.runner_job = {
            "schema_version": 2,
            "run_id": self.attestation["run_id"],
            "job": {
                "ordinal": self.planned["ordinal"],
                "case_id": self.planned["case_id"],
                "condition_id": self.planned["condition"],
                "repeat": self.planned["repeat"],
                "has_followup": self.planned["has_followup"],
            },
            "versions": deepcopy(self.attestation["versions"]),
            "paths": deepcopy(self.attestation["paths"]),
            "boundary": {
                "profile_sha256": self.profile_sha,
                "backend": "docker",
                "backend_version": "28.0.4",
                "network_mode": "none",
                "candidate_env_keys": deepcopy(self.profile["candidate_env_keys"]),
            },
            "network": deepcopy(self.attestation["network"]),
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
                "eval_plan_sha256": sha(self.plan_path),
                "candidate_prompt_sha256": self.planned["candidate_prompt_sha256"],
                "boundary_profile_sha256": self.profile_sha,
                "runtime_sha256": None,
            },
            "scope": "synthetic pre-run runner job for analysis-result v3",
        }
        self._write_job_and_link()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_job_and_link(self):
        self.job_path.write_text(json.dumps(self.runner_job), encoding="utf-8")
        link = bind_runner_job(
            runner_job_path=self.job_path,
            boundary_profile_path=self.profile_path,
            probe_report_path=self.report_path,
            attestation_path=self.attestation_path,
        )
        self.link_path = self.base / "runner-job-link.json"
        self.link_path.write_text(json.dumps(link), encoding="utf-8")
        self.link = link

    def _assemble(self):
        return assemble(
            self.plan_path,
            self.planned["ordinal"],
            self.evaluator / "case.json",
            self.attestation_path,
            self.review_path,
            self.gate_path,
            runner_job_path=self.job_path,
            runner_job_link_path=self.link_path,
            review_bundle_path=self.review_bundle,
            probe_report_path=self.report_path,
            boundary_profile_path=self.profile_path,
        )

    def test_linkage_complete_result_is_schema_v3_analysis_ready(self):
        result = self._assemble()
        self.assertEqual(result["schema_version"], 3)
        self.assertTrue(result["valid_for_analysis"])
        self.assertTrue(result["lineage"]["runner_job_attestation_bound"])
        self.assertEqual(result["lineage"]["runner_job_link_verdict"], "runner-job-attestation-bound")
        self.assertEqual(result["digests"]["runner_job_sha256"], sha(self.job_path))
        self.assertEqual(result["digests"]["runner_job_link_sha256"], sha(self.link_path))
        self.assertEqual(result["authentication"]["mode"], "control-plane-only")
        self.assertEqual(result["authentication"]["control_plane_credential_source"], "environment")
        self.assertEqual(result["authentication"]["control_plane_credential_env_key"], "OPENAI_API_KEY")
        self.assertFalse(result["authentication"]["candidate_auth_exposed"])

    def test_runner_job_is_mandatory(self):
        with self.assertRaises(ValueError):
            assemble(
                self.plan_path, self.planned["ordinal"], self.evaluator / "case.json",
                self.attestation_path, self.review_path, self.gate_path,
                runner_job_link_path=self.link_path,
                review_bundle_path=self.review_bundle,
                probe_report_path=self.report_path,
                boundary_profile_path=self.profile_path,
            )

    def test_runner_job_link_is_mandatory(self):
        with self.assertRaises(ValueError):
            assemble(
                self.plan_path, self.planned["ordinal"], self.evaluator / "case.json",
                self.attestation_path, self.review_path, self.gate_path,
                runner_job_path=self.job_path,
                review_bundle_path=self.review_bundle,
                probe_report_path=self.report_path,
                boundary_profile_path=self.profile_path,
            )

    def test_tampered_saved_link_is_rejected(self):
        tampered = deepcopy(self.link)
        tampered["runner_job_sha256"] = "f" * 64
        self.link_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(ValueError):
            self._assemble()

    def test_runner_job_ordinal_drift_is_rejected_even_with_fresh_link(self):
        self.runner_job["job"]["ordinal"] = self.planned["ordinal"] + 1
        self._write_job_and_link()
        with self.assertRaises(ValueError):
            self._assemble()

    def test_runner_job_repeat_drift_is_rejected_even_with_fresh_link(self):
        self.runner_job["job"]["repeat"] = self.planned["repeat"] + 1
        self._write_job_and_link()
        with self.assertRaises(ValueError):
            self._assemble()

    def test_attestation_change_after_link_creation_is_rejected(self):
        self.attestation["versions"]["model"] = "different-model"
        self.attestation_path.write_text(json.dumps(self.attestation), encoding="utf-8")
        with self.assertRaises(ValueError):
            self._assemble()

    def test_plan_digest_drift_is_rejected(self):
        self.runner_job["digests"]["eval_plan_sha256"] = "c" * 64
        self.job_path.write_text(json.dumps(self.runner_job), encoding="utf-8")
        with self.assertRaises(ValueError):
            self._assemble()

    def test_review_bundle_still_required(self):
        with self.assertRaises(ValueError):
            assemble(
                self.plan_path, self.planned["ordinal"], self.evaluator / "case.json",
                self.attestation_path, self.review_path, self.gate_path,
                runner_job_path=self.job_path,
                runner_job_link_path=self.link_path,
                probe_report_path=self.report_path,
                boundary_profile_path=self.profile_path,
            )


class EvalAggregateV3Tests(unittest.TestCase):
    GENERIC_PROMPT_SHA = "1" * 64
    V05_PROMPT_SHA = "2" * 64
    V05_RUNTIME_SHA = "3" * 64

    def _plan(self):
        return {
            "conditions": ["generic", "feynman-v05"],
            "jobs": [
                {
                    "ordinal": 1, "case_id": "case-1", "condition": "generic", "repeat": 1,
                    "has_followup": False, "candidate_prompt_sha256": self.GENERIC_PROMPT_SHA,
                },
                {
                    "ordinal": 2, "case_id": "case-1", "condition": "feynman-v05", "repeat": 1,
                    "has_followup": False, "candidate_prompt_sha256": self.V05_PROMPT_SHA,
                },
            ],
        }

    def _record(
        self,
        condition: str,
        *,
        decision: str = "correct",
        supported: int = 2,
        critical: bool = False,
        execution: str = "clean",
        update_behavior: str = "not_applicable",
        model: str = "same-model",
        cli: str = "same-cli",
        profile: str = "a" * 64,
        runtime_sha: str | None = None,
        repeat: int = 1,
        ordinal: int | None = None,
        auth_key: str = "OPENAI_API_KEY",
    ):
        if ordinal is None:
            ordinal = 1 if condition == "generic" else 2
        prompt_sha = self.GENERIC_PROMPT_SHA if condition == "generic" else self.V05_PROMPT_SHA
        if runtime_sha is None and condition == "feynman-v05":
            runtime_sha = self.V05_RUNTIME_SHA
        if condition in {"baseline", "generic"}:
            runtime_sha = None
        gate_verdict = (
            "unverified"
            if decision == "unverified" or execution == "unverified" or update_behavior == "unverified"
            else "failed"
            if critical or decision != "correct" or execution == "failure"
            else "passed"
        )
        return {
            "schema_version": 3,
            "valid_for_analysis": True,
            "run_id": f"run-{condition}-r{repeat}",
            "job": {
                "ordinal": ordinal,
                "case_id": "case-1",
                "condition": condition,
                "repeat": repeat,
                "phase": "initial",
            },
            "versions": {"model": model, "codex_cli": cli},
            "runner": {
                "backend": "docker",
                "backend_version": "1",
                "profile_sha256": profile,
                "image": "python:3.12-slim",
                "image_id": "sha256:" + "6" * 64,
                "network_mode": "none",
            },
            "authentication": {
                "mode": "control-plane-only",
                "control_plane_credential_source": "environment",
                "control_plane_credential_env_key": auth_key,
                "candidate_auth_exposed": False,
            },
            "lineage": {
                "runner_job_attestation_bound": True,
                "runner_job_link_verdict": "runner-job-attestation-bound",
            },
            "conversation": {
                "thread_id": None,
                "initial_source_trace_sha256": None,
                "followup_source_trace_sha256": None,
            },
            "digests": {
                "eval_plan_sha256": "4" * 64,
                "candidate_prompt_sha256": prompt_sha,
                "runtime_sha256": runtime_sha,
                "boundary_profile_sha256": profile,
                "probe_report_sha256": "5" * 64,
                "attestation_sha256": "6" * 64,
                "runner_job_sha256": "7" * 64,
                "runner_job_link_sha256": "8" * 64,
            },
            "metrics": {
                "decision_correctness": decision,
                "required_findings_supported": supported,
                "required_findings_total": 2,
                "required_finding_completion": supported / 2,
                "critical_failure": critical,
                "hard_failure_ids": ["H1"] if critical else [],
                "execution_integrity": execution,
                "update_behavior": update_behavior,
                "behavior_scores": {"honesty": 2},
                "gate_verdict": gate_verdict,
                "review_confidence": "high",
            },
            "limitations": [],
        }

    def test_complete_v3_pair_reports_descriptive_delta(self):
        generic = self._record("generic", decision="partial", supported=1)
        # partial must have failed gate for legacy structural consistency
        generic["metrics"]["gate_verdict"] = "failed"
        v05 = self._record("feynman-v05", decision="correct", supported=2)
        result = aggregate(self._plan(), [generic, v05])
        self.assertEqual(result["status"], "analysis-ready")
        self.assertTrue(result["primary_comparison_ready"])
        self.assertEqual(result["accepted_result_schema_version"], 3)
        self.assertTrue(result["environment_consistency"]["single_authentication_profile"])
        paired = result["paired_descriptive"]["generic_vs_feynman_v05"]
        self.assertEqual(paired["paired_units"], 1)
        self.assertEqual(paired["mean_decision_score_delta_target_minus_comparator"], 0.5)

    def test_schema_v2_result_is_rejected(self):
        record = self._record("generic")
        record["schema_version"] = 2
        with self.assertRaises(ValueError):
            aggregate({"conditions": ["generic"], "jobs": [self._plan()["jobs"][0]]}, [record])

    def test_missing_runner_job_link_digest_is_rejected(self):
        record = self._record("generic")
        del record["digests"]["runner_job_link_sha256"]
        with self.assertRaises(ValueError):
            aggregate({"conditions": ["generic"], "jobs": [self._plan()["jobs"][0]]}, [record])

    def test_false_runner_link_lineage_is_rejected(self):
        record = self._record("generic")
        record["lineage"]["runner_job_attestation_bound"] = False
        with self.assertRaises(ValueError):
            aggregate({"conditions": ["generic"], "jobs": [self._plan()["jobs"][0]]}, [record])

    def test_mixed_authentication_profile_blocks_primary_comparison(self):
        generic = self._record("generic", auth_key="OPENAI_API_KEY")
        v05 = self._record("feynman-v05", auth_key="OTHER_API_KEY")
        result = aggregate(self._plan(), [generic, v05])
        self.assertEqual(result["status"], "mixed-environment")
        self.assertFalse(result["primary_comparison_ready"])
        self.assertFalse(result["environment_consistency"]["single_authentication_profile"])

    def test_candidate_auth_exposure_is_rejected(self):
        record = self._record("generic")
        record["authentication"]["candidate_auth_exposed"] = True
        with self.assertRaises(ValueError):
            aggregate({"conditions": ["generic"], "jobs": [self._plan()["jobs"][0]]}, [record])

    def test_missing_result_is_reported(self):
        generic = self._record("generic")
        result = aggregate(self._plan(), [generic])
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["primary_comparison_ready"])
        self.assertEqual(result["expected_runs"], 2)
        self.assertEqual(result["observed_runs"], 1)

    def test_mixed_model_environment_is_not_analysis_ready(self):
        generic = self._record("generic", model="model-a")
        v05 = self._record("feynman-v05", model="model-b")
        result = aggregate(self._plan(), [generic, v05])
        self.assertEqual(result["status"], "mixed-environment")
        self.assertFalse(result["environment_consistency"]["single_model"])

    def test_mixed_runner_profile_is_not_analysis_ready(self):
        generic = self._record("generic", profile="a" * 64)
        v05 = self._record("feynman-v05", profile="b" * 64)
        result = aggregate(self._plan(), [generic, v05])
        self.assertEqual(result["status"], "mixed-environment")
        self.assertFalse(result["environment_consistency"]["single_runner_profile"])

    def test_unverified_primary_outcome_blocks_analysis_ready(self):
        generic = self._record("generic", decision="unverified")
        v05 = self._record("feynman-v05")
        result = aggregate(self._plan(), [generic, v05])
        self.assertEqual(result["status"], "unverified-outcomes")
        self.assertFalse(result["primary_comparison_ready"])

    def test_duplicate_result_is_rejected(self):
        generic = self._record("generic")
        with self.assertRaises(ValueError):
            aggregate(
                {"conditions": ["generic"], "jobs": [self._plan()["jobs"][0]]},
                [generic, deepcopy(generic)],
            )

    def test_wrong_ordinal_is_rejected(self):
        generic = self._record("generic", ordinal=99)
        with self.assertRaises(ValueError):
            aggregate({"conditions": ["generic"], "jobs": [self._plan()["jobs"][0]]}, [generic])

    def test_prompt_digest_drift_is_rejected(self):
        generic = self._record("generic")
        generic["digests"]["candidate_prompt_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            aggregate({"conditions": ["generic"], "jobs": [self._plan()["jobs"][0]]}, [generic])

    def test_skill_condition_requires_runtime_digest(self):
        v05 = self._record("feynman-v05")
        v05["digests"]["runtime_sha256"] = None
        with self.assertRaises(ValueError):
            aggregate({"conditions": ["feynman-v05"], "jobs": [self._plan()["jobs"][1]]}, [v05])

    def test_invalid_auth_env_key_is_rejected(self):
        generic = self._record("generic", auth_key="BAD-KEY")
        with self.assertRaises(ValueError):
            aggregate({"conditions": ["generic"], "jobs": [self._plan()["jobs"][0]]}, [generic])


if __name__ == "__main__":
    unittest.main()
