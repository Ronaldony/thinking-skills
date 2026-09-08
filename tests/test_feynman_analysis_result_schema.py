from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "evals" / "feynman-thinking" / "analysis-result.schema.json"


class AnalysisResultSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_schema_is_fail_closed_v3(self):
        self.assertEqual(self.schema["properties"]["schema_version"]["const"], 3)
        self.assertFalse(self.schema["additionalProperties"])
        self.assertIn("authentication", self.schema["required"])
        self.assertIn("lineage", self.schema["required"])
        self.assertIn("digests", self.schema["required"])

    def test_runner_job_lineage_is_mandatory(self):
        lineage = self.schema["properties"]["lineage"]
        self.assertFalse(lineage["additionalProperties"])
        self.assertEqual(
            set(lineage["required"]),
            {"runner_job_attestation_bound", "runner_job_link_verdict"},
        )
        self.assertTrue(lineage["properties"]["runner_job_attestation_bound"]["const"])
        self.assertEqual(
            lineage["properties"]["runner_job_link_verdict"]["const"],
            "runner-job-attestation-bound",
        )

    def test_runner_job_and_link_digests_are_mandatory(self):
        required = set(self.schema["properties"]["digests"]["required"])
        self.assertIn("runner_job_sha256", required)
        self.assertIn("runner_job_link_sha256", required)
        self.assertIn("attestation_sha256", required)
        self.assertIn("eval_plan_sha256", required)

    def test_authentication_contract_matches_runner_v2(self):
        auth = self.schema["properties"]["authentication"]
        self.assertFalse(auth["additionalProperties"])
        self.assertEqual(auth["properties"]["mode"]["const"], "control-plane-only")
        self.assertEqual(
            auth["properties"]["control_plane_credential_source"]["const"],
            "environment",
        )
        self.assertFalse(auth["properties"]["candidate_auth_exposed"]["const"])
        self.assertIn("control_plane_credential_env_key", auth["required"])

    def test_schema_does_not_define_a_credential_value_field(self):
        raw = SCHEMA_PATH.read_text(encoding="utf-8")
        self.assertNotIn('"credential_value"', raw)
        self.assertNotIn('"api_key_value"', raw)
        self.assertNotIn('"secret_value"', raw)


if __name__ == "__main__":
    unittest.main()
