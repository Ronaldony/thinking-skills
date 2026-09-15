#!/usr/bin/env python3
"""Derive a deterministic mock-model catalog from an installed Codex bundled catalog.

The input is expected to be the JSON emitted by ``codex debug models --bundled``.
This tool does not invent apply-patch support. It selects an existing bundled
model that already advertises all of the capabilities needed by the reference:

- ``apply_patch_tool_type == freeform``
- unified shell/exec support
- text input support

It then clones exactly that model and changes only ``slug`` and ``display_name``
to the requested mock slug. The output retains the original catalog envelope but
contains only the cloned model, removing ambiguity about which metadata Codex
will resolve during the mock reference.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

PATCH_TYPE = "freeform"
ALLOWED_SHELL_TYPES = {"unified_exec", "default", "local", "shell_command"}
DEFAULT_MOCK_SLUG = "mock-model"


def _regular(path: Path, label: str) -> Path:
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    return path


def _load(path: Path) -> dict[str, Any]:
    path = _regular(path, "bundled model catalog")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("bundled model catalog JSON root must be an object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate(model: Any) -> bool:
    if not isinstance(model, dict):
        return False
    if model.get("apply_patch_tool_type") != PATCH_TYPE:
        return False
    if model.get("shell_type") not in ALLOWED_SHELL_TYPES:
        return False
    modalities = model.get("input_modalities")
    if not isinstance(modalities, list) or "text" not in modalities:
        return False
    slug = model.get("slug")
    display_name = model.get("display_name")
    return isinstance(slug, str) and bool(slug.strip()) and isinstance(display_name, str) and bool(display_name.strip())


def derive_catalog(catalog: dict[str, Any], *, mock_slug: str = DEFAULT_MOCK_SLUG) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(mock_slug, str) or not mock_slug.strip() or mock_slug != mock_slug.strip():
        raise ValueError("mock slug must be a nonempty trimmed string")
    models = catalog.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("bundled model catalog must contain a nonempty models list")
    if any(not isinstance(model, dict) for model in models):
        raise ValueError("bundled model catalog models must all be objects")

    slugs = [model.get("slug") for model in models]
    if any(not isinstance(slug, str) or not slug for slug in slugs):
        raise ValueError("every bundled model must have a nonempty slug")
    if len(set(slugs)) != len(slugs):
        raise ValueError("bundled model slugs must be unique")

    candidates = [model for model in models if _candidate(model)]
    if not candidates:
        raise ValueError(
            "installed bundled catalog has no model that advertises freeform apply_patch + unified exec + text input"
        )

    source = candidates[0]
    clone = deepcopy(source)
    source_slug = clone["slug"]
    source_display_name = clone["display_name"]
    clone["slug"] = mock_slug
    clone["display_name"] = mock_slug

    # Fail closed if the two fields above were not the only semantic mutation.
    reconstructed = deepcopy(clone)
    reconstructed["slug"] = source_slug
    reconstructed["display_name"] = source_display_name
    if reconstructed != source:
        raise ValueError("mock catalog derivation changed source model metadata beyond slug/display_name")
    if clone.get("apply_patch_tool_type") != PATCH_TYPE:
        raise ValueError("derived mock model lost freeform apply_patch metadata")
    if clone.get("shell_type") not in ALLOWED_SHELL_TYPES:
        raise ValueError("derived mock model lost unified exec metadata")

    output = deepcopy(catalog)
    output["models"] = [clone]
    manifest = {
        "schema_version": 1,
        "mock_slug": mock_slug,
        "source_slug": source_slug,
        "source_display_name": source_display_name,
        "source_apply_patch_tool_type": source.get("apply_patch_tool_type"),
        "source_shell_type": source.get("shell_type"),
        "source_input_modalities": source.get("input_modalities"),
        "source_model_index": models.index(source),
        "candidate_count": len(candidates),
        "only_slug_and_display_name_changed": True,
        "scope": "derived from installed Codex bundled model catalog; no external model call",
    }
    return output, manifest


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundled-catalog", type=Path, required=True)
    parser.add_argument("--mock-slug", default=DEFAULT_MOCK_SLUG)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        source_path = _regular(args.bundled_catalog, "bundled model catalog")
        catalog = _load(source_path)
        output, manifest = derive_catalog(catalog, mock_slug=args.mock_slug)
        _write_new_json(args.output, output)
        manifest = {
            **manifest,
            "bundled_catalog_sha256": _sha(source_path),
            "derived_catalog_sha256": _sha(args.output.resolve()),
        }
        _write_new_json(args.manifest_output, manifest)
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
