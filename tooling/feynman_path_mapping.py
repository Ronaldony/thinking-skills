#!/usr/bin/env python3
r"""Canonical host-to-container path mapping for the Docker candidate boundary.

The runner job records host paths because the control plane creates and checks
those directories. Docker receives the separate POSIX destinations declared by
this module. Keeping the two namespaces explicit is required for native
Windows hosts, where a host path such as ``C:\\work\\candidate`` cannot also be
the Linux container workdir.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

PATH_KEYS = ("candidate_dir", "ephemeral_home", "codex_home", "temp_dir")
CONTAINER_DESTINATIONS = {
    "candidate_dir": "/run/candidate",
    "ephemeral_home": "/run/home",
    "codex_home": "/run/codex",
    "temp_dir": "/run/temp",
}
MOUNT_FIELDS = {"source", "destination", "access"}


def _host_absolute(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty absolute host path")
    path = Path(value)
    # The second branch makes the data contract testable on a non-Windows
    # host while retaining the native Windows drive-letter grammar.
    if path.is_absolute():
        return str(path.resolve(strict=False))
    windows = PureWindowsPath(value)
    if windows.is_absolute():
        return str(windows)
    raise ValueError(f"{label} must be an absolute host path: {value}")


def _container_absolute(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty absolute container path")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be an absolute POSIX path without traversal: {value}")
    return str(path)


def native_mounts(paths: Mapping[str, str]) -> list[dict[str, str]]:
    """Return the four canonical writable host-to-container bind mounts."""
    return [
        {
            "source": _host_absolute(paths[key], f"paths.{key}"),
            "destination": CONTAINER_DESTINATIONS[key],
            "access": "rw",
        }
        for key in PATH_KEYS
    ]


def build_mounts(paths: Mapping[str, str], profile: Mapping[str, Any]) -> list[dict[str, str]]:
    """Build a job mapping, retaining identity behavior for old POSIX fixtures."""
    profile_rw = {
        _container_absolute(value, "profile.read_write_mounts[]")
        for value in profile.get("read_write_mounts", [])
    }
    profile_ro = profile.get("read_only_mounts")
    if profile_rw == set(CONTAINER_DESTINATIONS.values()) and profile_ro == []:
        return native_mounts(paths)
    return _legacy_identity_mounts(paths, profile)


def _legacy_identity_mounts(paths: Mapping[str, str], profile: Mapping[str, Any]) -> list[dict[str, str]]:
    """Read pre-migration POSIX fixtures without treating them as Windows-safe."""
    rw = profile.get("read_write_mounts")
    if not isinstance(rw, list) or len(rw) != len(PATH_KEYS):
        raise ValueError("legacy boundary profile must declare exactly four writable mounts")
    expected_sources = {_host_absolute(paths[key], f"paths.{key}") for key in PATH_KEYS}
    normalized = {_container_absolute(value, "profile.read_write_mounts[]") for value in rw}
    if normalized != expected_sources:
        raise ValueError(
            "boundary profile writable mounts are neither canonical container destinations "
            "nor the legacy POSIX identity mapping"
        )
    return [
        {"source": source, "destination": source, "access": "rw"}
        for source in sorted(expected_sources)
    ]


def mounts_for_job(job: Mapping[str, Any], profile: Mapping[str, Any]) -> list[dict[str, str]]:
    """Resolve the explicit native mapping, or a legacy POSIX identity mapping."""
    paths = job.get("paths")
    if not isinstance(paths, Mapping):
        raise ValueError("runner job has no paths object")
    boundary = job.get("boundary")
    if not isinstance(boundary, Mapping):
        raise ValueError("runner job has no boundary object")
    supplied = boundary.get("mounts")
    if supplied is None:
        return _legacy_identity_mounts(paths, profile)
    if not isinstance(supplied, list) or not supplied:
        raise ValueError("runner job boundary.mounts must be a nonempty list")

    mounts: list[dict[str, str]] = []
    destinations: set[str] = set()
    sources: set[str] = set()
    for index, item in enumerate(supplied):
        if not isinstance(item, Mapping) or set(item) != MOUNT_FIELDS:
            raise ValueError(f"runner job boundary.mounts[{index}] has invalid fields")
        source = _host_absolute(item.get("source"), f"boundary.mounts[{index}].source")
        destination = _container_absolute(item.get("destination"), f"boundary.mounts[{index}].destination")
        access = item.get("access")
        if access not in {"rw", "ro"}:
            raise ValueError(f"boundary.mounts[{index}].access must be rw or ro")
        if source in sources or destination in destinations:
            raise ValueError("runner job boundary mounts must have unique source/destination paths")
        sources.add(source)
        destinations.add(destination)
        mounts.append({"source": source, "destination": destination, "access": access})

    expected_by_destination = {
        CONTAINER_DESTINATIONS[key]: _host_absolute(paths[key], f"paths.{key}")
        for key in PATH_KEYS
    }
    rw = {item["destination"]: item["source"] for item in mounts if item["access"] == "rw"}
    legacy_by_destination = {
        _host_absolute(paths[key], f"paths.{key}"): _host_absolute(paths[key], f"paths.{key}")
        for key in PATH_KEYS
    }
    ro = {item["destination"] for item in mounts if item["access"] == "ro"}
    profile_rw = {_container_absolute(value, "profile.read_write_mounts[]") for value in profile.get("read_write_mounts", [])}
    profile_ro = {_container_absolute(value, "profile.read_only_mounts[]") for value in profile.get("read_only_mounts", [])}
    if rw == legacy_by_destination and not ro and profile_rw == set(legacy_by_destination):
        return mounts
    if rw != expected_by_destination:
        raise ValueError("runner job writable mount mapping must cover the four candidate-owned roots exactly")
    if set(rw) != profile_rw or ro != profile_ro:
        raise ValueError("runner job mount destinations differ from boundary profile")
    return mounts


def container_path_for_key(job: Mapping[str, Any], profile: Mapping[str, Any], key: str) -> str:
    if key not in PATH_KEYS:
        raise ValueError(f"unsupported mapped path key: {key}")
    mounts = mounts_for_job(job, profile)
    for mount in mounts:
        if mount["destination"] == CONTAINER_DESTINATIONS[key]:
            return mount["destination"]
    paths = job.get("paths")
    if isinstance(paths, Mapping):
        source = _host_absolute(paths.get(key), f"paths.{key}")
        for mount in mounts:
            if mount["source"] == source and mount["source"] == mount["destination"]:
                return mount["destination"]
    raise ValueError(f"runner job has no mapped destination for {key}")
