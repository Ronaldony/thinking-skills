"""Build a one-run Codex MCP override without changing ``CODEX_HOME`` files.

The resulting values are intended for repeated ``-c/--config`` arguments.  The
model receives an empty input schema: all filesystem authority is fixed here by
the evaluator, before Codex starts.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


SERVER_NAME = "feynman_bounded_read"
TOOL_NAME = "feynman_read_probe_byte"


def _without_symlinks(path: Path, label: str, *, directory: bool) -> Path:
    absolute = path.absolute()
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
    return absolute


def _toml_string(value: str) -> str:
    # JSON basic strings are also valid TOML basic strings and correctly escape
    # native Windows backslashes without involving the caller's shell.
    return json.dumps(value, ensure_ascii=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class BoundedMcpOverride:
    values: tuple[str, ...]
    adapter_sha256: str
    candidate_sha256: str

    def cli_args(self) -> list[str]:
        result: list[str] = []
        for value in self.values:
            result.extend(("-c", value))
        return result

    def sanitized_lineage(self) -> dict[str, object]:
        return {
            "server_name": SERVER_NAME,
            "tool_name": TOOL_NAME,
            "config_override_count": len(self.values),
            "adapter_sha256": self.adapter_sha256,
            "candidate_sha256": self.candidate_sha256,
            "model_selectable_arguments": False,
            "fixed_read_limit_bytes": 1,
        }


def build_bounded_mcp_override(*, node_bin: Path, adapter: Path,
                               candidate: Path) -> BoundedMcpOverride:
    """Return deterministic CLI config values for the fixed one-byte tool."""
    node_bin = _without_symlinks(node_bin, "Node executable", directory=False)
    adapter = _without_symlinks(adapter, "bounded MCP adapter", directory=False)
    candidate = _without_symlinks(candidate, "candidate fixture", directory=True)
    target = _without_symlinks(candidate / "candidate.py", "candidate fixture file",
                               directory=False)
    try:
        target.relative_to(candidate)
    except ValueError as exc:
        raise ValueError("candidate fixture file escaped candidate directory") from exc

    prefix = f"mcp_servers.{SERVER_NAME}"
    values = (
        f"{prefix}.command={_toml_string(str(node_bin))}",
        f"{prefix}.args=[{_toml_string(str(adapter))}]",
        f"{prefix}.cwd={_toml_string(str(candidate))}",
        f"{prefix}.required=true",
        f"{prefix}.enabled=true",
        f"{prefix}.enabled_tools=[{_toml_string(TOOL_NAME)}]",
        f'{prefix}.default_tools_approval_mode="auto"',
        f"{prefix}.startup_timeout_sec=10",
        f"{prefix}.tool_timeout_sec=10",
        f"{prefix}.env.FEYNMAN_BOUNDED_READ_ROOT={_toml_string(str(candidate))}",
        f"{prefix}.env.FEYNMAN_BOUNDED_READ_FILE={_toml_string(str(target))}",
    )
    return BoundedMcpOverride(
        values=values,
        adapter_sha256=_sha256(adapter),
        candidate_sha256=_sha256(target),
    )
