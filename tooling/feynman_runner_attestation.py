#!/usr/bin/env python3
"""Validate structural invariants of a ChatGPT-subscription runner attestation.

Schema v3 records only the authentication architecture, never ChatGPT session
contents. The host control Codex uses a protected authenticated session; candidate
tools receive no auth environment variables, auth paths, or auth arguments.
"""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from typing import Any
try:
    from .feynman_boundary_probe_verify import validate_report as validate_boundary_report
except ImportError:
    from feynman_boundary_probe_verify import validate_report as validate_boundary_report

SECRET_KEY_PATTERN=re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE|AUTH|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)",
    re.IGNORECASE)
ENV_KEY_PATTERN=re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SKILL_CONDITIONS={"legacy-clean","feynman-v05"}; NO_SKILL_CONDITIONS={"baseline","generic"}
REQUIRED_PROBES={"candidate_read","evaluator_read_denied","source_read_denied","real_home_read_denied",
                 "candidate_write","forbidden_write_denied","ambient_skill_preflight","secret_env_scan"}
BOUNDARY_REPORT_PROBES={"candidate_read","evaluator_read_denied","source_read_denied","real_home_read_denied",
                       "candidate_write","forbidden_write_denied","secret_env_scan","tool_network_denied"}

def _object(v:Any,label:str)->dict[str,Any]:
    if not isinstance(v,dict): raise ValueError(f"{label} must be an object")
    return v
def _strings(v:Any,label:str)->list[str]:
    if not isinstance(v,list) or not all(isinstance(x,str) and x for x in v): raise ValueError(f"{label} must be a list of nonempty strings")
    if len(set(v))!=len(v): raise ValueError(f"{label} must not contain duplicates")
    return v
def _absolute(v:Any,label:str)->Path:
    if not isinstance(v,str) or not v or not Path(v).is_absolute(): raise ValueError(f"{label} must be a nonempty absolute path")
    return Path(v).resolve(strict=False)
def _contains(root:Path,path:Path)->bool: return path==root or path.is_relative_to(root)
def _overlap(a:Path,b:Path)->bool: return _contains(a,b) or _contains(b,a)
def _sha(v:Any,label:str)->str:
    if not isinstance(v,str) or re.fullmatch(r"[0-9a-f]{64}",v) is None: raise ValueError(f"{label} must be SHA-256")
    return v
def _probe(probes:dict[str,Any],name:str)->None:
    p=_object(probes.get(name),f"probe {name}")
    if p.get("passed") is not True: raise ValueError(f"required probe did not pass: {name}")
    _sha(p.get("artifact_sha256"),f"probe {name}.artifact_sha256")
    if not isinstance(p.get("method"),str) or not p["method"].strip(): raise ValueError(f"probe {name} has no method")

def _bind_report(att:dict[str,Any],report:dict[str,Any],report_sha:str,env_keys:list[str],probes:dict[str,Any])->None:
    validate_boundary_report(report)
    if report_sha!=_object(att.get("digests"),"digests").get("probe_report_sha256"): raise ValueError("boundary probe report bytes do not match attestation digest")
    if report.get("run_id")!=att.get("run_id"): raise ValueError("boundary probe report run_id mismatch")
    boundary=_object(att.get("boundary"),"boundary")
    if report.get("boundary_profile_sha256")!=boundary.get("profile_sha256"): raise ValueError("boundary probe report profile digest differs from attestation")
    if report.get("verdict")!="passed": raise ValueError("boundary probe report is not fully passed")
    rp=_object(report.get("probes"),"boundary probe report.probes")
    if set(rp)!=BOUNDARY_REPORT_PROBES: raise ValueError("boundary probe report has missing or unexpected probe IDs")
    for name in BOUNDARY_REPORT_PROBES:
        if _object(rp.get(name),f"boundary report {name}")!=probes.get(name): raise ValueError(f"attestation probe differs from verified boundary report: {name}")
    if sorted(report.get("observed_env_keys",[]))!=sorted(env_keys): raise ValueError("attested candidate environment keys differ from boundary probe observation")
    requires=_object(att.get("network"),"network").get("case_requires_tool_network")
    nr=set(report.get("not_required_probes",[]))
    if requires:
        if "tool_network_denied" not in nr: raise ValueError("network-required case must mark tool_network_denied not-required")
    else:
        if nr: raise ValueError("closed-network case may not mark required probes not-required")
        if report.get("network_reference_sha256") is None: raise ValueError("closed-network report requires control-plane network reference")

