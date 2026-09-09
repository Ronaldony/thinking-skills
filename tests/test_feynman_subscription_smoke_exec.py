from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tooling import feynman_subscription_smoke_exec as executor

CONFIG_TEXT = executor.CONFIG_TEXT
AUTH_CALLS = []
PREFLIGHT_CALLS = []


def fake_auth(control_home: Path, codex_bin: str = "codex", timeout_seconds: int = 20):
    AUTH_CALLS.append((Path(control_home), codex_bin, timeout_seconds))
    return {"verdict": "chatgpt-subscription-authenticated", "codex_cli": "codex-cli fake 1.0"}


def fake_preflight(**kwargs):
    PREFLIGHT_CALLS.append(kwargs)
    return {"verdict": "ready-for-local-chatgpt-session-check"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SubscriptionSmokeExecTests(unittest.TestCase):
    def setUp(self):
        AUTH_CALLS.clear(); PREFLIGHT_CALLS.clear()
        self.env_patch = patch.dict(os.environ, {"GITHUB_ACTIONS": ""}, clear=False)
        self.preflight_patch = patch.object(executor, "preflight_files", side_effect=fake_preflight)
        self.auth_patch = patch.object(executor, "check_auth", side_effect=fake_auth)
        self.env_patch.start(); self.preflight_patch.start(); self.auth_patch.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.candidate = self.base / "candidate"; self.evaluator = self.base / "evaluator"; self.control = self.base / "control-codex-home"
        self.candidate.mkdir(); self.evaluator.mkdir(); self.control.mkdir()
        (self.control / "config.toml").write_text(CONFIG_TEXT, encoding="utf-8")
        self.remote = self.control / "environments.toml"; self.remote.write_text('default = "candidate"\ninclude_local = false\n', encoding="utf-8")
        (self.candidate / "task.txt").write_text("RUN THIS EXACT TASK\n", encoding="utf-8")

        self.smoke_spec = self.base / "subscription-smoke-spec.json"
        self.smoke_spec.write_text(json.dumps({
            "schema_version": 2, "purpose": "integration-only-chatgpt-subscription-smoke",
            "analysis_use": "not-for-skill-performance-inference", "cases": ["tools-10"],
            "conditions": ["baseline", "feynman-v05"], "repeats": 1, "seed": 20260908,
            "authentication_mode": "chatgpt-subscription", "control_plane_auth_source": "codex-session",
            "api_key_auth_allowed": False, "requires_trusted_local_or_self_hosted_control_plane": True,
            "model_reasoning_effort_policy": "model-default",
        }), encoding="utf-8")
        self.plan = self.base / "plan.json"
        self.plan.write_text(json.dumps({
            "analysis_use": "not-for-skill-performance-inference", "authentication_mode": "chatgpt-subscription",
            "api_key_auth_allowed": False, "model_reasoning_effort_policy": "model-default",
            "smoke_spec_sha256": sha(self.smoke_spec),
            "jobs": [
                {"ordinal": 1, "case_id": "tools-10", "condition": "baseline", "repeat": 1, "has_followup": False},
                {"ordinal": 2, "case_id": "tools-10", "condition": "feynman-v05", "repeat": 1, "has_followup": False},
            ],
        }), encoding="utf-8")
        self.eval_case = self.base / "case.json"; self.eval_case.write_text('{"case_id":"tools-10"}', encoding="utf-8")
        self.profile = self.base / "profile.json"; self.profile.write_text('{"schema_version":1}', encoding="utf-8")
        self.job = self.base / "runner-job.json"
        self.job.write_text(json.dumps({
            "schema_version": 3, "run_id": "smoke-baseline-1",
            "job": {"ordinal": 1, "case_id": "tools-10", "condition_id": "baseline", "repeat": 1, "has_followup": False},
            "versions": {"model": "gpt-test", "codex_cli": "codex-cli fake 1.0"},
            "paths": {"candidate_dir": str(self.candidate.resolve()), "evaluator_dir": str(self.evaluator.resolve()), "control_codex_home": str(self.control.resolve())},
        }), encoding="utf-8")
        self.state = self.base / "fake-codex-state.json"; self.codex = self.base / "fake-codex"; self._write_fake_codex(success=True)

    def tearDown(self):
        self.auth_patch.stop(); self.preflight_patch.stop(); self.env_patch.stop(); self.tmp.cleanup()

    def _write_fake_codex(self, *, success: bool, failed_event: bool = False):
        code = f'''#!/usr/bin/env python3
import json, os, pathlib, sys
state=pathlib.Path({str(self.state)!r});args=sys.argv[1:]
if not args or args[0]!="exec": raise SystemExit(90)
prompt=sys.stdin.read();state.write_text(json.dumps({{"argv":args,"env":dict(os.environ),"prompt":prompt}},sort_keys=True),encoding="utf-8")
print(json.dumps({{"type":"thread.started","thread_id":"thread-smoke-1"}}));print(json.dumps({{"type":"turn.started"}}))
'''
        if failed_event: code += 'print(json.dumps({"type":"turn.failed","error":{"message":"fake"}}))\n'
        elif success:
            code += 'print(json.dumps({"type":"item.completed","item":{"id":"m1","type":"agent_message","text":"FAKE_SMOKE_OK"}}))\n'
            code += 'print(json.dumps({"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":3}}))\n'
        code += f'raise SystemExit({0 if success else 7})\n'
        self.codex.write_text(code, encoding="utf-8"); self.codex.chmod(0o755)

    def _run(self, **overrides):
        kwargs = dict(plan_path=self.plan, smoke_spec_path=self.smoke_spec, ordinal=1, evaluator_case_path=self.eval_case,
                      runner_job_path=self.job, boundary_profile_path=self.profile, remote_environment_path=self.remote,
                      output_dir=self.evaluator / "exec-1", codex_bin=str(self.codex), timeout_seconds=60)
        kwargs.update(overrides); return executor.execute_smoke_job(**kwargs)

    def test_success_uses_scrubbed_env_and_frozen_controls(self):
        result = self._run(); state = json.loads(self.state.read_text())
        self.assertEqual(result["verdict"], "subscription-codex-smoke-exec-completed")
        self.assertEqual(result["versions"]["model_reasoning_effort"], "model-default")
        self.assertEqual(result["conversation"]["thread_id"], "thread-smoke-1"); self.assertFalse(result["privacy"]["stderr_nonempty"])
        self.assertIn("smoke_spec_sha256", result["digests"]); self.assertNotIn("stderr_sha256", result["digests"])
        self.assertEqual((self.evaluator / "exec-1" / "candidate-final.txt").read_text(), "FAKE_SMOKE_OK")
        argv = state["argv"]
        for flag in ("--json", "--ephemeral", "--strict-config", "--ignore-rules", "--skip-git-repo-check"): self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write"); self.assertEqual(argv[argv.index("--model") + 1], "gpt-test")
        self.assertIn('web_search="disabled"', argv); self.assertEqual(state["prompt"], "RUN THIS EXACT TASK\n")
        self.assertTrue({"HOME", "CODEX_HOME", "PATH", "TMPDIR"}.issubset(state["env"]))
        self.assertTrue(set(state["env"]) <= {"HOME", "CODEX_HOME", "PATH", "TMPDIR", "LC_CTYPE"})
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"): self.assertNotIn(key, state["env"])
        self.assertFalse(Path(state["env"]["TMPDIR"]).exists()); self.assertEqual(len(AUTH_CALLS), 1); self.assertEqual(len(PREFLIGHT_CALLS), 1)

    def test_retired_auth_envs_are_rejected(self):
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
            with self.subTest(key=key), patch.dict(os.environ, {key: "forbidden"}, clear=False):
                with self.assertRaises(ValueError): self._run(output_dir=self.evaluator / f"out-{key}")

    def test_github_actions_is_rejected(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=False):
            with self.assertRaises(ValueError): self._run()

    def test_control_config_and_remote_path_are_exact(self):
        (self.control / "config.toml").write_text('forced_login_method = "api"\n', encoding="utf-8")
        with self.assertRaises(ValueError): self._run()
        (self.control / "config.toml").write_text(CONFIG_TEXT, encoding="utf-8"); other = self.base / "elsewhere.toml"; other.write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError): self._run(remote_environment_path=other)

    def test_smoke_spec_reasoning_and_raw_bytes_are_bound(self):
        plan = json.loads(self.plan.read_text()); plan["model_reasoning_effort_policy"] = "high"; self.plan.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaises(ValueError): self._run()
        plan["model_reasoning_effort_policy"] = "model-default"; plan["smoke_spec_sha256"] = "f" * 64; self.plan.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaises(ValueError): self._run()

    def test_mock_model_and_candidate_project_config_are_rejected(self):
        job = json.loads(self.job.read_text()); job["versions"]["model"] = "mock-model"; self.job.write_text(json.dumps(job), encoding="utf-8")
        with self.assertRaises(ValueError): self._run()
        job["versions"]["model"] = "gpt-test"; self.job.write_text(json.dumps(job), encoding="utf-8"); (self.candidate / ".codex").mkdir()
        with self.assertRaises(ValueError): self._run()

    def test_output_must_be_new_and_under_evaluator(self):
        with self.assertRaises(ValueError): self._run(output_dir=self.base / "outside")
        out = self.evaluator / "exec-1"; out.mkdir()
        with self.assertRaises(ValueError): self._run()

    def test_evaluator_and_control_home_must_be_disjoint(self):
        nested = self.evaluator / "control"; nested.mkdir(); (nested / "config.toml").write_text(CONFIG_TEXT, encoding="utf-8"); (nested / "environments.toml").write_text("x", encoding="utf-8")
        job = json.loads(self.job.read_text()); job["paths"]["control_codex_home"] = str(nested.resolve()); self.job.write_text(json.dumps(job), encoding="utf-8")
        with self.assertRaises(ValueError): self._run(remote_environment_path=nested / "environments.toml")

    def test_authenticated_cli_and_structural_preflight_are_mandatory(self):
        with patch.object(executor, "check_auth", return_value={"verdict":"chatgpt-subscription-authenticated", "codex_cli":"other"}):
            with self.assertRaises(ValueError): self._run()
        with patch.object(executor, "preflight_files", return_value={"verdict":"blocked"}):
            with self.assertRaises(ValueError): self._run()

    def test_nonzero_and_failed_trace_do_not_promote_result(self):
        self._write_fake_codex(success=False)
        with self.assertRaises(ValueError): self._run()
        out = self.evaluator / "exec-1"; self.assertTrue((out / "codex-trace.jsonl").exists()); self.assertFalse((out / "subscription-exec-result.json").exists()); self.assertFalse((out / ".control-tmp").exists())
        out.rename(self.evaluator / "failed-nonzero"); self._write_fake_codex(success=True, failed_event=True)
        with self.assertRaises(ValueError): self._run()
        self.assertFalse((self.evaluator / "exec-1" / "subscription-exec-result.json").exists())


class SubscriptionSmokeExecSchemaTests(unittest.TestCase):
    def test_schema_tracks_privacy_and_reasoning_policy(self):
        schema = json.loads((ROOT / "evals" / "feynman-thinking" / "subscription-smoke-exec-result.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        digests = schema["properties"]["digests"]; self.assertIn("smoke_spec_sha256", digests["required"]); self.assertNotIn("stderr_sha256", digests["properties"])
        self.assertEqual(schema["properties"]["versions"]["properties"]["model_reasoning_effort"]["const"], "model-default")
        self.assertIn("stderr_nonempty", schema["properties"]["privacy"]["required"])


if __name__ == "__main__": unittest.main()
