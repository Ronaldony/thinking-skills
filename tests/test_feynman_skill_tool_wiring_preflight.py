from __future__ import annotations

import unittest
from pathlib import Path

from tooling.feynman_skill_tool_wiring_preflight import _skill_disable_override, _summarize_skills


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


if __name__ == "__main__":
    unittest.main()
