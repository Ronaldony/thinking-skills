#!/usr/bin/env python3
"""Prepare and verify a dedicated ChatGPT-authenticated Codex control home.

This tool never opens, hashes, copies, or serializes credential files. The
``prepare`` command creates a new dedicated CODEX_HOME with configuration that
forces ChatGPT login and file-scoped credential storage. The ``check`` command
runs ``codex login status`` in a scrubbed, platform-minimal process environment
and emits only a coarse authentication classification; raw status output is
never preserved.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

CONFIG_TEXT = '''forced_login_method = "chatgpt"\ncli_auth_credentials_store = "file"\n'''
WINDOWS_SYSTEM_ENV_KEYS = ("SystemRoot", "ComSpec", "PATHEXT", "WINDIR")


def _absolute_no_symlink(path: Path, label: str, *, must_exist: bool) -> Path:
    path = path.expanduser().absolute()
    parts = path.parts
    if not parts:
        raise ValueError(f"{label} path is empty")
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} contains a symlink component: {current}")
        if not current.exists():
            break
    if must_exist and not path.is_dir():
        raise ValueError(f"{label} must be an existing directory: {path}")
    return path.resolve(strict=False)


def prepare(control_codex_home: Path) -> dict[str, Any]:
    path = _absolute_no_symlink(control_codex_home, "control CODEX_HOME", must_exist=False)
    if path.exists():
        raise ValueError("prepare requires a new, non-existing control CODEX_HOME")
    path.mkdir(parents=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    config = path / "config.toml"
    config.write_text(CONFIG_TEXT, encoding="utf-8")
    try:
        os.chmod(config, 0o600)
    except OSError:
        pass
    return {
        "schema_version": 1,
        "verdict": "dedicated-control-home-prepared",
        "control_codex_home": str(path),
        "forced_login_method": "chatgpt",
        "credential_store": "file",
        "credential_material_created": False,
        "next_action": "run codex login interactively with CODEX_HOME set to this directory",
        "scope": "configuration only; no login performed and no credential file inspected",
    }


def _resolve_executable(value: str) -> str:
    if not value.strip():
        raise ValueError("codex executable must be nonempty")
    looks_like_path = any(sep in value for sep in ("/", "\\"))
    if looks_like_path:
        path = Path(value).expanduser().absolute()
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"codex executable is missing or unsafe: {path}")
        if os.name != "nt" and not os.access(path, os.X_OK):
            raise ValueError(f"codex executable is not executable: {path}")
        return str(path.resolve())
    resolved = shutil.which(value)
    if resolved is None:
        raise ValueError(f"codex executable not found on PATH: {value}")
    return resolved


def _source_env_get(source: Mapping[str, str], key: str) -> str | None:
    direct = source.get(key)
    if direct:
        return direct
    target = key.upper()
    for name, value in source.items():
        if name.upper() == target and value:
            return value
    return None


def _safe_env(
    control_codex_home: Path,
    *,
    platform_name: str | None = None,
    source_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a scrubbed child environment with only platform-required launch data."""
    platform_name = os.name if platform_name is None else platform_name
    source = os.environ if source_env is None else source_env
    path_value = _source_env_get(source, "PATH") or (
        r"C:\Windows\System32" if platform_name == "nt" else "/usr/local/bin:/usr/bin:/bin"
    )

    if platform_name == "nt":
        temp_value = (
            _source_env_get(source, "TEMP")
            or _source_env_get(source, "TMP")
            or str(control_codex_home.parent)
        )
        result = {
            "HOME": str(control_codex_home.parent),
            "USERPROFILE": str(control_codex_home.parent),
            "CODEX_HOME": str(control_codex_home),
            "PATH": path_value,
            "TEMP": temp_value,
            "TMP": temp_value,
            "TMPDIR": temp_value,
        }
        for key in WINDOWS_SYSTEM_ENV_KEYS:
            value = _source_env_get(source, key)
            if value:
                result[key] = value
        return result

    temp_value = _source_env_get(source, "TMPDIR") or "/tmp"
    return {
        "HOME": str(control_codex_home.parent),
        "CODEX_HOME": str(control_codex_home),
        "PATH": path_value,
        "TMPDIR": temp_value,
    }


def check(control_codex_home: Path, codex_bin: str = "codex", timeout_seconds: int = 20) -> dict[str, Any]:
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
        raise ValueError("timeout_seconds must be an integer in 1..120")
    home = _absolute_no_symlink(control_codex_home, "control CODEX_HOME", must_exist=True)
    executable = _resolve_executable(codex_bin)
    env = _safe_env(home)

    version_proc = subprocess.run(
        [executable, "--version"], env=env, text=True, capture_output=True,
        encoding="utf-8", errors="replace", timeout=timeout_seconds, check=False,
    )
    if version_proc.returncode != 0:
        raise ValueError(
            f"Codex version command failed with exit code {version_proc.returncode}; "
            "raw stderr was not preserved"
        )
    version = (version_proc.stdout or version_proc.stderr).strip().splitlines()
    if len(version) != 1 or not version[0]:
        raise ValueError("Codex version output is not one nonempty line")

    status_proc = subprocess.run(
        [executable, "-c", 'forced_login_method="chatgpt"', "login", "status"],
        env=env, text=True, capture_output=True, encoding="utf-8", errors="replace",
        timeout=timeout_seconds, check=False,
    )
    raw = ((status_proc.stdout or "") + "\n" + (status_proc.stderr or "")).strip()
    lowered = raw.lower()
    # Raw output may include account details. It is used only in memory for this
    # coarse classification and is intentionally absent from the returned record.
    if status_proc.returncode != 0:
        raise ValueError("Codex login status failed under forced ChatGPT login policy")
    if "chatgpt" not in lowered:
        raise ValueError("Codex login status did not identify ChatGPT authentication")

    return {
        "schema_version": 1,
        "verdict": "chatgpt-subscription-authenticated",
        "authentication": {
            "mode": "chatgpt-subscription",
            "source": "codex-session",
            "forced_login_method": "chatgpt",
            "api_key_auth_allowed": False,
            "process_environment_inherited": False,
            "process_environment_allowlist": sorted(env),
        },
        "control_codex_home": str(home),
        "codex_cli": version[0],
        "raw_status_output_preserved": False,
        "credential_files_read_by_gate": False,
        "scope": "coarse local auth-method gate only; no token/account contents preserved and no model request sent",
    }


def _write_output(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--control-codex-home", type=Path, required=True)
    prepare_parser.add_argument("--output", type=Path)

    check_parser = sub.add_parser("check")
    check_parser.add_argument("--control-codex-home", type=Path, required=True)
    check_parser.add_argument("--codex-bin", default="codex")
    check_parser.add_argument("--timeout-seconds", type=int, default=20)
    check_parser.add_argument("--output", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.control_codex_home)
        else:
            result = check(args.control_codex_home, args.codex_bin, args.timeout_seconds)
        if args.output is not None:
            _write_output(args.output, result)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
