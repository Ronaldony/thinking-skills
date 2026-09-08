#!/usr/bin/env python3
"""Validate structural invariants of an external-runner attestation.

A valid result means the attestation is internally consistent with the evaluation
contract. It does NOT prove the external runner or its probe artifacts are honest.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

SECRET_KEY_PATTERN = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE|AUTH|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)",
    re.IGNORECASE,
)
SKILL_CONDITIONS = {"legacy-clean", "feynman-v05"}
NO_SKILL_CONDITIONS = {"baseline", "generic"}
REQUIRED_PROBES = {
    "candidate_read",
    "evaluator_read_denied",
    "source_read_denied",
    "real_home_read_denied",
    "candidate_write",
    "forbidden_write_denied",
    "ambient_skill_preflight",
    "secret_env_scan",
}


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise ValueError(f"{label} must be a list of nonempty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")
    return value


def _absolute(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute: {value}")
    return path.resolve(strict=False)


def _contains(root: Path, path: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _overlap(a: Path, b: Path) -> bool:
    return _contains(a, b) or _contains(b, a)


def _require_probe(probes: dict[str, Any], name: str) -> None:
    probe = _object(probes.get(name), f"probe {name}")
    if probe.get("passed") is not True:
        raise ValueError(f"required probe did not pass: {name}")
    sha = probe.get("artifact_sha256")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
        raise ValueError(f"probe {name} has invalid artifact_sha256")
    if not isinstance(probe.get("method"), str) or not probe["method"].strip():
        raise ValueError(f"probe {name} has no method")


def validate(attestation: dict[str, Any], *, allow_plugins: bool = False,
             allowed_system_skills: set[str] | None = None) -> dict[str, Any]:
    allowed_system_skills = allowed_system_skills or set()
    if attestation.get("schema_version") != 1:
        raise ValueError("unsupported schema_version")
    condition = attestation.get("condition_id")
    if condition not in SKILL_CONDITIONS | NO_SKILL_CONDITIONS:
        raise ValueError(f"unsupported condition_id: {condition!r}")

    boundary = _object(attestation.get("boundary"), "boundary")
    if boundary.get("external_enforcement") is not True:
        raise ValueError("external_enforcement must be true")
    for field in ("backend", "backend_version", "platform", "kernel"):
        if not isinstance(boundary.get(field), str) or not boundary[field].strip():
            raise ValueError(f"boundary.{field} must be nonempty")
    if re.fullmatch(r"[0-9a-f]{64}", str(boundary.get("profile_sha256", ""))) is None:
        raise ValueError("boundary.profile_sha256 must be SHA-256")

    paths = _object(attestation.get("paths"), "paths")
    p = {name: _absolute(paths.get(name), f"paths.{name}") for name in (
        "candidate_dir", "evaluator_dir", "source_repo", "ephemeral_home",
        "codex_home", "temp_dir", "real_home")}
    for protected_name in ("evaluator_dir", "source_repo", "real_home"):
        for candidate_name in ("candidate_dir", "ephemeral_home", "codex_home", "temp_dir"):
            if _overlap(p[protected_name], p[candidate_name]):
                raise ValueError(
                    f"protected path overlaps candidate-owned path: {protected_name} / {candidate_name}"
                )

    filesystem = _object(attestation.get("filesystem"), "filesystem")
    readable = [_absolute(x, "candidate_readable_data_roots[]") for x in
                _strings(filesystem.get("candidate_readable_data_roots"), "candidate_readable_data_roots")]
    writable = [_absolute(x, "candidate_writable_roots[]") for x in
                _strings(filesystem.get("candidate_writable_roots"), "candidate_writable_roots")]
    platform_roots = [_absolute(x, "platform_runtime_roots[]") for x in
                      _strings(filesystem.get("platform_runtime_roots"), "platform_runtime_roots")]
    forbidden_read = [_absolute(x, "forbidden_read_roots[]") for x in
                      _strings(filesystem.get("forbidden_read_roots"), "forbidden_read_roots")]
    forbidden_write = [_absolute(x, "forbidden_write_roots[]") for x in
                       _strings(filesystem.get("forbidden_write_roots"), "forbidden_write_roots")]

    protected = [p["evaluator_dir"], p["source_repo"], p["real_home"]]
    if not all(any(_contains(root, target) for root in forbidden_read) for target in protected):
        raise ValueError("forbidden_read_roots must cover evaluator_dir, source_repo, and real_home")
    if not all(any(_contains(root, target) for root in forbidden_write) for target in protected):
        raise ValueError("forbidden_write_roots must cover evaluator_dir, source_repo, and real_home")

    candidate_anchors = [p["candidate_dir"], p["ephemeral_home"], p["codex_home"], p["temp_dir"]]
    for root in readable:
        if not any(_contains(anchor, root) for anchor in candidate_anchors):
            raise ValueError(f"candidate readable data root is outside candidate-owned anchors: {root}")
    for root in writable:
        if not any(_contains(anchor, root) for anchor in candidate_anchors):
            raise ValueError(f"candidate writable root is outside candidate-owned anchors: {root}")

    # Fail closed on either containment direction. A runtime root inside a protected
    # directory leaks data just as surely as a broad runtime root containing it.
    for exposed_root in readable + writable + platform_roots:
        for target in protected:
            if _overlap(exposed_root, target):
                raise ValueError(f"exposed root overlaps protected path: {exposed_root} <-> {target}")
    for runtime_root in platform_roots:
        if runtime_root == Path(runtime_root.anchor):
            raise ValueError(f"platform runtime root may not expose filesystem root: {runtime_root}")

    network = _object(attestation.get("network"), "network")
    requires_network = network.get("case_requires_tool_network")
    if not isinstance(requires_network, bool):
        raise ValueError("case_requires_tool_network must be boolean")
    tool_network = network.get("tool_network")
    if tool_network not in {"blocked", "restricted", "open"}:
        raise ValueError("invalid tool_network")
    allowed_destinations = _strings(network.get("allowed_tool_destinations"), "allowed_tool_destinations")
    if tool_network == "blocked" and allowed_destinations:
        raise ValueError("blocked tool network must not declare allowed_tool_destinations")
    if not requires_network:
        if tool_network != "blocked":
            raise ValueError("closed-network case requires tool_network=blocked")
        if network.get("control_plane_separate_from_tool_network") is not True:
            raise ValueError("closed-network case requires control-plane/tool-network separation")

    environment = _object(attestation.get("environment"), "environment")
    env_keys = _strings(environment.get("candidate_env_keys"), "candidate_env_keys")
    secretish = sorted(key for key in env_keys if SECRET_KEY_PATTERN.search(key))
    if secretish:
        raise ValueError("candidate tool environment exposes secret-like variable names: " + ", ".join(secretish))
    if environment.get("api_auth_exposed_to_candidate_tools") is not False:
        raise ValueError("API auth must not be exposed to candidate tools")
    if environment.get("plugins_enabled") is not False and not allow_plugins:
        raise ValueError("plugins must be disabled unless explicitly allowed by the eval protocol")
    system_skills = set(_strings(environment.get("system_skills"), "system_skills"))
    if system_skills != allowed_system_skills:
        raise ValueError(
            f"system skill set mismatch: allowed={sorted(allowed_system_skills)} observed={sorted(system_skills)}"
        )
    expected_skills = set(_strings(environment.get("expected_candidate_skills"), "expected_candidate_skills"))
    observed_skills = set(_strings(environment.get("observed_candidate_skills"), "observed_candidate_skills"))
    if expected_skills != observed_skills:
        raise ValueError("expected/observed candidate skill sets differ")
    required_skills = {"feynman-thinking"} if condition in SKILL_CONDITIONS else set()
    if expected_skills != required_skills:
        raise ValueError(f"condition {condition} requires candidate skill set {sorted(required_skills)}")

    probes = _object(attestation.get("probes"), "probes")
    for name in REQUIRED_PROBES:
        _require_probe(probes, name)
    if not requires_network:
        _require_probe(probes, "tool_network_denied")

    versions = _object(attestation.get("versions"), "versions")
    for field in ("codex_cli", "model"):
        if not isinstance(versions.get(field), str) or not versions[field].strip():
            raise ValueError(f"versions.{field} must be nonempty")

    digests = _object(attestation.get("digests"), "digests")
    for field in ("eval_plan_sha256", "candidate_prompt_sha256"):
        if re.fullmatch(r"[0-9a-f]{64}", str(digests.get(field, ""))) is None:
            raise ValueError(f"digests.{field} must be SHA-256")
    runtime_sha = digests.get("runtime_sha256")
    if condition in SKILL_CONDITIONS:
        if not isinstance(runtime_sha, str) or re.fullmatch(r"[0-9a-f]{64}", runtime_sha) is None:
            raise ValueError("skill condition requires runtime_sha256")
    elif runtime_sha is not None:
        raise ValueError("no-skill condition must use runtime_sha256=null")

    limitations = attestation.get("limitations")
    if not isinstance(limitations, list) or not all(isinstance(x, str) for x in limitations):
        raise ValueError("limitations must be a list of strings")

    return {
        "verdict": "contract-valid",
        "run_id": attestation.get("run_id"),
        "case_id": attestation.get("case_id"),
        "condition_id": condition,
        "backend": boundary["backend"],
        "profile_sha256": boundary["profile_sha256"],
        "scope": "structural consistency of runner attestation; not cryptographic proof of sandbox honesty",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--allow-plugins", action="store_true")
    parser.add_argument("--allowed-system-skill", action="append", default=[])
    args = parser.parse_args()
    try:
        if args.attestation.is_symlink() or not args.attestation.is_file():
            raise ValueError("attestation must be a regular file")
        value = json.loads(args.attestation.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("attestation root must be an object")
        result = validate(value, allow_plugins=args.allow_plugins,
                          allowed_system_skills=set(args.allowed_system_skill))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
