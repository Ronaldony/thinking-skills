"""Model-free binding check for control CLI, Docker image and exec-server."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

try:
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_runner_job_validate import validate_job
    from .feynman_rpc_preflight import _safe_probe_env
    from .feynman_subscription_smoke_exec import _resolve_executable
except ImportError:
    from feynman_boundary_profile import validate_profile_file
    from feynman_runner_job_validate import validate_job
    from feynman_rpc_preflight import _safe_probe_env
    from feynman_subscription_smoke_exec import _resolve_executable


def verify(*, job_path: Path, profile_path: Path, codex_bin: str,
           docker_config: Path, docker: str = 'docker') -> dict:
    profile, digest, _ = validate_profile_file(profile_path)
    job = json.loads(job_path.read_text(encoding='utf-8'))
    if validate_job(job, profile, digest)['verdict'] != 'runner-job-valid':
        raise ValueError('runner job invalid')
    env = _safe_probe_env(docker_config)
    def capture(command):
        result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding='utf-8', timeout=45, check=False)
        if result.returncode:
            raise ValueError('runtime version command failed')
        return result.stdout.strip()
    image_id = capture([docker, 'image', 'inspect', profile['image'], '--format', '{{.Id}}'])
    if image_id != profile['image_id']:
        raise ValueError('runtime image ID differs from profile')
    control = capture([_resolve_executable(codex_bin), '--version'])
    server = capture([docker, 'run', '--rm', '--network', 'none', '--read-only',
                      '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                      '--user', profile['run_as'], '--entrypoint', 'codex', image_id, '--version'])
    if not re.fullmatch(r'codex-cli \d+\.\d+\.\d+', control):
        raise ValueError('unsupported control version format')
    if not control == server == job['versions']['codex_cli']:
        raise ValueError('control, server and job versions must match')
    return {'verdict': 'rpc-runtime-versions-matched', 'control_cli': control,
            'server_cli': server, 'image_id': image_id, 'model_calls': 0,
            'authentication_checked': False, 'tool_exposure_checked': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('job', 'profile', 'docker-config', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--codex-bin', required=True)
    parser.add_argument('--docker', default='docker')
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError('version report must be new')
        report = verify(job_path=args.job, profile_path=args.profile,
                        codex_bin=args.codex_bin, docker_config=args.docker_config,
                        docker=args.docker)
        with args.output.open('x', encoding='utf-8') as handle:
            handle.write(json.dumps(report, indent=2) + '\n')
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(2, 'error: runtime version gate failed: ' + type(exc).__name__ + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
