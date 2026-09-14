from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tooling.feynman_subscription_checkpoint import (
    CHECKPOINT_FIELDS, CheckpointError, load, validate,
)


class SubscriptionCheckpointTests(unittest.TestCase):
    def _value(self, root: Path) -> dict[str, object]:
        return {
            "schema_version": 1,
            "runner_job": str(root / "runner.json"),
            "boundary_profile": str(root / "profile.json"),
            "remote_environment": str(root / "environment.toml"),
            "binding": str(root / "binding.json"),
            "codex_bin": str(root / "codex.cmd"),
            "node_bin": str(root / "node.exe"),
            "adapter": str(root / "adapter.mjs"),
            "docker_bin": str(root / "docker.exe"),
            "docker_config": str(root / "docker-config"),
            "docker_image_id": "sha256:" + "a" * 64,
            "telemetry": str(root / "telemetry.json"),
            "output": str(root / "output"),
        }

    def _valid_fixture(self, root: Path) -> dict[str, object]:
        value = self._value(root)
        candidate = root / "candidate"
        evaluator = root / "evaluator"
        control_home = root / "control-home"
        candidate.mkdir()
        evaluator.mkdir()
        control_home.mkdir()
        (control_home / "environments.toml").write_text("[env]\n", encoding="utf-8")
        value["remote_environment"] = str(control_home / "environments.toml")
        value["telemetry"] = str(evaluator / "run" / "telemetry.json")
        value["output"] = str(evaluator / "run" / "output")
        value["runner_job"] = str(root / "runner.json")
        for field in ("boundary_profile", "binding", "codex_bin", "node_bin", "adapter", "docker_bin"):
            Path(str(value[field])).write_text("{}", encoding="utf-8")
        (root / "runner.json").write_text(json.dumps({
            "paths": {
                "candidate_dir": str(candidate),
                "evaluator_dir": str(evaluator),
                "control_codex_home": str(control_home),
            },
            "versions": {"model": "gpt-5.6-luna"},
        }), encoding="utf-8")
        (root / "docker-config").mkdir()
        return value

    def test_load_requires_exact_non_secret_contract(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "checkpoint.json"
            value = self._value(root)
            path.write_text(json.dumps(value), encoding="utf-8")
            loaded = load(path)
            self.assertEqual(set(loaded), CHECKPOINT_FIELDS)
            self.assertEqual(loaded["docker_image_id"], value["docker_image_id"])

            value["OPENAI_API_KEY"] = "forbidden"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(CheckpointError, "fields"):
                load(path)

            value.pop("OPENAI_API_KEY")
            value["docker_image_id"] = "sha256:" + "g" * 64
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(CheckpointError, "sha256 digest"):
                load(path)

    def test_validate_rejects_missing_input_without_running_process(self):
        with tempfile.TemporaryDirectory() as raw:
            value = self._value(Path(raw))
            with self.assertRaisesRegex(CheckpointError, "regular file"):
                validate(value)

    def test_validate_rejects_existing_output(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            value = self._value(root)
            for field in ("runner_job", "boundary_profile", "remote_environment", "binding",
                          "codex_bin", "node_bin", "adapter", "docker_bin"):
                Path(str(value[field])).write_text("{}", encoding="utf-8")
            root.joinpath("docker-config").mkdir()
            root.joinpath("output").mkdir()
            with self.assertRaisesRegex(CheckpointError, "new path"):
                validate(value)

    def test_validate_accepts_canonical_evaluator_owned_outputs(self):
        with tempfile.TemporaryDirectory() as raw:
            value = self._valid_fixture(Path(raw))
            with patch(
                "tooling.feynman_subscription_smoke_exec._validate_full_runner_binding",
                return_value=SimpleNamespace(values=()),
            ):
                result = validate(value)
            self.assertEqual(result["verdict"], "subscription-checkpoint-valid")
            self.assertEqual(result["subprocesses_started"], 0)

    def test_validate_rejects_noncanonical_remote_environment(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            value = self._valid_fixture(root)
            alternate = root / "alternate-environments.toml"
            alternate.write_text("[env]\n", encoding="utf-8")
            value["remote_environment"] = str(alternate)
            with self.assertRaisesRegex(CheckpointError, "canonical control CODEX_HOME"):
                validate(value)

    def test_validate_rejects_relative_output(self):
        with tempfile.TemporaryDirectory() as raw:
            value = self._valid_fixture(Path(raw))
            value["output"] = "relative-output"
            with self.assertRaisesRegex(CheckpointError, "absolute"):
                validate(value)

    def test_validate_rejects_same_telemetry_and_output_path(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            value = self._valid_fixture(root)
            value["telemetry"] = value["output"]
            with self.assertRaisesRegex(CheckpointError, "distinct"):
                validate(value)

    def test_validate_rejects_candidate_owned_output(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            value = self._valid_fixture(root)
            value["output"] = str(root / "candidate" / "execution")
            with self.assertRaisesRegex(CheckpointError, "evaluator-owned"):
                validate(value)

    def test_validate_rejects_output_under_file_ancestor(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            value = self._valid_fixture(root)
            blocker = root / "evaluator" / "blocking-file"
            blocker.write_text("synthetic", encoding="utf-8")
            value["output"] = str(blocker / "report.json")
            with self.assertRaisesRegex(CheckpointError, "parent must be a directory"):
                validate(value)

    def test_validate_rejects_overlapping_new_output_paths(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            value = self._valid_fixture(root)
            value["output"] = str(root / "evaluator" / "run")
            value["telemetry"] = str(root / "evaluator" / "run" / "telemetry.json")
            with self.assertRaisesRegex(CheckpointError, "non-overlapping"):
                validate(value)


if __name__ == "__main__":
    unittest.main()
