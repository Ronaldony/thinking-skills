from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
