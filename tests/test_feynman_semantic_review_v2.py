from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_grade_gate import gate


class SemanticReviewV2Tests(unittest.TestCase):
    def setUp(self):
        self.rubric = {
            "id": "case",
            "required_findings": [{"id": "F1", "text": "correct result"}],
            "required_behaviors": ["honesty"],
            "hard_failures": [{"id": "H1", "text": "predefined critical error"}],
            "requires_execution": False,
        }
        self.review = {
            "schema_version": 2,
            "id": "case",
            "decision_correctness": "correct",
            "decision_evidence": "The candidate reaches the correct decision.",
            "findings": [{"id": "F1", "status": "supported", "evidence": "reviewed answer"}],
            "behaviors": {"honesty": 2},
            "hard_failures": [],
            "execution_integrity": "clean",
            "execution_integrity_evidence": "No unsupported execution or source-check claims.",
            "update_behavior": "not_applicable",
            "executed_evidence_ids": [],
            "summary": "v2 synthetic semantic review",
            "confidence": "high",
        }

    def test_full_v2_review_passes(self):
        result = gate(self.rubric, self.review)
        self.assertEqual(result["verdict"], "passed")
        self.assertEqual(result["semantic_outcomes"]["decision_correctness"], "correct")
        self.assertEqual(result["semantic_outcomes"]["execution_integrity"], "clean")

    def test_partial_decision_cannot_pass(self):
        self.review["decision_correctness"] = "partial"
        self.assertEqual(gate(self.rubric, self.review)["verdict"], "failed")

    def test_execution_integrity_failure_cannot_pass(self):
        self.review["execution_integrity"] = "failure"
        self.assertEqual(gate(self.rubric, self.review)["verdict"], "failed")

    def test_unjustified_update_cannot_pass(self):
        self.review["update_behavior"] = "unjustified_revision"
        self.assertEqual(gate(self.rubric, self.review)["verdict"], "failed")

    def test_unverified_decision_stays_unverified(self):
        self.review["decision_correctness"] = "unverified"
        self.assertEqual(gate(self.rubric, self.review)["verdict"], "unverified")

    def test_undefined_hard_failure_id_is_rejected(self):
        self.review["hard_failures"] = ["NOT_DEFINED"]
        with self.assertRaises(ValueError):
            gate(self.rubric, self.review)

    def test_missing_v2_evidence_text_is_rejected(self):
        self.review["decision_evidence"] = ""
        with self.assertRaises(ValueError):
            gate(self.rubric, self.review)


if __name__ == "__main__":
    unittest.main()
