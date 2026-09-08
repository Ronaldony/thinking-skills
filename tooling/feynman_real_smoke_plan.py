#!/usr/bin/env python3
"""Build the preregistered two-job real-model integration smoke plan.

The smoke plan is explicitly not a skill-effect estimate.  It uses one public
execution case (`tools-10`) and two conditions (`baseline`, `feynman-v05`) only
to exercise the real model/control-plane/tool/evidence pipeline before a wider
pilot.  The raw smoke-spec SHA-256 is embedded in the generated frozen plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

try:
    from .feynman_eval_plan import build_plan, write_plan
except ImportError:
    from feynman_eval_plan import build_plan, write_plan

EXPECTED_PURPOSE = "integration-only-real-model-smoke"
EXPECTED_ANALYSIS_USE = "not-for-skill-performance-inference"
EXPECTED_CASES = ["tools-10"]
EXPECTED_CONDITIONS = ["baseline", "feynman-v05"]
EXPECTED_REPEATS = 1
EXPECTED_SEED = 20260908
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _load_spec(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe smoke spec: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("smoke spec JSON root must be object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.resolve().read_bytes()).hexdigest()


def validate_spec(spec: dict[str, Any]) -> None:
    expected = {
        "schema_version": 1,
        "purpose": EXPECTED_PURPOSE,
        "analysis_use": EXPECTED_ANALYSIS_USE,
        "cases": EXPECTED_CASES,
        "conditions": EXPECTED_CONDITIONS,
        "repeats": EXPECTED_REPEATS,
        "seed": EXPECTED_SEED,
        "requires_actual_external_model_service": True,
        "requires_control_plane_only_authentication": True,
    }
    for field, value in expected.items():
        if spec.get(field) != value:
            raise ValueError(f"smoke spec violates frozen integration contract: {field}")
    env_key = spec.get("default_control_plane_credential_env_key_name")
    if not isinstance(env_key, str) or ENV_KEY.fullmatch(env_key) is None:
        raise ValueError("smoke spec has invalid control-plane credential env-key name")
    required = spec.get("required_success_evidence")
    prohibited = spec.get("prohibited_claims")
    if not isinstance(required, list) or len(required) < 5 or not all(isinstance(x, str) and x for x in required):
        raise ValueError("smoke spec must enumerate required success evidence")
    if not isinstance(prohibited, list) or len(prohibited) < 3 or not all(isinstance(x, str) and x for x in prohibited):
        raise ValueError("smoke spec must enumerate prohibited claims")
    scope = spec.get("scope")
    if not isinstance(scope, str) or not scope:
        raise ValueError("smoke spec scope must be nonempty")


def build_smoke_plan(repo_root: Path, spec_path: Path) -> dict[str, Any]:
    spec_path = spec_path.resolve()
    spec = _load_spec(spec_path)
    validate_spec(spec)
    plan = build_plan(
        repo_root,
        case_ids=list(spec["cases"]),
        condition_ids=list(spec["conditions"]),
        repeats=spec["repeats"],
        seed=spec["seed"],
    )
    if len(plan.get("jobs", [])) != 2:
        raise ValueError("integration smoke must produce exactly two jobs")
    if {job.get("condition") for job in plan["jobs"]} != set(EXPECTED_CONDITIONS):
        raise ValueError("integration smoke plan condition set drift")
    if {job.get("case_id") for job in plan["jobs"]} != set(EXPECTED_CASES):
        raise ValueError("integration smoke plan case set drift")
    plan["smoke_spec_sha256"] = _sha(spec_path)
    plan["analysis_use"] = EXPECTED_ANALYSIS_USE
    plan["required_success_evidence"] = list(spec["required_success_evidence"])
    plan["prohibited_claims"] = list(spec["prohibited_claims"])
    plan["scope"] = (
        "public-development real-model integration smoke; frozen plan is for plumbing validation only "
        "and must not be used to estimate Feynman skill effect"
    )
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--spec",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "evals" / "feynman-thinking" / "real-model-smoke-spec.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = build_smoke_plan(args.root.resolve(), args.spec.resolve())
        write_plan(plan, args.output)
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps({
        "status": plan["status"],
        "purpose": EXPECTED_PURPOSE,
        "analysis_use": plan["analysis_use"],
        "jobs": [
            {"ordinal": job["ordinal"], "case_id": job["case_id"], "condition": job["condition"]}
            for job in plan["jobs"]
        ],
        "smoke_spec_sha256": plan["smoke_spec_sha256"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
