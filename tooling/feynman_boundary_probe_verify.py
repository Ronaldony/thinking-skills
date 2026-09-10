#!/usr/bin/env python3
"""Verify a boundary-probe artifact from outside the candidate sandbox.

The verifier checks synthetic canary files after the probe ran, rejects missing
host fixtures as non-evidence, and emits normalized per-probe records that can be
bound into runner attestation. It verifies observations; it does not prove that
the external runner itself is honest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Any

SECRET_KEY_PATTERN = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE|AUTH|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)",
    re.IGNORECASE,
)
SHA_PATTERN = re.compile(r"[0-9a-f]{64}")
BOUNDARY_PROBES = {
    "candidate_read",
    "evaluator_read_denied",
    "source_read_denied",
    "real_home_read_denied",
    "candidate_write",
    "forbidden_write_denied",
    "secret_env_scan",
    "tool_network_denied",
}
PATH_NAMESPACES = {"shared", "container"}


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_PATTERN.fullmatch(value) is not None


def _endpoint_identity(host: str, port: int) -> str:
    return hashlib.sha256(f"tcp://{host}:{port}".encode("utf-8")).hexdigest()


def _regular_marker(path: Path, marker: str, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} canary must exist as a regular file: {path}")
    raw = path.read_bytes()
    expected = marker.encode("utf-8")
    if raw != expected:
        raise ValueError(f"{label} canary marker mismatch: {path}")
    return {"path": str(path.absolute()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _container_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValueError(f"{label} must be an absolute POSIX container path")
    parsed = PurePosixPath(value)
    if parsed.as_posix() != value or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError(f"{label} must be a normalized POSIX container path")
    return value


def _expected_path(observation: dict[str, Any], path: Path, label: str,
                   container_path: str | None = None) -> None:
    if container_path is None:
        if observation.get("path_namespace") not in {None, "shared"}:
            raise ValueError(f"{label} observation path namespace mismatch")
        expected = str(path.absolute())
    else:
        if observation.get("path_namespace") != "container":
            raise ValueError(f"{label} observation is missing container path namespace")
        expected = container_path
    if observation.get("path") != expected:
        raise ValueError(f"{label} observation path mismatch")


def _probe(name: str, passed: bool, source_sha: str, observation: Any,
           host_check: Any, *, method_tag: str = "v1") -> dict[str, Any]:
    evidence = {
        "probe": name,
        "source_artifact_sha256": source_sha,
        "observation": observation,
        "host_check": host_check,
    }
    return {
        "passed": bool(passed),
        "artifact_sha256": _canonical_sha(evidence),
        "method": f"boundary-probe+evaluator-postcheck:{method_tag}:{name}",
    }


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema_version") != 1:
        raise ValueError("unsupported boundary probe report schema_version")
    if report.get("path_namespace") not in {None, "shared", "container"}:
        raise ValueError("boundary probe report path_namespace must be shared or container")
    if not isinstance(report.get("run_id"), str) or not report["run_id"].strip():
        raise ValueError("boundary probe report run_id must be nonempty")
    if not _valid_sha(report.get("boundary_profile_sha256")):
        raise ValueError("boundary probe report boundary_profile_sha256 must be SHA-256")
    if report.get("verdict") not in {"passed", "failed"}:
        raise ValueError("boundary probe report verdict must be passed/failed")
    for field in ("source_artifact_sha256", "probe_program_sha256"):
        if not _valid_sha(report.get(field)):
            raise ValueError(f"boundary probe report {field} must be SHA-256")
    network_sha = report.get("network_reference_sha256")
    if network_sha is not None and not _valid_sha(network_sha):
        raise ValueError("boundary probe report network_reference_sha256 must be SHA-256 or null")
    env_keys = report.get("observed_env_keys")
    if not isinstance(env_keys, list) or not all(isinstance(x, str) and x for x in env_keys):
        raise ValueError("boundary probe report observed_env_keys must be nonempty strings")
    if len(set(env_keys)) != len(env_keys):
        raise ValueError("boundary probe report observed_env_keys contain duplicates")

    probes = report.get("probes")
    if not isinstance(probes, dict) or set(probes) != BOUNDARY_PROBES:
        raise ValueError("boundary probe report has missing or unexpected probe IDs")
    for name, item in probes.items():
        if not isinstance(item, dict):
            raise ValueError(f"boundary probe report {name} must be object")
        if type(item.get("passed")) is not bool:
            raise ValueError(f"boundary probe report {name}.passed must be boolean")
        if not _valid_sha(item.get("artifact_sha256")):
            raise ValueError(f"boundary probe report {name}.artifact_sha256 must be SHA-256")
        method = item.get("method")
        if not isinstance(method, str) or not method.strip():
            raise ValueError(f"boundary probe report {name}.method must be nonempty")

    not_required = report.get("not_required_probes", [])
    if not isinstance(not_required, list) or not all(isinstance(x, str) for x in not_required):
        raise ValueError("not_required_probes must be a list of probe IDs")
    if len(set(not_required)) != len(not_required) or not set(not_required) <= BOUNDARY_PROBES:
        raise ValueError("not_required_probes contains duplicate or unknown IDs")
    failed_expected = sorted(
        name for name, item in probes.items()
        if item["passed"] is not True and name not in set(not_required)
    )
    failed_observed = report.get("failed_probes")
    if not isinstance(failed_observed, list) or failed_observed != failed_expected:
        raise ValueError("failed_probes does not match normalized probe states")
    expected_verdict = "passed" if not failed_expected else "failed"
    if report.get("verdict") != expected_verdict:
        raise ValueError("boundary probe report verdict differs from probe states")
    return report


def verify(*, artifact_path: Path, expected_run_id: str,
           expected_boundary_profile_sha256: str, probe_program: Path,
           candidate_read: Path, candidate_read_marker: str,
           evaluator_read: Path, evaluator_read_marker: str,
           source_read: Path, source_read_marker: str,
           real_home_read: Path, real_home_read_marker: str,
           candidate_write: Path, candidate_write_marker: str,
           forbidden_writes: list[Path], network_reference: Path | None = None,
           require_network_denied: bool = True,
           container_candidate_read: str | None = None,
           container_evaluator_read: str | None = None,
           container_source_read: str | None = None,
           container_real_home_read: str | None = None,
           container_candidate_write: str | None = None,
           container_forbidden_writes: list[str] | None = None) -> dict[str, Any]:
    if not _valid_sha(expected_boundary_profile_sha256):
        raise ValueError("expected boundary profile digest must be SHA-256")
    artifact_path = artifact_path.resolve()
    artifact = _load(artifact_path)
    source_sha = _sha(artifact_path)
    if artifact.get("schema_version") != 1 or artifact.get("run_id") != expected_run_id:
        raise ValueError("probe artifact schema/run_id mismatch")
    if artifact.get("boundary_profile_sha256") != expected_boundary_profile_sha256:
        raise ValueError("probe artifact boundary profile digest mismatch")
    container_paths: dict[str, str | None] = {
        "candidate_read": container_candidate_read,
        "evaluator_read": container_evaluator_read,
        "source_read": container_source_read,
        "real_home_read": container_real_home_read,
        "candidate_write": container_candidate_write,
    }
    native_namespace = any(value is not None for value in container_paths.values()) or container_forbidden_writes is not None
    if native_namespace:
        if any(value is None for value in container_paths.values()) or container_forbidden_writes is None:
            raise ValueError("native container path verification requires every container path")
        container_paths = {
            key: _container_path(value, f"container_{key}")
            for key, value in container_paths.items()
        }
        if len(container_forbidden_writes) != len(forbidden_writes):
            raise ValueError("container_forbidden_writes count mismatch")
        container_forbidden_writes = [
            _container_path(value, "container_forbidden_write")
            for value in container_forbidden_writes
        ]
        if len(set(container_forbidden_writes)) != len(container_forbidden_writes):
            raise ValueError("container_forbidden_writes must not contain duplicates")
        if artifact.get("path_namespace") != "container":
            raise ValueError("native container path verification requires container artifact namespace")
    elif artifact.get("path_namespace") not in {None, "shared"}:
        raise ValueError("shared path verification cannot accept a container artifact namespace")
    if probe_program.is_symlink() or not probe_program.is_file():
        raise ValueError("probe program must be a regular file")
    program_sha = _sha(probe_program.resolve())
    if artifact.get("probe_program_sha256") != program_sha:
        raise ValueError("probe artifact was not produced by the expected probe program bytes")
    observations = artifact.get("observations")
    if not isinstance(observations, dict):
        raise ValueError("probe artifact has no observations object")

    probes: dict[str, dict[str, Any]] = {}
    method_tag = "v1-native-container-namespace" if native_namespace else "v1"

    candidate_obs = observations.get("candidate_read")
    if not isinstance(candidate_obs, dict):
        raise ValueError("missing candidate_read observation")
    _expected_path(candidate_obs, candidate_read, "candidate_read", container_paths["candidate_read"])
    candidate_host = _regular_marker(candidate_read, candidate_read_marker, "candidate read")
    expected_marker_sha = hashlib.sha256(candidate_read_marker.encode("utf-8")).hexdigest()
    candidate_ok = (
        candidate_obs.get("succeeded") is True
        and candidate_obs.get("marker_match") is True
        and candidate_obs.get("sha256") == candidate_host["sha256"]
        and candidate_obs.get("expected_marker_sha256") == expected_marker_sha
    )
    probes["candidate_read"] = _probe(
        "candidate_read", candidate_ok, source_sha, candidate_obs, candidate_host, method_tag=method_tag
    )

    protected = observations.get("protected_reads")
    if not isinstance(protected, dict):
        raise ValueError("missing protected_reads observations")
    protected_specs = {
        "evaluator_read_denied": (
            "evaluator", evaluator_read, evaluator_read_marker, container_paths["evaluator_read"]
        ),
        "source_read_denied": (
            "source", source_read, source_read_marker, container_paths["source_read"]
        ),
        "real_home_read_denied": (
            "real_home", real_home_read, real_home_read_marker, container_paths["real_home_read"]
        ),
    }
    for probe_name, (obs_name, path, marker, container_path) in protected_specs.items():
        obs = protected.get(obs_name)
        if not isinstance(obs, dict):
            raise ValueError(f"missing protected read observation: {obs_name}")
        _expected_path(obs, path, probe_name, container_path)
        host = _regular_marker(path, marker, probe_name)
        passed = obs.get("succeeded") is False and obs.get("denied") is True
        probes[probe_name] = _probe(probe_name, passed, source_sha, obs, host, method_tag=method_tag)

    candidate_write_obs = observations.get("candidate_write")
    if not isinstance(candidate_write_obs, dict):
        raise ValueError("missing candidate_write observation")
    _expected_path(candidate_write_obs, candidate_write, "candidate_write", container_paths["candidate_write"])
    candidate_write_host = _regular_marker(candidate_write, candidate_write_marker, "candidate write")
    candidate_write_ok = (
        candidate_write_obs.get("succeeded") is True
        and candidate_write_obs.get("marker_sha256") == candidate_write_host["sha256"]
    )
    probes["candidate_write"] = _probe(
        "candidate_write", candidate_write_ok, source_sha, candidate_write_obs, candidate_write_host,
        method_tag=method_tag,
    )

    forbidden_obs = observations.get("forbidden_writes")
    if not isinstance(forbidden_obs, list) or len(forbidden_obs) != len(forbidden_writes):
        raise ValueError("forbidden write observation count mismatch")
    expected_forbidden_paths = (
        container_forbidden_writes
        if native_namespace
        else [None] * len(forbidden_writes)
    )
    forbidden_checks: list[dict[str, Any]] = []
    forbidden_ok = True
    for obs, path, container_path in zip(
        forbidden_obs, forbidden_writes, expected_forbidden_paths, strict=True
    ):
        if not isinstance(obs, dict):
            raise ValueError("forbidden write observation must be object")
        _expected_path(obs, path, "forbidden_write", container_path)
        parent = path.parent
        parent_ready = parent.exists() and parent.is_dir() and not parent.is_symlink()
        if not parent_ready:
            raise ValueError(f"forbidden write host parent must exist as a real directory: {parent}")
        absent = not path.exists() and not path.is_symlink()
        denied = obs.get("succeeded") is False and obs.get("denied") is True
        forbidden_ok = forbidden_ok and absent and denied
        forbidden_checks.append({
            "path": str(path.absolute()),
            "host_parent_exists": parent_ready,
            "absent_after_probe": absent,
        })
    probes["forbidden_write_denied"] = _probe(
        "forbidden_write_denied", forbidden_ok, source_sha, forbidden_obs, forbidden_checks,
        method_tag=method_tag,
    )

    env_obs = observations.get("environment")
    if not isinstance(env_obs, dict):
        raise ValueError("missing environment observation")
    env_keys = env_obs.get("keys")
    if not isinstance(env_keys, list) or not all(isinstance(x, str) and x for x in env_keys):
        raise ValueError("environment keys must be nonempty strings")
    if len(set(env_keys)) != len(env_keys):
        raise ValueError("environment keys contain duplicates")
    recomputed_secretish = sorted(key for key in env_keys if SECRET_KEY_PATTERN.search(key))
    observed_secretish = env_obs.get("secret_like_keys")
    env_ok = isinstance(observed_secretish, list) and sorted(observed_secretish) == recomputed_secretish == []
    probes["secret_env_scan"] = _probe(
        "secret_env_scan", env_ok, source_sha, env_obs, {"recomputed_secret_like_keys": recomputed_secretish},
        method_tag=method_tag,
    )

    network_obs = observations.get("network")
    if not isinstance(network_obs, dict):
        raise ValueError("missing network observation")
    network_host_check: dict[str, Any] = {"required": require_network_denied}
    network_ok = False
    network_reference_sha: str | None = None
    not_required: list[str] = []
    if require_network_denied:
        if network_reference is None:
            raise ValueError("network-denial verification requires a control-plane network reference")
        reference = _load(network_reference.resolve())
        network_reference_sha = _sha(network_reference.resolve())
        if reference.get("schema_version") != 1 or reference.get("reachable_from_control_plane") is not True:
            raise ValueError("network reference must confirm control-plane reachability")
        host, port = reference.get("host"), reference.get("port")
        if not isinstance(host, str) or not host or type(port) is not int or not (1 <= port <= 65535):
            raise ValueError("network reference has invalid endpoint")
        if reference.get("probe_method") != "tcp-connect:v1":
            raise ValueError("network reference must be created by tcp-connect:v1")
        if reference.get("endpoint_identity_sha256") != _endpoint_identity(host, port):
            raise ValueError("network reference endpoint identity mismatch")
        network_host_check.update({"host": host, "port": port, "reference_sha256": network_reference_sha})
        network_ok = (
            network_obs.get("attempted") is True
            and network_obs.get("host") == host
            and network_obs.get("port") == port
            and network_obs.get("connected") is False
            and isinstance(network_obs.get("error"), dict)
        )
    else:
        not_required.append("tool_network_denied")
    probes["tool_network_denied"] = _probe(
        "tool_network_denied", network_ok, source_sha, network_obs, network_host_check,
        method_tag=method_tag,
    )

    if set(probes) != BOUNDARY_PROBES:
        raise AssertionError("internal boundary probe set mismatch")
    failed = sorted(name for name, value in probes.items()
                    if value["passed"] is not True and name not in set(not_required))
    report = {
        "schema_version": 1,
        "run_id": expected_run_id,
        "boundary_profile_sha256": expected_boundary_profile_sha256,
        "verdict": "passed" if not failed else "failed",
        "failed_probes": failed,
        "not_required_probes": not_required,
        "source_artifact_sha256": source_sha,
        "probe_program_sha256": program_sha,
        "network_reference_sha256": network_reference_sha,
        "observed_env_keys": sorted(env_keys),
        "probes": probes,
        "scope": "evaluator-side verification of synthetic boundary canaries; not cryptographic proof of runner honesty",
    }
    if native_namespace:
        report["path_namespace"] = "container"
    return validate_report(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--expected-run-id", required=True)
    parser.add_argument("--boundary-profile-sha256", required=True)
    parser.add_argument("--probe-program", type=Path, default=Path(__file__).with_name("feynman_boundary_probe.py"))
    parser.add_argument("--candidate-read", type=Path, required=True)
    parser.add_argument("--candidate-read-marker", required=True)
    parser.add_argument("--evaluator-read", type=Path, required=True)
    parser.add_argument("--evaluator-read-marker", required=True)
    parser.add_argument("--source-read", type=Path, required=True)
    parser.add_argument("--source-read-marker", required=True)
    parser.add_argument("--real-home-read", type=Path, required=True)
    parser.add_argument("--real-home-read-marker", required=True)
    parser.add_argument("--candidate-write", type=Path, required=True)
    parser.add_argument("--candidate-write-marker", required=True)
    parser.add_argument("--forbidden-write", type=Path, action="append", required=True)
    parser.add_argument("--container-candidate-read")
    parser.add_argument("--container-evaluator-read")
    parser.add_argument("--container-source-read")
    parser.add_argument("--container-real-home-read")
    parser.add_argument("--container-candidate-write")
    parser.add_argument("--container-forbidden-write", action="append")
    parser.add_argument("--network-reference", type=Path)
    parser.add_argument("--allow-tool-network", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify(
            artifact_path=args.artifact,
            expected_run_id=args.expected_run_id,
            expected_boundary_profile_sha256=args.boundary_profile_sha256,
            probe_program=args.probe_program,
            candidate_read=args.candidate_read,
            candidate_read_marker=args.candidate_read_marker,
            evaluator_read=args.evaluator_read,
            evaluator_read_marker=args.evaluator_read_marker,
            source_read=args.source_read,
            source_read_marker=args.source_read_marker,
            real_home_read=args.real_home_read,
            real_home_read_marker=args.real_home_read_marker,
            candidate_write=args.candidate_write,
            candidate_write_marker=args.candidate_write_marker,
            forbidden_writes=args.forbidden_write,
            container_candidate_read=args.container_candidate_read,
            container_evaluator_read=args.container_evaluator_read,
            container_source_read=args.container_source_read,
            container_real_home_read=args.container_real_home_read,
            container_candidate_write=args.container_candidate_write,
            container_forbidden_writes=args.container_forbidden_write,
            network_reference=args.network_reference,
            require_network_denied=not args.allow_tool_network,
        )
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"refusing to overwrite: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["verdict"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
