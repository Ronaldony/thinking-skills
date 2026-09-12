from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_rpc_path_proxy import _docker_mounts, _fixed_error, _split_cli


class RpcPathProxyTests(unittest.TestCase):
    def test_windows_volume_spec_splits_from_the_right(self):
        mounts = _docker_mounts([
            "run", "-v", r"C:\DevWorks\candidate:/run/candidate:rw",
            "--volume", r"D:\Temp\home:/run/home:rw",
        ])
        self.assertEqual(mounts, [
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
            {"source": r"D:\Temp\home", "destination": "/run/home", "access": "rw"},
        ])

    def test_cli_requires_explicit_docker_separator(self):
        docker, args = _split_cli(["--docker", "docker.exe", "--", "run", "image"])
        self.assertEqual(docker, "docker.exe")
        self.assertEqual(args, ["run", "image"])
        with self.assertRaises(ValueError):
            _split_cli(["--docker", "docker.exe", "run", "image"])

    def test_mapping_error_response_contains_no_rejected_value(self):
        payload = _fixed_error(7)
        message = json.loads(payload)
        self.assertEqual(message, {
            "jsonrpc": "2.0",
            "error": {"code": -32001, "message": "RPC path mapping rejected"},
            "id": 7,
        })
        self.assertNotIn("C:\\", payload.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
