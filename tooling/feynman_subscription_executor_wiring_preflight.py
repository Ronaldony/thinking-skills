#!/usr/bin/env python3
"""Build a model-free subscription executor command-plan artifact.

This preflight validates the runner job, boundary profile, and full-runner
binding, then exercises the same two-pass App Server skill discovery used by
the subscription smoke executor.  It builds the canonical Codex command but
does not authenticate, start a thread or turn, call a model, or preserve the
command/prompt/path payloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_eval_preflight import preflight as filesystem_skill_preflight
    from .feynman_skill_tool_wiring_preflight import _task_invocation
    from .feynman_runner_job_validate import _load as load_job
    from .feynman_runner_job_validate import validate_job
    from .feynman_subscription_smoke_exec import (
        _directory,
        _load,
        _regular,
        prepare_full_runner_executor_wiring,
    )
except ImportError:
    from feynman_boundary_profile import validate_profile_file
    from feynman_eval_preflight import preflight as filesystem_skill_preflight
    from feynman_skill_tool_wiring_preflight import _task_invocation
    from feynman_runner_job_validate import _load as load_job
    from feynman_runner_job_validate import validate_job
    from feynman_subscription_smoke_exec import (
        _directory,
        _load,
        _regular,
        prepare_full_runner_executor_wiring,
    )


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_command_plan(*, wiring: dict[str, Any], model: str,
                           candidate: Path) -> dict[str, Any]:
    command = wiring["command"]
    all_overrides = tuple(wiring["all_config_overrides"])
    override = wiring["full_runner_override"]
    skill_overrides = tuple(wiring["skill_config_overrides"])
    if not isinstance(command, list) or command[-1] != "-":
        raise ValueError("canonical subscription command must end with stdin marker")
    if command.count("-c") != 5 + len(all_overrides):
        raise ValueError("canonical subscription command override count drift")
    if command[command.index("--model") + 1] != model:
        raise ValueError("canonical subscription command model binding drift")
    if Path(command[command.index("--cd") + 1]).resolve() != candidate.resolve():
        raise ValueError("canonical subscription command candidate cwd drift")
    if len(override.values) != 13:
        raise ValueError("full-runner override count drift")
    disabled_skill_count = wiring["app_server"]["skills"]["transiently_disabled_non_candidate_skill_count"]
    if bool(skill_overrides) != bool(disabled_skill_count):
        raise ValueError("transient skill disable binding drift")
    if len(skill_overrides) > 1:
        raise ValueError("transient skill disable overrides must be consolidated")
    if any("API_KEY" in value or "ACCESS_TOKEN" in value for value in all_overrides):
        raise ValueError("canonical command overrides contain retired credential names")
    return {
        "builder": "feynman_subscription_smoke_exec.build_codex_exec_command",
        "base_config_override_count": 5,
        "full_runner_override_count": len(override.values),
        "transient_skill_disable_override_count": len(skill_overrides),
        "full_runner_and_skill_override_count": len(all_overrides),
        "argv_terminates_with_stdin_marker": True,
        "model_arg_bound": True,
        "candidate_cwd_bound": True,
        "full_runner_mcp_bound": True,
        "transient_skill_isolation_bound": True,
        "command_payload_preserved": False,
    }


def run(*, runner_job_path: Path, boundary_profile_path: Path,
        binding_path: Path, codex_bin: Path, node_bin: Path,
        adapter: Path, docker_bin: Path, docker_config: Path,
        docker_image_id: str, output: Path, timeout_seconds: int = 30) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise ValueError("executor wiring preflight output must be new")
    runner_job_path = _regular(runner_job_path, "runner job")
    boundary_profile_path = _regular(boundary_profile_path, "boundary profile")
    binding_path = _regular(binding_path, "full-runner binding")
    codex_bin = _regular(codex_bin, "Codex executable")
    node_bin = _regular(node_bin, "Node executable")
    adapter = _regular(adapter, "full-runner adapter")
    docker_bin = _regular(docker_bin, "Docker executable")
    docker_config = _directory(docker_config, "Docker config directory")
    job = load_job(runner_job_path)
    profile, profile_sha, _ = validate_profile_file(boundary_profile_path)
    job_result = validate_job(job, profile, profile_sha)
    if job_result.get("verdict") != "runner-job-valid":
        raise ValueError("runner job/profile validation failed")
    binding = _load(binding_path, "full-runner binding")
    full_runner = binding.get("full_runner")
    if not isinstance(full_runner, dict) or not isinstance(full_runner.get("docker_image_id"), str):
        raise ValueError("full-runner binding image ID is missing")
    if full_runner["docker_image_id"] != docker_image_id:
        raise ValueError("provided Docker image ID differs from binding")
    # The boundary profile describes the candidate execution image.  The
    # full-runner binding's image is a separate tool-adapter image, so the two
    # content-addressed IDs are intentionally allowed to differ.

    candidate = _directory(Path(job["paths"]["candidate_dir"]), "candidate directory")
    expected_skills = job["skills"]["expected_candidate_skills"]
    candidate_home = _directory(Path(job["paths"]["ephemeral_home"]), "candidate HOME")
    candidate_codex_home = _directory(Path(job["paths"]["codex_home"]), "candidate CODEX_HOME")
    filesystem = filesystem_skill_preflight(
        candidate, set(expected_skills), home=candidate_home, codex_home=candidate_codex_home)
    task = _task_invocation(job, candidate)
    wiring = prepare_full_runner_executor_wiring(
        codex_bin=str(codex_bin), binding_path=binding_path,
        runner_job_path=runner_job_path, boundary_profile_path=boundary_profile_path,
        job=job, candidate_dir=candidate, node_bin=node_bin, adapter=adapter,
        docker_bin=docker_bin, docker_config=docker_config,
        docker_image_id=docker_image_id, timeout_seconds=timeout_seconds,
    )
    command_plan = _validate_command_plan(
        wiring=wiring, model=job["versions"]["model"], candidate=candidate)
    app_server = wiring["app_server"]
    result = {
        "schema_version": 1,
        "verdict": "subscription-executor-wiring-ready",
        "run_id": job["run_id"],
        "case_id": job["job"]["case_id"],
        "condition_id": job["job"]["condition_id"],
        "model": job["versions"]["model"],
        "lineage": {
            "runner_job_sha256": _sha(runner_job_path),
            "boundary_profile_sha256": profile_sha,
            "full_runner_binding_sha256": _sha(binding_path),
            "candidate_prompt_sha256": job["digests"]["candidate_prompt_sha256"],
            "runtime_sha256": job["digests"]["runtime_sha256"],
            "adapter_sha256": wiring["full_runner_override"].adapter_sha256,
            "docker_image_id": docker_image_id,
        },
        "checks": {
            "runner_job_profile_valid": True,
            "binding_valid": True,
            "filesystem_candidate_skill_set_exact": (
                sorted(filesystem["observed_candidate_skills"]) == sorted(expected_skills)),
            "explicit_skill_invocation_bound": True,
            "skill_discovery_exact": True,
            "transient_skill_isolation_bound": True,
            "full_runner_mcp_bound": True,
            "command_builder_bound": True,
            "model_calls": 0,
            "authentication_used": False,
        },
        "skill_exposure": {
            "expected_candidate_skills": list(expected_skills),
            "filesystem_observed_candidate_skills": sorted(filesystem["observed_candidate_skills"]),
            "app_server": app_server["skills"],
            "task_invocation": task,
        },
        "tool_wiring": {
            "mcp": app_server["mcp"],
            "command_plan": command_plan,
        },
        "privacy": {
            "model_request_started": False,
            "thread_started": False,
            "turn_started": False,
            "authentication_used": False,
            "credential_files_read": False,
            "control_codex_home_read": False,
            "command_payload_preserved": False,
            "candidate_prompt_payload_preserved": False,
            "skill_discovery_paths_preserved": False,
        },
        "scope": (
            "model-free subscription executor wiring and command-plan validation; "
            "authentication and actual model evaluation remain separately gated"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-job", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--codex-bin", type=Path, required=True)
    parser.add_argument("--node-bin", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--docker-bin", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--docker-image-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    try:
        result = run(
            runner_job_path=args.runner_job, boundary_profile_path=args.boundary_profile,
            binding_path=args.binding, codex_bin=args.codex_bin, node_bin=args.node_bin,
            adapter=args.adapter, docker_bin=args.docker_bin,
            docker_config=args.docker_config, docker_image_id=args.docker_image_id,
            output=args.output, timeout_seconds=args.timeout_seconds,
        )
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, "error: executor wiring preflight failed: " + type(exc).__name__ + "\n")
    print(json.dumps({
        "verdict": result["verdict"],
        "model": result["model"],
        "condition_id": result["condition_id"],
        "full_runner_override_count": result["tool_wiring"]["command_plan"]["full_runner_override_count"],
        "transient_skill_disable_override_count": result["tool_wiring"]["command_plan"]["transient_skill_disable_override_count"],
        "model_calls": result["checks"]["model_calls"],
        "authentication_used": result["checks"]["authentication_used"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
