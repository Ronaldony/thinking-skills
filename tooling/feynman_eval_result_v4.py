#!/usr/bin/env python3
"""Assemble one linkage-complete subscription-authenticated analysis result v4."""
from __future__ import annotations
import argparse, hashlib, json
from copy import deepcopy
from pathlib import Path
from typing import Any
try:
    from .feynman_eval_result_v2_legacy import assemble as assemble_base
    from .feynman_runner_job_link import bind as bind_runner_job
except ImportError:
    from feynman_eval_result_v2_legacy import assemble as assemble_base
    from feynman_runner_job_link import bind as bind_runner_job

PRIMARY_CONDITIONS={"baseline","generic","legacy-clean","feynman-v05"}

def _load(path:Path,label:str)->dict[str,Any]:
    path=path.resolve()
    if path.is_symlink() or not path.is_file(): raise ValueError(f"missing or unsafe {label}: {path}")
    v=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise ValueError(f"{label} JSON root must be object")
    return v
def _sha(path:Path)->str: return hashlib.sha256(path.resolve().read_bytes()).hexdigest()
def _planned(plan:dict[str,Any],ordinal:int)->dict[str,Any]:
    jobs=plan.get("jobs")
    if not isinstance(jobs,list): raise ValueError("eval plan has no jobs list")
    m=[j for j in jobs if isinstance(j,dict) and j.get("ordinal")==ordinal]
    if len(m)!=1: raise ValueError(f"eval plan must contain exactly one job with ordinal {ordinal}")
    return m[0]
def _verify_job(job:dict[str,Any],plan:dict[str,Any],plan_path:Path,ordinal:int)->None:
    if job.get("schema_version")!=3: raise ValueError("analysis result v4 requires runner-job schema v3")
    planned=_planned(plan,ordinal); info=job.get("job");dig=job.get("digests")
    if not isinstance(info,dict) or not isinstance(dig,dict): raise ValueError("runner job lacks job/digests")
    expected={"ordinal":planned.get("ordinal"),"case_id":planned.get("case_id"),"condition_id":planned.get("condition"),
              "repeat":planned.get("repeat"),"has_followup":planned.get("has_followup")}
    for f,v in expected.items():
        if info.get(f)!=v: raise ValueError(f"runner job differs from frozen plan field: {f}")
    if info.get("condition_id") not in PRIMARY_CONDITIONS: raise ValueError("unsupported primary condition")
    if dig.get("eval_plan_sha256")!=_sha(plan_path): raise ValueError("runner job is not bound to supplied plan bytes")
    if dig.get("candidate_prompt_sha256")!=planned.get("candidate_prompt_sha256"): raise ValueError("runner job prompt digest differs from plan")
    if dig.get("runtime_sha256")!=job.get("skills",{}).get("runtime_sha256"): raise ValueError("runner job runtime digest disagreement")
    auth=job.get("authentication")
    if not isinstance(auth,dict) or auth.get("mode")!="chatgpt-subscription" or auth.get("control_plane_auth_source")!="codex-session":
        raise ValueError("analysis result v4 requires ChatGPT-subscription Codex authentication")
    if auth.get("api_key_auth_allowed") is not False or auth.get("candidate_auth_exposed") is not False:
        raise ValueError("analysis result v4 forbids API-key auth and candidate auth exposure")
def _verify_link(saved:dict[str,Any],recomputed:dict[str,Any],job_path:Path,att_path:Path,plan_path:Path)->None:
    if saved!=recomputed: raise ValueError("saved runner-job-link differs from recomputed linkage")
    if saved.get("schema_version")!=3 or saved.get("verdict")!="runner-job-attestation-bound": raise ValueError("runner-job-link is not canonical schema v3")
    if saved.get("runner_job_sha256")!=_sha(job_path): raise ValueError("link does not bind runner job bytes")
    if saved.get("runner_attestation_sha256")!=_sha(att_path): raise ValueError("link does not bind attestation bytes")
    if saved.get("eval_plan_sha256")!=_sha(plan_path): raise ValueError("link does not bind eval plan bytes")

