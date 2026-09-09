from __future__ import annotations
from copy import deepcopy
import hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"tests"))
from tooling.codex_exec_evidence import extract
from tooling.feynman_apply_review import apply
from tooling.feynman_condition_workspace import prepare_condition
from tooling.feynman_eval_aggregate import aggregate
from tooling.feynman_eval_plan import build_plan,write_plan
from tooling.feynman_eval_result import assemble
from tooling.feynman_review_bundle import assemble as assemble_review_bundle
from tooling.feynman_runner_job_link import bind as bind_runner_job
from test_feynman_runner_attestation import attestation,boundary_report
from feynman_test_support import attach_native_mounts,use_native_profile
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
class EvalResultV4LinkageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.plan_path=self.base/"plan.json";self.plan=build_plan(ROOT,case_ids=["mechanism-01"],condition_ids=["baseline"],repeats=1,seed=0);write_plan(self.plan,self.plan_path);self.planned=self.plan["jobs"][0]
        self.candidate=self.base/"candidate";self.evaluator=self.base/"evaluator";prepare_condition(ROOT,"mechanism-01","baseline",self.candidate,self.evaluator)
        trace=self.base/"trace.jsonl";trace.write_text("\n".join([json.dumps({"type":"thread.started","thread_id":"thread-result-v4"}),
          json.dumps({"type":"item.completed","item":{"id":"msg-1","type":"agent_message","text":"Efficiency needs defined work, time, errors and cost before concluding."}})])+"\n",encoding="utf-8")
        self.evidence=self.base/"evidence";extract(trace,self.evidence);self.review_bundle=self.base/"review-bundle";assemble_review_bundle(self.evaluator,self.evidence,self.review_bundle)
        self.review_path=self.base/"review.json";self.review={"schema_version":2,"id":"mechanism-01","decision_correctness":"correct","decision_evidence":"Synthetic linked result.",
          "findings":[{"id":"F1","status":"supported","evidence":"synthetic"},{"id":"F2","status":"supported","evidence":"synthetic"}],
          "behaviors":{"mechanism":2,"honesty":2},"hard_failures":[],"execution_integrity":"clean","execution_integrity_evidence":"No unsupported claims.",
          "update_behavior":"not_applicable","executed_evidence_ids":[],"summary":"synthetic","confidence":"high"}
        self.review_path.write_text(json.dumps(self.review),encoding="utf-8");self.gate_path=self.base/"gate.json";apply(self.review_bundle,self.review_path,self.gate_path)
        if os.name == "nt":
            source_path=self.base/"source";source_path.mkdir()
            paths={"candidate_dir":str(self.candidate.resolve()),"evaluator_dir":str(self.evaluator.resolve()),"source_repo":str(source_path.resolve()),
              "ephemeral_home":str((self.base/"home").resolve()),"codex_home":str((self.base/"codex-home").resolve()),"temp_dir":str((self.base/"temp").resolve()),
              "real_home":str((self.base/"real-home").resolve()),"control_codex_home":str((self.base/"real-home"/".codex").resolve())}
            for key in ("ephemeral_home","codex_home","temp_dir","real_home","control_codex_home"):
                Path(paths[key]).mkdir(parents=True,exist_ok=True)
        else:
            paths={"candidate_dir":"/isolated/candidate","evaluator_dir":"/evaluator/run-1","source_repo":"/source/thinking-skills",
              "ephemeral_home":"/isolated/home","codex_home":"/isolated/codex-home","temp_dir":"/isolated/tmp",
              "real_home":"/home/real-user","control_codex_home":"/home/real-user/.codex"}
        self.profile={"schema_version":1,"backend":"docker","backend_version":"28.0.4","image":"python:3.12-slim","image_id":"sha256:"+"6"*64,
          "network_mode":"none","read_only_root":True,"no_new_privileges":True,"capabilities":[],"run_as":"1000:1000",
          "read_write_mounts":["/isolated/candidate","/isolated/home","/isolated/codex-home","/isolated/tmp"],"read_only_mounts":[],
          "tmpfs_mounts":["/tmp"],"protected_roots_mounted":[],"candidate_env_keys":["HOME","CODEX_HOME","PATH","TMPDIR"],"scope":"synthetic result v4 profile"}
        use_native_profile(self.profile,paths)
        self.profile_path=self.base/"profile.json";self.profile_path.write_text(json.dumps(self.profile,sort_keys=True),encoding="utf-8");self.profile_sha=sha(self.profile_path)
        self.attestation=attestation();self.attestation["paths"]=deepcopy(paths);self.attestation["boundary"].update({"backend":"docker","backend_version":"28.0.4","profile_sha256":self.profile_sha})
        if os.name == "nt":
            readable=[paths[x] for x in ("candidate_dir","ephemeral_home","codex_home","temp_dir")]
            forbidden=[paths[x] for x in ("evaluator_dir","source_repo","real_home")]
            self.attestation["filesystem"].update({"candidate_readable_data_roots":readable,"candidate_writable_roots":readable,
              "platform_runtime_roots":[r"C:\Windows\System32"],"forbidden_read_roots":forbidden,"forbidden_write_roots":forbidden})
        self.attestation["digests"]["eval_plan_sha256"]=sha(self.plan_path);self.attestation["digests"]["candidate_prompt_sha256"]=self.planned["candidate_prompt_sha256"]
        self.report=boundary_report(self.attestation);self.report_path=self.base/"report.json";self.report_path.write_text(json.dumps(self.report),encoding="utf-8")
        self.attestation["digests"]["probe_report_sha256"]=sha(self.report_path);self.attestation_path=self.base/"att.json";self.attestation_path.write_text(json.dumps(self.attestation),encoding="utf-8")
        self.runner_job={"schema_version":3,"run_id":self.attestation["run_id"],"job":{"ordinal":self.planned["ordinal"],"case_id":self.planned["case_id"],"condition_id":"baseline","repeat":1,"has_followup":False},
          "versions":deepcopy(self.attestation["versions"]),"paths":deepcopy(paths),"boundary":{"profile_sha256":self.profile_sha,"backend":"docker","backend_version":"28.0.4","network_mode":"none","candidate_env_keys":deepcopy(self.profile["candidate_env_keys"])},
          "network":deepcopy(self.attestation["network"]),"authentication":{"mode":"chatgpt-subscription","control_plane_auth_source":"codex-session","api_key_auth_allowed":False,
            "candidate_auth_exposed":False,"candidate_tool_auth_env_keys":[],"candidate_readable_auth_paths":[],"auth_command_arguments":[]},
          "skills":{"expected_candidate_skills":[],"runtime_sha256":None},"digests":{"eval_plan_sha256":sha(self.plan_path),"candidate_prompt_sha256":self.planned["candidate_prompt_sha256"],"boundary_profile_sha256":self.profile_sha,"runtime_sha256":None},"scope":"synthetic pre-run subscription job"}
        attach_native_mounts(self.runner_job,paths)
        self.job_path=self.base/"job.json";self._write_job_and_link()
    def tearDown(self):self.tmp.cleanup()
    def _write_job_and_link(self):
        self.job_path.write_text(json.dumps(self.runner_job),encoding="utf-8")
        link=bind_runner_job(runner_job_path=self.job_path,boundary_profile_path=self.profile_path,probe_report_path=self.report_path,attestation_path=self.attestation_path)
        self.link_path=self.base/"link.json";self.link_path.write_text(json.dumps(link),encoding="utf-8");self.link=link
    def _assemble(self):
        return assemble(self.plan_path,1,self.evaluator/"case.json",self.attestation_path,self.review_path,self.gate_path,
          runner_job_path=self.job_path,runner_job_link_path=self.link_path,review_bundle_path=self.review_bundle,
          probe_report_path=self.report_path,boundary_profile_path=self.profile_path)
    def test_subscription_result_is_schema_v4(self):
        r=self._assemble();self.assertEqual(r["schema_version"],4);self.assertTrue(r["valid_for_analysis"])
        self.assertEqual(r["authentication"],{"mode":"chatgpt-subscription","control_plane_auth_source":"codex-session","api_key_auth_allowed":False,"candidate_auth_exposed":False})
        self.assertEqual(r["digests"]["runner_job_sha256"],sha(self.job_path));self.assertEqual(r["digests"]["runner_job_link_sha256"],sha(self.link_path))
    def test_tampered_link_rejected(self):
        x=deepcopy(self.link);x["runner_job_sha256"]="f"*64;self.link_path.write_text(json.dumps(x),encoding="utf-8")
        with self.assertRaises(ValueError):self._assemble()
    def test_ordinal_drift_rejected(self):
        self.runner_job["job"]["ordinal"]=2;self._write_job_and_link()
        with self.assertRaises(ValueError):self._assemble()
    def test_attestation_change_after_link_rejected(self):
        self.attestation["versions"]["model"]="other";self.attestation_path.write_text(json.dumps(self.attestation),encoding="utf-8")
        with self.assertRaises(ValueError):self._assemble()
    def test_runner_job_mandatory(self):
        with self.assertRaises(ValueError):
            assemble(self.plan_path,1,self.evaluator/"case.json",self.attestation_path,self.review_path,self.gate_path,
              runner_job_link_path=self.link_path,review_bundle_path=self.review_bundle,probe_report_path=self.report_path,boundary_profile_path=self.profile_path)
