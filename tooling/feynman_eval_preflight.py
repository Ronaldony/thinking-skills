#!/usr/bin/env python3
"""Fail closed on obvious skill-root contamination before a model comparison run.

This checks filesystem skill roots only. It does not prove process, plugin, network,
or credential isolation and therefore cannot certify a hermetic evaluation by itself.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable


def _skill_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_symlink():
        raise ValueError(f"skill root symlink is not allowed in eval preflight: {root}")
    if not root.is_dir():
        raise ValueError(f"skill root is not a directory: {root}")
    files: list[Path] = []
    for path in root.rglob("SKILL.md"):
        if path.is_symlink():
            raise ValueError(f"skill file symlink is not allowed in eval preflight: {path}")
        if path.is_file():
            files.append(path.resolve())
    return sorted(files)


def _names_from_candidate(root: Path) -> dict[str, str]:
    observed: dict[str, str] = {}
    for skill_file in _skill_files(root):
        relative = skill_file.relative_to(root.resolve())
        if len(relative.parts) < 2:
            raise ValueError(f"unexpected candidate skill layout: {skill_file}")
        name = relative.parts[0]
        if name in observed:
            raise ValueError(f"duplicate/nested candidate skill name discovered: {name}")
        observed[name] = str(skill_file)
    return observed


def _dedupe_roots(roots: Iterable[tuple[str, Path]]) -> list[tuple[str, Path]]:
    seen: set[Path] = set()
    result: list[tuple[str, Path]] = []
    for label, root in roots:
        resolved = root.expanduser().absolute()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append((label, resolved))
    return result


def preflight(candidate_dir: Path, expected_skills: set[str], *, home: Path,
              codex_home: Path | None = None) -> dict[str, Any]:
    candidate_dir = candidate_dir.absolute()
    if candidate_dir.is_symlink() or not candidate_dir.is_dir():
        raise ValueError(f"candidate directory must be a real directory: {candidate_dir}")
    candidate_root = candidate_dir / ".agents" / "skills"
    observed = _names_from_candidate(candidate_root) if candidate_root.exists() else {}
    if set(observed) != expected_skills:
        raise ValueError(
            f"candidate skill set mismatch: expected={sorted(expected_skills)} observed={sorted(observed)}"
        )

    home = home.expanduser().absolute()
    effective_codex_home = (codex_home.expanduser().absolute()
                            if codex_home is not None else home / ".codex")
    contamination_roots: list[tuple[str, Path]] = [
        ("user-agents", home / ".agents" / "skills"),
        ("codex-home", effective_codex_home / "skills"),
    ]

    # Project skill discovery may walk parent directories. Candidate-local skills are
    # allowed, but any ancestor .agents/skills root outside candidate is contamination.
    for index, parent in enumerate(candidate_dir.parents):
        contamination_roots.append((f"ancestor-{index}", parent / ".agents" / "skills"))

    contaminated: list[dict[str, Any]] = []
    for label, root in _dedupe_roots(contamination_roots):
        if root == candidate_root.absolute():
            continue
        files = _skill_files(root)
        if files:
            contaminated.append({"label": label, "root": str(root),
                                 "skill_files": [str(path) for path in files]})
    if contaminated:
        rendered = "; ".join(f"{item['label']}={item['root']}" for item in contaminated)
        raise ValueError(f"skill-root contamination detected: {rendered}")

    system_roots = []
    for root in (Path("/etc/codex/skills"),):
        try:
            files = _skill_files(root)
        except ValueError:
            files = []
        if files:
            system_roots.append({"root": str(root), "skill_files": [str(p) for p in files]})

    return {
        "schema_version": 1,
        "candidate_dir": str(candidate_dir),
        "expected_candidate_skills": sorted(expected_skills),
        "observed_candidate_skills": observed,
        "home": str(home),
        "codex_home": str(effective_codex_home),
        "contamination_roots_checked": [str(root) for _, root in _dedupe_roots(contamination_roots)],
        "system_skill_roots_observed": system_roots,
        "scope": (
            "filesystem skill-root preflight only; does not isolate plugins, built-in/system skills, "
            "process environment, credentials, network, or other host files"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--expected-skill", action="append", default=[])
    parser.add_argument("--home", type=Path,
                        default=Path(os.environ.get("HOME", str(Path.home()))))
    parser.add_argument("--codex-home", type=Path,
                        default=Path(os.environ["CODEX_HOME"]) if os.environ.get("CODEX_HOME") else None)
    args = parser.parse_args()
    try:
        result = preflight(args.candidate_dir, set(args.expected_skill), home=args.home,
                           codex_home=args.codex_home)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
