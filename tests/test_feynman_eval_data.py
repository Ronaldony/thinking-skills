from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_eval_data import validate


class EvalDataTests(unittest.TestCase):
    def setUp(self):
        self.source = ROOT / "evals" / "feynman-thinking"

    def test_public_development_data_is_structurally_valid(self):
        result = validate(self.source)
        self.assertEqual(result["cases"], 18)
        self.assertEqual(result["rubrics"], 18)
        self.assertEqual(result["followup_cases"], ["retain-09", "revise-08"])
        self.assertEqual(result["execution_cases"], ["tools-10"])
        self.assertGreaterEqual(result["hard_failure_definitions"], 18)
        for required in (
            "positive-control",
            "multi-turn-reversal",
            "multi-turn-confirmation",
            "negative-trigger",
            "execution-integrity",
        ):
            self.assertIn(required, result["categories"])

    def _copy(self, base: Path) -> Path:
        target = base / "evals"
        shutil.copytree(self.source, target)
        return target

    def test_evaluator_metadata_in_candidate_case_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._copy(Path(tmp))
            path = base / "cases.jsonl"
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            rows[0]["required_findings"] = [{"id": "LEAK", "text": "do not expose"}]
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate(base)

    def test_missing_hard_failure_definitions_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._copy(Path(tmp))
            path = base / "rubrics.jsonl"
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            rows[0].pop("hard_failures")
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate(base)

    def test_execution_case_without_fixture_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._copy(Path(tmp))
            shutil.rmtree(base / "fixtures" / "tools-10")
            with self.assertRaises(ValueError):
                validate(base)


if __name__ == "__main__":
    unittest.main()
