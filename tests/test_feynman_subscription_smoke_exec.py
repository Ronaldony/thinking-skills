from __future__ import annotations

import hashlib
import io
import json
import os
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tooling import feynman_subscription_smoke_exec as executor
from tooling import feynman_subscription_startup_diagnostic as startup_module
from tooling.feynman_rpc_path_proxy import _ProxyTelemetry

CONFIG_TEXT = executor.CONFIG_TEXT
AUTH_CALLS = []
PREFLIGHT_CALLS = []


def fake_auth(control_home: Path, codex_bin: str = "codex", timeout_seconds: int = 20):
    AUTH_CALLS.append((Path(control_home), codex_bin, timeout_seconds))
    return {"verdict": "chatgpt-subscription-authenticated", "codex_cli": "codex-cli fake 1.0"}


def fake_preflight(**kwargs):
    PREFLIGHT_CALLS.append(kwargs)
    return {
        "verdict": "ready-for-local-chatgpt-session-check",
        "preflight": {"candidate_skill_preflight_valid": True},
    }


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
        self.state = self.base / "fake-codex-state.json"
        self.codex = self.base / ("fake-codex.cmd" if os.name == "nt" else "fake-codex")
        self._write_fake_codex(success=True)
        self.full_runner_binding = self.base / "binding.json"
        self.full_runner_binding.write_text("{}", encoding="utf-8")
        self.full_runner_node_bin = self.base / "node.bin"
        self.full_runner_node_bin.write_text("synthetic node", encoding="utf-8")
        self.full_runner_adapter = self.base / "adapter.mjs"
        self.full_runner_adapter.write_text("synthetic adapter", encoding="utf-8")
        self.full_runner_docker_bin = self.base / "docker.bin"
        self.full_runner_docker_bin.write_text("synthetic docker", encoding="utf-8")
        self.full_runner_docker_config = self.base / "docker-config"
        self.full_runner_docker_config.mkdir()
        self.startup_call = None
        self.control_call = None

    def tearDown(self):
        self.auth_patch.stop(); self.preflight_patch.stop(); self.env_patch.stop(); self.tmp.cleanup()

    def _write_fake_codex(self, *, success: bool, failed_event: bool = False,
                          tool_item_type: str | None = None):
        code = f'''#!/usr/bin/env python3
import json, os, pathlib, sys
state=pathlib.Path({str(self.state)!r});args=sys.argv[1:]
if not args or args[0]!="exec": raise SystemExit(90)
prompt=sys.stdin.read();state.write_text(json.dumps({{"argv":args,"env":dict(os.environ),"prompt":prompt}},sort_keys=True),encoding="utf-8")
print(json.dumps({{"type":"thread.started","thread_id":"thread-smoke-1"}}));print(json.dumps({{"type":"turn.started"}}))
'''
        if failed_event: code += 'print(json.dumps({"type":"turn.failed","error":{"message":"fake"}}))\n'
        elif success:
            if tool_item_type:
                code += f'print(json.dumps({{"type":"item.completed","item":{{"id":"t1","type":{tool_item_type!r}}}}}))\n'
            code += 'print(json.dumps({"type":"item.completed","item":{"id":"m1","type":"agent_message","text":"FAKE_SMOKE_OK"}}))\n'
            code += 'print(json.dumps({"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":3}}))\n'
        code += f'raise SystemExit({0 if success else 7})\n'
        if os.name == "nt":
            script = self.base / "fake-codex.py"
            script.write_text(code, encoding="utf-8")
            self.codex.write_text(
                f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
                encoding="utf-8",
            )
        else:
            self.codex.write_text(code, encoding="utf-8"); self.codex.chmod(0o755)

    def _fake_startup(self, **kwargs):
        telemetry = _ProxyTelemetry().snapshot()
        telemetry.update({
            "request_methods": {"initialize": 1, "thread/start": 1},
            "requests_seen": 2,
            "requests_forwarded": 2,
            "responses_seen": 2,
            "responses_forwarded": 2,
            "responses_matched": 2,
            "child_exit_code": 0,
        })
        gate = {
            "schema_version": 3,
            "preparation_fingerprint": kwargs.get(
                "prepared_wiring", {"preparation_fingerprint": "a" * 64}
            )["preparation_fingerprint"],
            "verdict": "subscription-startup-thread-ready",
            "model": "gpt-test",
            "checks": {
                "initialize_completed": True,
                "thread_started": True,
                "ephemeral_thread": True,
                "instruction_sources_present": True,
                "instruction_sources_allowed": True,
                "response_payload_preserved": False,
                "process_tree_reaped": True,
                "cleanup_verified": True,
                "proxy_telemetry_complete": True,
                "proxy_request_response_correlated": True,
                "request_mapping_clean": True,
                "error_code": None,
                "error_category": None,
                "error_signals": {
                    "mentions_environment": False,
                    "mentions_exec_server": False,
                    "mentions_connection": False,
                    "mentions_initialize": False,
                    "mentions_exit": False,
                    "mentions_closed": False,
                    "mentions_timeout": False,
                    "mentions_config": False,
                    "mentions_path": False,
                    "mentions_not_found": False,
                },
                "error_data_kind": "none",
                "turn_requests_sent": 0,
                "model_generation_requests_sent": 0,
            },
            "notification_methods": {},
            "proxy_telemetry_status": "available",
            "proxy_telemetry": telemetry,
            "privacy": {
                "request_or_response_payload_preserved": False,
                "thread_id_preserved": False,
                "instruction_source_paths_preserved": False,
                "raw_stderr_preserved": False,
                "credential_files_directly_read_by_probe": False,
                "control_home_contents_serialized": False,
            },
            "scope": "synthetic startup evidence for executor boundary testing",
        }
        self.startup_call = kwargs
        telemetry_path = Path(kwargs["telemetry_path"])
        report_path = Path(kwargs["output_path"])
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        telemetry_path.write_text(json.dumps(gate["proxy_telemetry"]), encoding="utf-8")
        report_path.write_text(json.dumps(gate), encoding="utf-8")
        return gate

    def _fake_control(self, **kwargs):
        self.control_call = kwargs
        return {"verdict": "subscription-control-plane-ready"}

    def _run(self, *, with_full_runner=True, startup_runner=None,
             control_runner=None, real_startup=False, prepared_wiring=None,
             **overrides):
        kwargs = dict(plan_path=self.plan, smoke_spec_path=self.smoke_spec, ordinal=1, evaluator_case_path=self.eval_case,
                      runner_job_path=self.job, boundary_profile_path=self.profile, remote_environment_path=self.remote,
                      output_dir=self.evaluator / "exec-1", codex_bin=str(self.codex), timeout_seconds=60)
        if with_full_runner:
            kwargs.update(
                full_runner_binding_path=self.full_runner_binding,
                full_runner_node_bin=self.full_runner_node_bin,
                full_runner_adapter=self.full_runner_adapter,
                full_runner_docker_bin=self.full_runner_docker_bin,
                full_runner_docker_config=self.full_runner_docker_config,
                full_runner_image_id="sha256:" + "a" * 64,
            )
        kwargs.update(overrides)
        with ExitStack() as stack:
            if with_full_runner:
                prepared = prepared_wiring or {
                    "full_runner_override": object(),
                    "all_config_overrides": (),
                    "skill_config_overrides": (),
                    "command": executor.build_codex_exec_command(
                        executable=str(self.codex), model="gpt-test",
                        candidate_dir=self.candidate,
                    ),
                    "app_server": {},
                    "preparation_fingerprint": "a" * 64,
                }
                stack.enter_context(patch.object(
                    executor, "prepare_full_runner_executor_wiring",
                    return_value=prepared,
                ))
                stack.enter_context(patch(
                    "tooling.feynman_subscription_control_plane_preflight.run",
                    side_effect=control_runner or self._fake_control,
                ))
                if real_startup:
                    stack.enter_context(patch.object(
                        startup_module, "validate_checkpoint", return_value={}))
                    stack.enter_context(patch.object(
                        startup_module, "validate_files",
                        return_value={"verdict": "remote-exec-environment-valid"}))
                    stack.enter_context(patch.object(
                        startup_module, "_validate_control_files",
                        return_value=(self.control, self.remote)))

                    telemetry = _ProxyTelemetry().snapshot()
                    telemetry.update({
                        "request_methods": {"initialize": 1, "thread/start": 1},
                        "requests_seen": 2, "requests_forwarded": 2,
                        "responses_seen": 2, "responses_forwarded": 2,
                        "responses_matched": 2, "child_exit_code": 0,
                    })

                    class FakeAppServerProcess:
                        def __init__(self, env):
                            self.stdin = io.BytesIO()
                            self.stdout = io.BytesIO(
                                b'{"id":1,"result":{}}\n'
                                b'{"id":2,"result":{"thread":{"id":"synthetic",'
                                b'"ephemeral":true},"instructionSources":['
                                b'"/run/candidate/AGENTS.md"]}}\n')
                            self.stderr = io.BytesIO()
                            self.returncode = None
                            Path(env[startup_module.TELEMETRY_OVERRIDE_ENV]).write_text(
                                json.dumps(telemetry), encoding="utf-8")

                        def wait(self, timeout=None):
                            self.returncode = 0
                            return 0

                        def poll(self):
                            return self.returncode

                    real_popen = startup_module.subprocess.Popen

                    def fake_app_server_or_real_process(command, *args, **kwargs):
                        if "app-server" in command:
                            return FakeAppServerProcess(kwargs["env"])
                        return real_popen(command, *args, **kwargs)

                    stack.enter_context(patch.object(
                        startup_module.subprocess, "Popen",
                        side_effect=fake_app_server_or_real_process))
                else:
                    stack.enter_context(patch(
                        "tooling.feynman_subscription_startup_diagnostic.run",
                        side_effect=startup_runner or self._fake_startup,
                    ))
            return executor.execute_smoke_job(**kwargs)

    def _actual_prepared_wiring(self):
        command = executor.build_codex_exec_command(
            executable=str(self.codex.resolve()), model="gpt-test",
            candidate_dir=self.candidate.resolve(),
        )
        fingerprint = executor._wiring_fingerprint(
            resolved_codex=str(self.codex.resolve()), model="gpt-test",
            candidate_dir=self.candidate.resolve(), runner_job_path=self.job.resolve(),
            boundary_profile_path=self.profile.resolve(),
            binding_path=self.full_runner_binding.resolve(),
            node_bin=self.full_runner_node_bin.resolve(),
            adapter=self.full_runner_adapter.resolve(),
            docker_bin=self.full_runner_docker_bin.resolve(),
            docker_config=self.full_runner_docker_config.resolve(),
            docker_image_id="sha256:" + "a" * 64,
            all_config_overrides=(), command=command,
        )
        return {
            "full_runner_override": object(),
            "all_config_overrides": (),
            "skill_config_overrides": (),
            "command": command,
            "app_server": {},
            "preparation_fingerprint": fingerprint,
        }

    def test_startup_artifacts_are_evaluator_owned_and_persisted(self):
        result = self._run()
        self.assertIsNotNone(self.startup_call)
        for field in ("telemetry_path", "output_path"):
            path = Path(self.startup_call[field])
            self.assertTrue(path.is_relative_to(self.evaluator / "exec-1"), path)
            self.assertTrue(path.is_file(), path)
        self.assertEqual(
            result["startup_gate"]["artifacts"]["report"],
            "startup-gate/startup-report.json",
        )
        self.assertIsNotNone(self.control_call)
        self.assertEqual(
            self.control_call["cwd"], self.candidate.resolve(),
        )
        self.assertEqual(
            tuple(self.control_call["config_overrides"]),
            tuple(self.startup_call["prepared_wiring"]["all_config_overrides"]),
        )
        self.assertEqual(
            self.startup_call["prepared_wiring"]["preparation_fingerprint"],
            result["startup_gate"]["preparation_fingerprint"],
        )
        spec_path = self.evaluator / "exec-1" / "execution-spec.json"
        self.assertTrue(spec_path.is_file())
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        execution_spec_schema = json.loads(
            (ROOT / "evals" / "feynman-thinking" /
             "subscription-execution-spec.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(execution_spec_schema).validate(spec)
        self.assertEqual(spec["verdict"], "subscription-execution-spec-frozen")
        self.assertEqual(result["execution_spec"]["artifact"], "execution-spec.json")
        self.assertEqual(result["execution_spec"]["artifact_sha256"], sha(spec_path))
        result_schema = json.loads(
            (ROOT / "evals" / "feynman-thinking" /
             "subscription-smoke-exec-result.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(result_schema).validate(result)
        self.assertNotIn(str(self.candidate), json.dumps(spec))
        self.assertFalse(spec["paths"]["docker_config_contents_read"])

    def test_smoke_calls_real_startup_and_validator_at_the_boundary(self):
        prepared = self._actual_prepared_wiring()
        result = self._run(real_startup=True, prepared_wiring=prepared)
        report = self.evaluator / "exec-1" / "startup-gate" / "startup-report.json"
        telemetry = self.evaluator / "exec-1" / "startup-gate" / "startup-rpc-telemetry.json"
        self.assertTrue(report.is_file())
        self.assertTrue(telemetry.is_file())
        persisted = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(persisted["verdict"], "subscription-startup-thread-ready")
        self.assertEqual(result["startup_gate"]["artifacts"]["report"], "startup-gate/startup-report.json")
        self.assertEqual(result["execution_spec"]["preparation_fingerprint"], prepared["preparation_fingerprint"])
        self.assertEqual(len(AUTH_CALLS), 1)

    def test_model_timeout_is_explicitly_forwarded_without_changing_startup_budget(self):
        calls = []
        original_run = executor.subprocess.run

        def capture(*args, **kwargs):
            calls.append(kwargs.get("timeout"))
            return original_run(*args, **kwargs)

        with patch.object(executor.subprocess, "run", side_effect=capture):
            self._run(timeout_seconds=300)
        self.assertEqual(calls, [300])

    def test_startup_fingerprint_drift_blocks_before_auth_or_model(self):
        def drifted_startup(**kwargs):
            gate = self._fake_startup(**kwargs)
            gate["preparation_fingerprint"] = "b" * 64
            return gate

        with self.assertRaisesRegex(ValueError, "differs from model command"):
            self._run(startup_runner=drifted_startup)
        self.assertEqual(AUTH_CALLS, [])

    def test_execution_spec_drift_blocks_after_control_plane_before_auth(self):
        def mutate_after_control(**kwargs):
            self.candidate.joinpath("task.txt").write_text("DRIFTED\n", encoding="utf-8")
            return self._fake_control(**kwargs)

        with self.assertRaisesRegex(ValueError, "frozen execution spec drift"):
            self._run(control_runner=mutate_after_control)
        self.assertEqual(AUTH_CALLS, [])

    def test_success_uses_scrubbed_env_and_frozen_controls(self):
        result = self._run(); state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(result["verdict"], "subscription-codex-smoke-exec-completed")
        self.assertEqual(result["schema_version"], 3)
        self.assertEqual(result["versions"]["model_reasoning_effort"], "model-default")
        self.assertEqual(result["conversation"]["thread_id"], "thread-smoke-1"); self.assertFalse(result["privacy"]["stderr_nonempty"])
        self.assertEqual(result["candidate_tool_activity"], {
            "completed_tool_item_count": 0,
            "completed_tool_item_types": [],
            "tool_use_verdict": "candidate-tool-use-not-observed",
            "postrun_evidence_eligibility": "blocked-no-candidate-tool-call",
        })
        self.assertIn("smoke_spec_sha256", result["digests"]); self.assertNotIn("stderr_sha256", result["digests"])
        self.assertEqual(result["startup_gate"]["verdict"], "subscription-startup-thread-ready")
        self.assertEqual(
            result["startup_gate"]["artifacts"]["report"],
            "startup-gate/startup-report.json",
        )
        self.assertEqual((self.evaluator / "exec-1" / "candidate-final.txt").read_text(encoding="utf-8"), "FAKE_SMOKE_OK")
        argv = state["argv"]
        for flag in ("--json", "--ephemeral", "--strict-config", "--ignore-rules", "--skip-git-repo-check"): self.assertIn(flag, argv)
        self.assertNotIn("--approve-for-me", argv)
        self.assertIn('approval_policy="never"', argv)
        self.assertEqual(result["execution_controls"]["approval_policy"], "never")
        self.assertNotIn("--ask-for-approval", argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write"); self.assertEqual(argv[argv.index("--model") + 1], "gpt-test")
        self.assertIn('web_search="disabled"', argv); self.assertEqual(state["prompt"], "RUN THIS EXACT TASK\n")
        self.assertTrue({"HOME", "CODEX_HOME", "PATH", "TMPDIR"}.issubset(state["env"]))
        allowed_env = {"HOME", "CODEX_HOME", "PATH", "TMPDIR", "LC_CTYPE"}
        if os.name == "nt":
            allowed_env.update(executor.WINDOWS_SYSTEM_ENV_KEYS)
            allowed_env.update({"USERPROFILE", "TEMP", "TMP"})
            allowed_env.update({"COMSPEC", "PROCESSOR_ARCHITECTURE", "PROMPT", "SYSTEMROOT"})
        self.assertTrue(set(state["env"]) <= allowed_env,
                        sorted(set(state["env"]) - allowed_env))
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"): self.assertNotIn(key, state["env"])
        self.assertFalse(Path(state["env"]["TMPDIR"]).exists()); self.assertEqual(len(AUTH_CALLS), 1); self.assertEqual(len(PREFLIGHT_CALLS), 1)

    def test_startup_gate_generation_count_reads_nested_checks(self):
        self.assertEqual(executor._startup_model_generation_requests({
            "checks": {"model_generation_requests_sent": 0},
        }), 0)
        with self.assertRaises(ValueError):
            executor._startup_model_generation_requests({
                "checks": {"model_generation_requests_sent": 1},
            })

    def test_startup_gate_requires_complete_model_free_evidence(self):
        gate = {
            "schema_version": 3,
            "preparation_fingerprint": "a" * 64,
            "verdict": "subscription-startup-thread-ready",
            "model": "gpt-test",
            "checks": {
                "initialize_completed": True,
                "thread_started": True,
                "ephemeral_thread": True,
                "instruction_sources_present": True,
                "instruction_sources_allowed": True,
                "response_payload_preserved": False,
                "process_tree_reaped": True,
                "cleanup_verified": True,
                "proxy_telemetry_complete": True,
                "proxy_request_response_correlated": True,
                "request_mapping_clean": True,
                "error_code": None,
                "error_category": None,
                "error_signals": {
                    "mentions_environment": False,
                    "mentions_exec_server": False,
                    "mentions_connection": False,
                    "mentions_initialize": False,
                    "mentions_exit": False,
                    "mentions_closed": False,
                    "mentions_timeout": False,
                    "mentions_config": False,
                    "mentions_path": False,
                    "mentions_not_found": False,
                },
                "error_data_kind": "none",
                "turn_requests_sent": 0,
                "model_generation_requests_sent": 0,
            },
            "notification_methods": {},
            "proxy_telemetry_status": "available",
            "proxy_telemetry": {
                **_ProxyTelemetry().snapshot(),
                "request_methods": {"initialize": 1, "thread/start": 1},
                "requests_seen": 2,
                "requests_forwarded": 2,
                "responses_seen": 2,
                "responses_forwarded": 2,
                "responses_matched": 2,
                "child_exit_code": 0,
            },
            "privacy": {
                "request_or_response_payload_preserved": False,
                "thread_id_preserved": False,
                "instruction_source_paths_preserved": False,
                "raw_stderr_preserved": False,
                "credential_files_directly_read_by_probe": False,
                "control_home_contents_serialized": False,
            },
            "scope": "synthetic startup evidence for validator testing",
        }
        executor._validate_startup_gate(gate)
        gate["checks"]["cleanup_verified"] = False
        with self.assertRaisesRegex(ValueError, "evidence is incomplete"):
            executor._validate_startup_gate(gate)

    def test_startup_gate_rejects_empty_telemetry_despite_green_flags(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            gate = self._fake_startup(
                telemetry_path=base / "telemetry.json",
                output_path=base / "startup.json",
            )
            gate["proxy_telemetry"] = {}
            with self.assertRaisesRegex(ValueError, "telemetry schema"):
                executor._validate_startup_gate(gate)

    def test_startup_gate_rejects_notification_only_telemetry(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            gate = self._fake_startup(
                telemetry_path=base / "telemetry.json",
                output_path=base / "startup.json",
            )
            telemetry = gate["proxy_telemetry"]
            telemetry.update({
                "responses_matched": 0,
                "notifications_seen": 2,
            })
            with self.assertRaisesRegex(ValueError, "telemetry is incomplete"):
                executor._validate_startup_gate(gate)

    def test_startup_gate_rejects_inconsistent_telemetry_counts(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            gate = self._fake_startup(
                telemetry_path=base / "telemetry.json",
                output_path=base / "startup.json",
            )
            gate["proxy_telemetry"]["requests_seen"] = 3
            with self.assertRaisesRegex(ValueError, "request total is inconsistent"):
                executor._validate_startup_gate(gate)

    def test_startup_gate_rejects_nonzero_child_exit_with_green_flags(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            gate = self._fake_startup(
                telemetry_path=base / "telemetry.json",
                output_path=base / "startup.json",
            )
            gate["proxy_telemetry"]["child_exit_code"] = 7
            with self.assertRaisesRegex(ValueError, "telemetry is incomplete"):
                executor._validate_startup_gate(gate)

    def test_command_builder_appends_validated_mcp_overrides_before_stdin(self):
        command = executor.build_codex_exec_command(
            executable="codex.cmd",
            model="gpt-test",
            candidate_dir=Path("C:/candidate"),
            config_overrides=("mcp_servers.feynman_full_runner.required=true",),
        )
        self.assertEqual(command[-1], "-")
        self.assertEqual(command[command.index("--model") + 1], "gpt-test")
        self.assertIn("mcp_servers.feynman_full_runner.required=true", command)
        with self.assertRaises(ValueError):
            executor.build_codex_exec_command(
                executable="codex.cmd", model="gpt-test", candidate_dir=Path("C:/candidate"),
                config_overrides=("",),
            )

    def test_completed_candidate_tool_call_is_only_eligible_for_evidence_extraction(self):
        self._write_fake_codex(success=True, tool_item_type="mcp_tool_call")
        result = self._run()
        self.assertEqual(result["candidate_tool_activity"], {
            "completed_tool_item_count": 1,
            "completed_tool_item_types": ["mcp_tool_call"],
            "tool_use_verdict": "candidate-tool-use-observed",
            "postrun_evidence_eligibility": "eligible-for-trace-evidence-extraction",
        })

    def test_windows_safe_exec_env_keeps_launch_requirements_only(self):
        env = executor._safe_exec_env(
            self.control,
            self.base / "temp",
            platform_name="nt",
            source_env={
                "Path": r"C:\Tools;C:\Windows\System32",
                "SystemRoot": r"C:\Windows",
                "ComSpec": r"C:\Windows\System32\cmd.exe",
                "PATHEXT": ".COM;.EXE;.BAT;.CMD",
                "WINDIR": r"C:\Windows",
                "OPENAI_API_KEY": "do-not-copy",
                "CODEX_ACCESS_TOKEN": "do-not-copy",
                "APPDATA": r"C:\Users\example\AppData\Roaming",
            },
        )
        self.assertEqual(env["PATH"], r"C:\Tools;C:\Windows\System32")
        self.assertEqual(env["TEMP"], str(self.base / "temp"))
        self.assertEqual(env["TMP"], str(self.base / "temp"))
        self.assertEqual(env["TMPDIR"], str(self.base / "temp"))
        self.assertEqual(env["USERPROFILE"], str(self.control.parent))
        self.assertEqual(
            set(env),
            {"HOME", "USERPROFILE", "CODEX_HOME", "PATH", "TEMP", "TMP", "TMPDIR",
             "SystemRoot", "ComSpec", "PATHEXT", "WINDIR"},
        )

    def test_windows_safe_exec_env_adds_local_docker_desktop_cli(self):
        local_app_data = self.base / "localappdata"
        docker_dir = local_app_data / "Programs" / "DockerDesktop" / "resources" / "bin"
        docker_dir.mkdir(parents=True)
        (docker_dir / "docker.exe").write_bytes(b"synthetic executable marker")
        env = executor._safe_exec_env(
            self.control,
            self.base / "temp",
            platform_name="nt",
            source_env={
                "Path": r"C:\Windows\System32",
                "LOCALAPPDATA": str(local_app_data),
            },
        )
        self.assertTrue(env["PATH"].startswith(str(docker_dir)))
        self.assertIn(r"C:\Windows\System32", env["PATH"])

    def test_windows_powershell_launcher_resolves_to_cmd_companion(self):
        powershell_launcher = self.base / "codex.ps1"
        cmd_launcher = self.base / "codex.cmd"
        powershell_launcher.write_text("# launcher", encoding="utf-8")
        cmd_launcher.write_text("@echo off", encoding="utf-8")
        resolved = executor._resolve_executable(str(powershell_launcher), platform_name="nt")
        self.assertEqual(resolved, str(cmd_launcher.resolve()))
        cmd_launcher.unlink()
        with self.assertRaises(ValueError):
            executor._resolve_executable(str(powershell_launcher), platform_name="nt")

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

    def test_partial_full_runner_inputs_fail_before_auth(self):
        with self.assertRaises(ValueError):
            self._run(with_full_runner=False, full_runner_binding_path=self.base / "binding.json")
        self.assertEqual(AUTH_CALLS, [])

    def test_missing_full_runner_inputs_block_before_auth_and_model(self):
        with patch.object(executor.subprocess, "run") as model_run:
            with self.assertRaisesRegex(ValueError, "complete full-runner"):
                self._run(with_full_runner=False)
        self.assertEqual(AUTH_CALLS, [])
        model_run.assert_not_called()

    def test_nonzero_and_failed_trace_do_not_promote_result(self):
        self._write_fake_codex(success=False)
        with self.assertRaises(ValueError): self._run()
        out = self.evaluator / "exec-1"; self.assertTrue((out / "codex-trace.jsonl").exists()); self.assertFalse((out / "subscription-exec-result.json").exists()); self.assertFalse((out / ".control-tmp").exists())
        out.rename(self.evaluator / "failed-nonzero"); self._write_fake_codex(success=True, failed_event=True)
        with self.assertRaises(ValueError): self._run()
        self.assertFalse((self.evaluator / "exec-1" / "subscription-exec-result.json").exists())


class SubscriptionSmokeExecSchemaTests(unittest.TestCase):
    def test_failure_categories_never_echo_raw_text(self):
        for diagnostic, expected in (
            ("unexpected argument", "cli-argument-error"),
            ("You've hit your usage limit", "usage-limit"),
            ("unknown field", "configuration-error"),
            ("exec-server failed", "remote-environment-error"),
            ("opaque failure", "unclassified"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(executor._failure_category(diagnostic + " synthetic-secret-account"), expected)

    def test_schema_tracks_privacy_and_reasoning_policy(self):
        schema = json.loads((ROOT / "evals" / "feynman-thinking" / "subscription-smoke-exec-result.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], 3)
        digests = schema["properties"]["digests"]; self.assertIn("smoke_spec_sha256", digests["required"]); self.assertNotIn("stderr_sha256", digests["properties"])
        self.assertEqual(schema["properties"]["versions"]["properties"]["model_reasoning_effort"]["const"], "model-default")
        self.assertIn("stderr_nonempty", schema["properties"]["privacy"]["required"])
        activity = schema["properties"]["candidate_tool_activity"]
        self.assertIn("candidate_tool_activity", schema["required"])
        self.assertIn("postrun_evidence_eligibility", activity["required"])
        self.assertEqual(
            schema["properties"]["startup_gate"]["properties"]["verdict"]["const"],
            "subscription-startup-thread-ready",
        )
        self.assertEqual(
            set(schema["properties"]["startup_gate"]["properties"]["artifacts"]["required"]),
            {"report", "telemetry", "report_sha256", "telemetry_sha256"},
        )
        self.assertIn("execution_spec", schema["required"])
        self.assertEqual(
            schema["properties"]["execution_spec"]["properties"]["artifact"]["const"],
            "execution-spec.json",
        )


if __name__ == "__main__": unittest.main()
