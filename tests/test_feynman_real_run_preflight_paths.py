from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_real_run_preflight import _real_directory, _regular


class RealRunPreflightPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.real_dir = self.base / "real"
        self.real_dir.mkdir()
        self.real_file = self.real_dir / "input.json"
        self.real_file.write_text("{}\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _symlink_or_skip(self, link: Path, target: Path, *, directory: bool = False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

    def test_regular_file_symlink_is_rejected_before_resolution(self):
        link = self.base / "file-link.json"
        self._symlink_or_skip(link, self.real_file)
        with self.assertRaises(ValueError):
            _regular(link, "test input")

    def test_intermediate_directory_symlink_is_rejected(self):
        link_dir = self.base / "dir-link"
        self._symlink_or_skip(link_dir, self.real_dir, directory=True)
        with self.assertRaises(ValueError):
            _regular(link_dir / "input.json", "test input")
        with self.assertRaises(ValueError):
            _real_directory(link_dir, "test directory")

    def test_real_file_and_directory_are_accepted(self):
        self.assertEqual(_regular(self.real_file, "test input"), self.real_file.resolve())
        self.assertEqual(_real_directory(self.real_dir, "test directory"), self.real_dir.resolve())


if __name__ == "__main__":
    unittest.main()
