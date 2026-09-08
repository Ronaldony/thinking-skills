#!/usr/bin/env python3
"""Validate a frozen job up to a trusted local ChatGPT-session execution boundary.

The preflight never reads files inside control_codex_home and never calls a model.
Success means the runner/profile/workspace are safe to hand to a locally or
self-hosted Codex process whose ChatGPT login state is established out-of-band.
"""
from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path
from typing import Any
try:
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_eval_preflight import preflight as skill_preflight
    from .feynman_remote_exec_environment import validate_files as validate_remote_environment
    from .feynman_runner_job_validate import _load as load_job_json,validate_job_files
except ImportError:
    from feynman_boundary_profile import validate_profile_file
    from feynman_eval_preflight import preflight as skill_preflight
    from feynman_remote_exec_environment import validate_files as validate_remote_environment
    from feynman_runner_job_validate import _load as load_job_json,validate_job_files
SHA=re.compile(r"^[0-9a-f]{64}$");PRIMARY={"baseline","generic","legacy-clean","feynman-v05"}

def _no_symlink(path:Path,label:str)->Path:
    a=path.expanduser().absolute();parts=a.parts
    if not parts: raise ValueError(f"{label} path is empty")
    cur=Path(parts[0])
    for part in parts[1:]:
        cur=cur/part
        if cur.is_symlink(): raise ValueError(f"{label} path contains symlink component: {cur}")
    return a

def _regular(path:Path,label:str)->Path:
    a=_no_symlink(path,label)
    if not a.is_file(): raise ValueError(f"{label} must be a regular file: {a}")
    return a.resolve()

def _directory(path:Path,label:str)->Path:
    a=_no_symlink(path,label)
    if not a.is_dir(): raise ValueError(f"{label} must be a real directory: {a}")
    return a.resolve()

def _load(path:Path,label:str)->dict[str,Any]:
    p=_regular(path,label);v=json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise ValueError(f"{label} JSON root must be object")
    return v

def _sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()

def _planned(plan:dict[str,Any],ordinal:int)->dict[str,Any]:
    jobs=plan.get("jobs")
    if not isinstance(jobs,list): raise ValueError("eval plan has no jobs list")
    m=[j for j in jobs if isinstance(j,dict) and j.get("ordinal")==ordinal]
    if len(m)!=1: raise ValueError(f"eval plan must contain exactly one job with ordinal {ordinal}")
    return m[0]

