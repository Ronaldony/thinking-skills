from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_eval_plan import build_plan


class EvalPlanTests(unittest.TestCase):
    def test_primary_matrix_has_four_conditions_per_case(self):
        plan = build_plan(ROOT, case_ids=["mechanism-01", "retain-09"], repeats=2, seed=7)
        self.assertEqual(len(plan["jobs"]), 2 * 4 * 2)
        self.assertEqual(set(plan["conditions"]), {"baseline", "generic", "legacy-clean", "feynman-v05"})
        self.assertEqual(plan["status"], "execution-plan-no-model-results")

    def test_baseline_prompt_is_raw_task_and_v05_is_explicit_only(self):
        plan = build_plan(ROOT, case_ids=["mechanism-01"],
                          condition_ids=["baseline", "feynman-v05"], repeats=1, seed=1)
        by_condition = {job["condition"]: job for job in plan["jobs"]}
        self.assertNotIn("$feynman-thinking", by_condition["baseline"]["candidate_prompt"])
        self.assertTrue(by_condition["feynman-v05"]["candidate_prompt"].startswith("$feynman-thinking"))
        self.assertEqual(by_condition["feynman-v05"]["expected_skills"], ["feynman-thinking"])

    def test_generic_comparator_does_not_name_feynman_or_call_skill(self):
        plan = build_plan(ROOT, case_ids=["mechanism-01"], condition_ids=["generic"], seed=1)
        prompt = plan["jobs"][0]["candidate_prompt"]
        self.assertNotIn("파인만", prompt)
        self.assertNotIn("$feynman-thinking", prompt)
        self.assertIn("직접 확인 가능한 계산이나 검사", prompt)

    def test_legacy_condition_is_pinned_to_audited_commit(self):
        plan = build_plan(ROOT, case_ids=["mechanism-01"], condition_ids=["legacy-clean"], seed=1)
        job = plan["jobs"][0]
        self.assertEqual(job["required_source_commit"], "1609b8b6909f9ab596c1ecf298fbec4a0c70d6b4")
        self.assertEqual(job["skill_source"], "external-pinned-legacy-v0.4")

    def test_plan_order_is_deterministic_for_same_seed(self):
        a = build_plan(ROOT, case_ids=["mechanism-01", "retain-09"], repeats=2, seed=42)
        b = build_plan(ROOT, case_ids=["mechanism-01", "retain-09"], repeats=2, seed=42)
        self.assertEqual(a["jobs"], b["jobs"])
        c = build_plan(ROOT, case_ids=["mechanism-01", "retain-09"], repeats=2, seed=43)
        self.assertNotEqual([x["case_id"] + x["condition"] + str(x["repeat"]) for x in a["jobs"]],
                            [x["case_id"] + x["condition"] + str(x["repeat"]) for x in c["jobs"]])

    def test_unknown_condition_is_rejected(self):
        with self.assertRaises(ValueError):
            build_plan(ROOT, case_ids=["mechanism-01"], condition_ids=["unknown"])


if __name__ == "__main__":
    unittest.main()
