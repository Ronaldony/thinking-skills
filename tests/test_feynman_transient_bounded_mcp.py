from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tooling.feynman_transient_bounded_mcp import build_bounded_mcp_override


class TransientBoundedMcpTests(unittest.TestCase):
    def test_override_has_fixed_empty_argument_tool_authority(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            node = root / "node.exe"
            adapter = root / "adapter.mjs"
            candidate = root / "candidate"
            candidate.mkdir()
            node.write_bytes(b"node")
            adapter.write_text("adapter", encoding="utf-8")
            (candidate / "candidate.py").write_text("print('ok')", encoding="utf-8")
            override = build_bounded_mcp_override(
                node_bin=node, adapter=adapter, candidate=candidate)

        encoded = "\n".join(override.values)
        self.assertIn("enabled_tools=[\"feynman_read_probe_byte\"]", encoded)
        self.assertIn("default_tools_approval_mode=\"auto\"", encoded)
        self.assertIn("FEYNMAN_BOUNDED_READ_FILE=", encoded)
        self.assertNotIn("OPENAI", encoded)
        self.assertEqual(len(override.cli_args()), len(override.values) * 2)
        self.assertEqual(override.sanitized_lineage()["fixed_read_limit_bytes"], 1)
        self.assertFalse(override.sanitized_lineage()["model_selectable_arguments"])

    def test_missing_candidate_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            node = root / "node.exe"
            adapter = root / "adapter.mjs"
            candidate = root / "candidate"
            candidate.mkdir()
            node.write_bytes(b"node")
            adapter.write_text("adapter", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_bounded_mcp_override(
                    node_bin=node, adapter=adapter, candidate=candidate)


if __name__ == "__main__":
    unittest.main()
