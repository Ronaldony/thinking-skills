from __future__ import annotations

from pathlib import Path
import unittest

from tooling.feynman_remote_mcp_catalog_preflight import _config_text, _docker_command


class RemoteMcpCatalogPreflightTests(unittest.TestCase):
    def test_config_has_fixed_container_paths_and_single_tool_allowlist(self):
        config = _config_text()
        self.assertIn('required = true', config)
        self.assertIn('enabled_tools = ["feynman_read_probe_byte"]', config)
        self.assertIn('FEYNMAN_BOUNDED_READ_ROOT = "/run/candidate"', config)
        self.assertNotIn("OPENAI_API_KEY", config)
        self.assertNotIn("CODEX_ACCESS_TOKEN", config)

    def test_docker_command_is_network_disabled_and_uses_readonly_candidate(self):
        command = _docker_command(
            docker="docker", docker_config=Path("docker-config"),
            image="sha256:" + "a" * 64, candidate=Path("candidate"),
            codex_home=Path("codex-home"), home=Path("home"), temp=Path("temp"),
        )
        self.assertEqual(command[0:3], ["docker", "--config", "docker-config"])
        self.assertIn("--network", command)
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertIn("candidate:/run/candidate:ro", command)
        self.assertEqual(command[-3:], ["codex", "app-server", "--stdio"])


if __name__ == "__main__":
    unittest.main()
