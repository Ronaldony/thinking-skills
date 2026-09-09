from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_subscription_auth_gate import CONFIG_TEXT, _safe_env, check, prepare


class SubscriptionAuthGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_codex(self, status: str, *, status_code: int = 0, version_code: int = 0) -> Path:
        path = self.base / f"fake-{len(list(self.base.glob('fake-*')))}"
        path.write_text(
            "#!/bin/sh\n"
            f"if [ \"$1\" = \"--version\" ]; then echo 'codex-cli synthetic'; exit {version_code}; fi\n"
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
        self.assertFalse(result["authentication"]["process_environment_inherited"])
        self.assertIn("CODEX_HOME", result["authentication"]["process_environment_allowlist"])
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

    def test_version_failure_reports_only_exit_code(self):
        home = self.base / "control"
        home.mkdir()
        fake = self._fake_codex("SHOULD_NOT_BE_PRESERVED", version_code=7)
        with self.assertRaisesRegex(ValueError, r"exit code 7") as caught:
            check(home, str(fake))
        self.assertNotIn("SHOULD_NOT_BE_PRESERVED", str(caught.exception))

    def test_posix_safe_env_remains_minimal(self):
        home = self.base / "control"
        source = {
            "PATH": "/custom/bin",
            "TMPDIR": "/custom/tmp",
            "OPENAI_API_KEY": "do-not-copy",
            "RANDOM_OTHER_VAR": "do-not-copy",
        }
        env = _safe_env(home, platform_name="posix", source_env=source)
        self.assertEqual(set(env), {"HOME", "CODEX_HOME", "PATH", "TMPDIR"})
        self.assertEqual(env["PATH"], "/custom/bin")
        self.assertEqual(env["TMPDIR"], "/custom/tmp")
        self.assertNotIn("OPENAI_API_KEY", env)

    def test_windows_safe_env_keeps_only_launch_requirements(self):
        home = self.base / "control"
        source = {
            "Path": r"C:\Tools;C:\Windows\System32",
            "TEMP": r"C:\Temp",
            "TMP": r"C:\OtherTemp",
            "SystemRoot": r"C:\Windows",
            "ComSpec": r"C:\Windows\System32\cmd.exe",
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
            "WINDIR": r"C:\Windows",
            "OPENAI_API_KEY": "do-not-copy",
            "CODEX_ACCESS_TOKEN": "do-not-copy",
            "APPDATA": r"C:\Users\example\AppData\Roaming",
        }
        env = _safe_env(home, platform_name="nt", source_env=source)
        self.assertEqual(env["PATH"], source["Path"])
        self.assertEqual(env["TEMP"], source["TEMP"])
        self.assertEqual(env["TMP"], source["TEMP"])
        self.assertEqual(env["TMPDIR"], source["TEMP"])
        self.assertEqual(env["SystemRoot"], source["SystemRoot"])
        self.assertEqual(env["ComSpec"], source["ComSpec"])
        self.assertEqual(env["PATHEXT"], source["PATHEXT"])
        self.assertEqual(env["WINDIR"], source["WINDIR"])
        self.assertEqual(env["USERPROFILE"], str(home.parent))
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CODEX_ACCESS_TOKEN", env)
        self.assertNotIn("APPDATA", env)

    def test_windows_safe_env_falls_back_to_existing_parent_for_temp(self):
        home = self.base / "control"
        env = _safe_env(home, platform_name="nt", source_env={"PATH": r"C:\Windows\System32"})
        self.assertEqual(env["TEMP"], str(home.parent))
        self.assertEqual(env["TMP"], str(home.parent))
        self.assertEqual(env["TMPDIR"], str(home.parent))


if __name__ == "__main__":
    unittest.main()
