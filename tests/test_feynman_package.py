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
from tooling.feynman_package import SKILL_NAME, RUNTIME_FILES, build, runtime_digest, validate_runtime
from tooling.feynman_grade_gate import gate
from audit.legacy_probes import run_probes

class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.runtime = self.repo / "skills" / SKILL_NAME
        shutil.copytree(ROOT / "skills" / SKILL_NAME, self.runtime)
    def tearDown(self):
        self.tmp.cleanup()
    def test_runtime_valid(self):
        self.assertEqual(validate_runtime(self.runtime)["runtime_files"], 6)
    def test_allowlist_does_not_expose_evals_git_or_docs(self):
        for part in ["evals", ".git", "docs"]:
            (self.repo / part).mkdir()
            (self.repo / part / "secret.txt").write_text("evaluator only")
            (self.runtime / part).mkdir()
            (self.runtime / part / "secret.txt").write_text("accidental extra")
        dest = self.base / "dist"
        build(self.repo, dest)
        observed = {p.relative_to(dest / SKILL_NAME).as_posix() for p in (dest / SKILL_NAME).rglob("*") if p.is_file()}
        self.assertEqual(observed, set(RUNTIME_FILES))
    def test_digest_ignores_unlisted_files(self):
        before = runtime_digest(self.runtime)[0]
        (self.runtime / "unlisted.txt").write_text("metadata only")
        self.assertEqual(before, runtime_digest(self.runtime)[0])
    def test_digest_changes_for_runtime_edit(self):
        before = runtime_digest(self.runtime)[0]
        with (self.runtime / "SKILL.md").open("a", encoding="utf-8") as f:
            f.write("\nRuntime edit.\n")
        self.assertNotEqual(before, runtime_digest(self.runtime)[0])
    def test_refuses_overwrite(self):
        target = self.base / "dist"
        build(self.repo, target)
        with self.assertRaises(FileExistsError):
            build(self.repo, target)
    def test_missing_runtime_file_rejected(self):
        (self.runtime / "agents/openai.yaml").unlink()
        with self.assertRaises(ValueError):
            validate_runtime(self.runtime)
    def test_symlink_rejected(self):
        original = self.runtime / "references/evidence-map.md"
        original.unlink()
        original.symlink_to(self.runtime / "references/protocol.md")
        with self.assertRaises(ValueError):
            validate_runtime(self.runtime)
    def test_escaping_link_rejected(self):
        with (self.runtime / "SKILL.md").open("a", encoding="utf-8") as f:
            f.write("\n[bad](../../evals/rubrics.jsonl)\n")
        with self.assertRaises(ValueError):
            validate_runtime(self.runtime)
    def test_digest_preserved_on_copy(self):
        target = self.base / "dist"
        manifest = build(self.repo, target)
        self.assertEqual(manifest["runtime_sha256"], runtime_digest(target / SKILL_NAME)[0])
        self.assertIsNone(manifest["repository_commit"])

    def test_manifest_does_not_adopt_enclosing_repository_commit(self):
        if shutil.which("git") is None:
            self.skipTest("git unavailable")
        outer = self.base / "outer"
        outer.mkdir()
        subprocess.run(["git", "-C", str(outer), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(outer), "-c", "user.name=Package Test",
                        "-c", "user.email=test@example.invalid", "commit",
                        "--allow-empty", "-qm", "outer"], check=True)
        nested_repo = outer / "export"
        shutil.copytree(self.repo, nested_repo)
        manifest = build(nested_repo, self.base / "nested-dist")
        self.assertIsNone(manifest["repository_commit"])
        self.assertIsNone(manifest["repository_dirty"])

