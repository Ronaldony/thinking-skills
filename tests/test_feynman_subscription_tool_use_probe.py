from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tooling import feynman_subscription_tool_use_probe as probe


class ToolUseProbeTests(unittest.TestCase):
    def test_contract_is_fixed_and_does_not_embed_evaluation_prompt(self):
        self.assertIn("exactly once", probe.PROBE_PROMPT)
        self.assertIn("candidate.py", probe.PROBE_PROMPT)
        self.assertNotIn("test_candidate.py", probe.PROBE_PROMPT)
        self.assertNotIn("feynman", probe.PROBE_PROMPT.lower())

    def test_only_repaired_feynman_fixture_is_accepted(self):
        accepted = {"job": {"case_id": "tools-10", "condition_id": "feynman-v05", "repeat": 1, "has_followup": False}}
        probe._validate_job(accepted)
        for field, value in (("case_id", "other"), ("condition_id", "baseline"), ("repeat", 2), ("has_followup", True)):
            invalid = json.loads(json.dumps(accepted)); invalid["job"][field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError): probe._validate_job(invalid)

    def test_parse_trace_reports_no_tool_without_retaining_message(self):
        with tempfile.TemporaryDirectory() as raw:
            trace = Path(raw) / "trace.jsonl"
            trace.write_text("\n".join([
                json.dumps({"type": "thread.started", "thread_id": "t"}),
                json.dumps({"type": "turn.started"}),
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "not retained by probe result"}}),
                json.dumps({"type": "turn.completed"}),
            ]), encoding="utf-8")
            parsed = probe.smoke._parse_trace(trace)
        self.assertEqual(parsed["completed_tool_item_count"], 0)
        self.assertEqual(parsed["completed_tool_item_types"], [])


if __name__ == "__main__":
    unittest.main()
