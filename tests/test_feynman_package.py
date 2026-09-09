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
from tooling.codex_exec_evidence import extract
from tooling.feynman_eval_workspace import prepare
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
            (self.repo / part / "secret.txt").write_text("evaluator only", encoding="utf-8")
            (self.runtime / part).mkdir()
            (self.runtime / part / "secret.txt").write_text("accidental extra", encoding="utf-8")
        dest = self.base / "dist"
        build(self.repo, dest)
        observed = {p.relative_to(dest / SKILL_NAME).as_posix() for p in (dest / SKILL_NAME).rglob("*") if p.is_file()}
        self.assertEqual(observed, set(RUNTIME_FILES))
    def test_digest_ignores_unlisted_files(self):
        before = runtime_digest(self.runtime)[0]
        (self.runtime / "unlisted.txt").write_text("metadata only", encoding="utf-8")
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
        try:
            original.symlink_to(self.runtime / "references/protocol.md")
        except OSError:
            self.skipTest("file symlink privilege unavailable")
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
    def test_review_schema_and_judge_prompt_are_evaluator_only_assets(self):
        base = ROOT / "evals/feynman-thinking"
        schema = json.loads((base / "review-schema.json").read_text(encoding="utf-8"))
        self.assertIn("executed_evidence_ids", schema["required"])
        prompt = (base / "judge-prompt.md").read_text(encoding="utf-8")
        self.assertIn("trusted_execution_ids", prompt)

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


class EvidenceExtractorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.trace = self.base / "trace.jsonl"
    def tearDown(self):
        self.tmp.cleanup()
    def _write(self, events):
        self.trace.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8")
    def test_command_failure_is_trusted_execution_and_reasoning_is_excluded(self):
        self._write([
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "item.completed", "item": {"id": "reason-1", "type": "reasoning", "text": "SECRET_REASONING"}},
            {"type": "item.completed", "item": {"id": "cmd-1", "type": "command_execution",
                "command": "python -m unittest", "aggregated_output": "FAILED: expected 7 got 4",
                "exit_code": 1, "status": "failed"}},
            {"type": "item.completed", "item": {"id": "msg-1", "type": "agent_message", "text": "The test exposed the bug."}},
        ])
        out = self.base / "evidence-bundle"
        index = extract(self.trace, out)
        self.assertEqual(index["trusted_execution_ids"], ["command_execution:cmd-1"])
        self.assertEqual((out / "final.md").read_text(encoding="utf-8"), "The test exposed the bug.")
        copied = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in out.rglob("*") if p.is_file())
        self.assertNotIn("SECRET_REASONING", copied)
        self.assertIn("FAILED: expected 7 got 4", copied)
    def test_declined_command_is_recorded_but_not_trusted_as_executed(self):
        self._write([{"type": "item.completed", "item": {"id": "cmd-1", "type": "command_execution",
                     "command": "pytest", "aggregated_output": "", "status": "declined"}}])
        index = extract(self.trace, self.base / "bundle")
        self.assertEqual(index["trusted_execution_ids"], [])
        self.assertEqual(index["records"][0]["status"], "declined")
    def test_malformed_jsonl_is_rejected_and_partial_bundle_removed(self):
        self.trace.write_text('{"type":"item.completed"}\nnot-json\n', encoding="utf-8")
        out = self.base / "bundle"
        with self.assertRaises(ValueError):
            extract(self.trace, out)
        self.assertFalse(out.exists())
    def test_duplicate_completed_evidence_id_is_rejected(self):
        event = {"type": "item.completed", "item": {"id": "dup", "type": "web_search", "query": "query"}}
        self._write([event, event])
        with self.assertRaises(ValueError):
            extract(self.trace, self.base / "bundle")
    def test_mcp_payload_is_evaluator_side_evidence(self):
        self._write([{"type": "item.completed", "item": {"id": "mcp-1", "type": "mcp_tool_call",
                     "server": "fixture", "tool": "read", "arguments": {"x": 1},
                     "result": {"content": [{"type": "text", "text": "observed"}]}, "status": "completed"}}])
        index = extract(self.trace, self.base / "bundle")
        self.assertEqual(index["records"][0]["kind"], "mcp_tool_call")
        payload = self.base / "bundle" / "evidence" / index["records"][0]["payload"]["file"]
        self.assertIn("observed", payload.read_text(encoding="utf-8"))

class EvalWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def test_candidate_workspace_excludes_rubric_and_includes_allowlisted_skill(self):
        candidate = self.base / "candidate"
        evaluator = self.base / "evaluator"
        record = prepare(ROOT, "translation-13", candidate, evaluator, install_skill=True)
        self.assertTrue((candidate / ".agents/skills/feynman-thinking/SKILL.md").is_file())
        self.assertTrue((evaluator / "case.json").is_file())
        self.assertIn("rubric", json.loads((evaluator / "case.json").read_text(encoding="utf-8")))
        self.assertTrue((evaluator / "review-schema.json").is_file())
        self.assertTrue((evaluator / "judge-prompt.md").is_file())
        candidate_text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                                   for p in candidate.rglob("*") if p.is_file())
        self.assertNotIn("required_findings", candidate_text)
        self.assertNotIn("rubrics.jsonl", candidate_text)
        self.assertTrue(record["skill_installed"])
    def test_fixture_is_copied_without_evaluator_rubric(self):
        candidate = self.base / "candidate"
        evaluator = self.base / "evaluator"
        prepare(ROOT, "tools-10", candidate, evaluator)
        self.assertTrue((candidate / "candidate.py").is_file())
        self.assertTrue((candidate / "test_candidate.py").is_file())
        self.assertFalse((candidate / "case.json").exists())
    def test_followup_is_withheld_from_initial_candidate_workspace(self):
        candidate = self.base / "candidate"
        evaluator = self.base / "evaluator"
        prepare(ROOT, "revise-08", candidate, evaluator)
        task = (candidate / "task.txt").read_text(encoding="utf-8")
        case_record = json.loads((evaluator / "case.json").read_text(encoding="utf-8"))
        self.assertNotIn("교정 후 안정 처리량", task)
        self.assertIn("교정 후 안정 처리량", case_record["followup"])
    def test_no_skill_condition_has_no_agent_skill(self):
        candidate = self.base / "candidate"
        evaluator = self.base / "evaluator"
        record = prepare(ROOT, "mechanism-01", candidate, evaluator, install_skill=False)
        self.assertFalse((candidate / ".agents").exists())
        self.assertFalse(record["skill_installed"])
    def test_candidate_and_evaluator_cannot_contain_one_another(self):
        with self.assertRaises(ValueError):
            prepare(ROOT, "mechanism-01", self.base / "run", self.base / "run/evaluator")

    def test_candidate_workspace_cannot_be_built_inside_source_repository(self):
        with self.assertRaises(ValueError):
            prepare(ROOT, "mechanism-01", ROOT / ".runtime-preview/test-candidate", self.base / "evaluator")

    def test_fixture_symlink_is_rejected(self):
        repo = self.base / "repo-copy"
        shutil.copytree(ROOT / "skills", repo / "skills")
        shutil.copytree(ROOT / "evals", repo / "evals")
        fixture = repo / "evals/feynman-thinking/fixtures/mechanism-01"
        fixture.mkdir(parents=True)
        link = fixture / "leak.txt"
        try:
            link.symlink_to(repo / "evals/feynman-thinking/rubrics.jsonl")
        except OSError:
            self.skipTest("symlink unavailable")
        with self.assertRaises(ValueError):
            prepare(repo, "mechanism-01", self.base / "candidate-symlink", self.base / "evaluator-symlink")

if __name__ == "__main__":
    unittest.main()
