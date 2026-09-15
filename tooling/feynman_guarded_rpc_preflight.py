"""Exercise the actual one-byte guard without a model or unrestricted process.

Passing these controls does not establish complete Codex discovery or a
model-facing tool contract. Keep those gates explicitly false.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import queue
import subprocess
import threading
import tomllib

try:
    from .feynman_remote_exec_environment import validate_files
    from .feynman_rpc_path_proxy import PROBE_CONFIG_PATH, PROXY_ERROR_CODE
    from .feynman_rpc_preflight import _ephemeral_command, _file_uri, _request, _notification, _safe_probe_env
except ImportError:
    from feynman_remote_exec_environment import validate_files
    from feynman_rpc_path_proxy import PROBE_CONFIG_PATH, PROXY_ERROR_CODE
    from feynman_rpc_preflight import _ephemeral_command, _file_uri, _request, _notification, _safe_probe_env


def verify(*, job_path: Path, profile_path: Path, remote_path: Path,
           docker_config: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError('guard report must be new')
    if validate_files(job_path, profile_path, remote_path)['verdict'] != 'remote-exec-environment-valid':
        raise ValueError('remote environment invalid')
    job = json.loads(job_path.read_text(encoding='utf-8'))
    candidate = Path(job['paths']['candidate_dir'])
    sentinel = candidate / '.feynman-diagnostic-absent.toml'
    if sentinel.exists() or sentinel.is_symlink():
        raise ValueError('config sentinel must be absent')
    uri = _file_uri(str(candidate))
    command = _ephemeral_command(tomllib.loads(remote_path.read_text(encoding='utf-8')), 'guard-controls')
    telemetry = output.with_name(output.stem + '-rpc.json')
    if telemetry.exists() or telemetry.is_symlink():
        raise ValueError('guard telemetry must be new')
    command[command.index('--telemetry-file') + 1] = str(telemetry)
    env = _safe_probe_env(docker_config)
    env.update(FEYNMAN_PROBE_RPC_READ_LIMIT_BYTES='1',
               FEYNMAN_PROBE_RPC_ALLOWED_METHODS='environmentConfig/read,fs/getMetadata,fs/readFile',
               FEYNMAN_PROBE_RPC_ALLOWED_PATH='/run/candidate/candidate.py')
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=env, bufsize=0)
    received = queue.Queue()
    def read():
        try:
            for line in proc.stdout:
                received.put(json.loads(line))
        except (ValueError, OSError):
            received.put(None)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    checks = {}
    def request(label, method, params, rejected=False):
        identifier = len(checks) + 1
        proc.stdin.write(_request(identifier, method, params))
        proc.stdin.flush()
        try:
            response = received.get(timeout=20)
        except queue.Empty as exc:
            raise ValueError('guarded response timed out') from exc
        if not isinstance(response, dict) or response.get('id') != identifier:
            raise ValueError('unexpected guarded response')
        code = response.get('error', {}).get('code')
        passed = code == PROXY_ERROR_CODE if rejected else code is None and 'result' in response
        checks[label] = passed
        if not passed and rejected is not None:
            raise ValueError('guarded RPC control check failed: ' + label)
        return response.get('result')
    try:
        request('initialize', 'initialize', {'clientName': 'feynman-guard-controls'})
        proc.stdin.write(_notification('initialized', {}))
        proc.stdin.flush()
        request('candidate_metadata', 'fs/getMetadata', {'path': uri + '/candidate.py'})
        request('absent_config_group', 'environmentConfig/read', {
            'cwd': uri, 'configPaths': [[PROBE_CONFIG_PATH]], 'requirementsPaths': []})
        request('other_file_denied', 'fs/readFile', {'path': uri + '/task.txt'}, True)
        request('parent_traversal_denied', 'fs/getMetadata', {'path': uri + '/../home/x'}, True)
        request('config_content_read_denied', 'environmentConfig/read', {
            'cwd': uri, 'configPaths': [[uri + '/candidate.py']], 'requirementsPaths': []}, True)
        request('process_denied', 'process/start', {}, True)
        request('walk_denied', 'fs/walk', {'path': uri}, True)
        request('canonicalize_denied', 'fs/canonicalize', {'path': uri}, True)
        result = request('one_byte_read', 'fs/readFile', {'path': uri + '/candidate.py', 'offset': 99, 'len': 999}, None)
        checks['response_is_one_byte'] = isinstance(result, dict) and len(
            base64.b64decode(result.get('dataBase64', ''), validate=True)) == 1
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
    if proc.returncode:
        raise ValueError('guarded server did not exit cleanly')
    report = {'verdict': 'guarded-rpc-controls-verified' if checks['response_is_one_byte'] else 'blocked-byte-read-contract', 'checks': checks,
              'model_calls': 0, 'file_contents_preserved': False,
              'complete_discovery_verified': False, 'model_tool_contract_ready': False,
              'remaining_blockers': ['code-mode-execution-not-covered-by-filesystem-only-probe']
              + ([] if checks['response_is_one_byte'] else ['server-read-response-exceeds-one-byte'])}
    with output.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('job', 'profile', 'remote', 'docker-config', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify(job_path=args.job, profile_path=args.profile, remote_path=args.remote,
                        docker_config=args.docker_config, output=args.output)
    except (ValueError, OSError, queue.Empty, subprocess.SubprocessError) as exc:
        parser.exit(2, 'error: guarded preflight failed: ' + type(exc).__name__ + '\n')
    print(json.dumps(report))
    if report['verdict'] != 'guarded-rpc-controls-verified':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
