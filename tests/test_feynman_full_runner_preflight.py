from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tooling.feynman_full_runner_contract import TOOL_NAMES
from tooling.feynman_full_runner_preflight import run


INTEGRATION_OPT_IN = "FEYNMAN_RUN_DOCKER_INTEGRATION"


def _integration_enabled() -> bool:
    """Keep Docker/Codex integration out of the default unit suite."""
    return os.environ.get(INTEGRATION_OPT_IN, "").strip().lower() in {
        "1", "true", "yes",
    }


class FullRunnerIntegrationGateTests(unittest.TestCase):
    def test_docker_catalog_is_disabled_without_explicit_opt_in(self):
        with patch.dict(os.environ, {INTEGRATION_OPT_IN: "0"}):
            self.assertFalse(_integration_enabled())

    def test_docker_catalog_accepts_only_explicit_true_values(self):
        for value in ("1", "true", "YES"):
            with self.subTest(value=value), patch.dict(
                    os.environ, {INTEGRATION_OPT_IN: value}):
                self.assertTrue(_integration_enabled())
        for value in ("", "0", "no", "enabled"):
            with self.subTest(value=value), patch.dict(
                    os.environ, {INTEGRATION_OPT_IN: value}):
                self.assertFalse(_integration_enabled())


@unittest.skipUnless(
    os.name == "nt" and _integration_enabled(),
    "native Docker/Codex catalog integration requires explicit "
    "FEYNMAN_RUN_DOCKER_INTEGRATION=1 opt-in",
)
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
            capture_output=True, text=True, check=False, timeout=10,
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
