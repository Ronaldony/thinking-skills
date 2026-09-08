from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_real_smoke_plan import (
    EXPECTED_ANALYSIS_USE,
    EXPECTED_CASES,
    EXPECTED_CONDITIONS,
    build_smoke_plan,
    validate_spec,
)

SPEC_PATH = ROOT / "evals" / "feynman-thinking" / "real-model-smoke-spec.json"


class RealSmokePlanTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    def test_committed_spec_is_valid_and_explicitly_non_performance(self):
        validate_spec(self.spec)
        self.assertEqual(self.spec["analysis_use"], EXPECTED_ANALYSIS_USE)
        self.assertEqual(self.spec["cases"], EXPECTED_CASES)
        self.assertEqual(self.spec["conditions"], EXPECTED_CONDITIONS)
        self.assertEqual(self.spec["repeats"], 1)
        joined = " ".join(self.spec["prohibited_claims"]).lower()
        self.assertIn("performance", joined)
        self.assertIn("held-out", joined)

    def test_plan_contains_exactly_two_expected_jobs(self):
        plan = build_smoke_plan(ROOT, SPEC_PATH)
        self.assertEqual(len(plan["jobs"]), 2)
        self.assertEqual({job["case_id"] for job in plan["jobs"]}, {"tools-10"})
        self.assertEqual(
            {job["condition"] for job in plan["jobs"]},
            {"baseline", "feynman-v05"},
        )
        self.assertEqual({job["repeat"] for job in plan["jobs"]}, {1})
        self.assertEqual(plan["analysis_use"], EXPECTED_ANALYSIS_USE)
        self.assertEqual(len(plan["smoke_spec_sha256"]), 64)

    def test_same_spec_build_is_deterministic(self):
        first = build_smoke_plan(ROOT, SPEC_PATH)
        second = build_smoke_plan(ROOT, SPEC_PATH)
        self.assertEqual(first, second)

    def test_expanding_conditions_is_rejected(self):
        spec = deepcopy(self.spec)
        spec["conditions"].append("generic")
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_increasing_repeats_is_rejected(self):
        spec = deepcopy(self.spec)
        spec["repeats"] = 5
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_changing_analysis_use_is_rejected(self):
        spec = deepcopy(self.spec)
        spec["analysis_use"] = "performance-estimate"
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_duplicate_or_different_case_is_rejected(self):
        for cases in (["mechanism-01"], ["tools-10", "tools-10"]):
            spec = deepcopy(self.spec)
            spec["cases"] = list(cases)
            with self.assertRaises(ValueError):
                validate_spec(spec)

    def test_invalid_auth_env_key_name_is_rejected(self):
        spec = deepcopy(self.spec)
        spec["default_control_plane_credential_env_key_name"] = "BAD-KEY"
        with self.assertRaises(ValueError):
            validate_spec(spec)


if __name__ == "__main__":
    unittest.main()