def preflight_files(*,plan_path:Path,ordinal:int,evaluator_case_path:Path,runner_job_path:Path,
                    boundary_profile_path:Path,remote_environment_path:Path)->dict[str,Any]:
    plan_path=_regular(plan_path,"eval plan");evaluator_case_path=_regular(evaluator_case_path,"evaluator case")
    runner_job_path=_regular(runner_job_path,"runner job");boundary_profile_path=_regular(boundary_profile_path,"boundary profile")
    remote_environment_path=_regular(remote_environment_path,"remote environment")
    job=load_job_json(runner_job_path)
    if job.get("schema_version")!=3: raise ValueError("subscription preflight requires runner-job schema v3")
    valid=validate_job_files(runner_job_path,boundary_profile_path)
    if valid.get("verdict")!="runner-job-valid": raise ValueError("runner job failed strict validation")
    plan=_load(plan_path,"eval plan");planned=_planned(plan,ordinal);info=job["job"];dig=job["digests"]
    expected={"ordinal":planned.get("ordinal"),"case_id":planned.get("case_id"),"condition_id":planned.get("condition"),
              "repeat":planned.get("repeat"),"has_followup":planned.get("has_followup")}
    for f,v in expected.items():
        if info.get(f)!=v: raise ValueError(f"runner job differs from frozen plan field: {f}")
    if info.get("condition_id") not in PRIMARY: raise ValueError("unsupported condition")
    if dig.get("eval_plan_sha256")!=_sha(plan_path): raise ValueError("runner job does not bind eval-plan bytes")
    if not isinstance(planned.get("candidate_prompt_sha256"),str) or SHA.fullmatch(planned["candidate_prompt_sha256"]) is None:
        raise ValueError("frozen plan prompt digest invalid")
    if dig.get("candidate_prompt_sha256")!=planned["candidate_prompt_sha256"]: raise ValueError("runner job prompt digest differs from plan")

    ev=_load(evaluator_case_path,"evaluator case")
    if ev.get("case_id")!=info["case_id"] or ev.get("condition_id")!=info["condition_id"]: raise ValueError("evaluator case differs from runner job")
    if ev.get("candidate_prompt_sha256")!=planned["candidate_prompt_sha256"]: raise ValueError("evaluator prompt digest differs from plan")
    if ev.get("expected_skills")!=job.get("skills",{}).get("expected_candidate_skills"): raise ValueError("evaluator expected skills differ from runner job")

    paths=job["paths"];candidate=_directory(Path(paths["candidate_dir"]),"candidate directory")
    task=_regular(candidate/"task.txt","candidate task");task_sha=_sha(task)
    if task_sha!=dig["candidate_prompt_sha256"]: raise ValueError("candidate task bytes differ from frozen prompt")
    _directory(Path(paths["control_codex_home"]),"control CODEX_HOME")
    _directory(Path(paths["real_home"]),"real home")

    profile,profile_sha,_=validate_profile_file(boundary_profile_path)
    if job["boundary"]["profile_sha256"]!=profile_sha: raise ValueError("runner job boundary profile digest drift")
    remote=validate_remote_environment(runner_job_path,boundary_profile_path,remote_environment_path)
    if remote.get("verdict")!="remote-exec-environment-valid": raise ValueError("remote environment failed validation")
    expected_skills=set(job.get("skills",{}).get("expected_candidate_skills",[]))
    skill=skill_preflight(Path(paths["candidate_dir"]),expected_skills,home=Path(paths["ephemeral_home"]),codex_home=Path(paths["codex_home"]))

    auth=job["authentication"]
    if auth!={"mode":"chatgpt-subscription","control_plane_auth_source":"codex-session","api_key_auth_allowed":False,
             "candidate_auth_exposed":False,"candidate_tool_auth_env_keys":[],"candidate_readable_auth_paths":[],"auth_command_arguments":[]}:
        raise ValueError("runner job does not use canonical subscription auth")

    return {
      "schema_version":1,"verdict":"ready-for-local-chatgpt-session-check","run_id":job["run_id"],
      "job":{"ordinal":info["ordinal"],"case_id":info["case_id"],"condition_id":info["condition_id"],"repeat":info["repeat"],"has_followup":info["has_followup"]},
      "versions":dict(job["versions"]),
      "authentication":{"mode":"chatgpt-subscription","auth_source":"codex-session","api_key_auth_allowed":False,
                        "candidate_auth_exposed":False,"control_session_contents_read_by_preflight":False},
      "digests":{"eval_plan_sha256":_sha(plan_path),"evaluator_case_sha256":_sha(evaluator_case_path),
                 "runner_job_sha256":_sha(runner_job_path),"boundary_profile_sha256":profile_sha,
                 "remote_environment_sha256":_sha(remote_environment_path),"candidate_task_sha256":task_sha},
      "preflight":{"runner_job_valid":True,"frozen_plan_job_match":True,"candidate_task_bytes_match":True,
                   "boundary_profile_valid":True,"remote_environment_valid":True,"candidate_skill_preflight_valid":True,
                   "control_codex_home_protected":True,"expected_candidate_skills":sorted(expected_skills),
                   "system_skill_roots_observed":skill["system_skill_roots_observed"]},
      "required_local_action":{"kind":"interactive-or-existing-chatgpt-codex-session",
          "instruction":"On the trusted local/self-hosted control plane, ensure Codex is signed in with the intended ChatGPT subscription. Do not copy control CODEX_HOME into candidate mounts or artifacts.",
          "api_key_not_permitted":True},
      "next_required_evidence":["successful subscription-authenticated control Codex model turn","same-profile boundary canary/report",
          "post-run runner attestation schema v3","recomputed runner-job-link schema v3","analysis-result schema v4 after review/gate"],
      "scope":"structural readiness only; no control-session token read, no model request, no behavior result"
    }

def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan",type=Path,required=True);p.add_argument("--ordinal",type=int,required=True);p.add_argument("--evaluator-case",type=Path,required=True)
    p.add_argument("--runner-job",type=Path,required=True);p.add_argument("--boundary-profile",type=Path,required=True);p.add_argument("--remote-environment",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    try:
        r=preflight_files(plan_path=a.plan,ordinal=a.ordinal,evaluator_case_path=a.evaluator_case,runner_job_path=a.runner_job,
                          boundary_profile_path=a.boundary_profile,remote_environment_path=a.remote_environment)
        if a.output.exists() or a.output.is_symlink(): raise FileExistsError(f"refusing to overwrite: {a.output}")
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    except (ValueError,OSError,UnicodeDecodeError,json.JSONDecodeError) as exc: p.exit(2,f"error: {exc}\n")
    print(json.dumps(r,ensure_ascii=False,indent=2));return 0
if __name__=="__main__": raise SystemExit(main())
