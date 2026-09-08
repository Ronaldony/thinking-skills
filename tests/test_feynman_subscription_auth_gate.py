from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_subscription_auth_gate import CONFIG_TEXT, check, prepare


class SubscriptionAuthGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_codex(self, status: str, *, status_code: int = 0) -> Path:
        path = self.base / f"fake-{len(list(self.base.glob('fake-*')))}"
        path.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"--version\" ]; then echo 'codex-cli synthetic'; exit 0; fi\n"
            f"printf '%s\\n' {status!r}\n"
            f"exit {status_code}\n",
            encoding="utf-8",
        )
        os.chmod(path, 0o755)
        return path

    def test_prepare_creates_only_forced_chatgpt_config(self):
        home = self.base / "control"
        result = prepare(home)
        self.assertEqual(result["verdict"], "dedicated-control-home-prepared")
        self.assertEqual((home / "config.toml").read_text(encoding="utf-8"), CONFIG_TEXT)
        self.assertFalse((home / "auth.json").exists())

    def test_prepare_refuses_existing_home(self):
        home = self.base / "control"
        home.mkdir()
        with self.assertRaises(ValueError):
            prepare(home)

    def test_check_accepts_chatgpt_status_and_preserves_no_raw_output(self):
        home = self.base / "control"
        home.mkdir()
        fake = self._fake_codex("Logged in using ChatGPT as person@example.invalid")
        result = check(home, str(fake))
        self.assertEqual(result["verdict"], "chatgpt-subscription-authenticated")
        self.assertFalse(result["raw_status_output_preserved"])
        self.assertFalse(result["credential_files_read_by_gate"])
        self.assertFalse(result["authentication"]["api_key_auth_allowed"])
        self.assertNotIn("person@example.invalid", str(result))

    def test_check_rejects_non_chatgpt_status(self):
        home = self.base / "control"
        home.mkdir()
        fake = self._fake_codex("Logged in with another authentication method")
        with self.assertRaises(ValueError):
            check(home, str(fake))

    def test_check_rejects_failed_status(self):
        home = self.base / "control"
        home.mkdir()
        fake = self._fake_codex("not logged in", status_code=1)
        with self.assertRaises(ValueError):
            check(home, str(fake))

    def test_check_rejects_symlink_control_home(self):
        target = self.base / "target"
        target.mkdir()
        home = self.base / "control"
        home.symlink_to(target, target_is_directory=True)
        fake = self._fake_codex("Logged in using ChatGPT")
        with self.assertRaises(ValueError):
            check(home, str(fake))


if __name__ == "__main__":
    unittest.main()
