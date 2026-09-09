from __future__ import annotations

from pathlib import Path
import os
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_eval_preflight import preflight
from tooling.feynman_eval_workspace import prepare


class EvalPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.home = self.base / "isolated-home"
        self.codex_home = self.base / "isolated-codex-home"
        self.home.mkdir()
        self.codex_home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipIf(os.name == "nt" and (Path.home() / ".agents" / "skills").exists(),
                     "Windows temp fixtures inherit the active user's ambient skill root")
    def test_skill_condition_passes_with_only_expected_candidate_skill(self):
        candidate = self.base / "runs" / "candidate"
        evaluator = self.base / "evaluator"
        candidate.parent.mkdir()
        prepare(ROOT, "mechanism-01", candidate, evaluator, install_skill=True)
        result = preflight(candidate, {"feynman-thinking"}, home=self.home,
                           codex_home=self.codex_home)
        self.assertEqual(result["expected_candidate_skills"], ["feynman-thinking"])
        self.assertEqual(set(result["observed_candidate_skills"]), {"feynman-thinking"})

    @unittest.skipIf(os.name == "nt" and (Path.home() / ".agents" / "skills").exists(),
                     "Windows temp fixtures inherit the active user's ambient skill root")
    def test_baseline_passes_with_no_candidate_skill(self):
        candidate = self.base / "runs" / "candidate"
        evaluator = self.base / "evaluator"
        candidate.parent.mkdir()
        prepare(ROOT, "mechanism-01", candidate, evaluator, install_skill=False)
        result = preflight(candidate, set(), home=self.home, codex_home=self.codex_home)
        self.assertEqual(result["observed_candidate_skills"], {})

    def test_user_home_skill_contamination_fails(self):
        candidate = self.base / "runs" / "candidate"
        evaluator = self.base / "evaluator"
        candidate.parent.mkdir()
        prepare(ROOT, "mechanism-01", candidate, evaluator, install_skill=False)
        rogue = self.home / ".agents" / "skills" / "rogue"
        rogue.mkdir(parents=True)
        (rogue / "SKILL.md").write_text("---\nname: rogue\ndescription: rogue\n---\n")
        with self.assertRaises(ValueError):
            preflight(candidate, set(), home=self.home, codex_home=self.codex_home)

    def test_codex_home_skill_contamination_fails(self):
        candidate = self.base / "runs" / "candidate"
        evaluator = self.base / "evaluator"
        candidate.parent.mkdir()
        prepare(ROOT, "mechanism-01", candidate, evaluator, install_skill=False)
        rogue = self.codex_home / "skills" / "rogue"
        rogue.mkdir(parents=True)
        (rogue / "SKILL.md").write_text("---\nname: rogue\ndescription: rogue\n---\n")
        with self.assertRaises(ValueError):
            preflight(candidate, set(), home=self.home, codex_home=self.codex_home)

    def test_ancestor_project_skill_contamination_fails(self):
        parent = self.base / "runs"
        candidate = parent / "candidate"
        evaluator = self.base / "evaluator"
        parent.mkdir()
        prepare(ROOT, "mechanism-01", candidate, evaluator, install_skill=False)
        rogue = parent / ".agents" / "skills" / "rogue"
        rogue.mkdir(parents=True)
        (rogue / "SKILL.md").write_text("---\nname: rogue\ndescription: rogue\n---\n")
        with self.assertRaises(ValueError):
            preflight(candidate, set(), home=self.home, codex_home=self.codex_home)

    def test_unexpected_candidate_skill_fails(self):
        candidate = self.base / "runs" / "candidate"
        evaluator = self.base / "evaluator"
        candidate.parent.mkdir()
        prepare(ROOT, "mechanism-01", candidate, evaluator, install_skill=True)
        rogue = candidate / ".agents" / "skills" / "rogue"
        rogue.mkdir(parents=True)
        (rogue / "SKILL.md").write_text("---\nname: rogue\ndescription: rogue\n---\n")
        with self.assertRaises(ValueError):
            preflight(candidate, {"feynman-thinking"}, home=self.home,
                      codex_home=self.codex_home)

    def test_preregistration_document_remains_explicitly_pre_result(self):
        text = (ROOT / "evals" / "feynman-thinking" / "preregister.md").read_text(encoding="utf-8")
        self.assertIn("no behavioral results yet", text)
        self.assertIn("public-development", (ROOT / "evals" / "feynman-thinking" / "cases.jsonl").read_text(encoding="utf-8"))
        self.assertIn("HOME과 CODEX_HOME", text)


if __name__ == "__main__":
    unittest.main()
