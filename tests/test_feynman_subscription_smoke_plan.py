from __future__ import annotations
from copy import deepcopy
import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tooling.feynman_subscription_smoke_plan import build_smoke_plan,validate_spec
class SubscriptionSmokePlanTests(unittest.TestCase):
    def setUp(self):
        self.spec_path=ROOT/"evals"/"feynman-thinking"/"subscription-smoke-spec.json"
        self.spec=json.loads(self.spec_path.read_text(encoding="utf-8"))
    def test_frozen_spec_valid(self):validate_spec(self.spec)
    def test_plan_exactly_two_jobs(self):
        p=build_smoke_plan(ROOT,self.spec_path);self.assertEqual(len(p["jobs"]),2)
        self.assertEqual({j["condition"] for j in p["jobs"]},{"baseline","feynman-v05"})
        self.assertEqual(p["analysis_use"],"not-for-skill-performance-inference");self.assertFalse(p["api_key_auth_allowed"])
    def test_api_key_auth_cannot_be_enabled(self):
        v=deepcopy(self.spec);v["api_key_auth_allowed"]=True
        with self.assertRaises(ValueError):validate_spec(v)
    def test_scope_cannot_add_generic(self):
        v=deepcopy(self.spec);v["conditions"].append("generic")
        with self.assertRaises(ValueError):validate_spec(v)
    def test_prohibited_claims_cover_effect_and_heldout(self):
        text=" ".join(self.spec["prohibited_claims"]).lower();self.assertIn("skill effect",text);self.assertIn("held-out",text);self.assertIn("behaviorally validated",text)
if __name__=="__main__":unittest.main()
