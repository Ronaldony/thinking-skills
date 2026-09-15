import json
import unittest
from pathlib import Path

from tooling import feynman_subscription_executor_wiring_preflight as preflight


class ExecutorWiringPreflightTests(unittest.TestCase):
    def test_command_plan_is_sanitized_and_counts_transient_overrides(self):
        candidate = Path("C:/candidate")
        command = ["codex.cmd", "exec", "--model", "gpt-5.6-luna", "--cd", str(candidate), "-c", "x", "-c", "y", "-c", "z", "-c", "a", "-c", "b"] + [item for value in ["full"] * 13 for item in ("-c", value)] + ["-c", "skill", "-"]
        wiring = {
            "command": command,
            "full_runner_override": type("Override", (), {"values": tuple("full" for _ in range(13))})(),
            "skill_config_overrides": ("skills.config=[{path=\"hidden\",enabled=false}]",),
            "all_config_overrides": tuple("full" for _ in range(13)) + ("skills.config=[{path=\"hidden\",enabled=false}]",),
            "app_server": {"skills": {"transiently_disabled_non_candidate_skill_count": 1}},
        }
        plan = preflight._validate_command_plan(wiring=wiring, model="gpt-5.6-luna", candidate=candidate)
        self.assertEqual(plan["full_runner_override_count"], 13)
        self.assertEqual(plan["transient_skill_disable_override_count"], 1)
        self.assertFalse(plan["command_payload_preserved"])

    def test_command_plan_rejects_retired_credential_names(self):
        wiring = {
            "command": ["codex", "exec", "--model", "gpt", "--cd", "C:/candidate", "-"],
            "full_runner_override": type("Override", (), {"values": tuple("full" for _ in range(13))})(),
            "skill_config_overrides": (),
            "all_config_overrides": tuple("full" for _ in range(12)) + ("x=OPENAI_API_KEY",),
            "app_server": {"skills": {"transiently_disabled_non_candidate_skill_count": 0}},
        }
        with self.assertRaises(ValueError):
            preflight._validate_command_plan(wiring=wiring, model="gpt", candidate=Path("C:/candidate"))

    def test_schema_is_valid_json(self):
        schema_path = Path("evals/feynman-thinking/subscription-executor-wiring-preflight.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["verdict"]["const"], "subscription-executor-wiring-ready")
        self.assertEqual(schema["$defs"]["mcp"]["properties"]["server_name"]["const"], "feynman_full_runner")


if __name__ == "__main__":
    unittest.main()
