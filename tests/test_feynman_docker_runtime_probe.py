from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tooling.feynman_docker_runtime_probe import _inspect_container, run


class DockerRuntimeProbeTests(unittest.TestCase):
    def test_inspect_container_keeps_only_safe_state_fields(self):
        completed = type("Completed", (), {
            "returncode": 0,
            "stdout": b"running|0|false\n",
        })()
        with patch("tooling.feynman_docker_runtime_probe.subprocess.run", return_value=completed):
            result = _inspect_container(Path("docker"), Path("config"), "owned-name")
        self.assertEqual(result, {
            "available": True, "status": "running", "exit_code": 0,
            "oom_killed": False,
        })

    def test_inspect_container_rejects_unexpected_state_text(self):
        completed = type("Completed", (), {
            "returncode": 0,
            "stdout": b"private-state|0|false\n",
        })()
        with patch("tooling.feynman_docker_runtime_probe.subprocess.run", return_value=completed):
            result = _inspect_container(Path("docker"), Path("config"), "owned-name")
        self.assertEqual(result["status"], "unknown")
        self.assertNotIn("private-state", json.dumps(result))

    def test_runtime_probe_rejects_existing_output_before_subprocess(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "report.json"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "new absolute"):
                run(docker=Path("docker"), config=Path(raw),
                    image="sha256:" + "0" * 64, output=output)


if __name__ == "__main__":
    unittest.main()
