from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.codex_exec_evidence import extract
from tooling.feynman_condition_workspace import prepare_condition
from tooling.feynman_review_bundle import assemble


class ConditionWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _prepare(self, condition: str):
        candidate = self.base / f"candidate-{condition}"
        evaluator = self.base / f"evaluator-{condition}"
        record = prepare_condition(ROOT, "mechanism-01", condition, candidate, evaluator)
        return candidate, evaluator, record

    def test_baseline_has_raw_task_and_no_skill(self):
        candidate, _, record = self._prepare("baseline")
        task = (candidate / "task.txt").read_text(encoding="utf-8")
        self.assertNotIn("사용자 과제:", task)
        self.assertFalse((candidate / ".agents").exists())
        self.assertEqual(record["condition_id"], "baseline")
        self.assertEqual(record["expected_skills"], [])

    def test_generic_has_fixed_comparator_prefix_but_no_skill(self):
        candidate, _, record = self._prepare("generic")
        task = (candidate / "task.txt").read_text(encoding="utf-8")
        self.assertIn("일반적인 비판적 사고 방식", task)
        self.assertIn("사용자 과제:", task)
        self.assertNotIn("$feynman-thinking", task)
        self.assertFalse((candidate / ".agents").exists())
        self.assertEqual(record["skill_source"], "none")

    def test_v05_installs_only_current_runtime_and_uses_explicit_prefix(self):
        candidate, _, record = self._prepare("feynman-v05")
        task = (candidate / "task.txt").read_text(encoding="utf-8")
        self.assertTrue(task.startswith("$feynman-thinking"))
        self.assertTrue((candidate / ".agents/skills/feynman-thinking/SKILL.md").is_file())
        self.assertEqual(record["expected_skills"], ["feynman-thinking"])
        self.assertIsInstance(record["runtime_manifest"], dict)

    def test_legacy_condition_requires_pinned_checkout_path(self):
        with self.assertRaises(ValueError):
            prepare_condition(ROOT, "mechanism-01", "legacy-clean",
                              self.base / "candidate-legacy", self.base / "evaluator-legacy")

    def test_semantic_review_input_omits_condition_metadata(self):
        _, evaluator, _ = self._prepare("feynman-v05")
        trace = self.base / "trace.jsonl"
        trace.write_text(json.dumps({"type": "item.completed", "item": {
            "id": "msg-1", "type": "agent_message", "text": "candidate output"}}) + "\n", encoding="utf-8")
        evidence = self.base / "evidence"
        extract(trace, evidence)
        review = self.base / "review"
        assemble(evaluator, evidence, review)
        review_input = json.loads((review / "review-input.json").read_text(encoding="utf-8"))
        self.assertNotIn("condition_id", review_input)
        self.assertNotIn("skill_source", review_input)
        self.assertEqual(review_input["task"], json.loads((evaluator / "case.json").read_text())["prompt"])


if __name__ == "__main__":
    unittest.main()
