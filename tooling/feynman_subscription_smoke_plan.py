#!/usr/bin/env python3
"""Build the frozen two-job ChatGPT-subscription Codex integration smoke plan."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from typing import Any
try:
    from .feynman_eval_plan import build_plan,write_plan
except ImportError:
    from feynman_eval_plan import build_plan,write_plan

EXPECTED_PURPOSE="integration-only-chatgpt-subscription-smoke"
EXPECTED_ANALYSIS_USE="not-for-skill-performance-inference"
EXPECTED_CASES=["tools-10"];EXPECTED_CONDITIONS=["baseline","feynman-v05"];EXPECTED_REPEATS=1;EXPECTED_SEED=20260908

def _load(path:Path)->dict[str,Any]:
    path=path.resolve()
    if path.is_symlink() or not path.is_file(): raise ValueError(f"missing or unsafe smoke spec: {path}")
    v=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise ValueError("smoke spec JSON root must be object")
    return v
def _sha(path:Path)->str: return hashlib.sha256(path.resolve().read_bytes()).hexdigest()
def validate_spec(spec:dict[str,Any])->None:
    expected={"schema_version":1,"purpose":EXPECTED_PURPOSE,"analysis_use":EXPECTED_ANALYSIS_USE,
      "cases":EXPECTED_CASES,"conditions":EXPECTED_CONDITIONS,"repeats":EXPECTED_REPEATS,"seed":EXPECTED_SEED,
      "authentication_mode":"chatgpt-subscription","control_plane_auth_source":"codex-session",
      "api_key_auth_allowed":False,"requires_trusted_local_or_self_hosted_control_plane":True}
    for f,v in expected.items():
        if spec.get(f)!=v: raise ValueError(f"smoke spec violates frozen subscription integration contract: {f}")
    for field,minlen in (("required_success_evidence",5),("prohibited_claims",3)):
        value=spec.get(field)
        if not isinstance(value,list) or len(value)<minlen or not all(isinstance(x,str) and x for x in value):
            raise ValueError(f"smoke spec must enumerate {field}")
    if not isinstance(spec.get("scope"),str) or not spec["scope"]: raise ValueError("smoke spec scope must be nonempty")
def build_smoke_plan(repo_root:Path,spec_path:Path)->dict[str,Any]:
    spec_path=spec_path.resolve();spec=_load(spec_path);validate_spec(spec)
    plan=build_plan(repo_root,case_ids=list(spec["cases"]),condition_ids=list(spec["conditions"]),repeats=spec["repeats"],seed=spec["seed"])
    if len(plan.get("jobs",[]))!=2: raise ValueError("subscription integration smoke must produce exactly two jobs")
    if {j.get("condition") for j in plan["jobs"]}!=set(EXPECTED_CONDITIONS): raise ValueError("smoke plan condition drift")
    if {j.get("case_id") for j in plan["jobs"]}!=set(EXPECTED_CASES): raise ValueError("smoke plan case drift")
    plan["smoke_spec_sha256"]=_sha(spec_path);plan["analysis_use"]=EXPECTED_ANALYSIS_USE
    plan["authentication_mode"]="chatgpt-subscription";plan["api_key_auth_allowed"]=False
    plan["required_success_evidence"]=list(spec["required_success_evidence"]);plan["prohibited_claims"]=list(spec["prohibited_claims"])
    plan["scope"]="public-development ChatGPT-subscription integration smoke; plumbing validation only, not skill-effect estimation"
    return plan
def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument("--spec",type=Path,default=Path(__file__).resolve().parents[1]/"evals"/"feynman-thinking"/"subscription-smoke-spec.json")
    p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    try: plan=build_smoke_plan(a.root.resolve(),a.spec.resolve());write_plan(plan,a.output)
    except (ValueError,OSError,UnicodeDecodeError,json.JSONDecodeError) as exc: p.exit(2,f"error: {exc}\n")
    print(json.dumps({"status":plan["status"],"purpose":EXPECTED_PURPOSE,"analysis_use":plan["analysis_use"],
      "jobs":[{"ordinal":j["ordinal"],"case_id":j["case_id"],"condition":j["condition"]} for j in plan["jobs"]],
      "smoke_spec_sha256":plan["smoke_spec_sha256"]},ensure_ascii=False,indent=2));return 0
if __name__=="__main__": raise SystemExit(main())
