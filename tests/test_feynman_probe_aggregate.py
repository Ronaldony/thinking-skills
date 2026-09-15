from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_eval_aggregate import aggregate


class ProbeAggregateTests(unittest.TestCase):
    def test_missing_probe_report_digest_is_rejected(self):
        prompt_sha = "1" * 64
        plan = {
            "conditions": ["generic"],
            "jobs": [{
                "ordinal": 1,
                "case_id": "case-1",
                "condition": "generic",
                "repeat": 1,
                "has_followup": False,
                "candidate_prompt_sha256": prompt_sha,
            }],
        }
        record = {
            "schema_version": 2,
            "valid_for_analysis": True,
            "run_id": "run-generic",
            "job": {
                "ordinal": 1,
                "case_id": "case-1",
                "condition": "generic",
                "repeat": 1,
                "phase": "initial",
            },
            "versions": {"model": "same-model", "codex_cli": "same-cli"},
            "runner": {
                "backend": "container",
                "backend_version": "1",
                "profile_sha256": "a" * 64,
            },
            "conversation": {
                "thread_id": None,
                "initial_source_trace_sha256": None,
                "followup_source_trace_sha256": None,
            },
            "digests": {
                "candidate_prompt_sha256": prompt_sha,
                "runtime_sha256": None,
            },
            "metrics": {
                "decision_correctness": "correct",
                "required_findings_supported": 1,
                "required_findings_total": 1,
                "required_finding_completion": 1.0,
                "critical_failure": False,
                "hard_failure_ids": [],
                "execution_integrity": "clean",
                "update_behavior": "not_applicable",
                "behavior_scores": {"honesty": 2},
                "gate_verdict": "passed",
                "review_confidence": "high",
            },
            "limitations": [],
        }
        with self.assertRaises(ValueError):
            aggregate(plan, [record])

    def test_malformed_probe_report_digest_is_rejected(self):
        prompt_sha = "1" * 64
        plan = {
            "conditions": ["generic"],
            "jobs": [{
                "ordinal": 1,
                "case_id": "case-1",
                "condition": "generic",
                "repeat": 1,
                "has_followup": False,
                "candidate_prompt_sha256": prompt_sha,
            }],
        }
        record = {
            "schema_version": 2,
            "valid_for_analysis": True,
            "run_id": "run-generic",
            "job": {
                "ordinal": 1,
                "case_id": "case-1",
                "condition": "generic",
                "repeat": 1,
                "phase": "initial",
            },
            "versions": {"model": "same-model", "codex_cli": "same-cli"},
            "runner": {
                "backend": "container",
                "backend_version": "1",
                "profile_sha256": "a" * 64,
            },
            "conversation": {
                "thread_id": None,
                "initial_source_trace_sha256": None,
                "followup_source_trace_sha256": None,
            },
            "digests": {
                "candidate_prompt_sha256": prompt_sha,
                "runtime_sha256": None,
                "probe_report_sha256": "not-a-sha",
            },
            "metrics": {
                "decision_correctness": "correct",
                "required_findings_supported": 1,
                "required_findings_total": 1,
                "required_finding_completion": 1.0,
                "critical_failure": False,
                "hard_failure_ids": [],
                "execution_integrity": "clean",
                "update_behavior": "not_applicable",
                "behavior_scores": {"honesty": 2},
                "gate_verdict": "passed",
                "review_confidence": "high",
            },
            "limitations": [],
        }
        with self.assertRaises(ValueError):
            aggregate(plan, [record])


if __name__ == "__main__":
    unittest.main()
