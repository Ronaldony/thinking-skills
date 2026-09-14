from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tooling import feynman_skill_tool_wiring_preflight as wiring
from tooling.feynman_skill_tool_wiring_preflight import (
    _app_server_probe, _rpc, _skill_disable_override, _summarize_skills,
)


class SkillToolWiringPreflightTests(unittest.TestCase):
    def test_candidate_skill_only_is_accepted(self) -> None:
        candidate = Path("C:/eval/candidate")
        result = {
            "data": [{
                "cwd": str(candidate),
                "skills": [{
                    "name": "feynman-thinking",
                    "path": str(candidate / ".agents/skills/feynman-thinking/SKILL.md"),
                    "enabled": True,
                }],
                "errors": [],
            }],
        }
        summary = _summarize_skills(
            result, candidate=candidate, expected_names=["feynman-thinking"])
        self.assertEqual(summary["candidate_skill_names"], ["feynman-thinking"])
        self.assertEqual(summary["non_candidate_enabled_skill_count"], 0)

    def test_non_candidate_enabled_skill_is_rejected(self) -> None:
        candidate = Path("C:/eval/candidate")
        result = {
            "data": [{
                "cwd": str(candidate),
                "skills": [
                    {
                        "name": "feynman-thinking",
                        "path": str(candidate / ".agents/skills/feynman-thinking/SKILL.md"),
                        "enabled": True,
                    },
                    {
                        "name": "ambient",
                        "path": "C:/user/.agents/skills/ambient/SKILL.md",
                        "enabled": True,
                    },
                ],
                "errors": [],
            }],
        }
        with self.assertRaises(ValueError):
            _summarize_skills(
                result, candidate=candidate, expected_names=["feynman-thinking"])

    def test_disabled_non_candidate_skill_is_ignored(self) -> None:
        candidate = Path("C:/eval/candidate")
        result = {
            "data": [{
                "cwd": str(candidate),
                "skills": [{
                    "name": "ambient",
                    "path": "C:/user/.agents/skills/ambient/SKILL.md",
                    "enabled": False,
                }],
                "errors": [],
            }],
        }
        summary = _summarize_skills(result, candidate=candidate, expected_names=[])
        self.assertEqual(summary["candidate_skill_names"], [])

    def test_transient_disable_override_contains_only_paths_and_false(self) -> None:
        value = _skill_disable_override([
            ("ambient", Path("C:/user/.agents/skills/ambient/SKILL.md")),
        ])
        self.assertTrue(value.startswith("skills.config=["))
        self.assertIn("enabled=false", value)
        self.assertNotIn("ambient\"", value)

    def test_rpc_uses_caller_deadline_instead_of_resetting_timeout(self) -> None:
        class Stdin:
            def __init__(self) -> None:
                self.writes: list[bytes] = []

            def write(self, value: bytes) -> None:
                self.writes.append(value)

            def flush(self) -> None:
                pass

        class Process:
            def __init__(self) -> None:
                self.stdin = Stdin()

        class Received:
            def __init__(self) -> None:
                self.timeout: float | None = None

            def get(self, *, timeout: float) -> dict[str, object]:
                self.timeout = timeout
                return {"id": 9, "result": {}}

        process = Process()
        received = Received()
        with patch.object(wiring.time, "monotonic", return_value=10.0):
            result = _rpc(
                process, received, 9, "initialize", {}, timeout_seconds=1,
                deadline=20.0,
            )
        self.assertEqual(result, {"id": 9, "result": {}})
        self.assertIsNotNone(received.timeout)
        self.assertGreater(received.timeout, 5.0)

    def test_app_server_probe_shares_one_deadline_across_sessions(self) -> None:
        session_calls: list[dict[str, object]] = []
        skills = {"data": [{"skills": [], "errors": []}]}
        catalog = {
            "server_count": 1,
            "servers": [{
                "name": wiring.SERVER_NAME,
                "tool_names": sorted(wiring.TOOL_NAMES),
                "tools_error_present": False,
            }],
        }

        def fake_session(**kwargs: object) -> tuple[dict[str, object], dict[str, object] | None]:
            session_calls.append(kwargs)
            return skills, None if len(session_calls) == 1 else catalog

        with patch.object(wiring, "_app_server_session", side_effect=fake_session):
            result = _app_server_probe(
                codex_bin=Path("C:/codex.cmd"),
                codex_home=Path("C:/codex-home"),
                candidate_home=Path("C:/candidate-home"),
                temp_dir=Path("C:/temp"),
                candidate=Path("C:/candidate"),
                override=SimpleNamespace(values=()),
                expected_skills=[],
                timeout_seconds=10,
            )

        self.assertEqual(len(session_calls), 2)
        self.assertIsNotNone(session_calls[0]["deadline"])
        self.assertEqual(session_calls[0]["deadline"], session_calls[1]["deadline"])
        self.assertTrue(result["initialize_ok"])


if __name__ == "__main__":
    unittest.main()
