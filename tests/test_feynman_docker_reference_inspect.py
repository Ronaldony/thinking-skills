from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_docker_reference_inspect import verify_reference


PROFILE = {
    "schema_version": 1,
    "backend": "docker",
    "backend_version": "28.0.4",
    "image": "python:3.12-slim",
    "image_id": "sha256:" + "a" * 64,
    "network_mode": "none",
    "read_only_root": True,
    "no_new_privileges": True,
    "capabilities": [],
    "run_as": "1000:1000",
    "read_write_mounts": ["/run/candidate", "/run/home", "/run/codex", "/run/temp"],
    "read_only_mounts": ["/probe/feynman_boundary_probe.py"],
    "tmpfs_mounts": ["/tmp"],
    "protected_roots_mounted": [],
    "candidate_env_keys": ["CODEX_HOME", "HOME", "PATH", "PYTHONDONTWRITEBYTECODE", "TMPDIR"],
    "scope": "synthetic Docker profile",
}


def payload(*, include_tmpfs_mount: bool = True):
    mounts = [
        {"Type": "bind", "Destination": "/run/candidate", "RW": True},
        {"Type": "bind", "Destination": "/run/home", "RW": True},
        {"Type": "bind", "Destination": "/run/codex", "RW": True},
        {"Type": "bind", "Destination": "/run/temp", "RW": True},
        {"Type": "bind", "Destination": "/probe/feynman_boundary_probe.py", "RW": False},
    ]
    if include_tmpfs_mount:
        mounts.append({"Type": "tmpfs", "Destination": "/tmp", "RW": True})
    return [{
        "Id": "container-1",
        "Image": PROFILE["image_id"],
        "Config": {
            "User": PROFILE["run_as"],
            "Cmd": [
                "env", "-i",
                "HOME=/run/home",
                "CODEX_HOME=/run/codex",
                "PATH=/usr/local/bin:/usr/bin:/bin",
                "TMPDIR=/run/temp",
                "PYTHONDONTWRITEBYTECODE=1",
                "python", "/probe/feynman_boundary_probe.py",
            ],
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "Tmpfs": {"/tmp": "rw,nosuid,nodev"},
            "Devices": [],
            "DeviceRequests": [],
        },
        "Mounts": mounts,
    }]


class DockerReferenceInspectTests(unittest.TestCase):
    def test_tmpfs_mount_entry_is_normalized_before_bind_comparison(self):
        result = verify_reference(deepcopy(PROFILE), payload())
        self.assertEqual(result["verdict"], "docker-inspect-matches-profile")
        self.assertEqual(result["tmpfs"]["tmpfs_mounts_observed_in_mounts"], ["/tmp"])

    def test_missing_tmpfs_mount_entry_is_allowed_when_hostconfig_matches(self):
        result = verify_reference(deepcopy(PROFILE), payload(include_tmpfs_mount=False))
        self.assertEqual(result["verdict"], "docker-inspect-matches-profile")
        self.assertEqual(result["tmpfs"]["tmpfs_mounts_observed_in_host_config"], ["/tmp"])

    def test_unexpected_tmpfs_destination_is_rejected(self):
        value = payload()
        value[0]["Mounts"].append({"Type": "tmpfs", "Destination": "/other", "RW": True})
        with self.assertRaises(ValueError):
            verify_reference(deepcopy(PROFILE), value)

    def test_read_only_tmpfs_is_rejected(self):
        value = payload()
        value[0]["Mounts"][-1]["RW"] = False
        with self.assertRaises(ValueError):
            verify_reference(deepcopy(PROFILE), value)

    def test_unknown_mount_type_is_rejected(self):
        value = payload()
        value[0]["Mounts"].append({"Type": "npipe", "Destination": "/pipe", "RW": True})
        with self.assertRaises(ValueError):
            verify_reference(deepcopy(PROFILE), value)


if __name__ == "__main__":
    unittest.main()
