#!/usr/bin/env python3
"""Build a fail-closed ChatGPT-subscription Codex runner job.

Runner-job schema v3 has no API-key mode. The host control-plane Codex must use
an already authenticated ChatGPT subscription session stored under a protected
control CODEX_HOME. Candidate tools use a separate CODEX_HOME, receive no auth
material, and run under the referenced external boundary profile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

try:
    from .feynman_boundary_profile import validate_profile_file
except ImportError:
    from feynman_boundary_profile import validate_profile_file

PRIMARY_CONDITIONS = {"baseline", "generic", "legacy-clean", "feynman-v05"}
SKILL_CONDITIONS = {"legacy-clean", "feynman-v05"}
SHA_PATTERN = re.compile(r"[0-9a-f]{64}")
SECRET_KEY_PATTERN = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE|AUTH|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)",
    re.IGNORECASE,
)

def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return value

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_PATTERN.fullmatch(value) is not None

def _absolute(path: Path, label: str) -> Path:
    path = path.expanduser().absolute()
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    return path.resolve(strict=False)

def _contains(root: Path, path: Path) -> bool:
    return path == root or path.is_relative_to(root)

def _overlap(a: Path, b: Path) -> bool:
    return _contains(a, b) or _contains(b, a)

def _job(plan: dict[str, Any], ordinal: int) -> dict[str, Any]:
    jobs = plan.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("eval plan has no jobs list")
    matches = [item for item in jobs if isinstance(item, dict) and item.get("ordinal") == ordinal]
    if len(matches) != 1:
        raise ValueError(f"eval plan must contain exactly one job with ordinal {ordinal}")
    return matches[0]

def build_job(*, plan_path: Path, ordinal: int, evaluator_case_path: Path,
              boundary_profile_path: Path, run_id: str, model: str, codex_cli: str,
              candidate_dir: Path, evaluator_dir: Path, source_repo: Path,
              ephemeral_home: Path, codex_home: Path, temp_dir: Path, real_home: Path,
              control_codex_home: Path | None = None, case_requires_tool_network: bool = False,
              allowed_tool_destinations: list[str] | None = None) -> dict[str, Any]:
    if not run_id.strip() or not model.strip() or not codex_cli.strip():
        raise ValueError("run_id, model, and codex_cli must be nonempty")
    allowed_tool_destinations = allowed_tool_destinations or []
    if len(set(allowed_tool_destinations)) != len(allowed_tool_destinations):
        raise ValueError("allowed tool destinations must not contain duplicates")
    if not all(isinstance(item, str) and item.strip() for item in allowed_tool_destinations):
        raise ValueError("allowed tool destinations must be nonempty strings")

    plan_path = plan_path.resolve()
    evaluator_case_path = evaluator_case_path.resolve()
    plan = _load(plan_path)
    planned = _job(plan, ordinal)
    evaluator_case = _load(evaluator_case_path)
    profile, profile_sha, _ = validate_profile_file(boundary_profile_path.resolve())

    case_id = planned.get("case_id")
    condition = planned.get("condition")
    repeat = planned.get("repeat")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("plan job has invalid case_id")
    if condition not in PRIMARY_CONDITIONS:
        raise ValueError("plan job has unsupported condition")
    if type(repeat) is not int or repeat < 1:
        raise ValueError("plan job has invalid repeat")
    prompt_sha = planned.get("candidate_prompt_sha256")
    if not _valid_sha(prompt_sha):
        raise ValueError("plan job has invalid candidate prompt digest")

    if evaluator_case.get("case_id") != case_id or evaluator_case.get("condition_id") != condition:
        raise ValueError("evaluator condition record differs from frozen plan job")
    if evaluator_case.get("candidate_prompt_sha256") != prompt_sha:
        raise ValueError("evaluator prompt digest differs from frozen plan job")
    if evaluator_case.get("required_source_commit") != planned.get("required_source_commit"):
        raise ValueError("evaluator source-commit requirement differs from frozen plan job")

    expected_skills = evaluator_case.get("expected_skills")
    required_skills = ["feynman-thinking"] if condition in SKILL_CONDITIONS else []
    if expected_skills != required_skills:
        raise ValueError("evaluator expected skill set differs from condition contract")
    runtime_manifest = evaluator_case.get("runtime_manifest")
    if condition in SKILL_CONDITIONS:
        if not isinstance(runtime_manifest, dict) or not _valid_sha(runtime_manifest.get("runtime_sha256")):
            raise ValueError("skill condition requires a runtime manifest SHA-256")
        runtime_sha: str | None = runtime_manifest["runtime_sha256"]
    else:
        if runtime_manifest is not None:
            raise ValueError("no-skill condition must not have a runtime manifest")
        runtime_sha = None

    if type(case_requires_tool_network) is not bool:
        raise ValueError("case_requires_tool_network must be boolean")
    network_mode = profile.get("network_mode")
    if not case_requires_tool_network:
        if network_mode != "none" or allowed_tool_destinations:
            raise ValueError("closed-network case requires profile network_mode=none and no allowed destinations")
        tool_network = "blocked"
    else:
        if network_mode not in {"restricted", "open"}:
            raise ValueError("network-required case needs restricted/open boundary profile")
        tool_network = network_mode
        if network_mode == "restricted" and not allowed_tool_destinations:
            raise ValueError("restricted tool network requires explicit allowed destinations")

    real_home_path = _absolute(real_home, "real_home")
    control_codex_home = control_codex_home or (real_home_path / ".codex")
    paths = {
        "candidate_dir": _absolute(candidate_dir, "candidate_dir"),
        "evaluator_dir": _absolute(evaluator_dir, "evaluator_dir"),
        "source_repo": _absolute(source_repo, "source_repo"),
        "ephemeral_home": _absolute(ephemeral_home, "ephemeral_home"),
        "codex_home": _absolute(codex_home, "codex_home"),
        "temp_dir": _absolute(temp_dir, "temp_dir"),
        "real_home": real_home_path,
        "control_codex_home": _absolute(control_codex_home, "control_codex_home"),
    }
    protected_names = ("evaluator_dir", "source_repo", "real_home", "control_codex_home")
    owned_names = ("candidate_dir", "ephemeral_home", "codex_home", "temp_dir")
    for protected_name in protected_names:
        for owned_name in owned_names:
            if _overlap(paths[protected_name], paths[owned_name]):
                raise ValueError(f"protected/candidate-owned path overlap: {protected_name}/{owned_name}")

    profile_env_keys = profile.get("candidate_env_keys")
    if not isinstance(profile_env_keys, list) or not profile_env_keys:
        raise ValueError("boundary profile has no candidate env-key allowlist")
    secretish = sorted(key for key in profile_env_keys if isinstance(key, str) and SECRET_KEY_PATTERN.search(key))
    if secretish:
        raise ValueError("candidate env allowlist contains secret-like names: " + ", ".join(secretish))

    return {
        "schema_version": 3,
        "run_id": run_id,
        "job": {
            "ordinal": ordinal,
            "case_id": case_id,
            "condition_id": condition,
            "repeat": repeat,
            "has_followup": planned.get("has_followup") is True,
        },
        "versions": {"model": model, "codex_cli": codex_cli},
        "paths": {name: str(path) for name, path in paths.items()},
        "boundary": {
            "profile_sha256": profile_sha,
            "backend": profile["backend"],
            "backend_version": profile["backend_version"],
            "network_mode": network_mode,
            "candidate_env_keys": sorted(profile_env_keys),
        },
        "network": {
            "case_requires_tool_network": case_requires_tool_network,
            "tool_network": tool_network,
            "allowed_tool_destinations": sorted(allowed_tool_destinations),
            "control_plane_separate_from_tool_network": True,
        },
        "authentication": {
            "mode": "chatgpt-subscription",
            "control_plane_auth_source": "codex-session",
            "api_key_auth_allowed": False,
            "candidate_auth_exposed": False,
            "candidate_tool_auth_env_keys": [],
            "candidate_readable_auth_paths": [],
            "auth_command_arguments": [],
        },
        "skills": {
            "expected_candidate_skills": required_skills,
            "runtime_sha256": runtime_sha,
        },
        "digests": {
            "eval_plan_sha256": _sha(plan_path),
            "candidate_prompt_sha256": prompt_sha,
            "boundary_profile_sha256": profile_sha,
            "runtime_sha256": runtime_sha,
        },
        "scope": (
            "immutable ChatGPT-subscription Codex runner contract; control-plane session state stays "
            "under protected control_codex_home and no API-key or candidate auth path is allowed"
        ),
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--ordinal", type=int, required=True)
    parser.add_argument("--evaluator-case", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--codex-cli", required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--evaluator-dir", type=Path, required=True)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--ephemeral-home", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--temp-dir", type=Path, required=True)
    parser.add_argument("--real-home", type=Path, required=True)
    parser.add_argument("--control-codex-home", type=Path)
    parser.add_argument("--case-requires-tool-network", action="store_true")
    parser.add_argument("--allowed-tool-destination", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_job(
            plan_path=args.plan, ordinal=args.ordinal, evaluator_case_path=args.evaluator_case,
            boundary_profile_path=args.boundary_profile, run_id=args.run_id, model=args.model,
            codex_cli=args.codex_cli, candidate_dir=args.candidate_dir, evaluator_dir=args.evaluator_dir,
            source_repo=args.source_repo, ephemeral_home=args.ephemeral_home, codex_home=args.codex_home,
            temp_dir=args.temp_dir, real_home=args.real_home, control_codex_home=args.control_codex_home,
            case_requires_tool_network=args.case_requires_tool_network,
            allowed_tool_destinations=args.allowed_tool_destination,
        )
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"refusing to overwrite: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
