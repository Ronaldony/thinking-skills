from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_runner_attestation import BOUNDARY_REPORT_PROBES, validate


SHA = "a" * 64


def probe(method: str = "synthetic external-boundary canary"):
    return {"passed": True, "artifact_sha256": SHA, "method": method}


def attestation(condition: str = "baseline"):
    skill = condition in {"legacy-clean", "feynman-v05"}
    return {
        "schema_version": 2,
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
            "control_plane_auth_mode": "control-plane-only",
            "control_plane_credential_source": "environment",
            "control_plane_credential_env_key": "OPENAI_API_KEY",
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
            "probe_report_sha256": SHA,
        },
        "limitations": ["synthetic unit-test attestation only"],
    }


def boundary_report(value: dict):
    requires_network = value["network"]["case_requires_tool_network"]
    not_required = ["tool_network_denied"] if requires_network else []
    return {
        "schema_version": 1,
        "run_id": value["run_id"],
        "boundary_profile_sha256": value["boundary"]["profile_sha256"],
        "verdict": "passed",
        "failed_probes": [],
        "not_required_probes": not_required,
        "source_artifact_sha256": SHA,
        "probe_program_sha256": SHA,
        "network_reference_sha256": None if requires_network else SHA,
        "observed_env_keys": sorted(value["environment"]["candidate_env_keys"]),
        "probes": {name: deepcopy(value["probes"][name]) for name in BOUNDARY_REPORT_PROBES},
        "scope": "synthetic normalized boundary report for unit tests",
    }


class RunnerAttestationTests(unittest.TestCase):
    def test_baseline_contract_valid(self):
        result = validate(attestation("baseline"))
        self.assertEqual(result["verdict"], "contract-valid")
        self.assertEqual(result["authentication_mode"], "control-plane-only")
        self.assertEqual(result["control_plane_credential_source"], "environment")
        self.assertEqual(result["control_plane_credential_env_key"], "OPENAI_API_KEY")

    def test_v05_contract_valid(self):
        self.assertEqual(validate(attestation("feynman-v05"))["verdict"], "contract-valid")

    def test_legacy_schema_v1_is_rejected(self):
        value = attestation()
        value["schema_version"] = 1
        with self.assertRaises(ValueError):
            validate(value)

    def test_control_plane_credential_key_must_not_be_candidate_env(self):
        value = attestation()
        value["environment"]["candidate_env_keys"].append("OPENAI_API_KEY")
        with self.assertRaises(ValueError):
            validate(value)

    def test_wrong_control_plane_auth_mode_is_rejected(self):
        value = attestation()
        value["environment"]["control_plane_auth_mode"] = "external-broker"
        with self.assertRaises(ValueError):
            validate(value)

    def test_unvalidated_control_plane_credential_source_is_rejected(self):
        value = attestation()
        value["environment"]["control_plane_credential_source"] = "file"
        with self.assertRaises(ValueError):
            validate(value)

    def test_invalid_control_plane_credential_env_key_is_rejected(self):
        value = attestation()
        value["environment"]["control_plane_credential_env_key"] = "BAD-KEY"
        with self.assertRaises(ValueError):
            validate(value)

    def test_verified_boundary_report_is_bound(self):
        value = attestation()
        result = validate(value, probe_report=boundary_report(value), probe_report_sha256=SHA)
        self.assertTrue(result["probe_report_bound"])

    def test_probe_report_profile_mismatch_is_rejected(self):
        value = attestation()
        report = boundary_report(value)
        report["boundary_profile_sha256"] = "b" * 64
        with self.assertRaises(ValueError):
            validate(value, probe_report=report, probe_report_sha256=SHA)

    def test_network_required_report_marks_denial_probe_not_required(self):
        value = attestation()
        value["network"].update({
            "case_requires_tool_network": True,
            "tool_network": "restricted",
            "control_plane_separate_from_tool_network": True,
            "allowed_tool_destinations": ["fixture.example.invalid"],
        })
        value["probes"]["tool_network_denied"]["passed"] = False
        report = boundary_report(value)
        result = validate(value, probe_report=report, probe_report_sha256=SHA)
        self.assertTrue(result["probe_report_bound"])

    def test_probe_report_digest_mismatch_is_rejected(self):
        value = attestation()
        with self.assertRaises(ValueError):
            validate(value, probe_report=boundary_report(value), probe_report_sha256="b" * 64)

    def test_probe_report_probe_mismatch_is_rejected(self):
        value = attestation()
        report = boundary_report(value)
        report["probes"]["candidate_read"]["artifact_sha256"] = "b" * 64
        with self.assertRaises(ValueError):
            validate(value, probe_report=report, probe_report_sha256=SHA)

    def test_probe_report_environment_mismatch_is_rejected(self):
        value = attestation()
        report = boundary_report(value)
        report["observed_env_keys"] = ["HOME"]
        with self.assertRaises(ValueError):
            validate(value, probe_report=report, probe_report_sha256=SHA)

    def test_missing_probe_report_digest_is_rejected(self):
        value = attestation()
        del value["digests"]["probe_report_sha256"]
        with self.assertRaises(ValueError):
            validate(value)

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
        value["environment"]["candidate_env_keys"].append("SOME_SECRET")
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
