#!/usr/bin/env python3
"""Aggregate linkage-complete Feynman analysis records (result schema v3).

The statistical/descriptive calculations are delegated to the preserved v2
aggregator after this module verifies the new runner-job linkage and
control-plane authentication metadata. Schema-v2 results are intentionally not
accepted by the canonical aggregator.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any, Iterable

try:
    from .feynman_eval_aggregate_v2_legacy import aggregate as aggregate_v2
except ImportError:
    from feynman_eval_aggregate_v2_legacy import aggregate as aggregate_v2

SHA = re.compile(r"^[0-9a-f]{64}$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return value


def _sha(value: Any) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _validate_v3(record: dict[str, Any]) -> tuple[str, str, str]:
    if record.get("schema_version") != 3 or record.get("valid_for_analysis") is not True:
        raise ValueError("canonical aggregation requires analysis-ready result schema v3")

    digests = record.get("digests")
    if not isinstance(digests, dict):
        raise ValueError("schema-v3 result has no digests object")
    for field in (
        "eval_plan_sha256",
        "candidate_prompt_sha256",
        "boundary_profile_sha256",
        "probe_report_sha256",
        "attestation_sha256",
        "runner_job_sha256",
        "runner_job_link_sha256",
    ):
        if not _sha(digests.get(field)):
            raise ValueError(f"schema-v3 result requires SHA-256 digest: {field}")

    lineage = record.get("lineage")
    if not isinstance(lineage, dict):
        raise ValueError("schema-v3 result lacks lineage object")
    if lineage.get("runner_job_attestation_bound") is not True:
        raise ValueError("schema-v3 result does not assert runner-job/attestation binding")
    if lineage.get("runner_job_link_verdict") != "runner-job-attestation-bound":
        raise ValueError("schema-v3 result has invalid runner-job-link verdict")

    auth = record.get("authentication")
    if not isinstance(auth, dict):
        raise ValueError("schema-v3 result lacks authentication object")
    if auth.get("mode") != "control-plane-only":
        raise ValueError("unsupported analysis-result authentication mode")
    if auth.get("control_plane_credential_source") != "environment":
        raise ValueError("unsupported analysis-result credential source")
    key = auth.get("control_plane_credential_env_key")
    if not isinstance(key, str) or ENV_KEY.fullmatch(key) is None:
        raise ValueError("analysis-result credential env key is invalid")
    if auth.get("candidate_auth_exposed") is not False:
        raise ValueError("analysis-result claims candidate authentication exposure")

    versions = record.get("versions")
    if not isinstance(versions, dict):
        raise ValueError("schema-v3 result lacks versions object")
    model = versions.get("model")
    cli = versions.get("codex_cli")
    if not isinstance(model, str) or not model or not isinstance(cli, str) or not cli:
        raise ValueError("schema-v3 result model/Codex versions must be nonempty")
    return auth["mode"], auth["control_plane_credential_source"], key


def aggregate(plan: dict[str, Any], records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(records)
    auth_profiles: set[tuple[str, str, str]] = set()
    translated: list[dict[str, Any]] = []
    for record in records:
        auth_profiles.add(_validate_v3(record))
        legacy = deepcopy(record)
        legacy["schema_version"] = 2
        translated.append(legacy)

    result = aggregate_v2(plan, translated)
    profiles = [
        {"mode": mode, "credential_source": source, "credential_env_key": key}
        for mode, source, key in sorted(auth_profiles)
    ]
    consistency = result.setdefault("environment_consistency", {})
    consistency["authentication_profiles"] = profiles
    consistency["single_authentication_profile"] = len(auth_profiles) <= 1

    if len(auth_profiles) > 1:
        result["status"] = "mixed-environment"
        result["primary_comparison_ready"] = False
        reasons = result.setdefault("blocking_reasons", [])
        reason = "control-plane authentication architecture differs across result records"
        if reason not in reasons:
            reasons.append(reason)

    result["schema_version"] = 2
    result["accepted_result_schema_version"] = 3
    result["scope"] = (
        "descriptive preregistered metrics over schema-v3 results with mandatory pre-run runner-job -> "
        "post-run attestation linkage; only status=analysis-ready may enter the primary comparison"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--result", type=Path, action="append", default=[])
    parser.add_argument("--result-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = _load(args.plan.resolve())
        paths = list(args.result)
        if args.result_dir:
            paths.extend(sorted(args.result_dir.glob("*.json")))
        if not paths:
            raise ValueError("at least one --result or --result-dir JSON file is required")
        records = [_load(path.resolve()) for path in paths]
        result = aggregate(plan, records)
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"refusing to overwrite: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
