"""Portable fixtures for tests that exercise the native Docker path contract."""
from __future__ import annotations

import os
from typing import Any, Mapping

from tooling.feynman_path_mapping import CONTAINER_DESTINATIONS, native_mounts


def use_native_profile(profile: dict[str, Any], paths: Mapping[str, str]) -> dict[str, Any]:
    """Use host-to-POSIX mounts on Windows and preserve legacy POSIX fixtures elsewhere."""
    if os.name == "nt":
        profile["read_write_mounts"] = [
            CONTAINER_DESTINATIONS[key]
            for key in ("candidate_dir", "ephemeral_home", "codex_home", "temp_dir")
        ]
        profile["read_only_mounts"] = []
    return profile


def attach_native_mounts(job: dict[str, Any], paths: Mapping[str, str]) -> dict[str, Any]:
    """Attach explicit native source/destination mounts where Windows needs them."""
    if os.name == "nt":
        job.setdefault("boundary", {})["mounts"] = native_mounts(paths)
    return job
