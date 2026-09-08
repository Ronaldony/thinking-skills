#!/usr/bin/env python3
"""Validate an external-boundary profile manifest and report its raw SHA-256.

This validates declared profile invariants; it does not independently prove that
a container/VM was launched with those settings. Behavioral canaries are still
required, and production runners should additionally derive this manifest from
actual backend inspection where possible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

SHA_PATTERN = re.compile(r"[0-9a-f]{64}")
SECRET_KEY_PATTERN = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE|AUTH|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)",
    re.IGNORECASE,
)
REQUIRED_FIELDS = {
    "schema_version", "backend", "backend_version", "image", "image_id",
    "network_mode", "read_only_root", "no_new_privileges", "capabilities",
    "run_as", "read_write_mounts", "read_only_mounts", "tmpfs_mounts",
    "protected_roots_mounted", "candidate_env_keys", "scope",
}


def _strings(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must be a list of nonempty strings")
    if not allow_empty and not value:
        raise ValueError(f"{label} must not be empty")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")
    return value


def _absolute_posix(value: str, label: str) -> None:
    path = PurePosixPath(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute POSIX path: {value}")
    if ".." in path.parts:
        raise ValueError(f"{label} may not contain parent traversal: {value}")


def validate_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise ValueError("boundary profile must be an object")
    if set(profile) != REQUIRED_FIELDS:
        missing = sorted(REQUIRED_FIELDS - set(profile))
        extra = sorted(set(profile) - REQUIRED_FIELDS)
        raise ValueError(f"boundary profile fields mismatch: missing={missing} extra={extra}")
    if profile.get("schema_version") != 1:
        raise ValueError("unsupported boundary profile schema_version")

    for field in ("backend", "backend_version", "image", "image_id", "network_mode", "run_as", "scope"):
        if not isinstance(profile.get(field), str) or not profile[field].strip():
            raise ValueError(f"boundary profile {field} must be nonempty")
    if profile["backend"] != "docker":
        raise ValueError("boundary profile v1 currently supports only backend=docker")
    if not profile["image_id"].startswith("sha256:"):
        raise ValueError("docker image_id must be a content-addressed sha256: identifier")
    if profile["network_mode"] not in {"none", "restricted", "open"}:
        raise ValueError("unsupported boundary network_mode")
    if profile.get("read_only_root") is not True:
        raise ValueError("reference boundary requires read_only_root=true")
    if profile.get("no_new_privileges") is not True:
        raise ValueError("reference boundary requires no_new_privileges=true")

    capabilities = _strings(profile.get("capabilities"), "capabilities")
    if capabilities:
        raise ValueError("reference boundary must drop all Linux capabilities")
    protected_mounted = _strings(profile.get("protected_roots_mounted"), "protected_roots_mounted")
    if protected_mounted:
        raise ValueError("protected roots must not be mounted into the candidate boundary")

    rw_mounts = _strings(profile.get("read_write_mounts"), "read_write_mounts", allow_empty=False)
    # A production tool boundary may need no separate read-only bind mounts when
    # the runtime is entirely inside the content-addressed image. Keep the field
    # explicit for auditability, but do not force an artificial mount merely to
    # satisfy the profile shape.
    ro_mounts = _strings(profile.get("read_only_mounts"), "read_only_mounts")
    tmpfs_mounts = _strings(profile.get("tmpfs_mounts"), "tmpfs_mounts", allow_empty=False)
    for label, values in (
        ("read_write_mounts", rw_mounts),
        ("read_only_mounts", ro_mounts),
        ("tmpfs_mounts", tmpfs_mounts),
    ):
        for value in values:
            _absolute_posix(value, f"{label}[]")
    all_mounts = rw_mounts + ro_mounts + tmpfs_mounts
    if len(set(all_mounts)) != len(all_mounts):
        raise ValueError("boundary mount lists must not overlap by exact path")

    env_keys = _strings(profile.get("candidate_env_keys"), "candidate_env_keys", allow_empty=False)
    secretish = sorted(key for key in env_keys if SECRET_KEY_PATTERN.search(key))
    if secretish:
        raise ValueError("boundary profile exposes secret-like environment keys: " + ", ".join(secretish))
    required_env = {"HOME", "CODEX_HOME", "PATH", "TMPDIR"}
    if not required_env <= set(env_keys):
        raise ValueError("boundary profile is missing required candidate environment keys")

    return {
        "verdict": "profile-valid",
        "backend": profile["backend"],
        "backend_version": profile["backend_version"],
        "image": profile["image"],
        "image_id": profile["image_id"],
        "network_mode": profile["network_mode"],
        "candidate_env_keys": sorted(env_keys),
        "scope": "declared boundary-profile invariants only; not proof of actual backend launch settings",
    }


def validate_profile_file(path: Path) -> tuple[dict[str, Any], str, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"boundary profile must be a regular file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("boundary profile root must be an object")
    result = validate_profile(value)
    return value, hashlib.sha256(raw).hexdigest(), result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    try:
        _, digest, result = validate_profile_file(args.profile.resolve())
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    result = {**result, "boundary_profile_sha256": digest}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
