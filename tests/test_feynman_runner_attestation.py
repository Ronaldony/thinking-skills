from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_runner_attestation import validate


SHA = "a" * 64


def probe(method: str = "synthetic external-boundary canary"):
    return {"passed": True, "artifact_sha256": SHA, "method": method}


def attestation(condition: str = "baseline"):
    skill = condition in {"legacy-clean", "feynman-v05"}
    return {
        "schema_version": 1,
        "run_id": "run-1",
        "case_id": "mechanism-01",
        "condition_id": condition,
        "boundary": {
            "backend": "test-container",
            "backend_version": "1",
            "platform": "linux",
            "kernel": "test-kernel",
            "external_enforcement": True,
            "profile_sha256": SHA,
        },
        "paths": {
            "candidate_dir": "/isolated/candidate",
            "evaluator_dir": "/evaluator/run-1",
            "source_repo": "/source/thinking-skills",
            "ephemeral_home": "/isolated/home",
            "codex_home": "/isolated/codex-home",
            "temp_dir": "/isolated/tmp",
            "real_home": "/home/real-user",
        },
        "filesystem": {
            "candidate_readable_data_roots": [
                "/isolated/candidate", "/isolated/home", "/isolated/codex-home", "/isolated/tmp"
            ],
            "candidate_writable_roots": [
                "/isolated/candidate", "/isolated/home", "/isolated/codex-home", "/isolated/tmp"
            ],
            "platform_runtime_roots": ["/usr", "/lib"],
            "forbidden_read_roots": ["/evaluator/run-1", "/source/thinking-skills", "/home/real-user"],
            "forbidden_write_roots": ["/evaluator/run-1", "/source/thinking-skills", "/home/real-user"],
        },
        "network": {
            "case_requires_tool_network": False,
            "tool_network": "blocked",
            "control_plane_separate_from_tool_network": True,
            "allowed_tool_destinations": [],
        },
        "environment": {
            "candidate_env_keys": ["HOME", "CODEX_HOME", "PATH", "TMPDIR"],
            "api_auth_exposed_to_candidate_tools": False,
            "plugins_enabled": False,
            "system_skills": [],
            "expected_candidate_skills": ["feynman-thinking"] if skill else [],
            "observed_candidate_skills": ["feynman-thinking"] if skill else [],
        },
        "probes": {
            "candidate_read": probe(),
            "evaluator_read_denied": probe(),
            "source_read_denied": probe(),
            "real_home_read_denied": probe(),
            "candidate_write": probe(),
            "forbidden_write_denied": probe(),
            "tool_network_denied": probe(),
            "ambient_skill_preflight": probe(),
            "secret_env_scan": probe(),
        },
        "versions": {"codex_cli": "codex-cli test", "model": "test-model"},
        "digests": {
            "eval_plan_sha256": SHA,
            "runtime_sha256": SHA if skill else None,
            "candidate_prompt_sha256": SHA,
        },
        "limitations": ["synthetic unit-test attestation only"],
    }


class RunnerAttestationTests(unittest.TestCase):
    def test_baseline_contract_valid(self):
        self.assertEqual(validate(attestation("baseline"))["verdict"], "contract-valid")

    def test_v05_contract_valid(self):
        self.assertEqual(validate(attestation("feynman-v05"))["verdict"], "contract-valid")

    def test_internal_only_enforcement_is_rejected(self):
        value = attestation()
        value["boundary"]["external_enforcement"] = False
        with self.assertRaises(ValueError):
            validate(value)

    def test_filesystem_root_as_platform_runtime_is_rejected(self):
        value = attestation()
        value["filesystem"]["platform_runtime_roots"] = ["/"]
        with self.assertRaises(ValueError):
            validate(value)

    def test_platform_runtime_must_not_expose_evaluator(self):
        value = attestation()
        value["filesystem"]["platform_runtime_roots"] = ["/evaluator"]
        with self.assertRaises(ValueError):
            validate(value)

    def test_real_home_must_not_be_under_readable_root(self):
        value = attestation()
        value["filesystem"]["candidate_readable_data_roots"].append("/home")
        with self.assertRaises(ValueError):
            validate(value)

    def test_closed_case_rejects_open_tool_network(self):
        value = attestation()
        value["network"]["tool_network"] = "open"
        with self.assertRaises(ValueError):
            validate(value)

    def test_closed_case_requires_control_plane_separation(self):
        value = attestation()
        value["network"]["control_plane_separate_from_tool_network"] = False
        with self.assertRaises(ValueError):
            validate(value)

    def test_secret_like_candidate_environment_key_is_rejected(self):
        value = attestation()
        value["environment"]["candidate_env_keys"].append("OPENAI_API_KEY")
        with self.assertRaises(ValueError):
            validate(value)

    def test_skill_condition_requires_exact_skill(self):
        value = attestation("feynman-v05")
        value["environment"]["observed_candidate_skills"] = []
        with self.assertRaises(ValueError):
            validate(value)

    def test_baseline_rejects_runtime_digest(self):
        value = attestation("baseline")
        value["digests"]["runtime_sha256"] = SHA
        with self.assertRaises(ValueError):
            validate(value)

    def test_skill_condition_requires_runtime_digest(self):
        value = attestation("legacy-clean")
        value["digests"]["runtime_sha256"] = None
        with self.assertRaises(ValueError):
            validate(value)

    def test_failed_read_canary_invalidates_contract(self):
        value = attestation()
        value["probes"]["evaluator_read_denied"]["passed"] = False
        with self.assertRaises(ValueError):
            validate(value)

    def test_plugins_are_fail_closed_by_default(self):
        value = attestation()
        value["environment"]["plugins_enabled"] = True
        with self.assertRaises(ValueError):
            validate(value)
        self.assertEqual(validate(value, allow_plugins=True)["verdict"], "contract-valid")

    def test_system_skill_set_must_be_explicitly_equalized(self):
        value = attestation()
        value["environment"]["system_skills"] = ["system-helper"]
        with self.assertRaises(ValueError):
            validate(value)
        self.assertEqual(validate(value, allowed_system_skills={"system-helper"})["verdict"], "contract-valid")

    def test_protected_path_cannot_overlap_ephemeral_home(self):
        value = attestation()
        value["paths"]["ephemeral_home"] = "/evaluator/run-1/home"
        with self.assertRaises(ValueError):
            validate(value)

    def test_network_required_case_does_not_require_denial_probe_to_pass(self):
        value = attestation()
        value["network"].update({
            "case_requires_tool_network": True,
            "tool_network": "restricted",
            "control_plane_separate_from_tool_network": True,
            "allowed_tool_destinations": ["fixture.example.invalid"],
        })
        value["probes"]["tool_network_denied"]["passed"] = False
        self.assertEqual(validate(value)["verdict"], "contract-valid")


if __name__ == "__main__":
    unittest.main()
