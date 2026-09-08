from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_mock_responses_server import (
    CALL_ID,
    FINAL_TEXT,
    NETWORK_MARKER,
    WORKSPACE_MARKER,
    _sse,
    final_events,
    find_matching_tool_output,
    function_call_events,
)


class MockResponsesServerTests(unittest.TestCase):
    def test_first_response_requests_exec_command_with_network_and_workspace_checks(self):
        events = function_call_events("172.17.0.1", 19001)
        self.assertEqual(events[0]["type"], "response.created")
        call = events[1]["item"]
        self.assertEqual(call["type"], "function_call")
        self.assertEqual(call["call_id"], CALL_ID)
        self.assertEqual(call["name"], "exec_command")
        args = json.loads(call["arguments"])
        self.assertIn(WORKSPACE_MARKER, args["cmd"])
        self.assertIn(NETWORK_MARKER, args["cmd"])
        self.assertIn("172.17.0.1", args["cmd"])
        self.assertIn("19001", args["cmd"])
        self.assertEqual(args["yield_time_ms"], 1000)

    def test_matching_function_output_is_found_recursively(self):
        body = {
            "input": [
                {"type": "message", "role": "user", "content": []},
                {
                    "type": "function_call_output",
                    "call_id": CALL_ID,
                    "output": f"{NETWORK_MARKER}\n{WORKSPACE_MARKER}\n",
                },
            ]
        }
        output = find_matching_tool_output(body)
        self.assertIsNotNone(output)
        self.assertIn(NETWORK_MARKER, output)
        self.assertIn(WORKSPACE_MARKER, output)

    def test_wrong_call_id_is_not_accepted(self):
        body = {
            "input": [{
                "type": "function_call_output",
                "call_id": "other-call",
                "output": f"{NETWORK_MARKER} {WORKSPACE_MARKER}",
            }]
        }
        self.assertIsNone(find_matching_tool_output(body))

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
            function_call_events("host;touch /tmp/bad", 19001)

    def test_invalid_tool_port_is_rejected(self):
        with self.assertRaises(ValueError):
            function_call_events("172.17.0.1", 0)


if __name__ == "__main__":
    unittest.main()