class EvalAggregateV4Tests(unittest.TestCase):
    G="1"*64;F="2"*64;R="3"*64
    def _plan(self):return {"conditions":["generic","feynman-v05"],"jobs":[
      {"ordinal":1,"case_id":"case-1","condition":"generic","repeat":1,"has_followup":False,"candidate_prompt_sha256":self.G},
      {"ordinal":2,"case_id":"case-1","condition":"feynman-v05","repeat":1,"has_followup":False,"candidate_prompt_sha256":self.F}]}
    def _record(self,condition,decision="correct",supported=2,critical=False,execution="clean",model="m",cli="c",profile="a"*64,runtime_sha=None,ordinal=None):
        if ordinal is None:ordinal=1 if condition=="generic" else 2
        prompt=self.G if condition=="generic" else self.F
        if condition=="feynman-v05" and runtime_sha is None:runtime_sha=self.R
        if condition in {"baseline","generic"}:runtime_sha=None
        gate="unverified" if decision=="unverified" or execution=="unverified" else "failed" if critical or decision!="correct" or execution=="failure" else "passed"
        return {"schema_version":4,"valid_for_analysis":True,"run_id":f"run-{condition}","job":{"ordinal":ordinal,"case_id":"case-1","condition":condition,"repeat":1,"phase":"initial"},
          "versions":{"model":model,"codex_cli":cli},"runner":{"backend":"docker","backend_version":"1","profile_sha256":profile,"image":"img","image_id":"sha256:"+"6"*64,"network_mode":"none"},
          "authentication":{"mode":"chatgpt-subscription","control_plane_auth_source":"codex-session","api_key_auth_allowed":False,"candidate_auth_exposed":False},
          "lineage":{"runner_job_attestation_bound":True,"runner_job_link_verdict":"runner-job-attestation-bound"},
          "conversation":{"thread_id":None,"initial_source_trace_sha256":None,"followup_source_trace_sha256":None},
          "digests":{"eval_plan_sha256":"4"*64,"candidate_prompt_sha256":prompt,"runtime_sha256":runtime_sha,"boundary_profile_sha256":profile,
            "probe_report_sha256":"5"*64,"attestation_sha256":"6"*64,"runner_job_sha256":"7"*64,"runner_job_link_sha256":"8"*64},
          "metrics":{"decision_correctness":decision,"required_findings_supported":supported,"required_findings_total":2,"required_finding_completion":supported/2,
            "critical_failure":critical,"hard_failure_ids":["H1"] if critical else [],"execution_integrity":execution,"update_behavior":"not_applicable",
            "behavior_scores":{"honesty":2},"gate_verdict":gate,"review_confidence":"high"},"limitations":[]}
    def test_complete_pair(self):
        g=self._record("generic",decision="partial",supported=1);g["metrics"]["gate_verdict"]="failed";f=self._record("feynman-v05")
        r=aggregate(self._plan(),[g,f]);self.assertEqual(r["status"],"analysis-ready");self.assertEqual(r["accepted_result_schema_version"],4)
    def test_schema_v3_rejected(self):
        r=self._record("generic");r["schema_version"]=3
        with self.assertRaises(ValueError):aggregate({"conditions":["generic"],"jobs":[self._plan()["jobs"][0]]},[r])
    def test_api_auth_result_rejected(self):
        r=self._record("generic");r["authentication"]={"mode":"control-plane-only","control_plane_credential_source":"environment","candidate_auth_exposed":False}
        with self.assertRaises(ValueError):aggregate({"conditions":["generic"],"jobs":[self._plan()["jobs"][0]]},[r])
    def test_candidate_auth_exposure_rejected(self):
        r=self._record("generic");r["authentication"]["candidate_auth_exposed"]=True
        with self.assertRaises(ValueError):aggregate({"conditions":["generic"],"jobs":[self._plan()["jobs"][0]]},[r])
    def test_missing_result_reported(self):
        r=aggregate(self._plan(),[self._record("generic")]);self.assertEqual(r["status"],"incomplete")
    def test_mixed_model_blocks(self):
        r=aggregate(self._plan(),[self._record("generic",model="a"),self._record("feynman-v05",model="b")]);self.assertEqual(r["status"],"mixed-environment")
    def test_prompt_drift_rejected(self):
        r=self._record("generic");r["digests"]["candidate_prompt_sha256"]="f"*64
        with self.assertRaises(ValueError):aggregate({"conditions":["generic"],"jobs":[self._plan()["jobs"][0]]},[r])
    def test_skill_runtime_required(self):
        r=self._record("feynman-v05");r["digests"]["runtime_sha256"]=None
        with self.assertRaises(ValueError):aggregate({"conditions":["feynman-v05"],"jobs":[self._plan()["jobs"][1]]},[r])
if __name__=="__main__":unittest.main()