def assemble(plan_path:Path,ordinal:int,evaluator_case_path:Path,attestation_path:Path,semantic_review_path:Path,gate_path:Path,*,
             runner_job_path:Path|None=None,runner_job_link_path:Path|None=None,review_bundle_path:Path|None=None,
             probe_report_path:Path|None=None,boundary_profile_path:Path|None=None,
             allowed_system_skills:set[str]|None=None,allow_plugins:bool=False)->dict[str,Any]:
    for value,label in ((runner_job_path,"pre-execution runner job"),(runner_job_link_path,"runner-job-link artifact"),
                        (review_bundle_path,"evaluator review bundle"),(probe_report_path,"verified boundary probe report"),
                        (boundary_profile_path,"original boundary profile manifest")):
        if value is None: raise ValueError(f"analysis-ready result v4 requires the {label}")
    plan_path=plan_path.resolve();runner_job_path=runner_job_path.resolve();runner_job_link_path=runner_job_link_path.resolve()
    attestation_path=attestation_path.resolve();boundary_profile_path=boundary_profile_path.resolve();probe_report_path=probe_report_path.resolve()
    plan=_load(plan_path,"eval plan");job=_load(runner_job_path,"runner job");saved=_load(runner_job_link_path,"runner-job-link")
    _verify_job(job,plan,plan_path,ordinal)
    recomputed=bind_runner_job(runner_job_path=runner_job_path,boundary_profile_path=boundary_profile_path,
        probe_report_path=probe_report_path,attestation_path=attestation_path,
        allowed_system_skills=allowed_system_skills or set(),allow_plugins=allow_plugins)
    _verify_link(saved,recomputed,runner_job_path,attestation_path,plan_path)
    base=assemble_base(plan_path,ordinal,evaluator_case_path,attestation_path,semantic_review_path,gate_path,
        review_bundle_path=review_bundle_path,probe_report_path=probe_report_path,boundary_profile_path=boundary_profile_path,
        allowed_system_skills=allowed_system_skills or set(),allow_plugins=allow_plugins)
    if base.get("schema_version")!=2 or base.get("valid_for_analysis") is not True:
        raise ValueError("base evidence/review linkage did not produce a valid schema-v2 record")
    if base.get("run_id")!=saved.get("run_id"): raise ValueError("link run_id differs from evidence result")
    rjob=base.get("job",{})
    if rjob.get("case_id")!=saved.get("case_id") or rjob.get("condition")!=saved.get("condition_id"): raise ValueError("link case/condition differs from evidence result")
    versions=base.get("versions",{})
    if versions.get("model")!=saved.get("model") or versions.get("codex_cli")!=saved.get("codex_cli"): raise ValueError("link model/Codex versions differ from evidence result")
    result=deepcopy(base);result["schema_version"]=4
    result["authentication"]={
        "mode":"chatgpt-subscription","control_plane_auth_source":"codex-session",
        "api_key_auth_allowed":False,"candidate_auth_exposed":False}
    result["lineage"]={"runner_job_attestation_bound":True,"runner_job_link_verdict":saved["verdict"]}
    result["digests"].update({"runner_job_sha256":_sha(runner_job_path),"runner_job_link_sha256":_sha(runner_job_link_path)})
    checks={"eval_plan_sha256":saved["eval_plan_sha256"],"candidate_prompt_sha256":saved["candidate_prompt_sha256"],
            "runtime_sha256":saved["runtime_sha256"],"boundary_profile_sha256":saved["boundary_profile_sha256"],
            "probe_report_sha256":saved["probe_report_sha256"],"attestation_sha256":saved["runner_attestation_sha256"],
            "runner_job_sha256":saved["runner_job_sha256"]}
    for f,e in checks.items():
        if result["digests"].get(f)!=e: raise ValueError(f"schema-v4 result/link digest mismatch: {f}")
    result["scope"]="frozen plan -> subscription runner job -> isolated boundary -> subscription attestation/link -> evidence/review/gate; no API-key path and no causal skill-benefit claim"
    return result

def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan",type=Path,required=True);p.add_argument("--ordinal",type=int,required=True);p.add_argument("--evaluator-case",type=Path,required=True)
    p.add_argument("--runner-job",type=Path,required=True);p.add_argument("--runner-job-link",type=Path,required=True);p.add_argument("--attestation",type=Path,required=True)
    p.add_argument("--boundary-profile",type=Path,required=True);p.add_argument("--probe-report",type=Path,required=True);p.add_argument("--review-bundle",type=Path,required=True)
    p.add_argument("--semantic-review",type=Path,required=True);p.add_argument("--gate",type=Path,required=True);p.add_argument("--allowed-system-skill",action="append",default=[])
    p.add_argument("--allow-plugins",action="store_true");p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    try:
        r=assemble(a.plan,a.ordinal,a.evaluator_case,a.attestation,a.semantic_review,a.gate,runner_job_path=a.runner_job,
          runner_job_link_path=a.runner_job_link,review_bundle_path=a.review_bundle,probe_report_path=a.probe_report,
          boundary_profile_path=a.boundary_profile,allowed_system_skills=set(a.allowed_system_skill),allow_plugins=a.allow_plugins)
        if a.output.exists() or a.output.is_symlink(): raise FileExistsError(f"refusing to overwrite: {a.output}")
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    except (ValueError,OSError,UnicodeDecodeError,json.JSONDecodeError) as exc: p.exit(2,f"error: {exc}\n")
    print(json.dumps(r,ensure_ascii=False,indent=2));return 0
if __name__=="__main__": raise SystemExit(main())
