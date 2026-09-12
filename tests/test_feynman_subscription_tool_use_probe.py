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
    def _gate_attempt(self, *, versions_error=None, guard_report=None):
        job = {'job': {'case_id': 'tools-10', 'condition_id': 'feynman-v05',
                       'repeat': 1, 'has_followup': False},
               'paths': {'evaluator_dir': 'evaluator'}}
        with patch.object(probe.smoke, '_assert_invocation_context'), \
             patch.object(probe.smoke, '_regular', side_effect=lambda p, label: p), \
             patch.object(probe.smoke, '_load', return_value=job), \
             patch.object(probe, 'preflight_files', return_value={'verdict': 'ready-for-local-chatgpt-session-check'}), \
             patch.object(probe.smoke, '_prepare_output_dir', return_value=Path('output')), \
             patch('tooling.feynman_rpc_version_gate.verify', side_effect=versions_error), \
             patch('tooling.feynman_guarded_rpc_preflight.verify', return_value=guard_report), \
             patch.object(probe.smoke, 'check_auth') as auth, \
             patch.object(probe.subprocess, 'run') as model:
            with self.assertRaises(ValueError):
                probe.probe(plan_path=Path('plan'), ordinal=1, evaluator_case_path=Path('case'),
                            runner_job_path=Path('job'), boundary_profile_path=Path('profile'),
                            remote_environment_path=Path('remote'), output_dir=Path('output'),
                            docker_config=Path('empty'))
            auth.assert_not_called()
            model.assert_not_called()

    def test_runtime_gate_failure_prevents_auth_and_model(self):
        self._gate_attempt(versions_error=ValueError('mismatched versions'))

    def test_incomplete_tool_binding_prevents_auth_and_model(self):
        self._gate_attempt(guard_report={'model_tool_contract_ready': False})

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

    def test_text_claim_cannot_override_missing_tool_trace(self):
        self.assertEqual(probe._response_claim_verdict("PROBE_TOOL_USED", 0), "text-claim-without-tool-trace")
        self.assertEqual(probe._response_claim_verdict("PROBE_TOOL_USED", 1), "trace-tool-use-observed")
        self.assertEqual(probe._response_claim_verdict("PROBE_NO_TOOL", 0), "explicit-no-tool-claim")

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
