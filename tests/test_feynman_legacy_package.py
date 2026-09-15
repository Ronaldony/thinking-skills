from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_legacy_package import build


class LegacyPackageTests(unittest.TestCase):
    def setUp(self):
        if shutil.which("git") is None:
            self.skipTest("git unavailable")
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.legacy = self.base / "legacy"
        self.legacy.mkdir()
        (self.legacy / "agents").mkdir()
        (self.legacy / "assets").mkdir()
        (self.legacy / "references").mkdir()
        (self.legacy / "evals").mkdir()
        (self.legacy / "scripts").mkdir()
        (self.legacy / "SKILL.md").write_text(
            "---\nname: feynman-thinking\nmetadata:\n  version: \"0.4.0\"\n---\n"
            "# legacy\n- [runtime](references/evidence-base.md)\n"
            "- 행동 평가와 A/B/C 비교: [references/evaluation.md](references/evaluation.md)\n",
            encoding="utf-8")
        (self.legacy / "agents/openai.yaml").write_text("policy: {}\n", encoding="utf-8")
        (self.legacy / "assets/model.md").write_text("runtime asset\n", encoding="utf-8")
        (self.legacy / "references/evidence-base.md").write_text("runtime reference\n", encoding="utf-8")
        (self.legacy / "references/evaluation.md").write_text("evaluator design\n", encoding="utf-8")
        (self.legacy / "evals/answers.jsonl").write_text('{"expected":"secret"}\n', encoding="utf-8")
        (self.legacy / "scripts/grade.py").write_text("print('grade')\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.legacy), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.legacy), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.legacy), "-c", "user.name=Legacy Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
        self.commit = subprocess.check_output(
            ["git", "-C", str(self.legacy), "rev-parse", "HEAD"], text=True).strip()

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_clean_package_excludes_eval_harness_and_records_sanitization(self):
        out = self.base / "out"
        manifest = build(self.legacy, out, expected_commit=self.commit)
        runtime = out / "feynman-thinking"
        self.assertTrue((runtime / "SKILL.md").is_file())
        self.assertTrue((runtime / "references/evidence-base.md").is_file())
        self.assertFalse((runtime / "references/evaluation.md").exists())
        self.assertFalse((runtime / "evals").exists())
        self.assertFalse((runtime / "scripts").exists())
        self.assertFalse((runtime / ".git").exists())
        self.assertNotIn("references/evaluation.md", (runtime / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_commit"], self.commit)
        self.assertEqual(manifest["comparison_condition"], "legacy-clean")
        self.assertIn("references/evaluation.md", manifest["sanitization"]["excluded_files"])

    def test_wrong_commit_is_rejected(self):
        with self.assertRaises(ValueError):
            build(self.legacy, self.base / "out", expected_commit="0" * 40)

    def test_dirty_checkout_is_rejected(self):
        (self.legacy / "SKILL.md").write_text((self.legacy / "SKILL.md").read_text(encoding="utf-8") + "dirty\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            build(self.legacy, self.base / "out", expected_commit=self.commit)

    def test_evaluation_reference_drift_is_rejected(self):
        text = (self.legacy / "SKILL.md").read_text(encoding="utf-8").replace(
            "- 행동 평가와 A/B/C 비교: [references/evaluation.md](references/evaluation.md)\n", "")
        (self.legacy / "SKILL.md").write_text(text, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.legacy), "add", "SKILL.md"], check=True)
        subprocess.run(["git", "-C", str(self.legacy), "-c", "user.name=Legacy Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "drift"], check=True)
        drift_commit = subprocess.check_output(
            ["git", "-C", str(self.legacy), "rev-parse", "HEAD"], text=True).strip()
        with self.assertRaises(ValueError):
            build(self.legacy, self.base / "out", expected_commit=drift_commit)

    def test_runtime_symlink_is_rejected(self):
        target = self.legacy / "assets/model.md"
        target.unlink()
        try:
            target.symlink_to(self.legacy / "references/evidence-base.md")
        except OSError:
            self.skipTest("symlink unavailable")
        subprocess.run(["git", "-C", str(self.legacy), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.legacy), "-c", "user.name=Legacy Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "symlink"], check=True)
        commit = subprocess.check_output(
            ["git", "-C", str(self.legacy), "rev-parse", "HEAD"], text=True).strip()
        with self.assertRaises(ValueError):
            build(self.legacy, self.base / "out", expected_commit=commit)


if __name__ == "__main__":
    unittest.main()
