from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.codex_exec_evidence import extract
from tooling.feynman_apply_review import apply
from tooling.feynman_eval_workspace import prepare
from tooling.feynman_review_bundle import assemble


class ReviewPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _trace_bundle(self, *, case="tools-10"):
        candidate = self.base / f"candidate-{case}"
        evaluator = self.base / f"evaluator-{case}"
        prepare(ROOT, case, candidate, evaluator, install_skill=True)
        trace = self.base / f"trace-{case}.jsonl"
        events = [
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "item.completed", "item": {
                "id": "reason-1", "type": "reasoning", "text": "PRIVATE_REASONING_SHOULD_NOT_APPEAR"}},
            {"type": "item.completed", "item": {
                "id": "cmd-1", "type": "command_execution", "command": "python test_candidate.py",
                "aggregated_output": "FAILED: expected 7 got 4", "exit_code": 1, "status": "failed"}},
            {"type": "item.completed", "item": {
                "id": "msg-1", "type": "agent_message", "text": "The executed test exposed the defect."}},
        ]
        trace.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8")
        evidence = self.base / f"evidence-{case}"
        extract(trace, evidence)
        return candidate, evaluator, evidence

    def _message_evidence(self, name: str, thread_id: str, message: str) -> Path:
        trace = self.base / f"trace-{name}.jsonl"
        events = [
            {"type": "thread.started", "thread_id": thread_id},
            {"type": "item.completed", "item": {
                "id": f"msg-{name}", "type": "agent_message", "text": message}},
        ]
        trace.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
        evidence = self.base / f"evidence-{name}"
        extract(trace, evidence)
        return evidence

    def test_review_bundle_contains_task_rubric_final_and_verified_evidence(self):
        _, evaluator, evidence = self._trace_bundle()
        review_bundle = self.base / "review-bundle"
        manifest = assemble(evaluator, evidence, review_bundle)
        review_input = json.loads((review_bundle / "review-input.json").read_text(encoding="utf-8"))
        self.assertEqual(review_input["case_id"], "tools-10")
        self.assertIn("candidate.py", review_input["task"])
        self.assertTrue(review_input["rubric"]["requires_execution"])
        self.assertEqual(review_input["candidate_final"], "The executed test exposed the defect.")
        self.assertIn("FAILED: expected 7 got 4", "\n".join(review_input["evidence_files"].values()))
        self.assertNotIn("PRIVATE_REASONING_SHOULD_NOT_APPEAR", (review_bundle / "review-input.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["trusted_execution_ids"], ["command_execution:cmd-1"])

    def test_semantic_review_can_pass_only_with_matching_trusted_execution(self):
        _, evaluator, evidence = self._trace_bundle()
        review_bundle = self.base / "review-bundle"
        assemble(evaluator, evidence, review_bundle)
        review = {
            "id": "tools-10",
            "findings": [
                {"id": "F1", "status": "supported", "evidence": "command_execution:cmd-1 and failure output"},
                {"id": "F2", "status": "supported", "evidence": "candidate did not fabricate success"},
            ],
            "behaviors": {"direct_check": 2, "honesty": 2},
            "hard_failures": [],
            "executed_evidence_ids": ["command_execution:cmd-1"],
            "summary": "Synthetic semantic review for pipeline testing.",
            "confidence": "high",
        }
        review_path = self.base / "review.json"
        review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        result = apply(review_bundle, review_path, self.base / "gate.json")
        self.assertEqual(result["verdict"], "passed")

    def test_fake_execution_id_fails_after_semantic_review(self):
        _, evaluator, evidence = self._trace_bundle()
        review_bundle = self.base / "review-bundle"
        assemble(evaluator, evidence, review_bundle)
        review = {
            "id": "tools-10",
            "findings": [
                {"id": "F1", "status": "supported", "evidence": "claimed execution"},
                {"id": "F2", "status": "supported", "evidence": "claimed honesty"},
            ],
            "behaviors": {"direct_check": 2, "honesty": 2},
            "hard_failures": [],
            "executed_evidence_ids": ["command_execution:invented"],
            "summary": "Synthetic bad review.",
            "confidence": "low",
        }
        review_path = self.base / "review.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        result = apply(review_bundle, review_path, self.base / "gate.json")
        self.assertEqual(result["verdict"], "failed")
        self.assertTrue(any("lack trusted matching records" in reason for reason in result["reasons"]))

    def test_tampered_stored_evidence_is_rejected_before_review(self):
        _, evaluator, evidence = self._trace_bundle()
        evidence_file = next((evidence / "evidence").iterdir())
        evidence_file.write_text("tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            assemble(evaluator, evidence, self.base / "review-bundle")

    def test_followup_review_contains_both_answers_from_same_thread(self):
        candidate = self.base / "candidate-followup"
        evaluator = self.base / "evaluator-followup"
        prepare(ROOT, "revise-08", candidate, evaluator, install_skill=True)
        initial_evidence = self._message_evidence(
            "initial", "thread-episode", "At 20/s, the system appears to meet the 15/s target."
        )
        followup_evidence = self._message_evidence(
            "followup", "thread-episode", "With corrected throughput 10/s, the system misses the 15/s target."
        )
        initial_review = self.base / "review-initial"
        followup_review = self.base / "review-followup"
        assemble(evaluator, initial_evidence, initial_review, include_followup=False)
        manifest = assemble(
            evaluator,
            followup_evidence,
            followup_review,
            include_followup=True,
            initial_evidence_bundle=initial_evidence,
        )
        initial_input = json.loads((initial_review / "review-input.json").read_text(encoding="utf-8"))
        followup_input = json.loads((followup_review / "review-input.json").read_text(encoding="utf-8"))
        self.assertIsNone(initial_input["followup"])
        self.assertIn("교정 후 안정 처리량", followup_input["followup"])
        self.assertIn("20/s", followup_input["initial_candidate_final"])
        self.assertIn("10/s", followup_input["candidate_final"])
        self.assertEqual(followup_input["conversation_thread_id"], "thread-episode")
        self.assertEqual(manifest["conversation_thread_id"], "thread-episode")
        self.assertNotEqual(manifest["initial_source_trace_sha256"], manifest["source_trace_sha256"])

    def test_followup_review_rejects_different_thread(self):
        candidate = self.base / "candidate-followup-mismatch"
        evaluator = self.base / "evaluator-followup-mismatch"
        prepare(ROOT, "retain-09", candidate, evaluator, install_skill=True)
        initial_evidence = self._message_evidence("initial-mismatch", "thread-a", "12")
        followup_evidence = self._message_evidence("followup-mismatch", "thread-b", "12")
        with self.assertRaises(ValueError):
            assemble(
                evaluator,
                followup_evidence,
                self.base / "review-followup-mismatch",
                include_followup=True,
                initial_evidence_bundle=initial_evidence,
            )

    def test_followup_review_requires_initial_evidence(self):
        candidate = self.base / "candidate-followup-missing"
        evaluator = self.base / "evaluator-followup-missing"
        prepare(ROOT, "retain-09", candidate, evaluator, install_skill=True)
        followup_evidence = self._message_evidence("followup-missing", "thread-a", "12")
        with self.assertRaises(ValueError):
            assemble(
                evaluator,
                followup_evidence,
                self.base / "review-followup-missing",
                include_followup=True,
            )

    def test_modified_review_input_breaks_manifest_linkage(self):
        _, evaluator, evidence = self._trace_bundle()
        review_bundle = self.base / "review-bundle"
        assemble(evaluator, evidence, review_bundle)
        review_input = review_bundle / "review-input.json"
        review_input.write_text(review_input.read_text(encoding="utf-8") + " ", encoding="utf-8")
        review = self.base / "review.json"
        review.write_text(json.dumps({"id": "tools-10"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            apply(review_bundle, review, self.base / "gate.json")


if __name__ == "__main__":
    unittest.main()
