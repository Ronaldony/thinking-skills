from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tooling.feynman_full_runner_contract import TOOL_NAMES
from tooling.feynman_full_runner_preflight import run


@unittest.skipUnless(os.name == "nt", "native Codex catalog integration test is Windows-only")
class FullRunnerCatalogPreflightTests(unittest.TestCase):
    def test_codex_app_server_exposes_exact_fixed_contract_without_model(self):
        app_data = os.environ.get("APPDATA") or r"C:\Users\wotmd\AppData\Roaming"
        program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
        local_app_data = os.environ.get("LOCALAPPDATA") or r"C:\Users\wotmd\AppData\Local"
        temp_dir = os.environ.get("TEMP") or r"C:\Users\wotmd\AppData\Local\Temp"
        codex = Path(app_data) / "npm" / "codex.cmd"
        node = Path(program_files) / "nodejs" / "node.exe"
        docker = Path(local_app_data) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
        docker_config = Path(temp_dir) / "feynman-empty-docker-config"
        image = "feynman-codex-remote:full-runner-local"
        if not all(path.is_file() for path in (codex, node, docker)) or not docker_config.is_dir():
            self.skipTest("local Codex, Node, Docker, or empty Docker config is unavailable")
        inspected = subprocess.run(
            [str(docker), "--config", str(docker_config), "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True, text=True, check=False,
        )
        if inspected.returncode != 0 or not inspected.stdout.strip().startswith("sha256:"):
            self.skipTest("full-runner local Docker image is unavailable")
        with tempfile.TemporaryDirectory(prefix="feynman-full-runner-catalog-") as raw:
            root = Path(raw)
            candidate = root / "candidate"
            candidate.mkdir()
            (candidate / "candidate.py").write_text("value = 1\n", encoding="utf-8")
            (candidate / "test_candidate.py").write_text("assert True\n", encoding="utf-8")
            catalog_home = root / "catalog-home"
            catalog_home.mkdir()
            output = root / "full-runner.json"
            result = run(
                codex_bin=str(codex), codex_home=catalog_home, output=output,
                node_bin=node, adapter=Path(__file__).parents[1] / "tooling" / "docker" / "codex-remote" / "feynman_full_runner_adapter.mjs",
                candidate=candidate, docker_bin=docker, docker_config=docker_config,
                docker_image_id=inspected.stdout.strip(), timeout_seconds=30,
            )
        self.assertEqual(result["verdict"], "full-runner-mcp-contract-ready")
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["catalog"]["tool_names"], sorted(TOOL_NAMES))
        self.assertEqual(result["privacy"]["model_request_started"], False)
        self.assertEqual(result["privacy"]["credential_files_read"], False)


if __name__ == "__main__":
    unittest.main()
