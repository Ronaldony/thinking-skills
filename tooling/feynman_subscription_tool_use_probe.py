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
    from .feynman_subscription_run_preflight import preflight_files
except ImportError:
    import feynman_subscription_smoke_exec as smoke
    from feynman_subscription_run_preflight import preflight_files


PROBE_PROMPT = (
    "Use the available filesystem tool exactly once to read one byte from "
    "candidate.py in the current workspace. Do not report the byte. Then reply "
    "with exactly PROBE_TOOL_USED. If no filesystem tool is available, reply "
    "with exactly PROBE_NO_TOOL."
)
EXPECTED_CASE_ID = "tools-10"


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


def probe(*, plan_path: Path, ordinal: int, evaluator_case_path: Path,
          runner_job_path: Path, boundary_profile_path: Path,
          remote_environment_path: Path, output_dir: Path,
          codex_bin: str = "codex", timeout_seconds: int = 180) -> dict[str, Any]:
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
    control_home, _ = smoke._validate_control_files(job, remote_environment_path)
    auth = smoke.check_auth(control_home, codex_bin=codex_bin,
                            timeout_seconds=min(timeout_seconds, 120))
    if auth.get("verdict") != "chatgpt-subscription-authenticated":
        raise ValueError("ChatGPT subscription auth gate did not pass")
    versions = job.get("versions")
    paths = job.get("paths")
    if not isinstance(versions, dict) or not isinstance(paths, dict):
        raise ValueError("runner job lacks versions/paths")
    if versions.get("codex_cli") != auth.get("codex_cli"):
        raise ValueError("runner-job Codex version differs from authenticated control Codex")
    model = versions.get("model")
    if not isinstance(model, str) or not model or model.lower().startswith("mock"):
        raise ValueError("tool-use probe requires a non-mock model")
    candidate_dir = smoke._directory(Path(paths["candidate_dir"]), "candidate directory")
    evaluator_dir = smoke._directory(Path(paths["evaluator_dir"]), "evaluator directory")
    if (candidate_dir / ".codex").exists() or not (candidate_dir / "candidate.py").is_file():
        raise ValueError("tool-use probe fixture is not safe or complete")
    output = smoke._prepare_output_dir(output_dir, evaluator_dir)
    result_path = output / "subscription-tool-use-probe.json"
    control_temp = output / ".control-tmp"
    control_temp.mkdir(mode=0o700)
    # The model trace can contain model-authored text.  Keep it only in the
    # ephemeral control area while extracting fixed activity signals; never
    # turn it into a result artifact.
    trace_path = control_temp / "codex-trace.jsonl"
    telemetry_path = evaluator_dir / "rpc-proxy-telemetry.json"
    probe_env = smoke._safe_exec_env(control_home, control_temp)
    # These fixed, non-secret controls are consumed only by the host-side RPC
    # proxy.  The canonical Docker command uses env -i, so candidate processes
    # never receive them.
    probe_env.update({
        "FEYNMAN_PROBE_RPC_READ_LIMIT_BYTES": "1",
        "FEYNMAN_PROBE_RPC_ALLOWED_METHODS": "fs/readFile",
        "FEYNMAN_PROBE_RPC_ALLOWED_PATH": "/run/candidate/candidate.py",
    })
    command = [
        smoke._resolve_executable(codex_bin), "exec", "--json", "--ephemeral",
        "--strict-config", "--ignore-rules", "--skip-git-repo-check",
        "-c", 'approval_policy="never"', "--sandbox", "workspace-write",
        "--model", model, "--cd", str(candidate_dir),
        "-c", 'web_search="disabled"', "-c", "hide_agent_reasoning=true",
        "-c", "show_raw_agent_reasoning=false", "-c", "check_for_update_on_startup=false", "-",
    ]
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
        telemetry: dict[str, Any] | None = None
        if telemetry_path.is_file() and not telemetry_path.is_symlink():
            parsed_telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
            if isinstance(parsed_telemetry, dict):
                telemetry = parsed_telemetry
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
            "rpc_telemetry": telemetry,
            "conversation": {"event_count": trace["event_count"], "reasoning_events_observed": trace["reasoning_events_observed"]},
            "privacy": {"process_environment_inherited": False, "raw_stderr_preserved": False,
                        "stderr_nonempty": bool(stderr_text), "raw_model_final_preserved": False,
                        "control_codex_home_contents_serialized": False},
            "scope": "non-evaluative fixed tool-discovery probe; not Feynman skill performance evidence",
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
    parser.add_argument("--timeout-seconds", type=int, default=180); args = parser.parse_args()
    try:
        result = probe(plan_path=args.plan, ordinal=args.ordinal, evaluator_case_path=args.evaluator_case,
                       runner_job_path=args.runner_job, boundary_profile_path=args.boundary_profile,
                       remote_environment_path=args.remote_environment, output_dir=args.output_dir,
                       codex_bin=args.codex_bin, timeout_seconds=args.timeout_seconds)
    except (ValueError, OSError, TimeoutError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps({"verdict": result["verdict"], "probe_verdict": result["probe"]["verdict"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
