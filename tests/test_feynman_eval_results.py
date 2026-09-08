from __future__ import annotations

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
from test_feynman_runner_attestation import attestation


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EvalResultLinkageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.plan_path = self.base / "plan.json"
        self.plan = build_plan(
            ROOT, case_ids=["mechanism-01"], condition_ids=["baseline"], repeats=1, seed=0
        )
        write_plan(self.plan, self.plan_path)
        self.job = self.plan["jobs"][0]
        self.candidate = self.base / "candidate"
        self.evaluator = self.base / "evaluator"
        prepare_condition(ROOT, "mechanism-01", "baseline", self.candidate, self.evaluator)

        trace = self.base / "trace.jsonl"
        events = [
            {"type": "thread.started", "thread_id": "thread-result"},
            {"type": "item.completed", "item": {
                "id": "msg-1", "type": "agent_message",
                "text": "Efficiency needs defined work, time, errors and cost before concluding."}},
        ]
        trace.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
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
        self.gate = json.loads(self.gate_path.read_text(encoding="utf-8"))

        self.attestation_path = self.base / "attestation.json"
        self.attestation = attestation("baseline")
        self.attestation["digests"]["eval_plan_sha256"] = sha(self.plan_path)
        self.attestation["digests"]["candidate_prompt_sha256"] = self.job["candidate_prompt_sha256"]
        self.attestation_path.write_text(json.dumps(self.attestation), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _assemble(self):
        return assemble(
            self.plan_path,
            self.job["ordinal"],
            self.evaluator / "case.json",
            self.attestation_path,
            self.review_path,
            self.gate_path,
            review_bundle_path=self.review_bundle,
        )

    def test_linked_baseline_result_is_analysis_ready(self):
        result = self._assemble()
        self.assertTrue(result["valid_for_analysis"])
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["metrics"]["decision_correctness"], "correct")
        self.assertEqual(result["metrics"]["required_finding_completion"], 1.0)
        self.assertEqual(result["job"]["condition"], "baseline")
        self.assertEqual(result["digests"]["candidate_final_sha256"], self.gate["candidate_final_sha256"])

    def test_attestation_bound_to_different_plan_is_rejected(self):
        self.attestation["digests"]["eval_plan_sha256"] = "c" * 64
        self.attestation_path.write_text(json.dumps(self.attestation), encoding="utf-8")
        with self.assertRaises(ValueError):
            self._assemble()

    def test_gate_bound_to_different_semantic_review_is_rejected(self):
        self.gate["semantic_review_sha256"] = "d" * 64
        self.gate_path.write_text(json.dumps(self.gate), encoding="utf-8")
        with self.assertRaises(ValueError):
            self._assemble()

    def test_gate_bound_to_different_review_manifest_is_rejected(self):
        self.gate["review_manifest_sha256"] = "e" * 64
        self.gate_path.write_text(json.dumps(self.gate), encoding="utf-8")
        with self.assertRaises(ValueError):
            self._assemble()

    def test_result_requires_review_bundle(self):
        with self.assertRaises(ValueError):
            assemble(
                self.plan_path,
                self.job["ordinal"],
                self.evaluator / "case.json",
                self.attestation_path,
                self.review_path,
                self.gate_path,
            )


