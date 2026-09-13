#!/usr/bin/env python3
"""Run a non-evaluative, ChatGPT-subscription tool-discovery probe.

This is deliberately narrower than the frozen Feynman smoke executor.  It
does not send ``task.txt``, rubrics, development notes, or an evaluation prompt
to the model.  After the same structural and auth gates it asks for one
filesystem read in the already-mounted candidate directory, then preserves
only fixed trace-level activity signals.  It is useful for separating a
control-plane tool-discovery failure from an evaluation-task failure.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

try:
    from . import feynman_subscription_smoke_exec as smoke
    from .feynman_mcp_catalog_preflight import run as verify_mcp_catalog
    from .feynman_subscription_run_preflight import preflight_files
    from .feynman_transient_bounded_mcp import build_bounded_mcp_override
except ImportError:
    import feynman_subscription_smoke_exec as smoke
    from feynman_mcp_catalog_preflight import run as verify_mcp_catalog
    from feynman_subscription_run_preflight import preflight_files
    from feynman_transient_bounded_mcp import build_bounded_mcp_override


PROBE_PROMPT = (
    "Call the available feynman_read_probe_byte tool exactly once. Do not report "
    "the tool output. Then reply "
    "with exactly PROBE_TOOL_USED. If no filesystem tool is available, reply "
    "with exactly PROBE_NO_TOOL."
)
EXPECTED_CASE_ID = "tools-10"
LEGACY_GUARD_SECURITY_CHECKS = (
    "initialize",
    "candidate_metadata",
    "absent_config_group",
    "other_file_denied",
    "parent_traversal_denied",
    "config_content_read_denied",
    "process_denied",
    "walk_denied",
    "canonicalize_denied",
)


def _response_claim_verdict(final_message: str, tool_count: int) -> str:
    """Compare fixed probe claims with trace activity without retaining text."""
    claims_used = final_message.strip() == "PROBE_TOOL_USED"
    claims_no_tool = final_message.strip() == "PROBE_NO_TOOL"
    if tool_count:
        return "trace-tool-use-observed"
    if claims_used:
        return "text-claim-without-tool-trace"
    if claims_no_tool:
        return "explicit-no-tool-claim"
    return "no-tool-trace-unclassified-response"


def _validate_job(job: dict[str, Any]) -> None:
    info = job.get("job")
    if not isinstance(info, dict):
        raise ValueError("runner job has no job object")
    if info.get("case_id") != EXPECTED_CASE_ID:
        raise ValueError("tool-use probe accepts only the mounted tools-10 fixture")
    if info.get("condition_id") != "feynman-v05":
        raise ValueError("tool-use probe accepts only the repaired feynman-v05 fixture")
    if info.get("repeat") != 1 or info.get("has_followup") is not False:
        raise ValueError("tool-use probe requires the single-turn fixture")


def _legacy_guard_security_ready(report: dict[str, Any]) -> bool:
    checks = report.get("checks")
    return isinstance(checks, dict) and all(
        checks.get(name) is True for name in LEGACY_GUARD_SECURITY_CHECKS
    )


def _transient_catalog_ready(report: dict[str, Any], lineage: dict[str, object]) -> bool:
    configuration = report.get("configuration")
    catalog = report.get("catalog")
    if not isinstance(configuration, dict) or not isinstance(catalog, dict):
        return False
    servers = catalog.get("servers")
    return (
        report.get("verdict") == "bounded-mcp-catalog-visible"
        and report.get("model_calls") == 0
        and report.get("authentication_used") is False
        and report.get("target_tool_visible") is True
        and configuration.get("transport") == "cli-overrides"
        and configuration.get("user_config_file_required") is False
        and configuration.get("override_lineage") == lineage
        and isinstance(servers, list)
        and catalog.get("server_count") == 1
        and len(servers) == 1
        and isinstance(servers[0], dict)
        and servers[0].get("name") == lineage.get("server_name")
        and servers[0].get("tool_names") == [lineage.get("tool_name")]
        and servers[0].get("target_tool_present") is True
        and servers[0].get("target_tool_has_empty_input_schema") is True
    )


def _probe_command(*, executable: str, model: str, candidate_dir: Path,
                   transient_mcp: Any) -> list[str]:
    return [
        executable, "exec", "--json", "--ephemeral",
        "--strict-config", "--ignore-user-config", "--ignore-rules",
        "--skip-git-repo-check", *transient_mcp.cli_args(),
        "-c", 'approval_policy="never"', "--sandbox", "workspace-write",
        "--model", model, "--cd", str(candidate_dir),
        "-c", 'web_search="disabled"', "-c", "hide_agent_reasoning=true",
        "-c", "show_raw_agent_reasoning=false", "-c",
        "check_for_update_on_startup=false", "-",
    ]


def _validate_diagnostic_control_home(job: dict[str, Any],
                                      remote_environment_path: Path) -> Path:
    """Keep auth state and the immutable diagnostic runtime document separate."""
    paths = job.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("runner job lacks paths")
    control_raw = paths.get("control_codex_home")
    evaluator_raw = paths.get("evaluator_dir")
    candidate_raw = paths.get("candidate_dir")
    if not all(isinstance(value, str) and value for value in (
            control_raw, evaluator_raw, candidate_raw)):
        raise ValueError("runner job lacks diagnostic control paths")
    control_home = smoke._directory(Path(control_raw), "control CODEX_HOME")
    evaluator_dir = smoke._directory(Path(evaluator_raw), "evaluator directory")
    candidate_dir = smoke._directory(Path(candidate_raw), "candidate directory")
    expected_remote = (evaluator_dir / "environments.toml").resolve(strict=False)
    if remote_environment_path.resolve(strict=False) != expected_remote:
        raise ValueError("diagnostic remote environment must be evaluator/environments.toml")
    def overlaps(left: Path, right: Path) -> bool:
        return left == right or left in right.parents or right in left.parents

    if overlaps(control_home, evaluator_dir) or overlaps(control_home, candidate_dir):
        raise ValueError("diagnostic control CODEX_HOME must be isolated from run directories")
    return control_home


def probe(*, plan_path: Path, ordinal: int, evaluator_case_path: Path,
          runner_job_path: Path, boundary_profile_path: Path,
          remote_environment_path: Path, output_dir: Path,
          codex_bin: str = "codex", timeout_seconds: int = 180,
          docker_config: Path | None = None, node_bin: Path | None = None,
          bounded_adapter: Path | None = None,
          preflight_only: bool = False) -> dict[str, Any]:
    if type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 3600:
        raise ValueError("timeout_seconds must be an integer in 30..3600")
    smoke._assert_invocation_context()
    plan_path = smoke._regular(plan_path, "eval plan")
    evaluator_case_path = smoke._regular(evaluator_case_path, "evaluator case")
    runner_job_path = smoke._regular(runner_job_path, "runner job")
    boundary_profile_path = smoke._regular(boundary_profile_path, "boundary profile")
    remote_environment_path = smoke._regular(remote_environment_path, "remote environment")
    job = smoke._load(runner_job_path, "runner job")
    _validate_job(job)
    preflight = preflight_files(
        plan_path=plan_path, ordinal=ordinal, evaluator_case_path=evaluator_case_path,
        runner_job_path=runner_job_path, boundary_profile_path=boundary_profile_path,
        remote_environment_path=remote_environment_path,
    )
    if preflight.get("verdict") != "ready-for-local-chatgpt-session-check":
        raise ValueError("subscription structural preflight did not pass")
    # A structural manifest and request-side len=1 alone are not readiness.
    # These live model-free gates must pass before authentication/model work.
    if docker_config is None:
        raise ValueError("probe requires --docker-config for live runtime and guarded RPC gates")
    if __package__:
        from .feynman_rpc_version_gate import verify as verify_versions
        from .feynman_guarded_rpc_preflight import verify as verify_guard
    else:
        from feynman_rpc_version_gate import verify as verify_versions
        from feynman_guarded_rpc_preflight import verify as verify_guard
    verify_versions(job_path=runner_job_path, profile_path=boundary_profile_path,
                    codex_bin=codex_bin, docker_config=docker_config)
    gate_output = smoke._prepare_output_dir(output_dir, Path(job['paths']['evaluator_dir']))
    readiness = verify_guard(job_path=runner_job_path, profile_path=boundary_profile_path,
                             remote_path=remote_environment_path, docker_config=docker_config,
                             output=gate_output / 'guarded-readiness.json')
    if not _legacy_guard_security_ready(readiness):
        raise ValueError("legacy RPC security controls did not pass; no auth or model call started")
    versions = job.get("versions")
    paths = job.get("paths")
    if not isinstance(versions, dict) or not isinstance(paths, dict):
        raise ValueError("runner job lacks versions/paths")
    model = versions.get("model")
    if not isinstance(model, str) or not model or model.lower().startswith("mock"):
        raise ValueError("tool-use probe requires a non-mock model")
    candidate_dir = smoke._directory(Path(paths["candidate_dir"]), "candidate directory")
    evaluator_dir = smoke._directory(Path(paths["evaluator_dir"]), "evaluator directory")
    if (candidate_dir / ".codex").exists() or not (candidate_dir / "candidate.py").is_file():
        raise ValueError("tool-use probe fixture is not safe or complete")
    sentinel = candidate_dir / ".feynman-diagnostic-absent.toml"
    if sentinel.exists() or sentinel.is_symlink():
        raise ValueError("guarded config sentinel must be absent")
    if node_bin is None or bounded_adapter is None:
        raise ValueError("tool-use probe requires the transient bounded MCP executable and adapter")
    transient_mcp = build_bounded_mcp_override(
        node_bin=node_bin, adapter=bounded_adapter, candidate=candidate_dir)
    catalog_home = gate_output / ".transient-catalog-home"
    catalog_home.mkdir(mode=0o700)
    try:
        catalog_report = verify_mcp_catalog(
            codex_bin=smoke._resolve_executable(codex_bin),
            codex_home=catalog_home,
            output=gate_output / "transient-mcp-catalog.json",
            timeout_seconds=min(timeout_seconds, 30),
            config_overrides=transient_mcp.values,
            override_lineage=transient_mcp.sanitized_lineage(),
        )
    finally:
        shutil.rmtree(catalog_home, ignore_errors=True)
    if not _transient_catalog_ready(catalog_report, transient_mcp.sanitized_lineage()):
        raise ValueError("transient bounded MCP catalog gate did not pass; no auth or model call started")
    control_home = _validate_diagnostic_control_home(job, remote_environment_path)
    if preflight_only:
        result = {
            "schema_version": 1,
            "verdict": "ready-for-subscription-tool-use-probe",
            "run_id": job["run_id"],
            "model": model,
            "model_calls": 0,
            "authentication_used": False,
            "protected_control_home_modified": False,
            "preflight": {
                "structural_verdict": preflight["verdict"],
                "legacy_rpc_security_controls_ready": True,
                "legacy_rpc_byte_read_contract_used": False,
                "transient_mcp_catalog_verdict": catalog_report["verdict"],
                "user_config_ignored_for_future_exec": True,
                "authentication_source_preserved_for_future_exec": True,
            },
            "transient_mcp": transient_mcp.sanitized_lineage(),
            "next_action": "one explicitly authorized non-evaluative subscription model probe",
        }
        (gate_output / "subscription-tool-use-preflight.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    auth = smoke.check_auth(control_home, codex_bin=codex_bin,
                            timeout_seconds=min(timeout_seconds, 120))
    if auth.get("verdict") != "chatgpt-subscription-authenticated":
        raise ValueError("ChatGPT subscription auth gate did not pass")
    if versions.get("codex_cli") != auth.get("codex_cli"):
        raise ValueError("runner-job Codex version differs from authenticated control Codex")
    output = gate_output
    result_path = output / "subscription-tool-use-probe.json"
    control_temp = output / ".control-tmp"
    control_temp.mkdir(mode=0o700)
    # The model trace can contain model-authored text.  Keep it only in the
    # ephemeral control area while extracting fixed activity signals; never
    # turn it into a result artifact.
    trace_path = control_temp / "codex-trace.jsonl"
    probe_env = smoke._safe_exec_env(control_home, control_temp)
    command = _probe_command(
        executable=smoke._resolve_executable(codex_bin), model=model,
        candidate_dir=candidate_dir, transient_mcp=transient_mcp)
    stderr_text = ""
    try:
        with trace_path.open("w", encoding="utf-8") as trace_handle:
            completed = subprocess.run(
                command, input=PROBE_PROMPT, env=probe_env,
                cwd=candidate_dir, text=True, encoding="utf-8", errors="replace",
                stdout=trace_handle, stderr=subprocess.PIPE, timeout=timeout_seconds, check=False,
            )
        stderr_text = completed.stderr or ""
        if completed.returncode != 0:
            category = smoke._failure_category(stderr_text)
            raise ValueError(f"Codex tool-use probe failed with exit code {completed.returncode}; category={category}; raw stderr was not preserved")
        trace = smoke._parse_trace(trace_path)
        tool_count = trace["completed_tool_item_count"]
        result = {
            "schema_version": 1,
            "verdict": "subscription-tool-use-probe-completed",
            "run_id": job["run_id"],
            "model": model,
            "authentication": {"mode": "chatgpt-subscription", "api_key_auth_allowed": False,
                               "auth_gate_verdict": auth["verdict"], "raw_status_output_preserved": False},
            "probe": {"prompt_contract": "fixed-one-byte-filesystem-read", "model_request_is_evaluation": False,
                      "candidate_task_or_rubric_sent": False, "completed_tool_item_count": tool_count,
                      "completed_tool_item_types": trace["completed_tool_item_types"],
                      "verdict": "tool-use-observed" if tool_count else "tool-use-not-observed",
                      "response_claim_verdict": _response_claim_verdict(trace["final_message"], tool_count)},
            "preflight": {
                "legacy_rpc_security_controls_ready": True,
                "legacy_rpc_byte_read_contract_used": False,
                "transient_mcp_catalog_verdict": catalog_report["verdict"],
            },
            "conversation": {"event_count": trace["event_count"], "reasoning_events_observed": trace["reasoning_events_observed"]},
            "privacy": {"process_environment_inherited": False, "raw_stderr_preserved": False,
                        "stderr_nonempty": bool(stderr_text), "raw_model_final_preserved": False,
                        "control_codex_home_contents_serialized": False},
            "scope": "non-evaluative fixed tool-discovery probe; not Feynman skill performance evidence",
            "transient_mcp": transient_mcp.sanitized_lineage(),
        }
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        shutil.rmtree(control_temp, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True); parser.add_argument("--ordinal", type=int, required=True)
    parser.add_argument("--evaluator-case", type=Path, required=True); parser.add_argument("--runner-job", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True); parser.add_argument("--remote-environment", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True); parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--docker-config", type=Path, required=True,
                        help="Dedicated Docker config for model-free readiness gates")
    parser.add_argument("--node-bin", type=Path, required=True)
    parser.add_argument("--bounded-adapter", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=180); args = parser.parse_args()
    try:
        result = probe(plan_path=args.plan, ordinal=args.ordinal, evaluator_case_path=args.evaluator_case,
                       runner_job_path=args.runner_job, boundary_profile_path=args.boundary_profile,
                       remote_environment_path=args.remote_environment, output_dir=args.output_dir,
                       codex_bin=args.codex_bin, timeout_seconds=args.timeout_seconds,
                       docker_config=args.docker_config, node_bin=args.node_bin,
                       bounded_adapter=args.bounded_adapter,
                       preflight_only=args.preflight_only)
    except (ValueError, OSError, TimeoutError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps({
        "verdict": result["verdict"],
        "probe_verdict": result.get("probe", {}).get("verdict"),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
