from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "tooling" / "docker" / "codex-remote" / "feynman_bounded_read_adapter.mjs"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for the bounded adapter protocol test")
class BoundedReadAdapterTests(unittest.TestCase):
    def run_adapter(self, fixture: bytes, calls: list[dict]) -> list[dict]:
        with tempfile.TemporaryDirectory(prefix="feynman-bounded-read-") as directory:
            root = Path(directory)
            target = root / "candidate.py"
            target.write_bytes(fixture)
            env = {
                name: os.environ[name]
                for name in ("PATH", "SystemRoot", "WINDIR", "ComSpec", "PATHEXT", "TEMP", "TMP")
                if name in os.environ
            }
            env.update(
                FEYNMAN_BOUNDED_READ_ROOT=str(root).replace("\\", "/"),
                FEYNMAN_BOUNDED_READ_FILE=str(target).replace("\\", "/"),
            )
            process = subprocess.Popen(
                ["node", str(ADAPTER)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
            )
            input_lines = "\n".join(json.dumps(item) for item in calls) + "\n"
            stdout, stderr = process.communicate(input_lines, timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            return [json.loads(line) for line in stdout.splitlines()]

    def test_initialize_lists_only_fixed_one_byte_tool(self):
        messages = self.run_adapter(b"secret-candidate-content", [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ])
        self.assertEqual(messages[0]["result"]["capabilities"], {"tools": {}})
        tool = messages[1]["result"]["tools"][0]
        self.assertEqual(tool["name"], "feynman_read_probe_byte")
        self.assertEqual(tool["inputSchema"]["additionalProperties"], False)
        self.assertNotIn("secret-candidate-content", json.dumps(messages))

    def test_call_reads_exactly_one_byte_and_second_call_is_rejected(self):
        messages = self.run_adapter(b"secret-candidate-content", [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "feynman_read_probe_byte", "arguments": {},
            }},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "feynman_read_probe_byte", "arguments": {},
            }},
        ])
        payload = json.loads(messages[0]["result"]["content"][0]["text"])
        self.assertEqual(payload["bytesRead"], 1)
        self.assertEqual(base64.b64decode(payload["byteBase64"]), b"s")
        self.assertEqual(messages[1]["error"]["message"], "bounded read call limit reached")

    def test_arbitrary_arguments_are_rejected_without_a_read(self):
        messages = self.run_adapter(b"secret-candidate-content", [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "feynman_read_probe_byte", "arguments": {"path": "/etc/passwd"},
            }},
        ])
        self.assertEqual(messages[0]["error"]["message"], "bounded read tool arguments rejected")


if __name__ == "__main__":
    unittest.main()
