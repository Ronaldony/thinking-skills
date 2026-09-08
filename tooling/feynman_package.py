#!/usr/bin/env python3
"""Build the explicit Feynman runtime allowlist; does not create a security sandbox."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

SKILL_NAME = "feynman-thinking"
RUNTIME_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "assets/result-card.md",
    "references/evidence-map.md",
    "references/protocol.md",
    "references/handoff-contract.md",
)

def checked_file(root: Path, relative: str) -> Path:
    path = root / relative
    if root.is_symlink():
        raise ValueError(f"symlink runtime root is not allowed: {root}")
    current = root
    for part in Path(relative).parts:
        if part in {"..", "."}:
            raise ValueError(f"unsafe relative path: {relative}")
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlink is not allowed: {current}")
    if not path.is_file():
        raise ValueError(f"missing runtime file: {relative}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"runtime file escapes package: {relative}")
    return path

def validate_runtime(root: Path) -> dict[str, Any]:
    files = {name: checked_file(root, name) for name in RUNTIME_FILES}
    text = files["SKILL.md"].read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if not text.startswith("---\n") or len(parts) != 3:
        raise ValueError("missing frontmatter")
    # This is a validator for this package's single-line fields, not a general YAML parser.
    header = parts[1]
    if not re.search(r"(?m)^name: feynman-thinking\s*$", header):
        raise ValueError("skill name does not match package directory")
    description = re.search(r'(?m)^description: "([^\n]+)"\s*$', header)
    if not description or not 1 <= len(description.group(1)) <= 1024:
        raise ValueError("description must be a nonempty single-line quoted string, <=1024 characters")
    if len(text.splitlines()) > 220:
        raise ValueError("local draft budget exceeded: SKILL.md >220 lines")
    for name, path in files.items():
        if path.suffix != ".md":
            continue
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("#"):
                continue
            target = target.split("#", 1)[0]
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(root.resolve()):
                raise ValueError(f"link escapes runtime: {name}: {target}")
            if not resolved.is_file():
                raise ValueError(f"broken runtime link: {name}: {target}")
            if resolved.relative_to(root.resolve()).as_posix() not in RUNTIME_FILES:
                raise ValueError(f"runtime link references non-allowlisted file: {target}")
    return {"runtime_files": len(files), "skill_lines": len(text.splitlines()),
            "skill_bytes": len(text.encode("utf-8")), "description_characters": len(description.group(1))}

def runtime_digest(root: Path) -> tuple[str, dict[str, str]]:
    digest = hashlib.sha256()
    per_file: dict[str, str] = {}
    for relative in sorted(RUNTIME_FILES):
        content = checked_file(root, relative).read_bytes()
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        per_file[relative] = hashlib.sha256(content).hexdigest()
    return digest.hexdigest(), per_file

def git_value(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None

def git_repository_state(root: Path) -> tuple[str | None, bool | None]:
    """Read provenance only when *root itself* is the Git worktree root.

    `git -C <dir>` normally walks to parent repositories. That is useful for Git,
    but wrong for a package manifest because it can silently attribute an enclosing
    repository's commit to a nested, non-repository package directory.
    """
    root = root.resolve()
    top = git_value(root, "rev-parse", "--show-toplevel")
    if top is None:
        return None, None
    try:
        top_path = Path(top).resolve()
    except OSError:
        return None, None
    if top_path != root:
        return None, None
    commit = git_value(root, "rev-parse", "HEAD")
    status = git_value(root, "status", "--porcelain")
    return commit, None if status is None else bool(status)

def build(repo_root: Path, output: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    runtime = repo_root / "skills" / SKILL_NAME
    stats = validate_runtime(runtime)
    sha, file_hashes = runtime_digest(runtime)
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite: {output}")
    if output.resolve().is_relative_to(runtime.resolve()):
        raise ValueError("output cannot be inside the runtime source")
    repository_commit, repository_dirty = git_repository_state(repo_root)
    manifest = {"schema_version": 1, "skill": SKILL_NAME,
                "runtime_sha256": sha, "files": file_hashes,
                "repository_commit": repository_commit,
                "repository_dirty": repository_dirty,
                "validation": stats,
                "scope": "allowlist packaging only; no OS/network isolation or behavioral validation"}
    output.mkdir(parents=True, exist_ok=False)
    try:
        target = output / SKILL_NAME
        for relative in RUNTIME_FILES:
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checked_file(runtime, relative), dest)
        validate_runtime(target)
        if runtime_digest(target)[0] != sha:
            raise ValueError("copied runtime digest mismatch")
        (output / "runtime-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(output)
        raise
    return manifest

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.root, args.output), ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
