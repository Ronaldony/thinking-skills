from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

from tooling.feynman_rpc_path_mapping import RpcPathMapper, RpcPathMappingError
from tooling.feynman_rpc_path_proxy import _map_request_payload, _read_response_within_limit
from tooling.feynman_rpc_version_gate import verify
from tooling.feynman_subscription_models import SUBSCRIPTION_WORK_MODELS, model_selection_report
from tooling.feynman_rpc_path_contract_probe import (
    PROBE_IMAGE, _docker_args, _namespace_contract_matches, _namespace_shape,
    _path_namespace, _probe_failure_stage, _response_shape_matches_by_id,
    _run_peer, _shape, _shape_is_comparable, _requests,
)


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.mapper = RpcPathMapper.from_mounts([
            {'source': r'C:\fixture\candidate', 'destination': '/run/candidate'},
            {'source': r'C:\fixture\home', 'destination': '/run/home'},
        ])

    def test_three_explicit_models_without_fallback_or_execution(self):
        self.assertEqual(SUBSCRIPTION_WORK_MODELS, ('gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-5.6-sol'))
        report = model_selection_report()
        for key in ('api_key_auth_allowed', 'automatic_fallback', 'automatic_model_runs',
                    'account_availability_verified', 'tool_use_verified_for_all_models'):
            self.assertFalse(report[key])

    def test_nested_config_groups_are_mapped_without_mutating_input(self):
        message = {'method': 'environmentConfig/read', 'params': {
            'cwd': 'file:///C:/fixture/candidate',
            'configPaths': [['file:///C:/fixture/candidate/a', 'file:///C:/fixture/candidate/b']],
            'requirementsPaths': [['file:///C:/fixture/candidate/c']],
        }}
        before = json.dumps(message)
        params = self.mapper.map_request(message)['params']
        self.assertEqual(params['configPaths'], [['file:///run/candidate/a', 'file:///run/candidate/b']])
        self.assertEqual(params['requirementsPaths'], [['file:///run/candidate/c']])
        self.assertEqual(json.dumps(message), before)

    def test_invalid_config_groups_and_protected_paths_are_rejected(self):
        for value in (['file:///run/candidate/a'], [[None]],
                      [['file:///C:/private/a']], [[['file:///run/candidate/a']]]):
            with self.subTest(value=value), self.assertRaises(RpcPathMappingError):
                self.mapper.map_request({'method': 'environmentConfig/read', 'params': {'configPaths': value}})
        mapped = self.mapper.map_request({
            'method': 'environmentConfig/read',
            'params': {'configPaths': [['relative']]},
        })
        self.assertEqual(mapped['params']['configPaths'], [['/run/candidate/relative']])

    def test_canonicalize_windows_path_is_mapped(self):
        self.assertEqual(self.mapper.map_request({'method': 'fs/canonicalize', 'params': {
            'path': 'file:///C:/fixture/candidate'}})['params']['path'], 'file:///run/candidate')

    def test_host_traversal_is_rejected_including_uri_encoding(self):
        for path in (r'C:\fixture\candidate\..\home\x',
                     'file:///C:/fixture/candidate/%2e%2e/home/x',
                     '/run/candidate/../home/x'):
            with self.subTest(path=path), self.assertRaises(RpcPathMappingError):
                self.mapper.host_to_container(path)

    def test_config_guard_cannot_be_used_to_read_arbitrary_file_contents(self):
        for path, accepted in (
            ('file:///run/candidate/.feynman-diagnostic-absent.toml', True),
            ('file:///run/candidate/candidate.py', False),
            ('file:///run/home/config.toml', False),
        ):
            raw = json.dumps({'id': 1, 'method': 'environmentConfig/read', 'params': {
                'cwd': 'file:///run/candidate', 'configPaths': [[path]], 'requirementsPaths': []}}).encode()
            payload, error = _map_request_payload(self.mapper, raw, allowed_path='/run/candidate/candidate.py')
            self.assertEqual(payload is not None, accepted)
            self.assertEqual(error is None, accepted)

    def test_response_guard_checks_actual_decoded_bytes(self):
        for value, accepted in ((b'', True), (b'x', True), (b'xx', False), (b'x'*1024, False)):
            self.assertEqual(_read_response_within_limit({'result': {
                'dataBase64': base64.b64encode(value).decode()}}, 1), accepted)

    def test_response_guard_rejects_extra_payload_and_malformed_data(self):
        for result in ({'dataBase64': 'eA==', 'text': 'SYNTHETIC_PRIVATE'},
                       {'dataBase64': 'invalid!'}, {'dataBase64': None}, None):
            self.assertFalse(_read_response_within_limit({'result': result}, 1))

    def test_path_contract_probe_uses_same_request_contracts(self):
        candidate = Path(r"C:\fixture\candidate")
        direct = _requests(candidate=candidate, direct=True)
        proxy = _requests(candidate=candidate, direct=False)
        self.assertEqual([item.get("method") for item in direct],
                         [item.get("method") for item in proxy])
        self.assertEqual(direct[2]["params"]["configPaths"],
                         [["file:///run/candidate/sub/config.toml"]])
        self.assertEqual(direct[5]["params"]["options"]["maxEntries"], 64)
        self.assertEqual(direct[7]["params"]["cwd"],
                         "file:///run/candidate/sub")
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(proxy))

    def test_path_contract_probe_can_pin_a_local_docker_endpoint(self):
        args = _docker_args(image="sha256:" + "a" * 64,
                            candidate=Path(r"C:\fixture\candidate"),
                            home=Path(r"C:\fixture\home"),
                            codex_home=Path(r"C:\fixture\codex"),
                            temp=Path(r"C:\fixture\temp"),
                            docker_host="npipe:////./pipe/docker_engine")
        self.assertEqual(args[0:3], ["--host", "npipe:////./pipe/docker_engine", "run"])

    def test_path_contract_probe_rejects_nonlocal_transport(self):
        from tooling.feynman_rpc_path_contract_probe import run
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            docker = root / "docker.exe"
            proxy = root / "proxy.py"
            docker.write_text("fixture", encoding="utf-8")
            proxy.write_text("fixture", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "local npipe"):
                run(docker=docker, docker_config=root, proxy=proxy,
                    image=PROBE_IMAGE,
                    output=root / "new-report.json",
                    docker_host="tcp://127.0.0.1:2375")

    def test_path_contract_probe_shape_redacts_values_and_normalizes_roles(self):
        candidate = Path(r"C:\fixture\candidate")
        shaped = _shape({
            "cwd": "file:///C:/fixture/candidate/sub",
            "path": "file:///C:/fixture/candidate/sub/config.toml",
            "message": "SYNTHETIC_PRIVATE",
        }, candidate=candidate)
        self.assertEqual(shaped["cwd"], {"path_role": "candidate/sub"})
        self.assertEqual(shaped["path"], {"path_role": "candidate/sub/config.toml"})
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(shaped))

    def test_candidate_mount_root_has_a_stable_root_role(self):
        candidate = Path(r"C:\fixture\candidate")
        self.assertEqual(
            _shape({"path": "file:///run/candidate"}, candidate=candidate),
            {"path": {"path_role": "candidate/"}},
        )

    def test_outside_mount_roles_are_not_comparable_even_when_equal(self):
        candidate = Path(r"C:\fixture\candidate")
        direct = _shape({"path": "file:///run/unknown/private"}, candidate=candidate)
        proxy = _shape({"path": "file:///run/unknown/private"}, candidate=candidate)
        self.assertEqual(direct, proxy)
        self.assertFalse(_shape_is_comparable(direct))
        self.assertFalse(_response_shape_matches_by_id(
            {"1": direct}, {"1": proxy})["1"])

    def test_path_contract_probe_shape_detects_different_fixture_values(self):
        candidate = Path(r"C:\fixture\candidate")
        first = _shape({"result": {"marker": "ROOT_CONFIG", "dataBase64": "QQ=="}}, candidate=candidate)
        second = _shape({"result": {"marker": "SUB_CONFIG", "dataBase64": "Qg=="}}, candidate=candidate)
        self.assertNotEqual(first, second)
        self.assertNotIn("ROOT_CONFIG", json.dumps(first))
        self.assertNotIn("SUB_CONFIG", json.dumps(second))

    def test_path_collections_compare_by_semantic_role(self):
        candidate = Path(r"C:\fixture\candidate")
        direct = _shape({
            "configPaths": [["file:///run/candidate/sub/config.toml"]],
            "requirementsPaths": [["file:///run/candidate/sub/requirements.txt"]],
        }, candidate=candidate)
        proxy = _shape({
            "configPaths": [["file:///C:/fixture/candidate/sub/config.toml"]],
            "requirementsPaths": [["file:///C:/fixture/candidate/sub/requirements.txt"]],
        }, candidate=candidate)
        self.assertEqual(direct, proxy)

    def test_distinct_non_candidate_mount_subpaths_do_not_collapse(self):
        candidate = Path(r"C:\fixture\candidate")
        first = _shape({"path": "file:///run/codex/first"}, candidate=candidate)
        second = _shape({"path": "file:///run/codex/second"}, candidate=candidate)
        self.assertNotEqual(first, second)
        self.assertNotIn("first", json.dumps(first))
        self.assertNotIn("second", json.dumps(second))

    def test_nested_path_value_is_semantic_without_relying_on_field_name(self):
        candidate = Path(r"C:\fixture\candidate")
        direct = _shape({"source": "file:///run/candidate/sub/config.toml"},
                        candidate=candidate)
        proxy = _shape({"source": "file:///C:/fixture/candidate/sub/config.toml"},
                       candidate=candidate)
        self.assertEqual(direct, proxy)
        self.assertEqual(direct["source"], {"path_role": "candidate/sub/config.toml"})

    def test_only_allowlisted_runtime_identity_is_normalized_as_opaque(self):
        candidate = Path(r"C:\fixture\candidate")
        for key in ("sessionId", "hostname"):
            self.assertEqual(
                _shape({key: "direct"}, candidate=candidate),
                _shape({key: "proxy"}, candidate=candidate),
            )
        self.assertNotEqual(
            _shape({"marker": "direct"}, candidate=candidate),
            _shape({"marker": "proxy"}, candidate=candidate),
        )

    def test_path_probe_classifies_no_initialize_as_peer_startup_failure(self):
        empty = {
            "response_ids": [], "timed_out": True,
            "peer_closed_after_requests": False,
        }
        self.assertEqual(_probe_failure_stage(empty, empty),
                         "docker-peer-startup-timeout")

    def test_path_probe_does_not_call_response_shape_a_path_failure(self):
        peer = {
            "response_ids": ["1"], "timed_out": False,
            "peer_closed_after_requests": False,
        }
        self.assertEqual(_probe_failure_stage(peer, peer),
                         "rpc-response-contract-not-equivalent")

    def test_response_shape_diagnostics_are_limited_to_fixed_ids(self):
        result = _response_shape_matches_by_id(
            {"1": {"value": 1}, "2": {"value": 2}, "private": {}},
            {"1": {"value": 1}, "2": {"value": 3}, "private": {}},
        )
        self.assertEqual(set(result), {str(value) for value in range(1, 8)})
        self.assertTrue(result["1"])
        self.assertFalse(result["2"])
        self.assertNotIn("private", result)

    def test_response_namespace_keeps_windows_and_container_forms_distinct(self):
        candidate = Path(r"C:\fixture\candidate")
        windows = _namespace_shape({
            "result": {"path": "file:///C:/fixture/candidate/sub"},
        }, candidate=candidate)
        container = _namespace_shape({
            "result": {"path": "file:///run/candidate/sub"},
        }, candidate=candidate)
        self.assertNotEqual(windows, container)
        self.assertEqual(_path_namespace(
            "file:///C:/fixture/candidate/sub", candidate), "host")
        self.assertEqual(_path_namespace(
            "file:///run/candidate/sub", candidate), "container")
        self.assertTrue(_namespace_contract_matches(container, windows))
        self.assertFalse(_namespace_contract_matches(windows, container))

    def test_peer_fixture_drains_stderr_without_blocking_rpc(self):
        fixture = Path(__file__).with_name("feynman_subscription_lifecycle_fixture.py")
        result = _run_peer(
            [sys.executable, "-B", str(fixture), "stderr-flood"],
            [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}],
            candidate=Path(r"C:\fixture\candidate"), timeout=3,
        )
        self.assertEqual(result["response_ids"], ["1"])
        self.assertGreaterEqual(result["stderr_bytes"], 1048576)
        self.assertTrue(result["stderr_drained"])
        self.assertFalse(result["stderr_read_error"])

    def test_peer_fixture_records_duplicate_response_ids(self):
        fixture = Path(__file__).with_name("feynman_subscription_lifecycle_fixture.py")
        result = _run_peer(
            [sys.executable, "-B", str(fixture), "duplicate-response"],
            [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}],
            candidate=Path(r"C:\fixture\candidate"), timeout=3,
        )
        self.assertEqual(result["response_ids"], ["1"])
        self.assertEqual(result["response_id_duplicates"], 1)


