from __future__ import annotations
import json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class AnalysisResultSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema=json.loads((ROOT/"evals"/"feynman-thinking"/"analysis-result.schema.json").read_text(encoding="utf-8"))
    def test_schema_version_is_v4(self): self.assertEqual(self.schema["properties"]["schema_version"]["const"],4)
    def test_auth_is_subscription_only(self):
        p=self.schema["properties"]["authentication"]["properties"]
        self.assertEqual(p["mode"]["const"],"chatgpt-subscription");self.assertEqual(p["control_plane_auth_source"]["const"],"codex-session")
        self.assertFalse(p["api_key_auth_allowed"]["const"]);self.assertNotIn("control_plane_credential_env_key",p)
    def test_runner_link_digests_required(self):
        r=set(self.schema["properties"]["digests"]["required"]);self.assertTrue({"runner_job_sha256","runner_job_link_sha256","attestation_sha256"}.issubset(r))
    def test_linkage_assertion_required(self):
        p=self.schema["properties"]["lineage"]["properties"];self.assertTrue(p["runner_job_attestation_bound"]["const"]);self.assertEqual(p["runner_job_link_verdict"]["const"],"runner-job-attestation-bound")
if __name__=="__main__":unittest.main()
