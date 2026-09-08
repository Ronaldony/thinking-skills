from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_boundary_probe import run_probe
from tooling.feynman_boundary_probe_verify import BOUNDARY_PROBES, verify


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BoundaryProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.probe_program = ROOT / "tooling/feynman_boundary_probe.py"
        self.candidate_read = self.base / "candidate/read-canary.txt"
        self.evaluator_read = self.base / "evaluator/read-canary.txt"
        self.source_read = self.base / "source/read-canary.txt"
        self.real_home_read = self.base / "real-home/read-canary.txt"
        self.candidate_write = self.base / "candidate/write-canary.txt"
        self.forbidden_writes = [
            self.base / "evaluator/forbidden-write.txt",
            self.base / "source/forbidden-write.txt",
            self.base / "real-home/forbidden-write.txt",
        ]
        self.markers = {
            "candidate": "candidate-marker",
            "evaluator": "evaluator-marker",
            "source": "source-marker",
            "real_home": "real-home-marker",
            "candidate_write": "candidate-write-marker",
        }
        for path, marker in (
            (self.candidate_read, self.markers["candidate"]),
            (self.evaluator_read, self.markers["evaluator"]),
            (self.source_read, self.markers["source"]),
            (self.real_home_read, self.markers["real_home"]),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(marker, encoding="utf-8")
        self.candidate_write.parent.mkdir(parents=True, exist_ok=True)
        self.candidate_write.write_text(self.markers["candidate_write"], encoding="utf-8")
        self.network_reference = self.base / "network-reference.json"
        self.network_reference.write_text(json.dumps({
            "schema_version": 1,
            "host": "127.0.0.1",
            "port": 43123,
            "reachable_from_control_plane": True,
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _artifact(self, *, secret_key: str | None = None):
        env_keys = ["HOME", "PATH", "TMPDIR"]
        if secret_key:
            env_keys.append(secret_key)
        program_sha = sha(self.probe_program)

        def denied(path: Path, *, err: int = errno.EACCES):
            error_type = "FileNotFoundError" if err == errno.ENOENT else "PermissionError"
            return {
                "path": str(path.absolute()),
                "succeeded": False,
                "denied": True,
                "error": {"type": error_type, "errno": err, "message": "blocked"},
            }

        return {
            "schema_version": 1,
            "run_id": "run-boundary",
            "probe_program_sha256": program_sha,
            "observations": {
                "candidate_read": {
                    "path": str(self.candidate_read.absolute()),
                    "succeeded": True,
                    "denied": False,
                    "bytes": len(self.markers["candidate"]),
                    "sha256": hashlib.sha256(self.markers["candidate"].encode()).hexdigest(),
                    "expected_marker_sha256": hashlib.sha256(self.markers["candidate"].encode()).hexdigest(),
                    "marker_match": True,
                },
                "protected_reads": {
                    "evaluator": denied(self.evaluator_read),
                    "source": denied(self.source_read),
                    "real_home": denied(self.real_home_read),
                },
                "candidate_write": {
                    "path": str(self.candidate_write.absolute()),
                    "succeeded": True,
                    "denied": False,
                    "marker_sha256": hashlib.sha256(self.markers["candidate_write"].encode()).hexdigest(),
                },
                "forbidden_writes": [denied(path) for path in self.forbidden_writes],
                "environment": {
                    "keys": env_keys,
                    "secret_like_keys": [secret_key] if secret_key else [],
                },
                "network": {
                    "attempted": True,
                    "host": "127.0.0.1",
                    "port": 43123,
                    "connected": False,
                    "error": {"type": "PermissionError", "errno": 13, "message": "blocked"},
                },
            },
        }

    def _write_artifact(self, value: dict) -> Path:
        path = self.base / "probe-artifact.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def _verify(self, artifact: Path):
        return verify(
            artifact_path=artifact,
            expected_run_id="run-boundary",
            probe_program=self.probe_program,
            candidate_read=self.candidate_read,
            candidate_read_marker=self.markers["candidate"],
            evaluator_read=self.evaluator_read,
            evaluator_read_marker=self.markers["evaluator"],
            source_read=self.source_read,
            source_read_marker=self.markers["source"],
            real_home_read=self.real_home_read,
            real_home_read_marker=self.markers["real_home"],
            candidate_write=self.candidate_write,
            candidate_write_marker=self.markers["candidate_write"],
            forbidden_writes=self.forbidden_writes,
            network_reference=self.network_reference,
            require_network_denied=True,
        )

    def test_synthetic_denials_and_postchecks_produce_passed_report(self):
        report = self._verify(self._write_artifact(self._artifact()))
        self.assertEqual(report["verdict"], "passed")
        self.assertEqual(set(report["probes"]), BOUNDARY_PROBES)
        self.assertTrue(all(item["passed"] for item in report["probes"].values()))

    def test_mount_namespace_hidden_paths_can_pass_when_host_fixtures_exist(self):
        artifact = self._artifact()
        for obs in artifact["observations"]["protected_reads"].values():
            obs["error"] = {"type": "FileNotFoundError", "errno": errno.ENOENT, "message": "hidden"}
            obs["denied"] = True
        for obs in artifact["observations"]["forbidden_writes"]:
            obs["error"] = {"type": "FileNotFoundError", "errno": errno.ENOENT, "message": "hidden"}
            obs["denied"] = True
        report = self._verify(self._write_artifact(artifact))
        self.assertEqual(report["verdict"], "passed")

    def test_accessible_protected_file_is_not_misclassified_as_denied(self):
        artifact = self._artifact()
        artifact["observations"]["protected_reads"]["evaluator"].update({
            "succeeded": True, "denied": False,
        })
        report = self._verify(self._write_artifact(artifact))
        self.assertEqual(report["verdict"], "failed")
        self.assertIn("evaluator_read_denied", report["failed_probes"])

    def test_missing_protected_canary_is_rejected_as_non_evidence(self):
        self.source_read.unlink()
        with self.assertRaises(ValueError):
            self._verify(self._write_artifact(self._artifact()))

    def test_missing_forbidden_write_host_parent_is_rejected(self):
        missing = self.base / "missing-host-parent/forbidden.txt"
        artifact = self._artifact()
        artifact["observations"]["forbidden_writes"] = [{
            "path": str(missing.absolute()),
            "succeeded": False,
            "denied": True,
            "error": {"type": "FileNotFoundError", "errno": errno.ENOENT, "message": "hidden"},
        }]
        path = self._write_artifact(artifact)
        with self.assertRaises(ValueError):
            verify(
                artifact_path=path,
                expected_run_id="run-boundary",
                probe_program=self.probe_program,
                candidate_read=self.candidate_read,
                candidate_read_marker=self.markers["candidate"],
                evaluator_read=self.evaluator_read,
                evaluator_read_marker=self.markers["evaluator"],
                source_read=self.source_read,
                source_read_marker=self.markers["source"],
                real_home_read=self.real_home_read,
                real_home_read_marker=self.markers["real_home"],
                candidate_write=self.candidate_write,
                candidate_write_marker=self.markers["candidate_write"],
                forbidden_writes=[missing],
                network_reference=self.network_reference,
                require_network_denied=True,
            )

    def test_secret_like_environment_key_fails_report(self):
        report = self._verify(self._write_artifact(self._artifact(secret_key="OPENAI_API_KEY")))
        self.assertEqual(report["verdict"], "failed")
        self.assertIn("secret_env_scan", report["failed_probes"])

    def test_probe_program_hash_mismatch_is_rejected(self):
        artifact = self._artifact()
        artifact["probe_program_sha256"] = "b" * 64
        with self.assertRaises(ValueError):
            self._verify(self._write_artifact(artifact))

    def test_network_denial_requires_control_plane_reference(self):
        artifact = self._write_artifact(self._artifact())
        with self.assertRaises(ValueError):
            verify(
                artifact_path=artifact,
                expected_run_id="run-boundary",
                probe_program=self.probe_program,
                candidate_read=self.candidate_read,
                candidate_read_marker=self.markers["candidate"],
                evaluator_read=self.evaluator_read,
                evaluator_read_marker=self.markers["evaluator"],
                source_read=self.source_read,
                source_read_marker=self.markers["source"],
                real_home_read=self.real_home_read,
                real_home_read_marker=self.markers["real_home"],
                candidate_write=self.candidate_write,
                candidate_write_marker=self.markers["candidate_write"],
                forbidden_writes=self.forbidden_writes,
                network_reference=None,
                require_network_denied=True,
            )

    def test_probe_marks_enoent_as_blocked_for_namespace_hiding(self):
        missing_root = self.base / "namespace-hidden"
        with patch.dict(os.environ, {"HOME": str(self.base / "home"), "PATH": "/usr/bin", "TMPDIR": str(self.base)}, clear=True):
            artifact = run_probe(
                run_id="namespace-run",
                candidate_read=self.candidate_read,
                candidate_read_marker=self.markers["candidate"],
                evaluator_read=missing_root / "evaluator/read.txt",
                source_read=missing_root / "source/read.txt",
                real_home_read=missing_root / "home/read.txt",
                candidate_write=self.base / "live-write.txt",
                candidate_write_marker="live",
                forbidden_writes=[missing_root / "source/forbidden.txt"],
                forbidden_write_marker="blocked",
            )
        self.assertTrue(artifact["observations"]["protected_reads"]["evaluator"]["denied"])
        self.assertEqual(artifact["observations"]["protected_reads"]["evaluator"]["error"]["errno"], errno.ENOENT)
        self.assertTrue(artifact["observations"]["forbidden_writes"][0]["denied"])

    def test_running_probe_without_external_boundary_does_not_fake_success(self):
        candidate_write = self.base / "live-candidate-write.txt"
        forbidden = [self.base / "live-forbidden-write.txt"]
        with patch.dict(os.environ, {"HOME": str(self.base / "home"), "PATH": "/usr/bin", "TMPDIR": str(self.base)}, clear=True):
            artifact = run_probe(
                run_id="live-run",
                candidate_read=self.candidate_read,
                candidate_read_marker=self.markers["candidate"],
                evaluator_read=self.evaluator_read,
                source_read=self.source_read,
                real_home_read=self.real_home_read,
                candidate_write=candidate_write,
                candidate_write_marker="live-write",
                forbidden_writes=forbidden,
                forbidden_write_marker="should-not-write",
            )
        self.assertTrue(artifact["observations"]["protected_reads"]["evaluator"]["succeeded"])
        self.assertTrue(artifact["observations"]["forbidden_writes"][0]["succeeded"])
        self.assertTrue(forbidden[0].is_file())


if __name__ == "__main__":
    unittest.main()
