from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_condition_workspace import prepare_condition
from tooling.feynman_eval_plan import build_plan


class PromptDigestRegressionTests(unittest.TestCase):
    def test_plan_workspace_and_evaluator_use_identical_prompt_bytes(self):
        for condition in ("baseline", "generic", "feynman-v05"):
            with self.subTest(condition=condition), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                candidate = base / "candidate"
                evaluator = base / "evaluator"

                plan = build_plan(
                    ROOT,
                    case_ids=["mechanism-01"],
                    condition_ids=[condition],
                    repeats=1,
                    seed=0,
                )
                job = plan["jobs"][0]
                record = prepare_condition(
                    ROOT,
                    "mechanism-01",
                    condition,
                    candidate,
                    evaluator,
                )

                actual_bytes = (candidate / "task.txt").read_bytes()
                actual_sha = hashlib.sha256(actual_bytes).hexdigest()
                evaluator_record = json.loads((evaluator / "case.json").read_text(encoding="utf-8"))

                self.assertEqual(actual_sha, job["candidate_prompt_sha256"])
                self.assertEqual(actual_sha, record["candidate_prompt_sha256"])
                self.assertEqual(actual_sha, evaluator_record["candidate_prompt_sha256"])
                self.assertEqual(actual_bytes, (job["candidate_prompt"] + "\n").encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
