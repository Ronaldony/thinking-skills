#!/usr/bin/env python3
"""Model-free comparison of guarded and ordinary exec-server discovery.

Only fixed metadata/config requests are sent. Response bodies stay in memory;
reports contain labels, error codes, and allowlisted shape/error signals.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import tomllib

from tooling.feynman_rpc_preflight import (
    _ephemeral_command, _file_uri, _request, _notification, _safe_probe_env,
)
from tooling.feynman_remote_exec_environment import validate_files


def summarize(message: dict) -> dict:
    error = message.get('error')
    error = error if isinstance(error, dict) else {}
    result = message.get('result')
    diagnostic = str(error.get('message', '')).lower()
    field = re.search(r'missing field [`\x27]([a-zA-Z_][a-zA-Z_0-9]{0,63})[`\x27]', diagnostic)
    return {
        'error_code': error.get('code') if type(error.get('code')) is int else None,
        'result_present': 'result' in message,
        'result_shape': sorted(set(result) & {'environmentInfo', 'sessionId', 'path', 'metadata', 'config', 'layers', 'entries', 'dataBase64'}) if isinstance(result, dict) else [],
        'invalid_path_or_uri': any(s in diagnostic for s in ('uri', 'absolute path', 'invalid path')),
        'not_found': any(s in diagnostic for s in ('not found', 'no such file', 'cannot find')),
        # A schema identifier from fixed synthetic requests, never its value.
        'missing_field': field.group(1) if field else None,
        'unknown_method_or_variant': any(s in diagnostic for s in ('unknown method', 'method not found', 'unknown variant')),
        'invalid_type': 'invalid type' in diagnostic,
    }


def run(job_path: Path, profile: Path, remote: Path, docker_config: Path, output: Path) -> dict:
    if validate_files(job_path, profile, remote).get('verdict') != 'remote-exec-environment-valid':
        raise ValueError('remote environment validation did not pass')
    job = json.loads(job_path.read_text(encoding='utf-8'))
    doc = tomllib.loads(remote.read_text(encoding='utf-8'))
    if output.exists() or output.is_symlink():
        raise ValueError('diagnostic output must be new')
    for mode in ('ordinary', 'guarded'):
        telemetry = output.with_name(output.stem + '-' + mode + '-rpc.json')
        if telemetry.exists() or telemetry.is_symlink():
            raise ValueError('diagnostic telemetry must be new')
    candidate = _file_uri(job['paths']['candidate_dir'])
    cases = [
        ('config-empty', 'environmentConfig/read', {}),
        ('config-host-cwd', 'environmentConfig/read', {'cwd': candidate}),
        ('config-container-cwd', 'environmentConfig/read', {'cwd': 'file:///run/candidate'}),
        ('config-host-config-paths', 'environmentConfig/read', {'cwd': candidate, 'configPaths': []}),
        ('config-container-config-paths', 'environmentConfig/read', {'cwd': 'file:///run/candidate', 'configPaths': []}),
        ('config-host-empty-path-lists', 'environmentConfig/read', {'cwd': candidate, 'configPaths': [], 'requirementsPaths': []}),
        ('config-container-empty-path-lists', 'environmentConfig/read', {'cwd': 'file:///run/candidate', 'configPaths': [], 'requirementsPaths': []}),
        ('metadata-existing', 'fs/getMetadata', {'path': candidate + '/candidate.py'}),
        ('metadata-missing', 'fs/getMetadata', {'path': candidate + '/.feynman-diagnostic-absent'}),
        ('canonicalize-candidate', 'fs/canonicalize', {'path': candidate}),
    ]
    report = {'schema_version': 1, 'model_requests': 0, 'payloads_preserved': False, 'modes': {}}
    for guarded in (False, True):
        mode = 'guarded' if guarded else 'ordinary'
        command = _ephemeral_command(doc, 'discovery-diagnostic')
        # Keep the actual model probe telemetry intact and bind each diagnostic.
        telemetry = output.with_name(output.stem + '-' + mode + '-rpc.json')
        if telemetry.exists() or telemetry.is_symlink():
            raise ValueError('diagnostic telemetry must be new')
        command[command.index('--telemetry-file') + 1] = str(telemetry)
        env = _safe_probe_env(docker_config)
        if guarded:
            env.update(FEYNMAN_PROBE_RPC_READ_LIMIT_BYTES='1',
                       FEYNMAN_PROBE_RPC_ALLOWED_METHODS='environmentConfig/read,fs/getMetadata,fs/readFile',
                       FEYNMAN_PROBE_RPC_ALLOWED_PATH='/run/candidate/candidate.py')
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=env, bufsize=0)
        received = queue.Queue()
        def receive():
            try:
                for line in proc.stdout:
                    received.put(json.loads(line))
            except (ValueError, OSError):
                received.put(None)
        reader = threading.Thread(target=receive, daemon=True)
        reader.start()
        records = {}
        report['modes'][mode] = records
        def request(identifier, method, params):
            proc.stdin.write(_request(identifier, method, params))
            proc.stdin.flush()
            response = received.get(timeout=20)
            if not isinstance(response, dict) or response.get('id') != identifier:
                raise ValueError('unexpected diagnostic response')
            return summarize(response)
        try:
            records['initialize'] = request(1, 'initialize', {'clientName': 'feynman-model-free-discovery'})
            proc.stdin.write(_notification('initialized', {}))
            proc.stdin.flush()
            for identifier, (label, method, params) in enumerate(cases, 2):
                records[label] = request(identifier, method, params)
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=10)
            reader.join(timeout=2)
            proc.stdout.close()
            report['modes'][mode]['child_exit_code'] = proc.returncode
    with output.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('job', 'profile', 'remote', 'docker-config', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.job, args.profile, args.remote, args.docker_config, args.output)
    except (OSError, ValueError, subprocess.SubprocessError, queue.Empty) as exc:
        parser.exit(2, 'error: discovery diagnostic failed: ' + type(exc).__name__ + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
