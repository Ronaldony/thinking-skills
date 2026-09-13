#!/usr/bin/env python3
"""Validate a ChatGPT-subscription runner job against its boundary profile.

Schema v3 is the only executable canonical contract. It contains no API-key
credential source. Historical v2 artifacts remain available only through Git
history/legacy modules and are not accepted for new execution.
"""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from typing import Any
try:
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_path_mapping import mounts_for_job
except ImportError:
    from feynman_boundary_profile import validate_profile_file
    from feynman_path_mapping import mounts_for_job

SHA_PATTERN = re.compile(r"[0-9a-f]{64}")
ENV_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SECRET_KEY_PATTERN = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE|AUTH|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)",
    re.IGNORECASE,
)
SKILL_CONDITIONS = {"legacy-clean", "feynman-v05"}
NO_SKILL_CONDITIONS = {"baseline", "generic"}

def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON file: {path}")
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return value

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _valid_sha(value: Any) -> bool:
    return isinstance(value,str) and SHA_PATTERN.fullmatch(value) is not None

def _absolute_string(value: Any,label: str)->str:
    if not isinstance(value,str) or not value:
        raise ValueError(f"{label} must be a nonempty absolute path")
    path=Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    return str(path.resolve(strict=False))

def _contains(root: str, child: str)->bool:
    r,c=Path(root),Path(child)
    return c==r or c.is_relative_to(r)

def _overlap(a:str,b:str)->bool:
    return _contains(a,b) or _contains(b,a)

