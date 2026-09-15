from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_docker_inspect import verify_inspect


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


def inspect_payload():
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
        "Mounts": [
            {"Destination": "/run/candidate", "RW": True},
            {"Destination": "/run/home", "RW": True},
            {"Destination": "/run/codex", "RW": True},
            {"Destination": "/run/temp", "RW": True},
            {"Destination": "/probe/feynman_boundary_probe.py", "RW": False},
        ],
    }]


class DockerInspectTests(unittest.TestCase):
    def test_matching_inspect_passes(self):
        result = verify_inspect(deepcopy(PROFILE), inspect_payload())
        self.assertEqual(result["verdict"], "docker-inspect-matches-profile")

    def test_extra_read_write_mount_is_rejected(self):
        value = inspect_payload()
        value[0]["Mounts"].append({"Destination": "/source", "RW": True})
        with self.assertRaises(ValueError):
            verify_inspect(deepcopy(PROFILE), value)

    def test_privileged_container_is_rejected(self):
        value = inspect_payload()
        value[0]["HostConfig"]["Privileged"] = True
        with self.assertRaises(ValueError):
            verify_inspect(deepcopy(PROFILE), value)

    def test_network_mode_drift_is_rejected(self):
        value = inspect_payload()
        value[0]["HostConfig"]["NetworkMode"] = "bridge"
        with self.assertRaises(ValueError):
            verify_inspect(deepcopy(PROFILE), value)

    def test_missing_no_new_privileges_is_rejected(self):
        value = inspect_payload()
        value[0]["HostConfig"]["SecurityOpt"] = []
        with self.assertRaises(ValueError):
            verify_inspect(deepcopy(PROFILE), value)

    def test_env_assignment_drift_is_rejected(self):
        value = inspect_payload()
        value[0]["Config"]["Cmd"].insert(2, "EXTRA=value")
        with self.assertRaises(ValueError):
            verify_inspect(deepcopy(PROFILE), value)

    def test_env_i_is_required(self):
        value = inspect_payload()
        value[0]["Config"]["Cmd"] = ["python", "/probe/feynman_boundary_probe.py"]
        with self.assertRaises(ValueError):
            verify_inspect(deepcopy(PROFILE), value)

    def test_host_device_exposure_is_rejected(self):
        value = inspect_payload()
        value[0]["HostConfig"]["Devices"] = [{"PathOnHost": "/dev/kvm"}]
        with self.assertRaises(ValueError):
            verify_inspect(deepcopy(PROFILE), value)

    def test_wrong_image_id_is_rejected(self):
        value = inspect_payload()
        value[0]["Image"] = "sha256:" + "b" * 64
        with self.assertRaises(ValueError):
            verify_inspect(deepcopy(PROFILE), value)


if __name__ == "__main__":
    unittest.main()
