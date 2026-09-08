#!/usr/bin/env python3
"""Validate and bind the credential-free mock remote-exec reference evidence.

This is intentionally stricter than the inline workflow summary it replaces. It
re-validates the runner job, canonical `environments.toml`, network reference,
mock model round trip, Codex JSONL trace, candidate proof file, and Docker
inspect snapshot before emitting one content-addressed result record.

It proves only the mock reference path. It does not authenticate to an external
model service and does not measure Feynman skill quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_docker_reference_inspect import verify_reference
    from .feynman_network_reference import endpoint_identity
    from .feynman_remote_exec_environment import validate_files as validate_remote_environment_files
    from .feynman_runner_job_validate import validate_job_files
except ImportError:
    from feynman_boundary_profile import validate_profile_file
    from feynman_docker_reference_inspect import verify_reference
    from feynman_network_reference import endpoint_identity
    from feynman_remote_exec_environment import validate_files as validate_remote_environment_files
    from feynman_runner_job_validate import validate_job_files

FINAL_TEXT = "REMOTE_EXEC_REFERENCE_OK"
WORKSPACE_MARKER = "REMOTE_EXEC_OK"
NETWORK_MARKER = "NETWORK_BLOCKED"
AUTH_ENV_MARKER = "AUTH_ENV_CLEAN"


def _regular(path: Path, label: str) -> Path:
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path, label: str) -> Any:
    path = _regular(path, label)
    return json.loads(path.read_text(encoding="utf-8"))


def _load_object(path: Path, label: str) -> dict[str, Any]:
    value = _load_json(path, label)
    if not isinstance(value, dict):
        raise ValueError(f"{label} JSON root must be object")
    return value


def _version(path: Path, label: str) -> str:
    path = _regular(path, label)
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"{label} must be nonempty")
    if "\n" in value or "\r" in value:
        raise ValueError(f"{label} must contain exactly one version line")
    return value


def _validate_network_reference(value: dict[str, Any]) -> tuple[str, int]:
    if value.get("schema_version") != 1:
        raise ValueError("network reference schema_version must be 1")
    host = value.get("host")
    port = value.get("port")
    if not isinstance(host, str) or not host.strip():
        raise ValueError("network reference host must be nonempty")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("network reference port must be in 1..65535")
    if value.get("reachable_from_control_plane") is not True:
        raise ValueError("network reference must prove control-plane reachability")
    if value.get("probe_method") != "tcp-connect:v1":
        raise ValueError("unsupported network reference probe method")
    if value.get("endpoint_identity_sha256") != endpoint_identity(host, port):
        raise ValueError("network reference endpoint identity mismatch")
    return host, port


def _validate_mock_state(value: dict[str, Any]) -> None:
    if value.get("schema_version") != 1:
        raise ValueError("mock state schema_version must be 1")
    if value.get("validation_error") is not None:
        raise ValueError("mock model server recorded a validation error")
    if value.get("final_text") != FINAL_TEXT:
        raise ValueError("mock state final_text differs from reference contract")
    requests = value.get("requests")
    if not isinstance(requests, list) or len(requests) != 2:
        raise ValueError("mock reference must contain exactly two model requests")
    first, second = requests
    if not isinstance(first, dict) or not isinstance(second, dict):
        raise ValueError("mock request records must be objects")
    if first.get("index") != 1 or second.get("index") != 2:
        raise ValueError("mock request indexes must be exactly 1,2")
    if first.get("has_matching_tool_output") is not False:
        raise ValueError("first mock request must not already contain tool output")
    if second.get("has_matching_tool_output") is not True:
        raise ValueError("second mock request lacks the matching tool output")
    for field in (
        "tool_output_contains_workspace_marker",
        "tool_output_contains_network_marker",
        "tool_output_contains_auth_env_marker",
    ):
        if second.get(field) is not True:
            raise ValueError(f"second mock request failed required assertion: {field}")
    for record in requests:
        digest = record.get("body_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("mock request body_sha256 must be SHA-256")


def _trace_assertions(path: Path, *, network_host: str, network_port: int) -> dict[str, Any]:
    path = _regular(path, "Codex trace")
    command_seen = False
    endpoint_seen = False
    final_seen = False
    thread_ids: set[str] = set()
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Codex trace line {line_no} is invalid JSON") from exc
        if not isinstance(event, dict):
            raise ValueError(f"Codex trace line {line_no} root must be object")
        if event.get("type") == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                thread_ids.add(thread_id)
            continue
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "command_execution":
            if item.get("status") != "completed":
                continue
            command_seen = True
            command = item.get("command")
            output = item.get("aggregated_output")
            command_text = command if isinstance(command, str) else json.dumps(command, ensure_ascii=False)
            output_text = output if isinstance(output, str) else ""
            if str(network_host) in command_text and str(network_port) in command_text:
                endpoint_seen = True
            required = (WORKSPACE_MARKER, NETWORK_MARKER, AUTH_ENV_MARKER)
            if not all(marker in output_text for marker in required):
                raise ValueError("completed reference command output lacks one or more boundary markers")
        elif kind == "agent_message":
            text = item.get("text")
            if text == FINAL_TEXT:
                final_seen = True
    if len(thread_ids) != 1:
        raise ValueError("mock remote-exec trace must contain exactly one nonempty thread_id")
    if not command_seen:
        raise ValueError("mock remote-exec trace has no completed command_execution")
    if not endpoint_seen:
        raise ValueError("mock remote-exec trace command is not bound to the control-plane network reference")
    if not final_seen:
        raise ValueError("mock remote-exec trace lacks the exact final agent message")
    return {
        "thread_id": next(iter(thread_ids)),
        "command_execution_observed": True,
        "final_agent_message_observed": True,
    }


def assemble(
    *,
    boundary_profile_path: Path,
    runner_job_path: Path,
    remote_environment_path: Path,
    network_reference_path: Path,
    mock_state_path: Path,
    codex_trace_path: Path,
    docker_inspect_path: Path,
    candidate_proof_path: Path,
    mock_server_program_path: Path,
    control_codex_version_path: Path,
    tool_codex_version_path: Path,
) -> dict[str, Any]:
    boundary_profile_path = _regular(boundary_profile_path, "boundary profile")
    runner_job_path = _regular(runner_job_path, "runner job")
    remote_environment_path = _regular(remote_environment_path, "remote environment")
    network_reference_path = _regular(network_reference_path, "network reference")
    mock_state_path = _regular(mock_state_path, "mock state")
    codex_trace_path = _regular(codex_trace_path, "Codex trace")
    docker_inspect_path = _regular(docker_inspect_path, "Docker inspect")
    candidate_proof_path = _regular(candidate_proof_path, "candidate proof")
    mock_server_program_path = _regular(mock_server_program_path, "mock server program")

    profile, profile_sha, _ = validate_profile_file(boundary_profile_path)
    runner_validation = validate_job_files(runner_job_path, boundary_profile_path)
    if runner_validation.get("verdict") != "runner-job-valid":
        raise ValueError("runner job is not valid")
    remote_validation = validate_remote_environment_files(
        runner_job_path, boundary_profile_path, remote_environment_path
    )
    if remote_validation.get("verdict") != "remote-exec-environment-valid":
        raise ValueError("remote execution environment is not canonical")

    network_reference = _load_object(network_reference_path, "network reference")
    network_host, network_port = _validate_network_reference(network_reference)
    mock_state = _load_object(mock_state_path, "mock state")
    _validate_mock_state(mock_state)
    trace = _trace_assertions(codex_trace_path, network_host=network_host, network_port=network_port)

    proof_text = candidate_proof_path.read_text(encoding="utf-8")
    if proof_text.strip() != WORKSPACE_MARKER:
        raise ValueError("candidate proof file does not contain the expected remote workspace marker")

    inspect_payload = _load_json(docker_inspect_path, "Docker inspect")
    inspect_result = verify_reference(profile, inspect_payload)
    if inspect_result.get("verdict") != "docker-inspect-matches-profile":
        raise ValueError("Docker inspect does not match boundary profile")

    control_version = _version(control_codex_version_path, "control Codex version")
    tool_version = _version(tool_codex_version_path, "tool Codex version")
    if control_version != tool_version:
        raise ValueError("control-plane and tool-boundary Codex versions differ")
    runner_job = _load_object(runner_job_path, "runner job")
    runner_version = runner_job.get("versions", {}).get("codex_cli")
    if runner_version != control_version:
        raise ValueError("runner job Codex version differs from observed control/tool versions")
    if runner_job.get("boundary", {}).get("profile_sha256") != profile_sha:
        raise ValueError("runner job is not bound to this boundary profile")

    return {
        "schema_version": 1,
        "verdict": "mock-remote-exec-reference-passed",
        "versions": {
            "control_codex": control_version,
            "tool_codex": tool_version,
        },
        "digests": {
            "boundary_profile_sha256": profile_sha,
            "runner_job_sha256": _sha(runner_job_path),
            "remote_environment_sha256": _sha(remote_environment_path),
            "network_reference_sha256": _sha(network_reference_path),
            "mock_state_sha256": _sha(mock_state_path),
            "codex_trace_sha256": _sha(codex_trace_path),
            "docker_inspect_sha256": _sha(docker_inspect_path),
            "candidate_proof_sha256": _sha(candidate_proof_path),
            "mock_server_program_sha256": _sha(mock_server_program_path),
        },
        "assertions": {
            "model_requests": 2,
            "tool_output_round_trip": True,
            "workspace_marker": True,
            "tool_network_blocked": True,
            "auth_env_clean": True,
            "candidate_proof_file": True,
            "command_execution_observed": trace["command_execution_observed"],
            "final_agent_message_observed": trace["final_agent_message_observed"],
            "docker_inspect_matches_profile": True,
            "control_plane_endpoint_reference_valid": True,
            "local_execution_disabled": remote_validation.get("include_local") is False,
        },
        "scope": (
            "credential-free mock model control plane -> Codex frontend -> network-none stdio exec-server -> "
            "tool output -> mock final, with content-bound evidence; not an external model-service authentication "
            "or Feynman-skill performance result"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--runner-job", type=Path, required=True)
    parser.add_argument("--remote-environment", type=Path, required=True)
    parser.add_argument("--network-reference", type=Path, required=True)
    parser.add_argument("--mock-state", type=Path, required=True)
    parser.add_argument("--codex-trace", type=Path, required=True)
    parser.add_argument("--docker-inspect", type=Path, required=True)
    parser.add_argument("--candidate-proof", type=Path, required=True)
    parser.add_argument("--mock-server-program", type=Path, required=True)
    parser.add_argument("--control-codex-version", type=Path, required=True)
    parser.add_argument("--tool-codex-version", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = assemble(
            boundary_profile_path=args.boundary_profile,
            runner_job_path=args.runner_job,
            remote_environment_path=args.remote_environment,
            network_reference_path=args.network_reference,
            mock_state_path=args.mock_state,
            codex_trace_path=args.codex_trace,
            docker_inspect_path=args.docker_inspect,
            candidate_proof_path=args.candidate_proof,
            mock_server_program_path=args.mock_server_program,
            control_codex_version_path=args.control_codex_version,
            tool_codex_version_path=args.tool_codex_version,
        )
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"refusing to overwrite: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
