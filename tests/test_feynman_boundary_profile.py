from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_boundary_profile import validate_profile


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


class BoundaryProfileTests(unittest.TestCase):
    def test_valid_reference_profile_passes(self):
        self.assertEqual(validate_profile(deepcopy(PROFILE))["verdict"], "profile-valid")

    def test_writable_root_is_rejected(self):
        value = deepcopy(PROFILE)
        value["read_only_root"] = False
        with self.assertRaises(ValueError):
            validate_profile(value)

    def test_new_privileges_are_rejected(self):
        value = deepcopy(PROFILE)
        value["no_new_privileges"] = False
        with self.assertRaises(ValueError):
            validate_profile(value)

    def test_linux_capability_is_rejected(self):
        value = deepcopy(PROFILE)
        value["capabilities"] = ["NET_ADMIN"]
        with self.assertRaises(ValueError):
            validate_profile(value)

    def test_protected_mount_is_rejected(self):
        value = deepcopy(PROFILE)
        value["protected_roots_mounted"] = ["/source"]
        with self.assertRaises(ValueError):
            validate_profile(value)

    def test_secret_like_environment_key_is_rejected(self):
        value = deepcopy(PROFILE)
        value["candidate_env_keys"].append("OPENAI_API_KEY")
        with self.assertRaises(ValueError):
            validate_profile(value)

    def test_non_content_addressed_docker_image_id_is_rejected(self):
        value = deepcopy(PROFILE)
        value["image_id"] = "latest"
        with self.assertRaises(ValueError):
            validate_profile(value)

    def test_relative_mount_is_rejected(self):
        value = deepcopy(PROFILE)
        value["read_write_mounts"] = ["relative/path"]
        with self.assertRaises(ValueError):
            validate_profile(value)

    def test_exact_mount_overlap_is_rejected(self):
        value = deepcopy(PROFILE)
        value["tmpfs_mounts"] = [value["read_write_mounts"][0]]
        with self.assertRaises(ValueError):
            validate_profile(value)

    def test_missing_required_env_key_is_rejected(self):
        value = deepcopy(PROFILE)
        value["candidate_env_keys"].remove("CODEX_HOME")
        with self.assertRaises(ValueError):
            validate_profile(value)


if __name__ == "__main__":
    unittest.main()
