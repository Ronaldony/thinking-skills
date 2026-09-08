#!/usr/bin/env python3
"""Aggregate ChatGPT-subscription Feynman analysis records (schema v4 only)."""
from __future__ import annotations
import argparse,json,re
from copy import deepcopy
from pathlib import Path
from typing import Any,Iterable
try:
    from .feynman_eval_aggregate_v2_legacy import aggregate as aggregate_base
except ImportError:
    from feynman_eval_aggregate_v2_legacy import aggregate as aggregate_base
SHA=re.compile(r"^[0-9a-f]{64}$")
def _load(path:Path)->dict[str,Any]:
    if path.is_symlink() or not path.is_file(): raise ValueError(f"missing or unsafe JSON file: {path}")
    v=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise ValueError(f"JSON root must be object: {path}")
    return v
def _sha(v:Any)->bool: return isinstance(v,str) and SHA.fullmatch(v) is not None
def _validate(record:dict[str,Any])->tuple[str,str,bool]:
    if record.get("schema_version")!=4 or record.get("valid_for_analysis") is not True:
        raise ValueError("canonical aggregation requires analysis-ready result schema v4")
    d=record.get("digests")
    if not isinstance(d,dict): raise ValueError("schema-v4 result has no digests")
    for f in ("eval_plan_sha256","candidate_prompt_sha256","boundary_profile_sha256","probe_report_sha256","attestation_sha256","runner_job_sha256","runner_job_link_sha256"):
        if not _sha(d.get(f)): raise ValueError(f"schema-v4 result requires SHA-256 digest: {f}")
    lineage=record.get("lineage")
    if not isinstance(lineage,dict) or lineage.get("runner_job_attestation_bound") is not True or lineage.get("runner_job_link_verdict")!="runner-job-attestation-bound":
        raise ValueError("schema-v4 result lacks valid runner-job linkage")
    auth=record.get("authentication")
    if not isinstance(auth,dict): raise ValueError("schema-v4 result lacks authentication")
    if auth!={"mode":"chatgpt-subscription","control_plane_auth_source":"codex-session","api_key_auth_allowed":False,"candidate_auth_exposed":False}:
        raise ValueError("schema-v4 result must use the canonical ChatGPT-subscription auth profile")
    versions=record.get("versions")
    if not isinstance(versions,dict) or not all(isinstance(versions.get(f),str) and versions[f] for f in ("model","codex_cli")):
        raise ValueError("schema-v4 result model/Codex versions must be nonempty")
    return auth["mode"],auth["control_plane_auth_source"],auth["api_key_auth_allowed"]
def aggregate(plan:dict[str,Any],records:Iterable[dict[str,Any]])->dict[str,Any]:
    records=list(records);profiles=set();translated=[]
    for r in records:
        profiles.add(_validate(r));x=deepcopy(r);x["schema_version"]=2;translated.append(x)
    out=aggregate_base(plan,translated)
    consistency=out.setdefault("environment_consistency",{})
    consistency["authentication_profiles"]=[{"mode":m,"auth_source":s,"api_key_auth_allowed":a} for m,s,a in sorted(profiles)]
    consistency["single_authentication_profile"]=len(profiles)<=1
    if len(profiles)>1:
        out["status"]="mixed-environment";out["primary_comparison_ready"]=False
        reason="control-plane subscription authentication architecture differs across result records"
        if reason not in out.setdefault("blocking_reasons",[]): out["blocking_reasons"].append(reason)
    out["schema_version"]=3;out["accepted_result_schema_version"]=4
    out["scope"]="descriptive preregistered metrics over schema-v4 ChatGPT-subscription results; API-auth results are excluded from canonical aggregation"
    return out
def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--plan",type=Path,required=True);p.add_argument("--result",type=Path,action="append",default=[]);p.add_argument("--result-dir",type=Path);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    try:
        plan=_load(a.plan.resolve());paths=list(a.result)
        if a.result_dir: paths.extend(sorted(a.result_dir.glob("*.json")))
        if not paths: raise ValueError("at least one result is required")
        out=aggregate(plan,[_load(x.resolve()) for x in paths])
        if a.output.exists() or a.output.is_symlink(): raise FileExistsError(f"refusing to overwrite: {a.output}")
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    except (ValueError,OSError,json.JSONDecodeError) as exc: p.exit(2,f"error: {exc}\n")
    print(json.dumps(out,ensure_ascii=False,indent=2));return 0
if __name__=="__main__": raise SystemExit(main())
