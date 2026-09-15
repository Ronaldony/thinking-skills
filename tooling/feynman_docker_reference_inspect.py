#!/usr/bin/env python3
"""Verify a Docker reference-boundary inspect snapshot against its profile.

Docker may represent tmpfs mounts both in HostConfig.Tmpfs and in the generic
Mounts list. This wrapper validates tmpfs entries separately, removes them from
the bind/volume comparison, then delegates the remaining launch checks to
`feynman_docker_inspect.verify_inspect`. When `--runner-job` is supplied, bind
sources are also compared with the native host-to-container mapping.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

try:
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_docker_inspect import verify_inspect
    from .feynman_path_mapping import mounts_for_job
except ImportError:
    from feynman_boundary_profile import validate_profile_file
    from feynman_docker_inspect import verify_inspect
    from feynman_path_mapping import mounts_for_job


def _load(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_inspect(profile: dict[str, Any], payload: Any) -> tuple[Any, dict[str, Any]]:
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ValueError("docker inspect JSON must contain exactly one container")
    item = deepcopy(payload[0])
    mounts = item.get("Mounts")
    host = item.get("HostConfig")
    if not isinstance(mounts, list) or not isinstance(host, dict):
        raise ValueError("docker inspect is missing Mounts/HostConfig")

    expected_tmpfs = set(profile.get("tmpfs_mounts", []))
    observed_tmpfs: set[str] = set()
    non_tmpfs: list[dict[str, Any]] = []
    for mount in mounts:
        if not isinstance(mount, dict):
            raise ValueError("docker inspect mount must be object")
        mount_type = mount.get("Type")
        destination = mount.get("Destination")
        if not isinstance(destination, str) or not destination:
            raise ValueError("docker inspect mount has no destination")
        if mount_type == "tmpfs":
            if mount.get("RW") is not True:
                raise ValueError("reference tmpfs mount must be writable")
            observed_tmpfs.add(destination)
            continue
        if mount_type not in {"bind", "volume", None}:
            raise ValueError(f"unsupported Docker mount type in reference boundary: {mount_type!r}")
        non_tmpfs.append(mount)

    host_tmpfs = host.get("Tmpfs") or {}
    if not isinstance(host_tmpfs, dict):
        raise ValueError("HostConfig.Tmpfs must be an object")
    if set(host_tmpfs) != expected_tmpfs:
        raise ValueError("HostConfig.Tmpfs differs from boundary profile")
    if observed_tmpfs and observed_tmpfs != expected_tmpfs:
        raise ValueError("Docker Mounts tmpfs destinations differ from boundary profile")

    item["Mounts"] = non_tmpfs
    normalized = [item]
    return normalized, {
        "tmpfs_mounts_observed_in_mounts": sorted(observed_tmpfs),
        "tmpfs_mounts_observed_in_host_config": sorted(host_tmpfs),
    }


def verify_reference(
    profile: dict[str, Any],
    inspect_payload: Any,
    *,
    expected_mounts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    normalized, tmpfs = normalize_inspect(profile, inspect_payload)
    result = verify_inspect(profile, normalized, expected_mounts=expected_mounts)
    return {
        **result,
        "tmpfs": tmpfs,
        "scope": (
            "pre-start Docker inspect/profile consistency after explicit tmpfs normalization; "
            "behavioral boundary properties still require canaries"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--inspect", type=Path, required=True)
    parser.add_argument("--runner-job", type=Path)
    args = parser.parse_args()
    try:
        profile, profile_sha, _ = validate_profile_file(args.profile.resolve())
        payload = _load(args.inspect.resolve())
        expected_mounts = None
        if args.runner_job is not None:
            job = _load(args.runner_job.resolve())
            expected_mounts = mounts_for_job(job, profile)
        result = verify_reference(profile, payload, expected_mounts=expected_mounts)
        result["boundary_profile_sha256"] = profile_sha
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