class EvalAggregateTests(unittest.TestCase):
    GENERIC_PROMPT_SHA = "1" * 64
    V05_PROMPT_SHA = "2" * 64
    V05_RUNTIME_SHA = "3" * 64

    def _plan(self):
        return {
            "conditions": ["generic", "feynman-v05"],
            "jobs": [
                {
                    "ordinal": 1,
                    "case_id": "case-1",
                    "condition": "generic",
                    "repeat": 1,
                    "has_followup": False,
                    "candidate_prompt_sha256": self.GENERIC_PROMPT_SHA,
                },
                {
                    "ordinal": 2,
                    "case_id": "case-1",
                    "condition": "feynman-v05",
                    "repeat": 1,
                    "has_followup": False,
                    "candidate_prompt_sha256": self.V05_PROMPT_SHA,
                },
            ],
        }

    def _record(self, condition: str, *, decision: str, supported: int,
                critical: bool = False, execution: str = "clean",
                update_behavior: str = "not_applicable", model: str = "same-model",
                cli: str = "same-cli", profile: str = "a" * 64,
                runtime_sha: str | None = None, repeat: int = 1,
                ordinal: int | None = None):
        if ordinal is None:
            ordinal = 1 if condition == "generic" else 2
        prompt_sha = self.GENERIC_PROMPT_SHA if condition == "generic" else self.V05_PROMPT_SHA
        if runtime_sha is None and condition == "feynman-v05":
            runtime_sha = self.V05_RUNTIME_SHA
        if condition in {"baseline", "generic"}:
            runtime_sha = None
        return {
            "schema_version": 2,
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
            "runner": {"backend": "container", "backend_version": "1", "profile_sha256": profile},
            "conversation": {"thread_id": None, "initial_source_trace_sha256": None, "followup_source_trace_sha256": None},
            "digests": {
                "candidate_prompt_sha256": prompt_sha,
                "runtime_sha256": runtime_sha,
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
                "gate_verdict": (
                    "unverified" if decision == "unverified" or execution == "unverified"
                    or update_behavior == "unverified"
                    else "failed" if critical or decision != "correct" or execution == "failure"
                    else "passed"
                ),
                "review_confidence": "high",
            },
            "limitations": [],
        }

    def test_complete_pair_reports_descriptive_delta(self):
        generic = self._record("generic", decision="partial", supported=1)
        v05 = self._record("feynman-v05", decision="correct", supported=2)
        result = aggregate(self._plan(), [generic, v05])
        self.assertEqual(result["status"], "analysis-ready")
        self.assertTrue(result["primary_comparison_ready"])
        self.assertEqual(result["conditions"]["feynman-v05"]["decision_correct_rate_over_all_runs"], 1.0)
        paired = result["paired_descriptive"]["generic_vs_feynman_v05"]
        self.assertEqual(paired["paired_units"], 1)
        self.assertEqual(paired["mean_decision_score_delta_target_minus_comparator"], 0.5)
        self.assertEqual(paired["mean_required_finding_completion_delta"], 0.5)

    def test_missing_result_is_reported_not_silently_dropped(self):
        generic = self._record("generic", decision="correct", supported=2)
        result = aggregate(self._plan(), [generic])
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["primary_comparison_ready"])
        self.assertEqual(result["expected_runs"], 2)
        self.assertEqual(result["observed_runs"], 1)
        self.assertEqual(len(result["missing_jobs"]), 1)

    def test_mixed_model_environment_is_not_analysis_ready(self):
        generic = self._record("generic", decision="correct", supported=2, model="model-a")
        v05 = self._record("feynman-v05", decision="correct", supported=2, model="model-b")
        result = aggregate(self._plan(), [generic, v05])
        self.assertEqual(result["status"], "mixed-environment")
        self.assertFalse(result["primary_comparison_ready"])
        self.assertFalse(result["environment_consistency"]["single_model"])

    def test_mixed_runner_profile_is_not_analysis_ready(self):
        generic = self._record("generic", decision="correct", supported=2, profile="a" * 64)
        v05 = self._record("feynman-v05", decision="correct", supported=2, profile="b" * 64)
        result = aggregate(self._plan(), [generic, v05])
        self.assertEqual(result["status"], "mixed-environment")
        self.assertFalse(result["environment_consistency"]["single_runner_profile"])

    def test_mixed_runtime_within_condition_is_not_analysis_ready(self):
        plan = {
            "conditions": ["feynman-v05"],
            "jobs": [
                {
                    "ordinal": 1, "case_id": "case-1", "condition": "feynman-v05",
                    "repeat": 1, "has_followup": False,
                    "candidate_prompt_sha256": self.V05_PROMPT_SHA,
                },
                {
                    "ordinal": 2, "case_id": "case-1", "condition": "feynman-v05",
                    "repeat": 2, "has_followup": False,
                    "candidate_prompt_sha256": self.V05_PROMPT_SHA,
                },
            ],
        }
        first = self._record(
            "feynman-v05", decision="correct", supported=2,
            runtime_sha="3" * 64, repeat=1, ordinal=1,
        )
        second = self._record(
            "feynman-v05", decision="correct", supported=2,
            runtime_sha="4" * 64, repeat=2, ordinal=2,
        )
        result = aggregate(plan, [first, second])
        self.assertEqual(result["status"], "mixed-environment")
        self.assertFalse(result["environment_consistency"]["single_runtime_per_condition"])

    def test_unverified_primary_outcome_is_not_analysis_ready(self):
        generic = self._record("generic", decision="unverified", supported=2)
        v05 = self._record("feynman-v05", decision="correct", supported=2)
        result = aggregate(self._plan(), [generic, v05])
        self.assertEqual(result["status"], "unverified-outcomes")
        self.assertFalse(result["primary_comparison_ready"])
        self.assertEqual(len(result["unverified_primary_jobs"]), 1)

    def test_wrong_prompt_digest_is_rejected(self):
        generic = self._record("generic", decision="correct", supported=2)
        generic["digests"]["candidate_prompt_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            aggregate(self._plan(), [generic])

    def test_wrong_ordinal_is_rejected(self):
        v05 = self._record("feynman-v05", decision="correct", supported=2)
        v05["job"]["ordinal"] = 999
        with self.assertRaises(ValueError):
            aggregate(self._plan(), [v05])

    def test_missing_runtime_digest_for_skill_condition_is_rejected(self):
        v05 = self._record("feynman-v05", decision="correct", supported=2)
        v05["digests"]["runtime_sha256"] = None
        with self.assertRaises(ValueError):
            aggregate(self._plan(), [v05])

    def test_duplicate_result_key_is_rejected(self):
        generic = self._record("generic", decision="correct", supported=2)
        with self.assertRaises(ValueError):
            aggregate(self._plan(), [generic, generic])

    def test_unplanned_result_is_rejected(self):
        baseline = self._record("baseline", decision="correct", supported=2)
        with self.assertRaises(ValueError):
            aggregate(self._plan(), [baseline])


if __name__ == "__main__":
    unittest.main()
