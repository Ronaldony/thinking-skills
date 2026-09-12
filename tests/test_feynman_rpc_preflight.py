from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_rpc_preflight import _ephemeral_command, _file_uri


class RpcPreflightTests(unittest.TestCase):
    def test_windows_file_uri_is_encoded(self):
        self.assertEqual(_file_uri(r"C:\DevWorks\candidate\task.txt"), "file:///C:/DevWorks/candidate/task.txt")

    def test_ephemeral_command_replaces_name_and_adds_rm(self):
        document = {
            "environments": [{
                "program": "python.exe",
                "args": ["proxy.py", "--docker", "docker", "--", "run", "--name", "old", "image"],
            }],
        }
        command = _ephemeral_command(document, "safe-run")
        self.assertEqual(command[:5], ["python.exe", "proxy.py", "--docker", "docker", "--"])
        self.assertIn("--rm", command)
        self.assertNotIn("old", command)
        self.assertTrue(command[command.index("--name") + 1].startswith("feynman-rpc-preflight-safe-run-"))


if __name__ == "__main__":
    unittest.main()
