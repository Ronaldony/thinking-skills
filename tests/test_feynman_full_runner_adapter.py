from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "tooling" / "docker" / "codex-remote" / "feynman_full_runner_adapter.mjs"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for the full-runner adapter protocol test")
class FullRunnerAdapterTests(unittest.TestCase):
    def run_adapter(self, messages: list[dict]) -> list[dict]:
        with tempfile.TemporaryDirectory(prefix="feynman-full-runner-adapter-") as raw:
            root = Path(raw)
            candidate = root / "candidate"
            docker_config = root / "docker-config"
            candidate.mkdir()
            docker_config.mkdir()
            (candidate / "candidate.py").write_text("value = 1\n", encoding="utf-8")
            (candidate / "test_candidate.py").write_text("assert True\n", encoding="utf-8")
            env = {
                key: os.environ[key]
                for key in ("PATH", "SystemRoot", "WINDIR", "ComSpec", "PATHEXT", "TEMP", "TMP")
                if key in os.environ
            }
            env.update({
                "FEYNMAN_FULL_RUNNER_ROOT": str(candidate),
                "FEYNMAN_FULL_RUNNER_DOCKER": os.environ.get("ComSpec", os.environ.get("SystemRoot", "")),
                "FEYNMAN_FULL_RUNNER_DOCKER_CONFIG": str(docker_config),
                "FEYNMAN_FULL_RUNNER_IMAGE": "sha256:" + "d" * 64,
            })
            docker = Path(env["FEYNMAN_FULL_RUNNER_DOCKER"])
            if not docker.is_file():
                self.skipTest("Windows command host executable is unavailable")
            process = subprocess.Popen(
                [shutil.which("node"), str(ADAPTER)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", env=env,
            )
            payload = "\n".join(json.dumps(item) for item in messages) + "\n"
            stdout, stderr = process.communicate(payload, timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            return [json.loads(line) for line in stdout.splitlines()]

    def test_tools_are_fixed_and_read_write_have_no_path_argument(self):
        messages = self.run_adapter([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "feynman_read_candidate", "arguments": {},
            }},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                "name": "feynman_write_candidate", "arguments": {"content": "value = 2\n"},
            }},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
                "name": "feynman_read_candidate", "arguments": {"path": "candidate.py"},
            }},
        ])
        tools = messages[1]["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], [
            "feynman_read_candidate", "feynman_write_candidate", "feynman_run_tests",
        ])
        read_result = json.loads(messages[2]["result"]["content"][0]["text"])
        write_result = json.loads(messages[3]["result"]["content"][0]["text"])
        self.assertEqual(read_result["file"], "candidate.py")
        self.assertEqual(write_result["file"], "candidate.py")
        self.assertEqual(write_result["verdict"], "candidate-written")
        self.assertEqual(messages[4]["error"]["message"], "candidate read arguments rejected")

    def test_unknown_tool_and_arbitrary_write_path_are_rejected(self):
        messages = self.run_adapter([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "shell", "arguments": {},
            }},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "feynman_write_candidate", "arguments": {
                    "content": "x", "path": "../outside",
                },
            }},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "feynman_run_tests", "arguments": {"command": "whoami"},
            }},
        ])
        self.assertEqual(messages[0]["error"]["message"], "full-runner tool name rejected")
        self.assertEqual(messages[1]["error"]["message"], "candidate write arguments rejected")
        self.assertEqual(messages[2]["error"]["message"], "fixed test arguments rejected")


if __name__ == "__main__":
    unittest.main()