def validate(attestation:dict[str,Any],*,allow_plugins:bool=False,allowed_system_skills:set[str]|None=None,
             probe_report:dict[str,Any]|None=None,probe_report_sha256:str|None=None)->dict[str,Any]:
    allowed_system_skills=allowed_system_skills or set()
    if attestation.get("schema_version")!=3: raise ValueError("unsupported schema_version; expected runner attestation v3")
    condition=attestation.get("condition_id")
    if condition not in SKILL_CONDITIONS|NO_SKILL_CONDITIONS: raise ValueError("unsupported condition_id")
    boundary=_object(attestation.get("boundary"),"boundary")
    if boundary.get("external_enforcement") is not True: raise ValueError("external_enforcement must be true")
    for f in ("backend","backend_version","platform","kernel"):
        if not isinstance(boundary.get(f),str) or not boundary[f].strip(): raise ValueError(f"boundary.{f} must be nonempty")
    _sha(boundary.get("profile_sha256"),"boundary.profile_sha256")
    paths=_object(attestation.get("paths"),"paths")
    p={n:_absolute(paths.get(n),f"paths.{n}") for n in ("candidate_dir","evaluator_dir","source_repo","ephemeral_home","codex_home","temp_dir","real_home","control_codex_home")}
    protected=[p["evaluator_dir"],p["source_repo"],p["real_home"],p["control_codex_home"]]
    owned=[p["candidate_dir"],p["ephemeral_home"],p["codex_home"],p["temp_dir"]]
    for a in protected:
        for b in owned:
            if _overlap(a,b): raise ValueError("protected path overlaps candidate-owned path")

    fs=_object(attestation.get("filesystem"),"filesystem")
    readable=[_absolute(x,"candidate_readable_data_roots[]") for x in _strings(fs.get("candidate_readable_data_roots"),"candidate_readable_data_roots")]
    writable=[_absolute(x,"candidate_writable_roots[]") for x in _strings(fs.get("candidate_writable_roots"),"candidate_writable_roots")]
    platform=[_absolute(x,"platform_runtime_roots[]") for x in _strings(fs.get("platform_runtime_roots"),"platform_runtime_roots")]
    fr=[_absolute(x,"forbidden_read_roots[]") for x in _strings(fs.get("forbidden_read_roots"),"forbidden_read_roots")]
    fw=[_absolute(x,"forbidden_write_roots[]") for x in _strings(fs.get("forbidden_write_roots"),"forbidden_write_roots")]
    if not all(any(_contains(root,t) for root in fr) for t in protected): raise ValueError("forbidden_read_roots must cover protected roots including control_codex_home")
    if not all(any(_contains(root,t) for root in fw) for t in protected): raise ValueError("forbidden_write_roots must cover protected roots including control_codex_home")
    for root in readable+writable:
        if not any(_contains(anchor,root) for anchor in owned): raise ValueError("candidate data root outside candidate-owned anchors")
    for exposed in readable+writable+platform:
        for target in protected:
            if _overlap(exposed,target): raise ValueError("exposed root overlaps protected path")
    for root in platform:
        if root==Path(root.anchor): raise ValueError("platform runtime root may not expose filesystem root")

    net=_object(attestation.get("network"),"network"); requires=net.get("case_requires_tool_network")
    if type(requires) is not bool: raise ValueError("case_requires_tool_network must be boolean")
    tool=net.get("tool_network"); dest=_strings(net.get("allowed_tool_destinations"),"allowed_tool_destinations")
    if tool not in {"blocked","restricted","open"}: raise ValueError("invalid tool_network")
    if net.get("control_plane_separate_from_tool_network") is not True: raise ValueError("runner attestation requires control-plane/tool-network separation")
    if tool=="blocked" and dest: raise ValueError("blocked tool network must not declare destinations")
    if not requires and tool!="blocked": raise ValueError("closed-network case requires tool_network=blocked")

    env=_object(attestation.get("environment"),"environment"); env_keys=_strings(env.get("candidate_env_keys"),"candidate_env_keys")
    if not all(ENV_KEY_PATTERN.fullmatch(k) for k in env_keys): raise ValueError("candidate environment contains invalid variable name")
    secretish=sorted(k for k in env_keys if SECRET_KEY_PATTERN.search(k))
    if secretish: raise ValueError("candidate tool environment exposes secret-like variable names: "+", ".join(secretish))
    expected_auth={
        "candidate_auth_exposed":False,
        "control_plane_auth_mode":"chatgpt-subscription",
        "control_plane_auth_source":"codex-session",
        "api_key_auth_allowed":False,
        "candidate_tool_auth_env_keys":[],
        "candidate_readable_auth_paths":[],
        "auth_command_arguments":[],
    }
    for k,v in expected_auth.items():
        if env.get(k)!=v: raise ValueError(f"invalid subscription authentication field: {k}")
    if env.get("plugins_enabled") is not False and not allow_plugins: raise ValueError("plugins must be disabled unless explicitly allowed")
    system=set(_strings(env.get("system_skills"),"system_skills"))
    if system!=allowed_system_skills: raise ValueError("system skill set mismatch")
    expected=set(_strings(env.get("expected_candidate_skills"),"expected_candidate_skills"))
    observed=set(_strings(env.get("observed_candidate_skills"),"observed_candidate_skills"))
    if expected!=observed: raise ValueError("expected/observed candidate skill sets differ")
    required={"feynman-thinking"} if condition in SKILL_CONDITIONS else set()
    if expected!=required: raise ValueError("condition requires different candidate skill set")

    probes=_object(attestation.get("probes"),"probes")
    for name in REQUIRED_PROBES: _probe(probes,name)
    if not requires: _probe(probes,"tool_network_denied")
    versions=_object(attestation.get("versions"),"versions")
    for f in ("codex_cli","model"):
        if not isinstance(versions.get(f),str) or not versions[f].strip(): raise ValueError(f"versions.{f} must be nonempty")
    dig=_object(attestation.get("digests"),"digests")
    for f in ("eval_plan_sha256","candidate_prompt_sha256","probe_report_sha256"): _sha(dig.get(f),f"digests.{f}")
    runtime=dig.get("runtime_sha256")
    if condition in SKILL_CONDITIONS: _sha(runtime,"digests.runtime_sha256")
    elif runtime is not None: raise ValueError("no-skill condition must use runtime_sha256=null")
    if (probe_report is None)!=(probe_report_sha256 is None): raise ValueError("probe_report and digest must be supplied together")
    if probe_report is not None:
        _sha(probe_report_sha256,"probe_report_sha256"); _bind_report(attestation,probe_report,probe_report_sha256,env_keys,probes)
    lim=attestation.get("limitations")
    if not isinstance(lim,list) or not all(isinstance(x,str) for x in lim): raise ValueError("limitations must be a list of strings")
    return {"verdict":"contract-valid","run_id":attestation.get("run_id"),"case_id":attestation.get("case_id"),
            "condition_id":condition,"backend":boundary["backend"],"profile_sha256":boundary["profile_sha256"],
            "authentication_mode":"chatgpt-subscription","control_plane_auth_source":"codex-session",
            "api_key_auth_allowed":False,"candidate_auth_exposed":False,"probe_report_bound":probe_report is not None,
            "scope":"subscription attestation consistency; no ChatGPT session/token contents are inspected or preserved"}

def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--attestation",type=Path,required=True);p.add_argument("--probe-report",type=Path)
    p.add_argument("--allow-plugins",action="store_true");p.add_argument("--allowed-system-skill",action="append",default=[]);a=p.parse_args()
    try:
        value=json.loads(a.attestation.read_text(encoding="utf-8")); report=None; report_sha=None
        if not isinstance(value,dict): raise ValueError("attestation root must be object")
        if a.probe_report:
            report=json.loads(a.probe_report.read_text(encoding="utf-8")); report_sha=hashlib.sha256(a.probe_report.read_bytes()).hexdigest()
        result=validate(value,allow_plugins=a.allow_plugins,allowed_system_skills=set(a.allowed_system_skill),probe_report=report,probe_report_sha256=report_sha)
    except (ValueError,OSError,json.JSONDecodeError) as exc: p.exit(2,f"error: {exc}\n")
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0
if __name__=="__main__": raise SystemExit(main())
