from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_mock_responses_server import (
    AUTH_ENV_MARKER,
    AUTH_VALUE_MARKER,
    EXEC_CALL_ID,
    FINAL_TEXT,
    NETWORK_MARKER,
    PATCH_CALL_ID,
    PATCH_FILENAME,
    PATCH_MARKER,
    SCENARIO_EXEC_ONLY,
    SCENARIO_PATCH_THEN_EXEC,
    SCENARIOS,
    WORKSPACE_MARKER,
    _bearer_digest,
    _sse,
    apply_patch_events,
    exec_command_events,
    final_events,
    find_exec_output,
    find_patch_output,
)


class MockResponsesServerTests(unittest.TestCase):
    def test_scenarios_are_explicit(self):
        self.assertEqual(SCENARIOS, {SCENARIO_EXEC_ONLY, SCENARIO_PATCH_THEN_EXEC})

    def test_patch_response_requests_apply_patch_for_remote_marker_file(self):
        events = apply_patch_events()
        call = events[1]["item"]
        self.assertEqual(call["type"], "custom_tool_call")
        self.assertEqual(call["call_id"], PATCH_CALL_ID)
        self.assertEqual(call["name"], "apply_patch")
        self.assertIn(f"*** Add File: {PATCH_FILENAME}", call["input"])
        self.assertIn(f"+{PATCH_MARKER}", call["input"])

    def test_exec_only_command_checks_boundary_without_patch_dependency(self):
        events = exec_command_events("172.17.0.1", 19001)
        call = events[1]["item"]
        self.assertEqual(call["type"], "function_call")
        self.assertEqual(call["call_id"], EXEC_CALL_ID)
        self.assertEqual(call["name"], "exec_command")
        args = json.loads(call["arguments"])
        self.assertNotIn(PATCH_FILENAME, args["cmd"])
        self.assertNotIn(PATCH_MARKER, args["cmd"])
        self.assertIn(WORKSPACE_MARKER, args["cmd"])
        self.assertIn(NETWORK_MARKER, args["cmd"])
        self.assertIn(AUTH_ENV_MARKER, args["cmd"])
        self.assertNotIn(AUTH_VALUE_MARKER, args["cmd"])
        self.assertIn("172.17.0.1", args["cmd"])
        self.assertIn("19001", args["cmd"])
        self.assertEqual(args["yield_time_ms"], 1000)

    def test_synthetic_bearer_digest_adds_value_hash_check_without_raw_secret(self):
        raw_secret = "synthetic-credential-value"
        secret_sha = hashlib.sha256(raw_secret.encode()).hexdigest()
        events = exec_command_events(
            "172.17.0.1",
            19001,
            expected_bearer_sha256=secret_sha,
        )
        args = json.loads(events[1]["item"]["arguments"])
        self.assertIn(AUTH_VALUE_MARKER, args["cmd"])
        self.assertIn(secret_sha, args["cmd"])
        self.assertNotIn(raw_secret, args["cmd"])

    def test_invalid_bearer_digest_is_rejected(self):
        with self.assertRaises(ValueError):
            exec_command_events("172.17.0.1", 19001, expected_bearer_sha256="not-a-sha")

    def test_bearer_digest_records_only_hash(self):
        token = "very-sensitive-synthetic-token"
        present, digest = _bearer_digest("Bearer " + token)
        self.assertTrue(present)
        self.assertEqual(digest, hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, digest)

    def test_missing_or_empty_bearer_is_not_present(self):
        self.assertEqual(_bearer_digest(None), (False, None))
        self.assertEqual(_bearer_digest("Bearer "), (False, None))
        self.assertEqual(_bearer_digest("Basic abc"), (False, None))

    def test_patch_then_exec_command_requires_patch_marker(self):
        events = exec_command_events("172.17.0.1", 19001, require_patch=True)
        args = json.loads(events[1]["item"]["arguments"])
        self.assertIn(PATCH_FILENAME, args["cmd"])
        self.assertIn(PATCH_MARKER, args["cmd"])
        self.assertIn(WORKSPACE_MARKER, args["cmd"])

    def test_matching_patch_output_is_found_recursively(self):
        body = {
            "input": [{
                "type": "custom_tool_call_output",
                "call_id": PATCH_CALL_ID,
                "output": {"content": "Done!", "success": True},
            }]
        }
        output = find_patch_output(body)
        self.assertIsNotNone(output)
        self.assertIn("Done!", output)

    def test_matching_exec_output_is_found_recursively(self):
        body = {
            "input": [{
                "type": "function_call_output",
                "call_id": EXEC_CALL_ID,
                "output": f"{AUTH_ENV_MARKER}\n{NETWORK_MARKER}\n{WORKSPACE_MARKER}\n",
            }]
        }
        output = find_exec_output(body)
        self.assertIsNotNone(output)
        self.assertIn(AUTH_ENV_MARKER, output)
        self.assertIn(NETWORK_MARKER, output)
        self.assertIn(WORKSPACE_MARKER, output)

    def test_wrong_patch_call_id_is_not_accepted(self):
        body = {"input": [{
            "type": "custom_tool_call_output",
            "call_id": "other-call",
            "output": "Done!",
        }]}
        self.assertIsNone(find_patch_output(body))

    def test_wrong_exec_call_id_is_not_accepted(self):
        body = {"input": [{
            "type": "function_call_output",
            "call_id": "other-call",
            "output": f"{AUTH_ENV_MARKER} {NETWORK_MARKER} {WORKSPACE_MARKER}",
        }]}
        self.assertIsNone(find_exec_output(body))

    def test_final_response_contains_only_expected_reference_text(self):
        events = final_events()
        message = events[1]["item"]
        self.assertEqual(message["type"], "message")
        self.assertEqual(message["content"], [{"type": "output_text", "text": FINAL_TEXT}])

    def test_sse_uses_event_and_data_records(self):
        raw = _sse(final_events()).decode("utf-8")
        self.assertIn("event: response.created\n", raw)
        self.assertIn("event: response.output_item.done\n", raw)
        self.assertIn("event: response.completed\n", raw)
        self.assertIn(f'"text":"{FINAL_TEXT}"', raw)

    def test_invalid_tool_host_is_rejected(self):
        with self.assertRaises(ValueError):
            exec_command_events("host;touch /tmp/bad", 19001)

    def test_invalid_tool_port_is_rejected(self):
        with self.assertRaises(ValueError):
            exec_command_events("172.17.0.1", 0)


if __name__ == "__main__":
    unittest.main()
