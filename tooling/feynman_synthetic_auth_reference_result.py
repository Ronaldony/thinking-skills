#!/usr/bin/env python3
"""Bind synthetic control-plane authentication separation evidence.

This verifier requires a mock remote-exec reference that already proved the
network-none remote tool boundary. It adds three authentication assertions:

1. every mock Responses request carried the expected synthetic bearer digest;
2. the remote tool output proved no auth-like key and no environment value with
   the same SHA-256 as the bearer;
3. an evaluator-side exact-byte leak scan found no raw bearer in the configured
   scan set.

The raw synthetic bearer is read only from a protected file and is never emitted
in the result. This is not a real external model-service authentication result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

SHA_PATTERN = re.compile(r"[0-9a-f]{64}")
AUTH_VALUE_MARKER = "AUTH_VALUE_CLEAN"


def _regular(path: Path, label: str) -> Path:
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file: {path}")
    return path


def _load_object(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} JSON root must be object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _secret(path: Path) -> bytes:
    path = _regular(path, "synthetic secret file")
    data = path.read_bytes()
    if data.endswith(b"\r\n"):
        data = data[:-2]
    elif data.endswith(b"\n"):
        data = data[:-1]
    if not data or len(data) > 4096:
        raise ValueError("synthetic secret must contain 1..4096 bytes after trailing newline removal")
    return data


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_PATTERN.fullmatch(value) is not None


def assemble(
    *,
    secret_file: Path,
    remote_reference_result_path: Path,
    mock_state_path: Path,
    leak_scan_path: Path,
) -> dict[str, Any]:
    secret_file = _regular(secret_file, "synthetic secret file")
    remote_reference_result_path = _regular(remote_reference_result_path, "remote reference result")
    mock_state_path = _regular(mock_state_path, "mock state")
    leak_scan_path = _regular(leak_scan_path, "credential leak scan")

    secret = _secret(secret_file)
    secret_sha = hashlib.sha256(secret).hexdigest()
    remote = _load_object(remote_reference_result_path, "remote reference result")
    mock = _load_object(mock_state_path, "mock state")
    leak = _load_object(leak_scan_path, "credential leak scan")

    if remote.get("schema_version") != 3 or remote.get("verdict") != "mock-remote-tool-reference-passed":
        raise ValueError("synthetic auth requires a passed remote-tool reference result schema v3")
    if remote.get("scenario") != "exec-only":
        raise ValueError("synthetic auth primary reference must use exec-only scenario")
    assertions = remote.get("assertions")
    digests = remote.get("digests")
    if not isinstance(assertions, dict) or not isinstance(digests, dict):
        raise ValueError("remote reference result lacks assertions/digests")
    for field in (
        "exec_output_round_trip", "workspace_marker", "tool_network_blocked",
        "auth_env_clean", "command_execution_observed", "final_agent_message_observed",
        "docker_inspect_matches_profile", "control_plane_endpoint_reference_valid",
        "local_execution_disabled",
    ):
        if assertions.get(field) is not True:
            raise ValueError(f"remote reference assertion is not true: {field}")
    if digests.get("mock_state_sha256") != _sha(mock_state_path):
        raise ValueError("remote reference result is not bound to supplied mock-state bytes")

    if mock.get("schema_version") != 4 or mock.get("scenario") != "exec-only":
        raise ValueError("synthetic auth requires mock-state schema v4 exec-only")
    if mock.get("validation_error") is not None:
        raise ValueError("mock server recorded validation error")
    if mock.get("expected_bearer_sha256") != secret_sha:
        raise ValueError("mock-state expected bearer digest differs from protected synthetic secret")
    requests = mock.get("requests")
    if not isinstance(requests, list) or len(requests) != 2 or not all(isinstance(item, dict) for item in requests):
        raise ValueError("synthetic exec-only mock state must contain exactly two request records")
    for index, record in enumerate(requests, 1):
        if record.get("index") != index:
            raise ValueError("mock request index sequence mismatch")
        if record.get("authorization_bearer_present") is not True:
            raise ValueError("model request did not carry bearer authorization")
        if record.get("authorization_matches_expected") is not True:
            raise ValueError("model request bearer did not match expected synthetic credential")
        if record.get("authorization_bearer_sha256") != secret_sha:
            raise ValueError("model request bearer digest differs from protected synthetic credential")
        if not _valid_sha(record.get("body_sha256")):
            raise ValueError("mock request body digest must be SHA-256")
    final_request = requests[-1]
    if final_request.get("has_exec_output") is not True:
        raise ValueError("synthetic auth final model request lacks remote exec output")
    if final_request.get("exec_output_contains_auth_env_marker") is not True:
        raise ValueError("remote exec output did not prove auth-like env-key absence")
    if final_request.get("exec_output_contains_auth_value_marker") is not True:
        raise ValueError("remote exec output did not prove credential-value hash absence")

    if leak.get("schema_version") != 1 or leak.get("verdict") != "credential-exact-bytes-not-found":
        raise ValueError("credential leak scan did not pass")
    if leak.get("secret_sha256") != secret_sha:
        raise ValueError("credential leak scan was performed against a different secret")
    if leak.get("exact_secret_found") is not False or leak.get("symlinks_allowed") is not False:
        raise ValueError("credential leak scan result is not fail-closed")
    file_count = leak.get("scanned_file_count")
    total_bytes = leak.get("scanned_total_bytes")
    if type(file_count) is not int or file_count < 1 or type(total_bytes) is not int or total_bytes < 1:
        raise ValueError("credential leak scan did not cover nonempty file data")
    files = leak.get("files")
    if not isinstance(files, list) or len(files) != file_count:
        raise ValueError("credential leak scan file manifest/count mismatch")
    for item in files:
        if not isinstance(item, dict) or not _valid_sha(item.get("sha256")):
            raise ValueError("credential leak scan file manifest is invalid")

    return {
        "schema_version": 1,
        "verdict": "synthetic-control-plane-auth-reference-passed",
        "secret_sha256": secret_sha,
        "digests": {
            "remote_reference_result_sha256": _sha(remote_reference_result_path),
            "mock_state_sha256": _sha(mock_state_path),
            "credential_leak_scan_sha256": _sha(leak_scan_path),
            "remote_codex_trace_sha256": digests.get("codex_trace_sha256"),
            "boundary_profile_sha256": digests.get("boundary_profile_sha256"),
            "runner_job_sha256": digests.get("runner_job_sha256"),
        },
        "assertions": {
            "all_model_requests_used_expected_synthetic_bearer": True,
            "raw_bearer_not_recorded_by_mock_contract": True,
            "remote_tool_auth_like_env_keys_absent": True,
            "remote_tool_matching_credential_env_value_absent": True,
            "tool_network_blocked": True,
            "local_execution_disabled": True,
            "exact_secret_bytes_absent_from_scanned_artifacts": True,
            "scan_symlinks_disallowed": True,
        },
        "scan_coverage": {
            "files": file_count,
            "bytes": total_bytes,
            "roots": leak.get("roots"),
            "explicit_files": leak.get("explicit_files"),
        },
        "scope": (
            "synthetic bearer used by host-side mock model control plane and absent as exact bytes from "
            "the verified remote tool environment/scanned artifacts; does not prove real external "
            "model-service authentication, encoded-secret absence, or Feynman skill performance"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secret-file", type=Path, required=True)
    parser.add_argument("--remote-reference-result", type=Path, required=True)
    parser.add_argument("--mock-state", type=Path, required=True)
    parser.add_argument("--leak-scan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = assemble(
            secret_file=args.secret_file,
            remote_reference_result_path=args.remote_reference_result,
            mock_state_path=args.mock_state,
            leak_scan_path=args.leak_scan,
        )
        output = args.output.resolve()
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"refusing to overwrite: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
