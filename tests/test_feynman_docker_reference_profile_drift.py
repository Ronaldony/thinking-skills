from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_docker_reference_inspect import verify_reference
from tests.test_feynman_docker_reference_inspect import PROFILE, payload


class DockerReferenceProfileDriftTests(unittest.TestCase):
    def test_hostconfig_tmpfs_missing_from_profile_is_rejected(self):
        profile = deepcopy(PROFILE)
        profile["tmpfs_mounts"] = []
        with self.assertRaises(ValueError):
            verify_reference(profile, payload())

    def test_hostconfig_tmpfs_extra_destination_is_rejected(self):
        value = payload()
        value[0]["HostConfig"]["Tmpfs"]["/other"] = "rw"
        with self.assertRaises(ValueError):
            verify_reference(deepcopy(PROFILE), value)


if __name__ == "__main__":
    unittest.main()
