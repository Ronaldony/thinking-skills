#!/usr/bin/env python3
"""Bind the fixed full-runner MCP contract to a tools-10 runner artifact.

This is a model-free, pre-execution check.  The existing runner job/profile
remain immutable inputs.  The full-runner MCP image is recorded as a separate
tool-boundary implementation because the legacy remote-exec profile may point
at a different Docker image.  No model, login, credential, or candidate task
payload is read by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_full_runner_contract import (
        FIXED_CANDIDATE_FILE,
        FIXED_CONTAINER_ROOT,
        FIXED_TEST_COMMAND,
        READ_LIMIT_BYTES,
        TEST_OUTPUT_LIMIT_BYTES,
        TEST_TOOL_NAME,
        TOOL_NAMES,
        WRITE_LIMIT_BYTES,
        build_full_runner_override,
    )
    from .feynman_path_mapping import CONTAINER_DESTINATIONS, mounts_for_job
    from .feynman_runner_job_validate import _load as load_job
    from .feynman_runner_job_validate import validate_job
except ImportError:
    from feynman_boundary_profile import validate_profile_file
    from feynman_full_runner_contract import (
        FIXED_CANDIDATE_FILE,
        FIXED_CONTAINER_ROOT,
        FIXED_TEST_COMMAND,
        READ_LIMIT_BYTES,
        TEST_OUTPUT_LIMIT_BYTES,
        TEST_TOOL_NAME,
        TOOL_NAMES,
        WRITE_LIMIT_BYTES,
        build_full_runner_override,
    )
    from feynman_path_mapping import CONTAINER_DESTINATIONS, mounts_for_job
    from feynman_runner_job_validate import _load as load_job
    from feynman_runner_job_validate import validate_job


EXPECTED_CASE = "tools-10"
EXPECTED_CONDITIONS = {"baseline", "feynman-v05"}
EXPECTED_DOCKER_PRELIGHT_VERDICT = "full-runner-mcp-docker-preflight-passed"
EXPECTED_CATALOG_VERDICT = "full-runner-mcp-contract-ready"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} JSON root must be an object")
    return value


def _assert_bool(value: Any, label: str, expected: bool) -> None:
    if value is not expected:
        raise ValueError(f"{label} must be {str(expected).lower()}")


def _validate_catalog(report: dict[str, Any], override: Any) -> dict[str, Any]:
    if report.get("verdict") != EXPECTED_CATALOG_VERDICT:
        raise ValueError("full-runner catalog preflight verdict is not ready")
    if report.get("model_calls") != 0:
        raise ValueError("catalog binding requires model_calls=0")
    _assert_bool(report.get("authentication_used"), "catalog authentication_used", False)
    privacy = report.get("privacy")
    if not isinstance(privacy, dict):
        raise ValueError("catalog preflight privacy block is missing")
    for field in ("model_request_started", "credential_files_read", "tool_payloads_preserved"):
        _assert_bool(privacy.get(field), f"catalog privacy.{field}", False)
    lineage = report.get("lineage")
    if not isinstance(lineage, dict):
        raise ValueError("catalog preflight lineage is missing")
    if lineage != override.sanitized_lineage():
        raise ValueError("catalog preflight lineage differs from the supplied full-runner inputs")
    catalog = report.get("catalog")
    if not isinstance(catalog, dict):
        raise ValueError("catalog preflight catalog block is missing")
    if catalog.get("server_name") != "feynman_full_runner":
        raise ValueError("catalog preflight server name differs")
    if catalog.get("tool_names") != sorted(TOOL_NAMES):
        raise ValueError("catalog preflight tool set differs")
    return {
        "verdict": report["verdict"],
        "server_name": catalog["server_name"],
        "tool_names": catalog["tool_names"],
        "model_calls": 0,
        "authentication_used": False,
    }


def _validate_docker_preflight(report: dict[str, Any], image_id: str) -> dict[str, Any]:
    if report.get("verdict") != EXPECTED_DOCKER_PRELIGHT_VERDICT:
        raise ValueError("full-runner Docker preflight verdict is not passed")
    if report.get("model_calls") != 0:
        raise ValueError("Docker binding requires model_calls=0")
    _assert_bool(report.get("authentication_used"), "Docker authentication_used", False)
    checks = report.get("checks")
    if not isinstance(checks, dict) or set(checks) != {
        "initialize_ok", "exact_tool_catalog", "fixed_read_observed",
        "fixed_write_observed", "fixed_test_passed", "write_visible_to_followup_read",
    } or not all(value is True for value in checks.values()):
        raise ValueError("full-runner Docker preflight checks are incomplete")
    policy = report.get("fixed_policy")
    if not isinstance(policy, dict):
        raise ValueError("Docker preflight fixed policy is missing")
    if policy.get("tool_names") != list(TOOL_NAMES):
        raise ValueError("Docker preflight tool set differs")
    if policy.get("candidate_file") != FIXED_CANDIDATE_FILE:
        raise ValueError("Docker preflight candidate file differs")
    if policy.get("test_command") != list(FIXED_TEST_COMMAND):
        raise ValueError("Docker preflight test command differs")
    if policy.get("network_mode") != "none" or policy.get("read_only_root") is not True:
        raise ValueError("Docker preflight security policy differs")
    if policy.get("candidate_mount_access") != "ro" or policy.get("write_target") != FIXED_CANDIDATE_FILE:
        raise ValueError("Docker preflight candidate access policy differs")
    privacy = report.get("privacy")
    if not isinstance(privacy, dict):
        raise ValueError("Docker preflight privacy block is missing")
    for field in ("model_request_started", "credential_files_read"):
        _assert_bool(privacy.get(field), f"Docker privacy.{field}", False)
    payload_field = "raw_tool_payloads_preserved" if "raw_tool_payloads_preserved" in privacy else "tool_payloads_preserved"
    _assert_bool(privacy.get(payload_field), f"Docker privacy.{payload_field}", False)
    if "candidate_fixture_discarded" in privacy:
        _assert_bool(privacy.get("candidate_fixture_discarded"), "Docker privacy.candidate_fixture_discarded", True)
    return {
        "verdict": report["verdict"],
        "checks_passed": len(checks),
        "docker_image_id": image_id,
        "model_calls": 0,
        "authentication_used": False,
    }


def bind(*, runner_job_path: Path, boundary_profile_path: Path,
         catalog_preflight_path: Path, docker_preflight_path: Path,
         node_bin: Path, adapter: Path, docker_bin: Path, docker_config: Path,
         docker_image_id: str, output: Path) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise ValueError("binding output must be new")
    runner_job_path = runner_job_path.resolve()
    boundary_profile_path = boundary_profile_path.resolve()
    job = load_job(runner_job_path)
    profile, profile_sha, _ = validate_profile_file(boundary_profile_path)
    validation = validate_job(job, profile, profile_sha)
    if validation.get("verdict") != "runner-job-valid":
        raise ValueError("runner job is not valid")
    info = job["job"]
    if info.get("case_id") != EXPECTED_CASE:
        raise ValueError("full-runner binding requires case_id=tools-10")
    if info.get("condition_id") not in EXPECTED_CONDITIONS:
        raise ValueError("full-runner binding requires baseline or feynman-v05")

    mounts = mounts_for_job(job, profile)
    expected = {
        CONTAINER_DESTINATIONS[key]
        for key in CONTAINER_DESTINATIONS
    }
    if {item["destination"] for item in mounts} != expected:
        raise ValueError("runner artifact does not use the canonical native Windows mapping")
    if any(item["access"] != "rw" for item in mounts):
        raise ValueError("runner artifact candidate-owned mounts must be writable")

    override = build_full_runner_override(
        node_bin=node_bin,
        adapter=adapter,
        candidate=Path(job["paths"]["candidate_dir"]),
        docker_bin=docker_bin,
        docker_config=docker_config,
        docker_image_id=docker_image_id,
    )
    catalog = _validate_catalog(_json(catalog_preflight_path, "catalog preflight"), override)
    docker = _validate_docker_preflight(_json(docker_preflight_path, "Docker preflight"), docker_image_id)

    result: dict[str, Any] = {
        "schema_version": 1,
        "verdict": "full-runner-mcp-artifact-chain-bound",
        "run_id": job["run_id"],
        "case_id": info["case_id"],
        "condition_id": info["condition_id"],
        "model": job["versions"]["model"],
        "codex_cli": job["versions"]["codex_cli"],
        "lineage": {
            "runner_job_sha256": _sha(runner_job_path),
            "boundary_profile_sha256": profile_sha,
            "eval_plan_sha256": job["digests"]["eval_plan_sha256"],
            "candidate_prompt_sha256": job["digests"]["candidate_prompt_sha256"],
            "runtime_sha256": job["digests"]["runtime_sha256"],
        },
        "native_windows_mapping": {
            "mount_count": len(mounts),
            "container_destinations": sorted(expected),
            "candidate_mount_destination": FIXED_CONTAINER_ROOT,
            "candidate_mount_access": "rw",
        },
        "declared_runner_boundary": {
            "backend": profile["backend"],
            "backend_version": profile["backend_version"],
            "profile_image_id": profile["image_id"],
            "network_mode": profile["network_mode"],
            "run_as": profile["run_as"],
            "read_only_root": profile["read_only_root"],
            "no_new_privileges": profile["no_new_privileges"],
            "capabilities": profile["capabilities"],
        },
        "full_runner": {
            "server_name": "feynman_full_runner",
            "tool_names": list(TOOL_NAMES),
            "adapter_sha256": override.adapter_sha256,
            "docker_image_id": docker_image_id,
            "initial_candidate_sha256": override.initial_candidate_sha256,
            "test_sha256": override.test_sha256,
            "fixed_candidate_file": FIXED_CANDIDATE_FILE,
            "fixed_test_command": list(FIXED_TEST_COMMAND),
            "read_limit_bytes": READ_LIMIT_BYTES,
            "write_limit_bytes": WRITE_LIMIT_BYTES,
            "test_output_limit_bytes": TEST_OUTPUT_LIMIT_BYTES,
            "network_mode": "none",
            "candidate_mount_access": "ro",
            "write_target": FIXED_CANDIDATE_FILE,
        },
        "checks": {
            "runner_job_valid": True,
            "tools_10_job": True,
            "canonical_native_windows_mapping": True,
            "full_runner_catalog_preflight": True,
            "full_runner_docker_preflight": True,
            "model_calls": 0,
            "authentication_used": False,
            "profile_image_is_separate_declared_remote_exec_image": profile["image_id"] != docker_image_id,
        },
        "preflight_evidence": {
            "catalog_preflight_sha256": _sha(catalog_preflight_path.resolve()),
            "docker_preflight_sha256": _sha(docker_preflight_path.resolve()),
            "catalog": catalog,
            "docker": docker,
        },
        "privacy": {
            "credential_files_read": False,
            "control_codex_home_read": False,
            "candidate_task_payload_read": False,
            "model_request_started": False,
            "tool_payloads_preserved": False,
        },
        "scope": (
            "model-free binding of a tools-10 runner-job/profile to the fixed full-runner MCP contract; "
            "not model, auth, or Feynman skill performance evidence"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-job", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--catalog-preflight", type=Path, required=True)
    parser.add_argument("--docker-preflight", type=Path, required=True)
    parser.add_argument("--node-bin", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--docker-bin", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--docker-image-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = bind(
            runner_job_path=args.runner_job,
            boundary_profile_path=args.boundary_profile,
            catalog_preflight_path=args.catalog_preflight,
            docker_preflight_path=args.docker_preflight,
            node_bin=args.node_bin,
            adapter=args.adapter,
            docker_bin=args.docker_bin,
            docker_config=args.docker_config,
            docker_image_id=args.docker_image_id,
            output=args.output,
        )
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, "error: full-runner binding failed: " + type(exc).__name__ + "\n")
    print(json.dumps({
        "verdict": result["verdict"],
        "run_id": result["run_id"],
        "model": result["model"],
        "condition_id": result["condition_id"],
        "model_calls": result["checks"]["model_calls"],
        "authentication_used": result["checks"]["authentication_used"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