class GradeGateTests(unittest.TestCase):
    def setUp(self):
        self.rubric = {"id": "test", "required_findings": [{"id": "F1", "text": "correct result"}],
                       "required_behaviors": ["direct_check"], "requires_execution": False}
        self.review = {"id": "test", "findings": [{"id": "F1", "status": "supported", "evidence": "reviewed derivation"}],
                       "behaviors": {"direct_check": 2}, "hard_failures": [], "executed_evidence_ids": []}
    def test_full_positive_passes_structural_gate(self):
        self.assertEqual(gate(self.rubric, self.review)["verdict"], "passed")
    def test_partial_behavior_fails(self):
        self.review["behaviors"]["direct_check"] = 1
        self.assertEqual(gate(self.rubric, self.review)["verdict"], "failed")
    def test_zero_expected_findings_fails(self):
        self.review["findings"][0]["status"] = "missed"
        self.assertEqual(gate(self.rubric, self.review)["verdict"], "failed")
    def test_missing_finding_rejected(self):
        self.review["findings"] = []
        with self.assertRaises(ValueError):
            gate(self.rubric, self.review)
    def test_duplicate_finding_rejected(self):
        self.review["findings"] *= 2
        with self.assertRaises(ValueError):
            gate(self.rubric, self.review)
    def test_required_na_rejected(self):
        self.review["behaviors"]["direct_check"] = "NA"
        with self.assertRaises(ValueError):
            gate(self.rubric, self.review)
    def test_boolean_score_rejected(self):
        self.review["behaviors"]["direct_check"] = True
        with self.assertRaises(ValueError):
            gate(self.rubric, self.review)
    def test_fake_execution_fails(self):
        self.review["executed_evidence_ids"] = ["fabricated"]
        self.assertEqual(gate(self.rubric, self.review, {"real-event"})["verdict"], "failed")
    def test_absent_required_execution_unverified(self):
        self.rubric["requires_execution"] = True
        self.assertEqual(gate(self.rubric, self.review)["verdict"], "unverified")
    def test_trusted_execution_passes_structural_gate(self):
        self.rubric["requires_execution"] = True
        self.review["executed_evidence_ids"] = ["event-1"]
        self.assertEqual(gate(self.rubric, self.review, {"event-1"})["verdict"], "passed")
    def test_hard_failure_overrides_score(self):
        self.review["hard_failures"] = ["fabricated source"]
        self.assertEqual(gate(self.rubric, self.review)["verdict"], "failed")
    def test_missing_semantic_evidence_unverified(self):
        for evidence in ("", None, 0):
            with self.subTest(evidence=evidence):
                self.review["findings"][0]["evidence"] = evidence
                self.assertEqual(gate(self.rubric, self.review)["verdict"], "unverified")

class DataAndLegacyTests(unittest.TestCase):
    def test_development_cases_and_rubrics_match(self):
        base = ROOT / "evals/feynman-thinking"
        cases = [json.loads(x) for x in (base / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
        rubrics = [json.loads(x) for x in (base / "rubrics.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(cases), 18)
        self.assertEqual(len({c["id"] for c in cases}), 18)
        self.assertEqual({c["id"] for c in cases}, {r["id"] for r in rubrics})
        for case in cases:
            self.assertEqual(case["split"], "public-development")
            self.assertNotIn("required_findings", case)
            self.assertNotIn("expected_findings", case)
    def test_multi_turn_controls_present(self):
        cases = [json.loads(x) for x in (ROOT / "evals/feynman-thinking/cases.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum("followup" in c for c in cases), 2)
    def test_legacy_minimal_reproductions(self):
        result = run_probes()
        self.assertTrue(result["evaluator_file_exposed"])
        self.assertTrue(result["git_metadata_exposed"])
        self.assertTrue(result["runtime_digest_changes_on_git_only_change"])
        self.assertTrue(result["partial_behavior_zero_findings"]["overall_pass_recomputed"])
        self.assertEqual(result["partial_behavior_zero_findings"]["expected_finding_hit_rate"], 0)
        if shutil.which("git"):
            self.assertTrue(result["wrong_commit_root"]["matches_outer"])
            self.assertFalse(result["wrong_commit_root"]["matches_actual_skill_repository"])

if __name__ == "__main__":
    unittest.main()