class RuntimeVersionTests(unittest.TestCase):
    def run_gate(self, versions):
        profile = {'image': 'pinned', 'image_id': 'sha256:'+'a'*64, 'run_as': '1000:1000'}
        job = {'versions': {'codex_cli': 'codex-cli 0.154.0'}}
        with patch('tooling.feynman_rpc_version_gate.validate_profile_file', return_value=(profile, 'digest', {})), \
             patch('tooling.feynman_rpc_version_gate.validate_job', return_value={'verdict': 'runner-job-valid'}), \
             patch.object(Path, 'read_text', return_value=json.dumps(job)), \
             patch('tooling.feynman_rpc_version_gate._safe_probe_env', return_value={'PATH': 'safe'}), \
             patch('tooling.feynman_rpc_version_gate._resolve_executable', return_value='codex'), \
             patch('tooling.feynman_rpc_version_gate.subprocess.run', side_effect=[
                 SimpleNamespace(returncode=0, stdout=x) for x in versions]) as run:
            result = verify(job_path=Path('job'), profile_path=Path('profile'), codex_bin='codex', docker_config=Path('empty'))
            self.assertEqual(run.call_count, 3)
            self.assertTrue(all(x.kwargs['env'] == {'PATH': 'safe'} for x in run.call_args_list))
            return result

    def test_control_server_job_match(self):
        result = self.run_gate(['sha256:'+'a'*64, 'codex-cli 0.154.0', 'codex-cli 0.154.0'])
        self.assertEqual(result['verdict'], 'rpc-runtime-versions-matched')
        self.assertFalse(result['tool_exposure_checked'])

    def test_server_version_mismatch_fails(self):
        with self.assertRaisesRegex(ValueError, 'versions must match'):
            self.run_gate(['sha256:'+'a'*64, 'codex-cli 0.154.0', 'codex-cli 0.153.4'])

    def test_image_drift_fails(self):
        with self.assertRaisesRegex(ValueError, 'image ID differs'):
            self.run_gate(['sha256:'+'b'*64])


if __name__ == '__main__':
    unittest.main()
