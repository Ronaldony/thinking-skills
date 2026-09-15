from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_credential_leak_scan import scan


class CredentialLeakScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.secret = b"synthetic-control-plane-secret-value"
        self.secret_file = self.base / "protected-secret.txt"
        self.secret_file.write_bytes(self.secret + b"\n")
        self.root = self.base / "candidate"
        self.root.mkdir()
        (self.root / "clean.txt").write_text("safe candidate data\n", encoding="utf-8")
        self.trace = self.base / "trace.jsonl"
        self.trace.write_text('{"safe":true}\n', encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_root_and_trace_pass(self):
        result = scan(secret_file=self.secret_file, roots=[self.root], files=[self.trace])
        self.assertEqual(result["verdict"], "credential-exact-bytes-not-found")
        self.assertEqual(result["secret_sha256"], hashlib.sha256(self.secret).hexdigest())
        self.assertFalse(result["exact_secret_found"])
        self.assertEqual(result["scanned_file_count"], 2)

    def test_secret_inside_candidate_file_is_rejected(self):
        (self.root / "leak.txt").write_bytes(b"prefix-" + self.secret + b"-suffix")
        with self.assertRaises(ValueError):
            scan(secret_file=self.secret_file, roots=[self.root], files=[self.trace])

    def test_secret_inside_trace_is_rejected(self):
        self.trace.write_bytes(b'{"token":"' + self.secret + b'"}\n')
        with self.assertRaises(ValueError):
            scan(secret_file=self.secret_file, roots=[self.root], files=[self.trace])

    @unittest.skipIf(os.name == "nt", "symlink behavior differs on Windows test hosts")
    def test_symlink_in_root_is_rejected(self):
        target = self.base / "outside.txt"
        target.write_text("outside\n", encoding="utf-8")
        (self.root / "link.txt").symlink_to(target)
        with self.assertRaises(ValueError):
            scan(secret_file=self.secret_file, roots=[self.root], files=[self.trace])

    def test_oversized_file_is_rejected(self):
        (self.root / "large.bin").write_bytes(b"x" * 101)
        with self.assertRaises(ValueError):
            scan(
                secret_file=self.secret_file,
                roots=[self.root],
                files=[self.trace],
                max_file_bytes=100,
                max_total_bytes=1000,
            )

    def test_total_byte_limit_is_rejected(self):
        (self.root / "a.bin").write_bytes(b"a" * 50)
        (self.root / "b.bin").write_bytes(b"b" * 50)
        with self.assertRaises(ValueError):
            scan(
                secret_file=self.secret_file,
                roots=[self.root],
                files=[self.trace],
                max_file_bytes=100,
                max_total_bytes=90,
            )

    def test_explicit_file_already_under_root_is_rejected(self):
        with self.assertRaises(ValueError):
            scan(
                secret_file=self.secret_file,
                roots=[self.root],
                files=[self.root / "clean.txt"],
            )

    def test_duplicate_roots_are_rejected(self):
        with self.assertRaises(ValueError):
            scan(secret_file=self.secret_file, roots=[self.root, self.root], files=[])

    def test_empty_secret_is_rejected(self):
        self.secret_file.write_bytes(b"")
        with self.assertRaises(ValueError):
            scan(secret_file=self.secret_file, roots=[self.root], files=[])

    def test_secret_with_only_newline_is_rejected(self):
        self.secret_file.write_bytes(b"\n")
        with self.assertRaises(ValueError):
            scan(secret_file=self.secret_file, roots=[self.root], files=[])

    @unittest.skipIf(os.name == "nt", "FIFO unavailable on Windows")
    def test_special_file_is_rejected(self):
        fifo = self.root / "pipe"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            scan(secret_file=self.secret_file, roots=[self.root], files=[self.trace])


if __name__ == "__main__":
    unittest.main()
