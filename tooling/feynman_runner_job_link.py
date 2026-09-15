#!/usr/bin/env python3
"""Bind a subscription runner-job v3 to a verified runner attestation v3."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any
try:
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_runner_attestation import validate as validate_attestation
    from .feynman_runner_job_validate import validate_job_files
except ImportError:
    from feynman_boundary_profile import validate_profile_file
    from feynman_runner_attestation import validate as validate_attestation
    from feynman_runner_job_validate import validate_job_files

def _load(path:Path)->dict[str,Any]:
    if path.is_symlink() or not path.is_file(): raise ValueError(f"missing or unsafe JSON file: {path}")
    v=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise ValueError(f"JSON root must be object: {path}")
    return v
def _sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()

def bind(*,runner_job_path:Path,boundary_profile_path:Path,probe_report_path:Path,attestation_path:Path,
         allowed_system_skills:set[str]|None=None,allow_plugins:bool=False)->dict[str,Any]:
    runner_job_path=runner_job_path.resolve(); boundary_profile_path=boundary_profile_path.resolve()
    probe_report_path=probe_report_path.resolve(); attestation_path=attestation_path.resolve()
    job=_load(runner_job_path); jv=validate_job_files(runner_job_path,boundary_profile_path)
    _,profile_sha,_=validate_profile_file(boundary_profile_path)
    report=_load(probe_report_path); report_sha=_sha(probe_report_path); att=_load(attestation_path)
    av=validate_attestation(att,allow_plugins=allow_plugins,allowed_system_skills=allowed_system_skills or set(),
                            probe_report=report,probe_report_sha256=report_sha)
    if jv.get("verdict")!="runner-job-valid": raise ValueError("runner job is not valid")
    if av.get("verdict")!="contract-valid" or av.get("probe_report_bound") is not True:
        raise ValueError("runner attestation is not bound to a valid boundary report")
    if job.get("schema_version")!=3 or att.get("schema_version")!=3: raise ValueError("subscription linkage requires runner-job/attestation schema v3")

    ji,jvrs,jpaths,jbound,jnet,jauth,jskills,jdig=(job["job"],job["versions"],job["paths"],job["boundary"],job["network"],job["authentication"],job["skills"],job["digests"])
    if job.get("run_id")!=att.get("run_id"): raise ValueError("runner-job/attestation run_id mismatch")
    if ji.get("case_id")!=att.get("case_id") or ji.get("condition_id")!=att.get("condition_id"):
        raise ValueError("runner-job/attestation case or condition mismatch")
    if jvrs!=att.get("versions"): raise ValueError("runner-job/attestation model or Codex version mismatch")
    ap=att.get("paths")
    if not isinstance(ap,dict): raise ValueError("attestation has no paths object")
    for f,v in jpaths.items():
        if ap.get(f)!=v: raise ValueError(f"runner-job/attestation path mismatch: {f}")
    ab=att.get("boundary")
    if not isinstance(ab,dict): raise ValueError("attestation has no boundary object")
    for f in ("profile_sha256","backend","backend_version"):
        if jbound.get(f)!=ab.get(f): raise ValueError(f"runner-job/attestation boundary mismatch: {f}")
    if jbound.get("profile_sha256")!=profile_sha: raise ValueError("runner job does not bind supplied profile bytes")
    an=att.get("network")
    if not isinstance(an,dict): raise ValueError("attestation has no network object")
    for f in ("case_requires_tool_network","tool_network","allowed_tool_destinations","control_plane_separate_from_tool_network"):
        if jnet.get(f)!=an.get(f): raise ValueError(f"runner-job/attestation network mismatch: {f}")
    ae=att.get("environment")
    if not isinstance(ae,dict): raise ValueError("attestation has no environment object")
    if sorted(jbound.get("candidate_env_keys",[]))!=sorted(ae.get("candidate_env_keys",[])):
        raise ValueError("runner-job/attestation candidate env-key mismatch")
    if jskills.get("expected_candidate_skills")!=ae.get("expected_candidate_skills"):
        raise ValueError("runner-job/attestation expected skill-set mismatch")
    pairs={"mode":"control_plane_auth_mode","control_plane_auth_source":"control_plane_auth_source",
           "api_key_auth_allowed":"api_key_auth_allowed","candidate_auth_exposed":"candidate_auth_exposed",
           "candidate_tool_auth_env_keys":"candidate_tool_auth_env_keys",
           "candidate_readable_auth_paths":"candidate_readable_auth_paths","auth_command_arguments":"auth_command_arguments"}
    for jf,af in pairs.items():
        if jauth.get(jf)!=ae.get(af): raise ValueError(f"runner-job/attestation authentication mismatch: {jf}/{af}")
    if jauth.get("mode")!="chatgpt-subscription" or jauth.get("control_plane_auth_source")!="codex-session":
        raise ValueError("non-subscription auth is not linkable")
    if jauth.get("api_key_auth_allowed") is not False or jauth.get("candidate_auth_exposed") is not False:
        raise ValueError("subscription link forbids API-key auth and candidate auth exposure")
    ad=att.get("digests")
    if not isinstance(ad,dict): raise ValueError("attestation has no digests object")
    for f in ("eval_plan_sha256","candidate_prompt_sha256","runtime_sha256"):
        if jdig.get(f)!=ad.get(f): raise ValueError(f"runner-job/attestation digest mismatch: {f}")
    if ad.get("probe_report_sha256")!=report_sha: raise ValueError("attestation does not bind supplied probe report bytes")
    return {
        "schema_version":3,"verdict":"runner-job-attestation-bound","run_id":job["run_id"],
        "case_id":ji["case_id"],"condition_id":ji["condition_id"],"runner_job_sha256":_sha(runner_job_path),
        "boundary_profile_sha256":profile_sha,"probe_report_sha256":report_sha,
        "runner_attestation_sha256":_sha(attestation_path),"eval_plan_sha256":jdig["eval_plan_sha256"],
        "candidate_prompt_sha256":jdig["candidate_prompt_sha256"],"runtime_sha256":jdig["runtime_sha256"],
        "model":jvrs["model"],"codex_cli":jvrs["codex_cli"],"authentication_mode":"chatgpt-subscription",
        "control_plane_auth_source":"codex-session","api_key_auth_allowed":False,"candidate_auth_exposed":False,
        "scope":"evaluator-side linkage of subscription-authenticated control plane to isolated candidate execution; no auth token material preserved",
    }

def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("runner-job","boundary-profile","probe-report","attestation"): p.add_argument("--"+n,type=Path,required=True)
    p.add_argument("--allowed-system-skill",action="append",default=[]);p.add_argument("--allow-plugins",action="store_true");p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    try:
        r=bind(runner_job_path=a.runner_job,boundary_profile_path=a.boundary_profile,probe_report_path=a.probe_report,
               attestation_path=a.attestation,allowed_system_skills=set(a.allowed_system_skill),allow_plugins=a.allow_plugins)
        if a.output.exists() or a.output.is_symlink(): raise FileExistsError(f"refusing to overwrite: {a.output}")
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    except (ValueError,OSError,UnicodeDecodeError,json.JSONDecodeError) as exc: p.exit(2,f"error: {exc}\n")
    print(json.dumps(r,ensure_ascii=False,indent=2));return 0
if __name__=="__main__": raise SystemExit(main())
