#!/usr/bin/env python3
"""Generate/validate a Codex stdio remote environment from a runner job.

The control-plane Codex process stays outside the candidate tool boundary. The
selected environment launches `docker run -i ... codex exec-server --listen
stdio` with `include_local=false`, so shell/filesystem execution is delegated to
the network-disabled container. This tool does not launch Codex or Docker.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tomllib
from typing import Any

try:
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_runner_job_validate import _load as load_job_json
    from .feynman_runner_job_validate import validate_job
except ImportError:
    from feynman_boundary_profile import validate_profile_file
    from feynman_runner_job_validate import _load as load_job_json
    from feynman_runner_job_validate import validate_job

ENVIRONMENT_ID = "candidate"
SUPPORTED_ENV_KEYS = {"HOME", "CODEX_HOME", "PATH", "TMPDIR", "PYTHONDONTWRITEBYTECODE"}
DOCKER_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def _toml_string(value: str) -> str:
    # JSON basic strings are a compatible subset for the ASCII paths/arguments
    # emitted by this generator.
    return json.dumps(value, ensure_ascii=False)


def _container_name(run_id: str) -> str:
    name = DOCKER_NAME_PATTERN.sub("-", run_id).strip("-._")
    if not name:
        raise ValueError("run_id cannot be converted to a Docker container name")
    return ("feynman-tool-" + name)[:120]


def _env_assignments(job: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    paths = job["paths"]
    values = {
        "HOME": paths["ephemeral_home"],
        "CODEX_HOME": paths["codex_home"],
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "TMPDIR": paths["temp_dir"],
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    keys = profile["candidate_env_keys"]
    unknown = sorted(set(keys) - SUPPORTED_ENV_KEYS)
    if unknown:
        raise ValueError("remote exec generator has no explicit value policy for env keys: " + ", ".join(unknown))
    return [f"{key}={values[key]}" for key in keys]


def expected_docker_args(job: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    if profile["network_mode"] != "none":
        raise ValueError("stdio remote-exec reference currently supports only network_mode=none")
    if profile["read_only_mounts"]:
        raise ValueError("stdio remote-exec profile must not require undeclared read-only host bind sources")
    if profile["tmpfs_mounts"] != ["/tmp"]:
        raise ValueError("stdio remote-exec reference currently requires tmpfs_mounts=[/tmp]")

    paths = job["paths"]
    rw_order = [
        paths["candidate_dir"],
        paths["ephemeral_home"],
        paths["codex_home"],
        paths["temp_dir"],
    ]
    args = [
        "run",
        "--name", _container_name(job["run_id"]),
        "-i",
        "--network", "none",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--user", profile["run_as"],
        "--tmpfs", "/tmp:rw,nosuid,nodev",
    ]
    for path in rw_order:
        args.extend(["-v", f"{path}:{path}:rw"])
    args.extend([
        "--workdir", paths["candidate_dir"],
        profile["image"],
        "env", "-i",
        *_env_assignments(job, profile),
        "codex", "exec-server", "--listen", "stdio",
    ])
    return args


def build_document(job: dict[str, Any], profile: dict[str, Any], profile_sha: str) -> dict[str, Any]:
    validation = validate_job(job, profile, profile_sha)
    if validation["verdict"] != "runner-job-valid":
        raise ValueError("runner job is not valid")
    return {
        "default": ENVIRONMENT_ID,
        "include_local": False,
        "environments": [{
            "id": ENVIRONMENT_ID,
            "program": "docker",
            "args": expected_docker_args(job, profile),
        }],
    }


def render_toml(document: dict[str, Any]) -> str:
    environments = document.get("environments")
    if not isinstance(environments, list) or len(environments) != 1:
        raise ValueError("remote exec document must contain exactly one environment")
    environment = environments[0]
    if not isinstance(environment, dict):
        raise ValueError("remote exec environment must be an object")
    args = environment.get("args")
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise ValueError("remote exec environment args must be strings")
    lines = [
        f"default = {_toml_string(str(document['default']))}",
        "include_local = false",
        "",
        "[[environments]]",
        f"id = {_toml_string(str(environment['id']))}",
        f"program = {_toml_string(str(environment['program']))}",
        "args = [",
    ]
    lines.extend(f"  {_toml_string(item)}," for item in args)
    lines.extend(["]", ""])
    return "\n".join(lines)


def validate_document(document: dict[str, Any], job: dict[str, Any], profile: dict[str, Any], profile_sha: str) -> dict[str, Any]:
    expected = build_document(job, profile, profile_sha)
    if document != expected:
        raise ValueError("environments.toml differs from canonical runner-job/profile remote exec document")
    args = document["environments"][0]["args"]
    return {
        "verdict": "remote-exec-environment-valid",
        "run_id": job["run_id"],
        "environment_id": ENVIRONMENT_ID,
        "include_local": False,
        "container_name": _container_name(job["run_id"]),
        "boundary_profile_sha256": profile_sha,
        "docker_args": args,
        "scope": "pre-execution Codex stdio remote environment contract; does not prove Docker or model behavior",
    }


def build_files(job_path: Path, profile_path: Path, output_path: Path) -> dict[str, Any]:
    job = load_job_json(job_path.resolve())
    profile, profile_sha, _ = validate_profile_file(profile_path.resolve())
    document = build_document(job, profile, profile_sha)
    text = render_toml(document)
    # Round-trip through the same TOML parser Codex-style config relies on. This
    # catches rendering mistakes before the external runner consumes the file.
    parsed = tomllib.loads(text)
    result = validate_document(parsed, job, profile, profile_sha)
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return result


def validate_files(job_path: Path, profile_path: Path, environment_path: Path) -> dict[str, Any]:
    job = load_job_json(job_path.resolve())
    profile, profile_sha, _ = validate_profile_file(profile_path.resolve())
    if environment_path.is_symlink() or not environment_path.is_file():
        raise ValueError("environments.toml must be a regular file")
    document = tomllib.loads(environment_path.read_text(encoding="utf-8"))
    return validate_document(document, job, profile, profile_sha)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args()
    if (args.output is None) == (args.validate is None):
        parser.error("choose exactly one of --output or --validate")
    try:
        if args.output is not None:
            result = build_files(args.job, args.boundary_profile, args.output)
        else:
            result = validate_files(args.job, args.boundary_profile, args.validate)
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
