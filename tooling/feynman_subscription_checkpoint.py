#!/usr/bin/env python3
"""Load and validate a non-secret subscription-run checkpoint.

The checkpoint contains only immutable input paths and a Docker image digest.
It never contains authentication material and validation never starts Codex,
Docker, an App Server, or a model.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


CHECKPOINT_FIELDS = frozenset({
    "schema_version", "runner_job", "boundary_profile", "remote_environment",
    "binding", "codex_bin", "node_bin", "adapter", "docker_bin",
    "docker_config", "docker_image_id", "telemetry", "output",
})
PATH_FIELDS = frozenset(CHECKPOINT_FIELDS - {"schema_version", "docker_image_id"})
INPUT_FILE_FIELDS = frozenset({
    "runner_job", "boundary_profile", "remote_environment", "binding",
    "codex_bin", "node_bin", "adapter", "docker_bin",
})
DIRECTORY_FIELDS = frozenset({"docker_config"})
NEW_PATH_FIELDS = frozenset({"telemetry", "output"})


class CheckpointError(ValueError):
    """A checkpoint is malformed or does not describe a safe local run."""


def _absolute_path(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise CheckpointError(f"checkpoint field is not a nonempty string: {field}")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise CheckpointError(f"checkpoint path must be absolute: {field}")
    return path


def load(path: Path) -> dict[str, Any]:
    """Read a checkpoint and return a validated, non-secret dictionary."""
    if path.is_symlink() or not path.is_file():
        raise CheckpointError("checkpoint must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointError("checkpoint is not readable JSON") from exc
    if not isinstance(value, dict) or set(value) != CHECKPOINT_FIELDS:
        raise CheckpointError("checkpoint fields do not match the fixed contract")
    if value.get("schema_version") != 1:
        raise CheckpointError("unsupported checkpoint schema")
    for field in PATH_FIELDS:
        value[field] = str(_absolute_path(value[field], field))
    image = value.get("docker_image_id")
    if not isinstance(image, str) or not image.startswith("sha256:") or len(image) != 71:
        raise CheckpointError("checkpoint Docker image must be a sha256 digest")
    serialized = json.dumps(value, ensure_ascii=True)
    if any(token in serialized for token in ("OPENAI_API_KEY", "CODEX_ACCESS_TOKEN", "api.openai.com")):
        raise CheckpointError("checkpoint contains a retired credential contract")
    return value


def _path_kind(value: str, *, directory: bool) -> bool:
    path = Path(value)
    if path.is_symlink():
        return False
    return path.is_dir() if directory else path.is_file()


def _resolved_existing_directory(value: Any, field: str) -> Path:
    path = _absolute_path(value, field)
    if not _path_kind(str(path), directory=True):
        raise CheckpointError(f"checkpoint input is not a regular directory: {field}")
    return path.resolve()


def _new_evaluator_path(value: Any, field: str, evaluator: Path) -> Path:
    path = _absolute_path(value, field)
    if path.exists() or path.is_symlink():
        raise CheckpointError(f"checkpoint output must be a new path: {field}")
    # Resolve the existing prefix without following a symlink in the new
    # portion.  This keeps an absent output from escaping evaluator ownership
    # through a symlinked parent while still allowing a fresh child path.
    resolved = path.resolve(strict=False)
    if resolved == evaluator or not resolved.is_relative_to(evaluator):
        raise CheckpointError(f"checkpoint output must be evaluator-owned: {field}")
    return resolved


def validate(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate paths and binding identity without launching a subprocess."""
    if set(value) != CHECKPOINT_FIELDS or value.get("schema_version") != 1:
        raise CheckpointError("checkpoint fields do not match the fixed contract")
    normalized = dict(value)
    for field in PATH_FIELDS:
        normalized[field] = str(_absolute_path(value.get(field), field))
    image = normalized.get("docker_image_id")
    if not isinstance(image, str) or not image.startswith("sha256:") or len(image) != 71:
        raise CheckpointError("checkpoint Docker image must be a sha256 digest")
    directories = DIRECTORY_FIELDS
    files = INPUT_FILE_FIELDS
    for field in files:
        if not _path_kind(normalized[field], directory=False):
            raise CheckpointError(f"checkpoint input is not a regular file: {field}")
    for field in directories:
        output = Path(normalized[field])
        if not _path_kind(str(output), directory=True):
            raise CheckpointError(f"checkpoint input is not a directory: {field}")
    for field in NEW_PATH_FIELDS:
        output = Path(normalized[field])
        if output.exists() or output.is_symlink():
            raise CheckpointError(f"checkpoint output must be a new path: {field}")

    # Reuse the runner's existing immutable binding validator.  Imports are
    # lazy so this module remains usable by validate-only tooling without
    # introducing an import cycle during normal executor startup.
    try:
        from .feynman_subscription_smoke_exec import (
            _directory, _load, _validate_full_runner_binding,
        )
    except ImportError:
        from feynman_subscription_smoke_exec import (
            _directory, _load, _validate_full_runner_binding,
        )
    job = _load(Path(str(value["runner_job"])), "runner job")
    paths = job.get("paths")
    if not isinstance(paths, dict):
        raise CheckpointError("runner job lacks paths")
    if not isinstance(paths.get("candidate_dir"), str):
        raise CheckpointError("runner job lacks candidate directory")
    if not isinstance(paths.get("evaluator_dir"), str):
        raise CheckpointError("runner job lacks evaluator directory")
    if not isinstance(paths.get("control_codex_home"), str):
        raise CheckpointError("runner job lacks control CODEX_HOME")
    candidate = _directory(Path(paths["candidate_dir"]), "candidate directory")
    evaluator = _resolved_existing_directory(paths["evaluator_dir"], "evaluator directory")
    control_home = _resolved_existing_directory(paths["control_codex_home"], "control CODEX_HOME")
    remote_environment = Path(normalized["remote_environment"])
    if not _path_kind(str(remote_environment), directory=False):
        raise CheckpointError("checkpoint remote environment is not a regular file")
    remote_environment = remote_environment.resolve()
    if remote_environment != control_home / "environments.toml":
        raise CheckpointError(
            "checkpoint remote environment must be the canonical control CODEX_HOME/environments.toml"
        )
    telemetry = _new_evaluator_path(normalized["telemetry"], "telemetry", evaluator)
    output = _new_evaluator_path(normalized["output"], "output", evaluator)
    if telemetry == output:
        raise CheckpointError("checkpoint telemetry and output must be distinct paths")
    try:
        override = _validate_full_runner_binding(
            binding_path=Path(normalized["binding"]),
            runner_job_path=Path(normalized["runner_job"]),
            boundary_profile_path=Path(normalized["boundary_profile"]),
            job=job,
            node_bin=Path(normalized["node_bin"]),
            adapter=Path(normalized["adapter"]),
            docker_bin=Path(normalized["docker_bin"]),
            docker_config=Path(normalized["docker_config"]),
            docker_image_id=str(normalized["docker_image_id"]),
            candidate_dir=candidate,
        )
    except (OSError, ValueError) as exc:
        raise CheckpointError("checkpoint binding identity validation failed") from exc
    versions = job.get("versions") if isinstance(job.get("versions"), dict) else {}
    return {
        "schema_version": 1,
        "verdict": "subscription-checkpoint-valid",
        "input_checks": {
            field: True for field in sorted(PATH_FIELDS)
        },
        "binding_valid": True,
        "binding_config_override_count": len(override.values),
        "model": versions.get("model") if isinstance(versions.get("model"), str) else "unknown",
        "subprocesses_started": 0,
        "authentication_material_present": False,
    }


def validate_file(path: Path) -> dict[str, Any]:
    return validate(load(path))
