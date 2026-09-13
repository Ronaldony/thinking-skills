#!/usr/bin/env python3
"""Verify a Docker container inspect snapshot against a validated boundary profile.

This checks the actual container configuration before it is started. It does not
replace behavioral canaries, but it prevents a hand-written profile manifest from
silently drifting away from the Docker launch configuration.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

try:
    from .feynman_boundary_profile import validate_profile_file
except ImportError:
    from feynman_boundary_profile import validate_profile_file


def _load(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return value


def _env_keys_from_cmd(cmd: Any) -> set[str]:
    if not isinstance(cmd, list) or len(cmd) < 3 or cmd[0:2] != ["env", "-i"]:
        raise ValueError("Docker command must start with `env -i`")
    keys: set[str] = set()
    found_program = False
    for token in cmd[2:]:
        if not isinstance(token, str):
            raise ValueError("Docker command tokens must be strings")
        if not found_program and "=" in token:
            key, _ = token.split("=", 1)
            if not key:
                raise ValueError("Docker env assignment has empty key")
            if key in keys:
                raise ValueError(f"duplicate Docker env assignment: {key}")
            keys.add(key)
            continue
        found_program = True
    if not found_program:
        raise ValueError("Docker `env -i` command has no program to execute")
    return keys


def _same_host_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def verify_inspect(
    profile: dict[str, Any],
    inspect_payload: Any,
    *,
    expected_mounts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if not isinstance(inspect_payload, list) or len(inspect_payload) != 1:
        raise ValueError("docker inspect JSON must contain exactly one container")
    item = inspect_payload[0]
    if not isinstance(item, dict):
        raise ValueError("docker inspect container entry must be an object")
    host = item.get("HostConfig")
    config = item.get("Config")
    mounts = item.get("Mounts")
    if not isinstance(host, dict) or not isinstance(config, dict) or not isinstance(mounts, list):
        raise ValueError("docker inspect is missing HostConfig/Config/Mounts")

    if item.get("Image") != profile.get("image_id"):
        raise ValueError("Docker inspect image ID differs from boundary profile")
    if host.get("NetworkMode") != profile.get("network_mode"):
        raise ValueError("Docker inspect network mode differs from boundary profile")
    if host.get("ReadonlyRootfs") is not profile.get("read_only_root"):
        raise ValueError("Docker inspect read-only root differs from boundary profile")
    if host.get("Privileged") is not False:
        raise ValueError("Docker reference boundary may not be privileged")

    cap_drop = set(_string_list(host.get("CapDrop"), "HostConfig.CapDrop"))
    if cap_drop != {"ALL"}:
        raise ValueError("Docker reference boundary must use CapDrop=[ALL]")
    security_opts = set(_string_list(host.get("SecurityOpt"), "HostConfig.SecurityOpt"))
    if not any(opt in {"no-new-privileges", "no-new-privileges:true"} for opt in security_opts):
        raise ValueError("Docker reference boundary must set no-new-privileges")
    if profile.get("capabilities") != []:
        raise ValueError("boundary profile must declare no retained capabilities")

    if config.get("User") != profile.get("run_as"):
        raise ValueError("Docker inspect user differs from boundary profile")
    cmd_env_keys = _env_keys_from_cmd(config.get("Cmd"))
    if cmd_env_keys != set(profile.get("candidate_env_keys", [])):
        raise ValueError("Docker `env -i` assignments differ from boundary profile env keys")

    observed_rw: set[str] = set()
    observed_ro: set[str] = set()
    observed_sources: dict[str, tuple[str, bool]] = {}
    for mount in mounts:
        if not isinstance(mount, dict):
            raise ValueError("Docker inspect mount must be object")
        destination = mount.get("Destination")
        rw = mount.get("RW")
        if not isinstance(destination, str) or type(rw) is not bool:
            raise ValueError("Docker inspect mount lacks Destination/RW")
        source = mount.get("Source")
        if expected_mounts is not None and (not isinstance(source, str) or not source):
            raise ValueError("Docker inspect mount lacks Source for runner-job mapping verification")
        if isinstance(source, str):
            observed_sources[destination] = (source, rw)
        (observed_rw if rw else observed_ro).add(destination)
    if observed_rw != set(profile.get("read_write_mounts", [])):
        raise ValueError("Docker read-write mount destinations differ from boundary profile")
    if observed_ro != set(profile.get("read_only_mounts", [])):
        raise ValueError("Docker read-only mount destinations differ from boundary profile")
    if expected_mounts is not None:
        expected_sources = {
            mount["destination"]: (mount["source"], mount["access"] == "rw")
            for mount in expected_mounts
        }
        if set(observed_sources) != set(expected_sources):
            raise ValueError("Docker inspect mount destinations differ from runner-job mapping")
        for destination, (expected_source, expected_rw) in expected_sources.items():
            observed_source, observed_rw_flag = observed_sources[destination]
            if expected_rw != observed_rw_flag or not _same_host_path(expected_source, observed_source):
                raise ValueError(f"Docker inspect source mapping differs from runner job: {destination}")

    tmpfs = host.get("Tmpfs") or {}
    if not isinstance(tmpfs, dict):
        raise ValueError("HostConfig.Tmpfs must be an object")
    if set(tmpfs) != set(profile.get("tmpfs_mounts", [])):
        raise ValueError("Docker tmpfs mount destinations differ from boundary profile")

    devices = host.get("Devices") or []
    device_requests = host.get("DeviceRequests") or []
    if devices or device_requests:
        raise ValueError("Docker reference boundary may not expose host devices")

    return {
        "verdict": "docker-inspect-matches-profile",
        "container_id": item.get("Id"),
        "image_id": item.get("Image"),
        "network_mode": host.get("NetworkMode"),
        "read_write_mounts": sorted(observed_rw),
        "read_only_mounts": sorted(observed_ro),
        "tmpfs_mounts": sorted(tmpfs),
        "candidate_env_keys": sorted(cmd_env_keys),
        "scope": "pre-start Docker inspect/profile consistency; behavioral boundary properties still require canaries",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--inspect", type=Path, required=True)
    args = parser.parse_args()
    try:
        profile, profile_sha, _ = validate_profile_file(args.profile.resolve())
        inspect_payload = _load(args.inspect.resolve())
        result = verify_inspect(profile, inspect_payload)
        result["boundary_profile_sha256"] = profile_sha
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