def validate_job(job: dict[str,Any], profile: dict[str,Any], profile_sha: str)->dict[str,Any]:
    if job.get("schema_version") != 3:
        raise ValueError("unsupported runner job schema_version; expected 3")
    if not isinstance(job.get("run_id"),str) or not job["run_id"].strip():
        raise ValueError("runner job run_id must be nonempty")
    for name in ("job","versions","paths","boundary","network","authentication","skills","digests"):
        if not isinstance(job.get(name),dict):
            raise ValueError(f"runner job {name} must be an object")

    info,versions,paths=job["job"],job["versions"],job["paths"]
    boundary,network,auth,skills,digests=job["boundary"],job["network"],job["authentication"],job["skills"],job["digests"]
    condition=info.get("condition_id")
    if condition not in SKILL_CONDITIONS|NO_SKILL_CONDITIONS:
        raise ValueError("unsupported runner job condition")
    if not isinstance(info.get("case_id"),str) or not info["case_id"]:
        raise ValueError("runner job case_id must be nonempty")
    if type(info.get("ordinal")) is not int or info["ordinal"]<1:
        raise ValueError("runner job ordinal must be positive integer")
    if type(info.get("repeat")) is not int or info["repeat"]<1:
        raise ValueError("runner job repeat must be positive integer")
    if type(info.get("has_followup")) is not bool:
        raise ValueError("runner job has_followup must be boolean")
    for field in ("model","codex_cli"):
        if not isinstance(versions.get(field),str) or not versions[field].strip():
            raise ValueError(f"runner job versions.{field} must be nonempty")

    path_values={name:_absolute_string(paths.get(name),f"paths.{name}") for name in (
        "candidate_dir","evaluator_dir","source_repo","ephemeral_home","codex_home",
        "temp_dir","real_home","control_codex_home")}
    candidate_owned={path_values[n] for n in ("candidate_dir","ephemeral_home","codex_home","temp_dir")}
    protected={path_values[n] for n in ("evaluator_dir","source_repo","real_home","control_codex_home")}
    for p in protected:
        for c in candidate_owned:
            if _overlap(p,c):
                raise ValueError("candidate-owned and protected path roots must be disjoint")

    if not _valid_sha(profile_sha):
        raise ValueError("boundary profile digest must be SHA-256")
    if boundary.get("profile_sha256")!=profile_sha or digests.get("boundary_profile_sha256")!=profile_sha:
        raise ValueError("runner job boundary profile digest mismatch")
    for field in ("backend","backend_version","network_mode"):
        if boundary.get(field)!=profile.get(field):
            raise ValueError(f"runner job boundary {field} differs from profile")

    profile_env=profile.get("candidate_env_keys")
    job_env=boundary.get("candidate_env_keys")
    if not isinstance(profile_env,list) or not isinstance(job_env,list) or sorted(profile_env)!=sorted(job_env):
        raise ValueError("runner job candidate env-key allowlist differs from profile")
    if not all(isinstance(k,str) and ENV_KEY_PATTERN.fullmatch(k) for k in job_env):
        raise ValueError("runner job candidate env keys must be valid environment variable names")
    secretish=sorted(k for k in job_env if SECRET_KEY_PATTERN.search(k))
    if secretish:
        raise ValueError("candidate env allowlist contains secret-like names: "+", ".join(secretish))

    mounts = mounts_for_job(job, profile)
    writable_sources = {
        _absolute_string(item["source"], "boundary.mounts[].source")
        for item in mounts
        if item["access"] == "rw"
    }
    if writable_sources != candidate_owned:
        raise ValueError("boundary writable mount sources must equal candidate-owned roots")
    if any(any(_overlap(p,r) for p in protected) for r in writable_sources):
        raise ValueError("protected path appears in boundary writable mount sources")

    expected_auth={
        "mode":"chatgpt-subscription",
        "control_plane_auth_source":"codex-session",
        "api_key_auth_allowed":False,
        "candidate_auth_exposed":False,
        "candidate_tool_auth_env_keys":[],
        "candidate_readable_auth_paths":[],
        "auth_command_arguments":[],
    }
    if auth != expected_auth:
        raise ValueError("runner job authentication must be the canonical ChatGPT-subscription contract")
    raw=json.dumps(job,sort_keys=True)
    if "OPENAI_API_KEY" in raw or "control_plane_credential" in raw:
        raise ValueError("runner job contains retired API credential contract fields")

    requires=network.get("case_requires_tool_network")
    destinations=network.get("allowed_tool_destinations")
    if type(requires) is not bool or not isinstance(destinations,list):
        raise ValueError("runner job network fields are invalid")
    if network.get("control_plane_separate_from_tool_network") is not True:
        raise ValueError("runner job requires control-plane/tool-network separation")
    expected_tool={"none":"blocked","restricted":"restricted","open":"open"}.get(profile["network_mode"])
    if network.get("tool_network")!=expected_tool:
        raise ValueError("runner job tool-network policy differs from profile")
    if not requires and (expected_tool!="blocked" or destinations):
        raise ValueError("closed-network runner job must block tool network with no destinations")
    if requires and expected_tool=="restricted" and not destinations:
        raise ValueError("restricted network runner job requires explicit destinations")

    expected_skills=["feynman-thinking"] if condition in SKILL_CONDITIONS else []
    if skills.get("expected_candidate_skills")!=expected_skills:
        raise ValueError("runner job expected skill set differs from condition")
    runtime=skills.get("runtime_sha256")
    if digests.get("runtime_sha256")!=runtime:
        raise ValueError("runner job runtime digest fields disagree")
    if condition in SKILL_CONDITIONS:
        if not _valid_sha(runtime): raise ValueError("skill condition requires runtime SHA-256")
    elif runtime is not None:
        raise ValueError("no-skill condition must not have runtime SHA")
    for field in ("eval_plan_sha256","candidate_prompt_sha256","boundary_profile_sha256"):
        if not _valid_sha(digests.get(field)):
            raise ValueError(f"runner job digests.{field} must be SHA-256")
    return {
        "verdict":"runner-job-valid","run_id":job["run_id"],"case_id":info["case_id"],
        "condition_id":condition,"boundary_profile_sha256":profile_sha,
        "candidate_owned_roots":sorted(candidate_owned),"protected_roots":sorted(protected),
        "tool_network":expected_tool,"authentication_mode":"chatgpt-subscription",
        "control_plane_auth_source":"codex-session","api_key_auth_allowed":False,
        "mounts": mounts,
        "scope":"pre-execution subscription runner-job/profile consistency; does not inspect login token material",
    }

def validate_job_files(job_path:Path,profile_path:Path)->dict[str,Any]:
    job=_load(job_path.resolve())
    profile,profile_sha,_=validate_profile_file(profile_path.resolve())
    result=validate_job(job,profile,profile_sha)
    result["runner_job_sha256"]=_sha(job_path.resolve())
    return result

def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job",type=Path,required=True);p.add_argument("--boundary-profile",type=Path,required=True)
    a=p.parse_args()
    try: result=validate_job_files(a.job,a.boundary_profile)
    except (ValueError,OSError,UnicodeDecodeError,json.JSONDecodeError) as exc: p.exit(2,f"error: {exc}\n")
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0
if __name__=="__main__": raise SystemExit(main())
