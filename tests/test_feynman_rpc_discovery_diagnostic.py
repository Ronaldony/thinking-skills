from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tooling.feynman_rpc_discovery_diagnostic import run, summarize


class DiscoverySummaryTests(unittest.TestCase):
    def test_does_not_preserve_response_values_or_unknown_keys(self):
        result = summarize({'result': {
            'config': 'SYNTHETIC_PRIVATE_VALUE',
            'SYNTHETIC_PRIVATE_KEY': 'SYNTHETIC_PRIVATE_VALUE',
            'dataBase64': 'SYNTHETIC_PRIVATE_VALUE',
        }})
        self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(result))
        self.assertEqual(result['result_shape'], ['config', 'dataBase64'])

    def test_missing_field_is_a_bounded_schema_identifier_not_a_value(self):
        result = summarize({'error': {
            'code': -32602,
            'message': 'missing field `configPaths`; SYNTHETIC_PRIVATE_VALUE',
        }})
        self.assertEqual(result['missing_field'], 'configpaths')
        self.assertEqual(result['error_code'], -32602)
        self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(result))
        self.assertIsNone(summarize({'error': {
            'message': 'missing field `' + 'x' * 65 + '`',
        }})['missing_field'])

    def test_malformed_error_does_not_leak_code_values(self):
        self.assertIsNone(summarize({'error': 'SYNTHETIC_PRIVATE'})['error_code'])
        self.assertIsNone(summarize({'error': {'code': 'SYNTHETIC_PRIVATE'}})['error_code'])
        self.assertIsNone(summarize({'error': {'code': True}})['error_code'])

    def test_fixed_failure_signals(self):
        result = summarize({'error': {
            'code': -32004, 'message': 'no such file: SYNTHETIC_PRIVATE',
        }})
        self.assertTrue(result['not_found'])
        self.assertFalse(result['result_present'])
        self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(result))

    @patch('tooling.feynman_rpc_discovery_diagnostic.subprocess.Popen')
    @patch('tooling.feynman_rpc_discovery_diagnostic.validate_files')
    def test_invalid_boundary_never_launches(self, validate, popen):
        validate.return_value = {'verdict': 'invalid'}
        with self.assertRaisesRegex(ValueError, 'validation did not pass'):
            run(*(Path('unused') for _ in range(5)))
        popen.assert_not_called()

    @patch('tooling.feynman_rpc_discovery_diagnostic.subprocess.Popen')
    @patch('tooling.feynman_rpc_discovery_diagnostic.validate_files')
    @patch.object(Path, 'read_text')
    def test_existing_output_or_either_telemetry_never_launches(self, read, validate, popen):
        validate.return_value = {'verdict': 'remote-exec-environment-valid'}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'report.json'
            for name in ('report.json', 'report-ordinary-rpc.json', 'report-guarded-rpc.json'):
                with self.subTest(name=name):
                    read.side_effect = ['{}', '']
                    occupied = output.with_name(name)
                    occupied.touch()
                    with self.assertRaisesRegex(ValueError, 'must be new'):
                        run(Path('job'), Path('profile'), Path('remote'), Path('config'), output)
                    popen.assert_not_called()
                    occupied.unlink()


if __name__ == '__main__':
    unittest.main()
