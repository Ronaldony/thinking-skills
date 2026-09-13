"""Build the fixed MCP contract for a model-free full-runner preflight.

The full runner deliberately exposes three model-facing tools only:

* read the fixed ``candidate.py`` file;
* replace the fixed ``candidate.py`` file;
* run the fixed ``test_candidate.py`` command in a network-disabled Docker
  container.

The model cannot choose a path, shell, executable, argv, Docker image, or
network policy.  This module only builds immutable CLI overrides; it does not
launch Codex, Docker, or a model.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


SERVER_NAME = "feynman_full_runner"
READ_TOOL_NAME = "feynman_read_candidate"
WRITE_TOOL_NAME = "feynman_write_candidate"
TEST_TOOL_NAME = "feynman_run_tests"
TOOL_NAMES = (READ_TOOL_NAME, WRITE_TOOL_NAME, TEST_TOOL_NAME)
FIXED_CANDIDATE_FILE = "candidate.py"
FIXED_TEST_FILE = "test_candidate.py"
FIXED_CONTAINER_ROOT = "/run/candidate"
FIXED_TEST_COMMAND = ("python3", "-B", "-I", "/run/candidate/test_candidate.py")
READ_LIMIT_BYTES = 131072
WRITE_LIMIT_BYTES = 131072
TEST_OUTPUT_LIMIT_BYTES = 32768
MAX_CALLS = {READ_TOOL_NAME: 8, WRITE_TOOL_NAME: 8, TEST_TOOL_NAME: 8}
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _without_symlinks(path: Path, label: str, *, directory: bool) -> Path:
    absolute = path.expanduser().absolute()
    if not absolute.exists():
        raise ValueError(f"{label} does not exist")
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} contains a symbolic link")
    if directory and not absolute.is_dir():
        raise ValueError(f"{label} is not a directory")
    if not directory and not absolute.is_file():
        raise ValueError(f"{label} is not a regular file")
    return absolute.resolve(strict=True)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class FullRunnerMcpOverride:
    values: tuple[str, ...]
    adapter_sha256: str
    initial_candidate_sha256: str
    test_sha256: str
    docker_image_id: str

    def cli_args(self) -> list[str]:
        result: list[str] = []
        for value in self.values:
            result.extend(("-c", value))
        return result

    def sanitized_lineage(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "server_name": SERVER_NAME,
            "tool_names": list(TOOL_NAMES),
            "config_override_count": len(self.values),
            "adapter_sha256": self.adapter_sha256,
            "initial_candidate_sha256": self.initial_candidate_sha256,
            "test_sha256": self.test_sha256,
            "docker_image_id": self.docker_image_id,
            "model_selectable_paths": False,
            "model_selectable_commands": False,
            "model_selectable_network": False,
            "fixed_candidate_file": FIXED_CANDIDATE_FILE,
            "fixed_test_file": FIXED_TEST_FILE,
            "fixed_test_command": list(FIXED_TEST_COMMAND),
            "network_mode": "none",
            "read_limit_bytes": READ_LIMIT_BYTES,
            "write_limit_bytes": WRITE_LIMIT_BYTES,
            "test_output_limit_bytes": TEST_OUTPUT_LIMIT_BYTES,
            "max_calls": dict(MAX_CALLS),
        }


def build_full_runner_override(*, node_bin: Path, adapter: Path, candidate: Path,
                               docker_bin: Path, docker_config: Path,
                               docker_image_id: str) -> FullRunnerMcpOverride:
    """Return deterministic CLI config values for the fixed full-runner MCP."""
    node_bin = _without_symlinks(node_bin, "Node executable", directory=False)
    adapter = _without_symlinks(adapter, "full-runner MCP adapter", directory=False)
    candidate = _without_symlinks(candidate, "candidate fixture", directory=True)
    docker_bin = _without_symlinks(docker_bin, "Docker executable", directory=False)
    docker_config = _without_symlinks(docker_config, "Docker config directory", directory=True)
    if not isinstance(docker_image_id, str) or not IMAGE_ID_PATTERN.fullmatch(docker_image_id):
        raise ValueError("full-runner MCP requires a content-addressed Docker image ID")

    candidate_file = _without_symlinks(candidate / FIXED_CANDIDATE_FILE,
                                       "candidate source file", directory=False)
    test_file = _without_symlinks(candidate / FIXED_TEST_FILE,
                                   "fixed candidate test file", directory=False)
    try:
        candidate_file.relative_to(candidate)
        test_file.relative_to(candidate)
    except ValueError as exc:
        raise ValueError("full-runner fixture escaped candidate directory") from exc

    prefix = f"mcp_servers.{SERVER_NAME}"
    values = (
        f"{prefix}.command={_toml_string(str(node_bin))}",
        f"{prefix}.args=[{_toml_string(str(adapter))}]",
        f"{prefix}.cwd={_toml_string(str(candidate))}",
        f"{prefix}.required=true",
        f"{prefix}.enabled=true",
        f"{prefix}.enabled_tools=[{','.join(_toml_string(name) for name in TOOL_NAMES)}]",
        f'{prefix}.default_tools_approval_mode="auto"',
        f"{prefix}.startup_timeout_sec=10",
        f"{prefix}.tool_timeout_sec=90",
        f"{prefix}.env.FEYNMAN_FULL_RUNNER_ROOT={_toml_string(str(candidate))}",
        f"{prefix}.env.FEYNMAN_FULL_RUNNER_DOCKER={_toml_string(str(docker_bin))}",
        f"{prefix}.env.FEYNMAN_FULL_RUNNER_DOCKER_CONFIG={_toml_string(str(docker_config))}",
        f"{prefix}.env.FEYNMAN_FULL_RUNNER_IMAGE={_toml_string(docker_image_id)}",
    )
    return FullRunnerMcpOverride(
        values=values,
        adapter_sha256=_sha256(adapter),
        initial_candidate_sha256=_sha256(candidate_file),
        test_sha256=_sha256(test_file),
        docker_image_id=docker_image_id,
    )


def contract_document(lineage: dict[str, object]) -> dict[str, object]:
    """Normalize the public, payload-free contract manifest for preflight."""
    if lineage.get("server_name") != SERVER_NAME or lineage.get("tool_names") != list(TOOL_NAMES):
        raise ValueError("full-runner lineage has an unexpected server/tool set")
    return {
        "schema_version": 1,
        "verdict": "full-runner-mcp-contract-ready",
        "server_name": SERVER_NAME,
        "transport": "stdio",
        "tools": [
            {
                "name": READ_TOOL_NAME,
                "model_selectable_arguments": False,
                "fixed_file": FIXED_CANDIDATE_FILE,
                "max_calls": MAX_CALLS[READ_TOOL_NAME],
                "max_bytes": READ_LIMIT_BYTES,
            },
            {
                "name": WRITE_TOOL_NAME,
                "model_selectable_arguments": True,
                "model_selectable_path": False,
                "fixed_file": FIXED_CANDIDATE_FILE,
                "max_calls": MAX_CALLS[WRITE_TOOL_NAME],
                "max_bytes": WRITE_LIMIT_BYTES,
            },
            {
                "name": TEST_TOOL_NAME,
                "model_selectable_arguments": False,
                "model_selectable_command": False,
                "fixed_file": FIXED_TEST_FILE,
                "fixed_command": list(FIXED_TEST_COMMAND),
                "max_calls": MAX_CALLS[TEST_TOOL_NAME],
                "max_output_bytes": TEST_OUTPUT_LIMIT_BYTES,
                "network_mode": "none",
            },
        ],
        "candidate_auth_exposed": False,
        "candidate_readable_auth_paths": [],
        "candidate_tool_auth_env_keys": [],
        "docker_root_read_only": True,
        "docker_no_new_privileges": True,
        "docker_capabilities": [],
        "scope": "model-free fixed full-runner MCP contract; not model or skill evaluation evidence",
    }
