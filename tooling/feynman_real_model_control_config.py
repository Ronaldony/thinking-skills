#!/usr/bin/env python3
"""Generate/validate the control-plane Codex config for a real-model smoke run.

The output names the control-plane credential environment variable declared by
runner-job schema v2 but never contains its value. Candidate tool commands still
execute through the canonical remote `exec-server` environment and receive an
explicit `inherit = "none"` shell environment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
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

PROVIDER_ID = "openai-api"
PROVIDER_NAME = "OpenAI API"
PROVIDER_BASE_URL = "https://api.openai.com/v1"
PROVIDER_ENV_KEY = "OPENAI_API_KEY"  # default runner-job v2 key; not a credential value


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _credential_env_key(job: dict[str, Any]) -> str:
    auth = job.get("authentication")
    if not isinstance(auth, dict):
        raise ValueError("runner job has no authentication object")
    value = auth.get("control_plane_credential_env_key")
    if not isinstance(value, str) or not value:
        raise ValueError("runner job has no control-plane credential env key")
    return value


def build_document(job: dict[str, Any], profile: dict[str, Any], profile_sha: str) -> dict[str, Any]:
    validation = validate_job(job, profile, profile_sha)
    if validation.get("verdict") != "runner-job-valid":
        raise ValueError("runner job is not valid")
    model = job.get("versions", {}).get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("runner job model must be nonempty")
    if model.startswith("mock-"):
        raise ValueError("real model control config may not use a mock model id")
    credential_env_key = _credential_env_key(job)
    paths = job["paths"]
    return {
        "model": model,
        "model_provider": PROVIDER_ID,
        "approval_policy": "never",
        "sandbox_mode": "danger-full-access",
        "model_providers": {
            PROVIDER_ID: {
                "name": PROVIDER_NAME,
                "base_url": PROVIDER_BASE_URL,
                "env_key": credential_env_key,
                "wire_api": "responses",
            }
        },
        "shell_environment_policy": {
            "inherit": "none",
            "set": {
                "HOME": paths["ephemeral_home"],
                "CODEX_HOME": paths["codex_home"],
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "TMPDIR": paths["temp_dir"],
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        },
    }


def render_toml(document: dict[str, Any]) -> str:
    provider = document["model_providers"][PROVIDER_ID]
    shell = document["shell_environment_policy"]
    env_set = shell["set"]
    assignments = ", ".join(f"{key} = {_q(value)}" for key, value in env_set.items())
    return "\n".join([
        f"model = {_q(document['model'])}",
        f"model_provider = {_q(document['model_provider'])}",
        f"approval_policy = {_q(document['approval_policy'])}",
        f"sandbox_mode = {_q(document['sandbox_mode'])}",
        "",
        f"[model_providers.{PROVIDER_ID}]",
        f"name = {_q(provider['name'])}",
        f"base_url = {_q(provider['base_url'])}",
        f"env_key = {_q(provider['env_key'])}",
        f"wire_api = {_q(provider['wire_api'])}",
        "",
        "[shell_environment_policy]",
        f"inherit = {_q(shell['inherit'])}",
        f"set = {{ {assignments} }}",
        "",
    ])


def validate_document(document: dict[str, Any], job: dict[str, Any], profile: dict[str, Any], profile_sha: str) -> dict[str, Any]:
    expected = build_document(job, profile, profile_sha)
    if document != expected:
        raise ValueError("control config differs from canonical real-model document")
    raw_text = json.dumps(document, ensure_ascii=False, sort_keys=True)
    if "Bearer " in raw_text or "sk-" in raw_text:
        raise ValueError("control config appears to contain credential material")
    credential_env_key = _credential_env_key(job)
    return {
        "verdict": "real-model-control-config-valid",
        "model": document["model"],
        "provider": PROVIDER_ID,
        "provider_base_url": PROVIDER_BASE_URL,
        "credential_env_key_name": credential_env_key,
        "credential_value_stored": False,
        "authentication_mode": "control-plane-only",
        "credential_source": "environment",
        "tool_shell_inherit": "none",
        "tool_shell_env_keys": sorted(document["shell_environment_policy"]["set"]),
        "boundary_profile_sha256": profile_sha,
        "scope": "control-plane config contract only; no credential lookup or external model request",
    }


def build_files(job_path: Path, profile_path: Path, output_path: Path) -> dict[str, Any]:
    job = load_job_json(job_path.resolve())
    profile, profile_sha, _ = validate_profile_file(profile_path.resolve())
    document = build_document(job, profile, profile_sha)
    text = render_toml(document)
    parsed = tomllib.loads(text)
    result = validate_document(parsed, job, profile, profile_sha)
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return result


def validate_files(job_path: Path, profile_path: Path, config_path: Path) -> dict[str, Any]:
    job = load_job_json(job_path.resolve())
    profile, profile_sha, _ = validate_profile_file(profile_path.resolve())
    if config_path.is_symlink() or not config_path.is_file():
        raise ValueError("control config must be a regular file")
    document = tomllib.loads(config_path.read_text(encoding="utf-8"))
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
