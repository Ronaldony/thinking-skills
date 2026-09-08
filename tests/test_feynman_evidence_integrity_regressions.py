from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.codex_exec_evidence import extract
from tooling.feynman_eval_workspace import prepare
from tooling.feynman_review_bundle import assemble


class EvidenceIntegrityRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.candidate = self.base / "candidate"
        self.evaluator = self.base / "evaluator"
        prepare(ROOT, "tools-10", self.candidate, self.evaluator, install_skill=True)
        self.trace = self.base / "trace.jsonl"
        events = [
            {"type": "item.completed", "item": {
                "id": "cmd-1", "type": "command_execution", "command": "python test_candidate.py",
                "aggregated_output": "FAILED: expected 7 got 4", "exit_code": 1, "status": "failed"}},
            {"type": "item.completed", "item": {
                "id": "msg-1", "type": "agent_message", "text": "Original final answer."}},
        ]
        self.trace.write_text("\n".join(json.dumps(x) for x in events) + "\n", encoding="utf-8")
        self.evidence = self.base / "evidence"
        extract(self.trace, self.evidence)

    def tearDown(self):
        self.tmp.cleanup()

    def test_final_answer_tampering_is_rejected_before_review(self):
        (self.evidence / "final.md").write_text("Tampered final answer.", encoding="utf-8")
        with self.assertRaises(ValueError):
            assemble(self.evaluator, self.evidence, self.base / "review")

    def test_fabricated_trusted_execution_id_is_rejected_before_review(self):
        index_path = self.evidence / "evidence-index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["trusted_execution_ids"] = ["command_execution:invented"]
        index_path.write_text(json.dumps(index), encoding="utf-8")
        with self.assertRaises(ValueError):
            assemble(self.evaluator, self.evidence, self.base / "review")

    def test_review_manifest_binds_candidate_final_hash(self):
        index = json.loads((self.evidence / "evidence-index.json").read_text(encoding="utf-8"))
        manifest = assemble(self.evaluator, self.evidence, self.base / "review")
        self.assertEqual(manifest["candidate_final_sha256"], index["final_sha256"])


if __name__ == "__main__":
    unittest.main()
