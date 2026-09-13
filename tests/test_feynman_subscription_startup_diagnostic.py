from __future__ import annotations

import json
from pathlib import Path
import queue
import unittest

from tooling.feynman_subscription_startup_diagnostic import (
    StartupDiagnosticError, _thread_start_params, _thread_summary,
    _wait_for_thread_start,
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
            "error_signals": {
                "mentions_environment": False,
                "mentions_exec_server": False,
                "mentions_connection": False,
                "mentions_initialize": False,
                "mentions_exit": False,
                "mentions_closed": False,
                "mentions_timeout": False,
                "mentions_config": False,
                "mentions_path": False,
                "mentions_not_found": False,
            },
            "error_data_kind": "none",
            "ephemeral_thread": True,
            "instruction_sources_present": True,
            "response_payload_preserved": False,
        })
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(summary))

    def test_error_summary_preserves_only_numeric_code(self):
        summary = _thread_summary({"error": {
            "code": -32001,
            "message": "Remote environment exec-server connection initialization failed at SYNTHETIC_PRIVATE_PATH",
            "data": {"private": "SYNTHETIC_PRIVATE_DATA"},
        }})
        self.assertEqual(summary["error_code"], -32001)
        self.assertEqual(summary["error_category"], "remote-path-error")
        self.assertTrue(summary["error_signals"]["mentions_environment"])
        self.assertTrue(summary["error_signals"]["mentions_exec_server"])
        self.assertTrue(summary["error_signals"]["mentions_connection"])
        self.assertTrue(summary["error_signals"]["mentions_initialize"])
        self.assertTrue(summary["error_signals"]["mentions_path"])
        self.assertEqual(summary["error_data_kind"], "object")
        self.assertFalse(summary["thread_started"])
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(summary))

    def test_unknown_notification_method_is_not_preserved(self):
        received = queue.Queue()
        received.put({"method": "SYNTHETIC_PRIVATE_NOTIFICATION", "params": {}})
        received.put({"id": 2, "error": {"code": -32603, "message": "environment failed"}})
        response, notifications = _wait_for_thread_start(received, 2, 10)
        self.assertEqual(response["id"], 2)
        self.assertEqual(notifications, {"unknown": 1})
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(notifications))

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
        self.assertIn("request_mapping_rejection_method_reasons",
                      schema["properties"]["proxy_telemetry"]["properties"])
        self.assertIn("request_mapping_rejection_method_reason_fields",
                      schema["properties"]["proxy_telemetry"]["properties"])
        self.assertIn("error_signals", schema["properties"]["checks"]["properties"])
        self.assertIn("error_data_kind", schema["properties"]["checks"]["properties"])


if __name__ == "__main__":
    unittest.main()
