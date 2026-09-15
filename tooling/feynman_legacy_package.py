#!/usr/bin/env python3
"""Build a sanitized v0.4.0 comparison runtime from the pinned legacy checkout.

The core v0.4 runtime is preserved, while evaluation-only assets/scripts and the
SKILL.md link to references/evaluation.md are removed. The sanitization is
recorded in the manifest; this package is therefore `legacy-clean`, not byte-for-byte v0.4.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

try:
    from .feynman_package import git_repository_state
except ImportError:  # direct script execution
    from feynman_package import git_repository_state

PINNED_LEGACY_COMMIT = "1609b8b6909f9ab596c1ecf298fbec4a0c70d6b4"
SKILL_NAME = "feynman-thinking"
ALLOWED_TOP_LEVEL = {"SKILL.md", "agents", "assets", "references"}
EXCLUDED_LEGACY_FILES = {"references/evaluation.md"}


def _source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for top in sorted(ALLOWED_TOP_LEVEL):
        path = root / top
        if path.is_symlink():
            raise ValueError(f"legacy runtime path symlink is not allowed: {path}")
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_symlink():
                    raise ValueError(f"legacy runtime symlink is not allowed: {child}")
                if child.is_file() and child.relative_to(root).as_posix() not in EXCLUDED_LEGACY_FILES:
                    files.append(child)
        else:
            raise ValueError(f"missing legacy runtime path: {path}")
    return files


def _sanitize_skill(text: str) -> str:
    if not re.search(r'(?m)^\s{2}version:\s*["\']?0\.4\.0["\']?\s*$', text):
        raise ValueError("legacy SKILL.md is not version 0.4.0")
    lines = text.splitlines()
    removed = [line for line in lines if "references/evaluation.md" in line]
    if len(removed) != 1:
        raise ValueError(f"expected exactly one evaluation.md reference in legacy SKILL.md, found {len(removed)}")
    cleaned = "\n".join(line for line in lines if "references/evaluation.md" not in line)
    if text.endswith("\n"):
        cleaned += "\n"
    return cleaned


def _digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        name = relative.encode("utf-8")
        content = files[relative]
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def build(legacy_root: Path, output: Path, *, expected_commit: str = PINNED_LEGACY_COMMIT) -> dict[str, Any]:
    legacy_root = legacy_root.resolve()
    commit, dirty = git_repository_state(legacy_root)
    if commit != expected_commit:
        raise ValueError(f"legacy checkout commit mismatch: expected {expected_commit}, observed {commit}")
    if dirty is not False:
        raise ValueError("legacy checkout must be clean")
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite: {output}")

    staged: dict[str, bytes] = {}
    for source in _source_files(legacy_root):
        relative = source.relative_to(legacy_root).as_posix()
        if relative == "SKILL.md":
            staged[relative] = _sanitize_skill(source.read_text(encoding="utf-8")).encode("utf-8")
        else:
            staged[relative] = source.read_bytes()
    if "references/evaluation.md" in staged:
        raise ValueError("evaluation.md must not enter legacy-clean runtime")

    digest = _digest(staged)
    output.mkdir(parents=True, exist_ok=False)
    try:
        target = output / SKILL_NAME
        for relative, content in staged.items():
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        manifest = {
            "schema_version": 1,
            "skill": SKILL_NAME,
            "comparison_condition": "legacy-clean",
            "source_commit": commit,
            "source_dirty": dirty,
            "runtime_sha256": digest,
            "file_count": len(staged),
            "sanitization": {
                "excluded_top_level": [".git", ".github", "README.md", ".gitignore", "evals", "scripts"],
                "excluded_files": sorted(EXCLUDED_LEGACY_FILES),
                "skill_md_transform": "remove the single references/evaluation.md list entry only",
                "reason": "prevent evaluator/harness material from entering candidate runtime while preserving v0.4 core behavior instructions",
            },
            "scope": "sanitized comparison runtime; not byte-for-byte v0.4.0",
        }
        (output / "runtime-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    except Exception:
        shutil.rmtree(output)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build(args.legacy_root, args.output)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
