from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tooling.feynman_rpc_path_mapping import RpcPathMapper, RpcPathMappingError
from tooling.feynman_rpc_path_proxy import _map_request_payload, _read_response_within_limit
from tooling.feynman_rpc_version_gate import verify
from tooling.feynman_subscription_models import SUBSCRIPTION_WORK_MODELS, model_selection_report


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
        for value in (['file:///run/candidate/a'], [['relative']], [[None]],
                      [['file:///C:/private/a']], [[['file:///run/candidate/a']]]):
            with self.subTest(value=value), self.assertRaises(RpcPathMappingError):
                self.mapper.map_request({'method': 'environmentConfig/read', 'params': {'configPaths': value}})

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
