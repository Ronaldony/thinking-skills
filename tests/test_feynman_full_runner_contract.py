from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tooling.feynman_full_runner_contract import (
    FIXED_TEST_COMMAND,
    READ_TOOL_NAME,
    TEST_TOOL_NAME,
    TOOL_NAMES,
    WRITE_TOOL_NAME,
    build_full_runner_override,
    contract_document,
)


class FullRunnerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="feynman-full-runner-contract-")
        self.root = Path(self.temp.name)
        self.node = self.root / "node.exe"
        self.adapter = self.root / "adapter.mjs"
        self.docker = self.root / "docker.exe"
        self.docker_config = self.root / "docker-config"
        self.candidate = self.root / "candidate"
        self.docker_config.mkdir()
        self.candidate.mkdir()
        self.node.write_bytes(b"node")
        self.adapter.write_text("adapter", encoding="utf-8")
        self.docker.write_bytes(b"docker")
        (self.candidate / "candidate.py").write_text("value = 1\n", encoding="utf-8")
        (self.candidate / "test_candidate.py").write_text("assert True\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_override_has_exact_three_fixed_tools_and_no_auth_names(self):
        override = build_full_runner_override(
            node_bin=self.node, adapter=self.adapter, candidate=self.candidate,
            docker_bin=self.docker, docker_config=self.docker_config,
            docker_image_id="sha256:" + "a" * 64,
        )
        encoded = "\n".join(override.values)
        self.assertIn(
            'enabled_tools=["feynman_read_candidate","feynman_write_candidate","feynman_run_tests"]',
            encoded,
        )
        self.assertIn("FEYNMAN_FULL_RUNNER_ROOT=", encoded)
        self.assertIn("FEYNMAN_FULL_RUNNER_IMAGE=\"sha256:", encoded)
        self.assertNotIn("OPENAI_API_KEY", encoded)
        self.assertEqual(len(override.cli_args()), len(override.values) * 2)
        lineage = override.sanitized_lineage()
        self.assertEqual(lineage["tool_names"], list(TOOL_NAMES))
        self.assertFalse(lineage["model_selectable_paths"])
        self.assertFalse(lineage["model_selectable_commands"])
        self.assertFalse(lineage["model_selectable_network"])
        self.assertEqual(lineage["fixed_test_command"], ["python3", "-B", "-I", "/run/candidate/test_candidate.py"])

    def test_contract_document_is_payload_free_and_fixed(self):
        override = build_full_runner_override(
            node_bin=self.node, adapter=self.adapter, candidate=self.candidate,
            docker_bin=self.docker, docker_config=self.docker_config,
            docker_image_id="sha256:" + "b" * 64,
        )
        document = contract_document(override.sanitized_lineage())
        encoded = json.dumps(document)
        self.assertEqual(document["verdict"], "full-runner-mcp-contract-ready")
        self.assertEqual([item["name"] for item in document["tools"]], [
            READ_TOOL_NAME, WRITE_TOOL_NAME, TEST_TOOL_NAME,
        ])
        self.assertNotIn(str(self.candidate), encoded)
        self.assertNotIn("OPENAI", encoded)
        self.assertEqual(document["candidate_tool_auth_env_keys"], [])

    def test_missing_test_file_is_rejected(self):
        (self.candidate / "test_candidate.py").unlink()
        with self.assertRaises(ValueError):
            build_full_runner_override(
                node_bin=self.node, adapter=self.adapter, candidate=self.candidate,
                docker_bin=self.docker, docker_config=self.docker_config,
                docker_image_id="sha256:" + "c" * 64,
            )

    def test_non_content_addressed_image_is_rejected(self):
        with self.assertRaises(ValueError):
            build_full_runner_override(
                node_bin=self.node, adapter=self.adapter, candidate=self.candidate,
                docker_bin=self.docker, docker_config=self.docker_config,
                docker_image_id="feynman-codex-remote:local",
            )


if __name__ == "__main__":
    unittest.main()
