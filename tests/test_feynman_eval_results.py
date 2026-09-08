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

from tooling.feynman_condition_workspace import prepare_condition
from tooling.feynman_eval_aggregate import aggregate
from tooling.feynman_eval_plan import build_plan, write_plan
from tooling.feynman_eval_result import assemble
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
        self.gate = {
            "schema_version": 2,
            "case_id": "mechanism-01",
            "phase": "initial",
            "verdict": "passed",
            "reasons": [],
            "unverified": [],
            "hard_failure_ids": [],
            "semantic_outcomes": {
                "decision_correctness": "correct",
                "execution_integrity": "clean",
                "update_behavior": "not_applicable",
            },
            "semantic_review_sha256": sha(self.review_path),
            "review_input_sha256": "b" * 64,
            "trusted_execution_ids": [],
        }
        self.gate_path.write_text(json.dumps(self.gate), encoding="utf-8")

        self.attestation_path = self.base / "attestation.json"
        self.attestation = attestation("baseline")
        self.attestation["digests"]["eval_plan_sha256"] = sha(self.plan_path)
        self.attestation["digests"]["candidate_prompt_sha256"] = self.job["candidate_prompt_sha256"]
        self.attestation_path.write_text(json.dumps(self.attestation), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_linked_baseline_result_is_analysis_ready(self):
        result = assemble(
            self.plan_path,
            self.job["ordinal"],
            self.evaluator / "case.json",
            self.attestation_path,
            self.review_path,
            self.gate_path,
        )
        self.assertTrue(result["valid_for_analysis"])
        self.assertEqual(result["metrics"]["decision_correctness"], "correct")
        self.assertEqual(result["metrics"]["required_finding_completion"], 1.0)
        self.assertEqual(result["job"]["condition"], "baseline")

    def test_attestation_bound_to_different_plan_is_rejected(self):
        self.attestation["digests"]["eval_plan_sha256"] = "c" * 64
        self.attestation_path.write_text(json.dumps(self.attestation), encoding="utf-8")
        with self.assertRaises(ValueError):
            assemble(
                self.plan_path, self.job["ordinal"], self.evaluator / "case.json",
                self.attestation_path, self.review_path, self.gate_path,
            )

    def test_gate_bound_to_different_semantic_review_is_rejected(self):
        self.gate["semantic_review_sha256"] = "d" * 64
        self.gate_path.write_text(json.dumps(self.gate), encoding="utf-8")
        with self.assertRaises(ValueError):
            assemble(
                self.plan_path, self.job["ordinal"], self.evaluator / "case.json",
                self.attestation_path, self.review_path, self.gate_path,
            )


class EvalAggregateTests(unittest.TestCase):
    def _plan(self):
        return {
            "conditions": ["generic", "feynman-v05"],
            "jobs": [
                {"ordinal": 1, "case_id": "case-1", "condition": "generic", "repeat": 1, "has_followup": False},
                {"ordinal": 2, "case_id": "case-1", "condition": "feynman-v05", "repeat": 1, "has_followup": False},
            ],
        }

    def _record(self, condition: str, *, decision: str, supported: int,
                critical: bool = False, execution: str = "clean"):
        return {
            "schema_version": 1,
            "valid_for_analysis": True,
            "run_id": f"run-{condition}",
            "job": {"ordinal": 1, "case_id": "case-1", "condition": condition, "repeat": 1, "phase": "initial"},
            "versions": {"model": "same-model", "codex_cli": "same-cli"},
            "runner": {"backend": "container", "backend_version": "1", "profile_sha256": "a" * 64},
            "digests": {},
            "metrics": {
                "decision_correctness": decision,
                "required_findings_supported": supported,
                "required_findings_total": 2,
                "required_finding_completion": supported / 2,
                "critical_failure": critical,
                "hard_failure_ids": ["H1"] if critical else [],
                "execution_integrity": execution,
                "update_behavior": "not_applicable",
                "behavior_scores": {"honesty": 2},
                "gate_verdict": "failed" if critical or decision != "correct" else "passed",
                "review_confidence": "high",
            },
            "limitations": [],
        }

    def test_complete_pair_reports_descriptive_delta(self):
        generic = self._record("generic", decision="partial", supported=1)
        v05 = self._record("feynman-v05", decision="correct", supported=2)
        result = aggregate(self._plan(), [generic, v05])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["conditions"]["feynman-v05"]["decision_correct_rate_over_all_runs"], 1.0)
        paired = result["paired_descriptive"]["generic_vs_feynman_v05"]
        self.assertEqual(paired["paired_units"], 1)
        self.assertEqual(paired["mean_decision_score_delta_target_minus_comparator"], 0.5)
        self.assertEqual(paired["mean_required_finding_completion_delta"], 0.5)

    def test_missing_result_is_reported_not_silently_dropped(self):
        generic = self._record("generic", decision="correct", supported=2)
        result = aggregate(self._plan(), [generic])
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["expected_runs"], 2)
        self.assertEqual(result["observed_runs"], 1)
        self.assertEqual(len(result["missing_jobs"]), 1)

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
