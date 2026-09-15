from __future__ import annotations

import unittest

from pathlib import Path
import tempfile
from unittest.mock import patch

from tooling.feynman_mcp_catalog_preflight import run, summarize_status


class McpCatalogPreflightTests(unittest.TestCase):
    def test_summary_exposes_tool_names_but_not_auth_or_payload(self):
        result = summarize_status({"data": [{
            "name": "bounded",
            "authStatus": "notLoggedIn",
            "runtimeStatus": "connected",
            "toolsError": None,
            "tools": {
                "feynman_read_probe_byte": {
                    "inputSchema": {
                        "type": "object", "properties": {}, "additionalProperties": False,
                    },
                    "description": "private tool payload must not be persisted",
                },
            },
        }]})
        self.assertTrue(result["servers"][0]["target_tool_present"])
        self.assertTrue(result["servers"][0]["target_tool_has_empty_input_schema"])
        encoded = str(result)
        self.assertNotIn("authStatus", encoded)
        self.assertNotIn("notLoggedIn", encoded)
        self.assertNotIn("private tool payload", encoded)

    def test_invalid_catalog_is_rejected(self):
        with self.assertRaises(ValueError):
            summarize_status({"data": [{"name": "bounded", "tools": []}]})

    def test_transient_mode_rejects_nonempty_codex_home_before_launch(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            home.mkdir()
            (home / "config.toml").write_text("model='x'", encoding="utf-8")
            with patch("tooling.feynman_mcp_catalog_preflight.subprocess.Popen") as launch:
                with self.assertRaises(ValueError):
                    run(codex_bin="codex", codex_home=home, output=root / "out.json",
                        config_overrides=("mcp_servers.x.enabled=true",))
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
