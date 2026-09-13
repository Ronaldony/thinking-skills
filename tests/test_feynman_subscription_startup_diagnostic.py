from __future__ import annotations

import json
from pathlib import Path
import unittest

from tooling.feynman_subscription_startup_diagnostic import (
    StartupDiagnosticError, _thread_start_params, _thread_summary,
)


class SubscriptionStartupDiagnosticTests(unittest.TestCase):
    def test_thread_start_is_ephemeral_and_has_no_turn_or_prompt(self):
        params = _thread_start_params(model="gpt-5.6-luna")
        self.assertTrue(params["ephemeral"])
        self.assertEqual(params["approvalPolicy"], "never")
        self.assertEqual(params["sandbox"], "workspace-write")
        self.assertEqual(params["environments"][0]["environmentId"], "candidate")
        self.assertEqual(params["cwd"], "/run/candidate")
        self.assertEqual(params["environments"][0]["cwd"], "/run/candidate")
        serialized = json.dumps(params)
        self.assertNotIn("prompt", serialized)
        self.assertNotIn("input", serialized)

    def test_thread_summary_preserves_no_id_or_instruction_path(self):
        summary = _thread_summary({"result": {
            "thread": {"id": "SYNTHETIC_PRIVATE_THREAD", "ephemeral": True},
            "instructionSources": ["C:/SYNTHETIC_PRIVATE/AGENTS.md"],
        }})
        self.assertEqual(summary, {
            "thread_started": True,
            "error_code": None,
            "error_category": None,
            "ephemeral_thread": True,
            "instruction_sources_present": True,
            "response_payload_preserved": False,
        })
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(summary))

    def test_error_summary_preserves_only_numeric_code(self):
        summary = _thread_summary({"error": {
            "code": -32001, "message": "SYNTHETIC_PRIVATE_PATH"}})
        self.assertEqual(summary["error_code"], -32001)
        self.assertEqual(summary["error_category"], "remote-path-error")
        self.assertFalse(summary["thread_started"])
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(summary))

    def test_durable_thread_is_rejected(self):
        with self.assertRaisesRegex(StartupDiagnosticError, "not-ephemeral"):
            _thread_summary({"result": {"thread": {"id": "x", "ephemeral": False}}})

    def test_artifact_schema_is_valid_json(self):
        schema = json.loads(Path(
            "evals/feynman-thinking/subscription-startup-diagnostic.schema.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertEqual(schema["properties"]["checks"]["properties"]
                         ["model_generation_requests_sent"]["const"], 0)


if __name__ == "__main__":
    unittest.main()
