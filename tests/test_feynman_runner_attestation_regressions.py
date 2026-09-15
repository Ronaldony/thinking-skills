from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tooling.feynman_runner_attestation import validate
from test_feynman_runner_attestation import attestation


class RunnerAttestationRegressionTests(unittest.TestCase):
    def test_platform_runtime_nested_inside_evaluator_is_rejected(self):
        value = attestation()
        value["filesystem"]["platform_runtime_roots"] = ["/evaluator/run-1/lib"]
        with self.assertRaises(ValueError):
            validate(value)

    def test_platform_runtime_nested_inside_real_home_is_rejected(self):
        value = attestation()
        value["filesystem"]["platform_runtime_roots"] = ["/home/real-user/.local/lib"]
        with self.assertRaises(ValueError):
            validate(value)

    def test_blocked_network_cannot_declare_allowed_destinations(self):
        value = attestation()
        value["network"]["allowed_tool_destinations"] = ["example.invalid"]
        with self.assertRaises(ValueError):
            validate(value)


if __name__ == "__main__":
    unittest.main()
