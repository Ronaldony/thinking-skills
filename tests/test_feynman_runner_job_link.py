from __future__ import annotations
from copy import deepcopy
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"tests"))
from tooling.feynman_runner_job_link import bind
from test_feynman_runner_attestation import attestation,boundary_report
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
class RunnerJobLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();b=Path(self.tmp.name)
        paths={"candidate_dir":str((b/"candidate").resolve()),"evaluator_dir":str((b/"eval").resolve()),"source_repo":str((b/"source").resolve()),
          "ephemeral_home":str((b/"home").resolve()),"codex_home":str((b/"tool-codex").resolve()),"temp_dir":str((b/"tmp").resolve()),
          "real_home":str((b/"real").resolve()),"control_codex_home":str((b/"real"/".codex").resolve())}
        self.profile={"schema_version":1,"backend":"docker","backend_version":"1","image":"img","image_id":"sha256:"+"6"*64,"network_mode":"none",
          "read_only_root":True,"no_new_privileges":True,"capabilities":[],"run_as":"1000:1000",
          "read_write_mounts":[paths[x] for x in ("candidate_dir","ephemeral_home","codex_home","temp_dir")],"read_only_mounts":[],
          "tmpfs_mounts":["/tmp"],"protected_roots_mounted":[],"candidate_env_keys":["HOME","CODEX_HOME","PATH","TMPDIR"],"scope":"test"}
        self.pp=b/"profile.json";self.pp.write_text(json.dumps(self.profile,sort_keys=True),encoding="utf-8");ps=sha(self.pp)
        self.att=attestation();self.att["paths"]=deepcopy(paths);self.att["boundary"].update({"backend":"docker","backend_version":"1","profile_sha256":ps})
        self.att["filesystem"]={
          "candidate_readable_data_roots":[paths[x] for x in ("candidate_dir","ephemeral_home","codex_home","temp_dir")],
          "candidate_writable_roots":[paths[x] for x in ("candidate_dir","ephemeral_home","codex_home","temp_dir")],
          "platform_runtime_roots":["/usr","/lib"],
          "forbidden_read_roots":[paths["evaluator_dir"],paths["source_repo"],paths["real_home"]],
          "forbidden_write_roots":[paths["evaluator_dir"],paths["source_repo"],paths["real_home"]],
        }
        self.report=boundary_report(self.att);self.rp=b/"report.json";self.rp.write_text(json.dumps(self.report),encoding="utf-8")
        self.att["digests"]["probe_report_sha256"]=sha(self.rp);self.ap=b/"att.json";self.ap.write_text(json.dumps(self.att),encoding="utf-8")
        self.job={"schema_version":3,"run_id":self.att["run_id"],"job":{"ordinal":1,"case_id":self.att["case_id"],"condition_id":"baseline","repeat":1,"has_followup":False},
          "versions":deepcopy(self.att["versions"]),"paths":deepcopy(paths),"boundary":{"profile_sha256":ps,"backend":"docker","backend_version":"1","network_mode":"none","candidate_env_keys":deepcopy(self.profile["candidate_env_keys"])},
          "network":deepcopy(self.att["network"]),"authentication":{"mode":"chatgpt-subscription","control_plane_auth_source":"codex-session","api_key_auth_allowed":False,
          "candidate_auth_exposed":False,"candidate_tool_auth_env_keys":[],"candidate_readable_auth_paths":[],"auth_command_arguments":[]},
          "skills":{"expected_candidate_skills":[],"runtime_sha256":None},"digests":{"eval_plan_sha256":"a"*64,"candidate_prompt_sha256":"a"*64,"boundary_profile_sha256":ps,"runtime_sha256":None},"scope":"test"}
        self.jp=b/"job.json";self.jp.write_text(json.dumps(self.job),encoding="utf-8")
    def tearDown(self): self.tmp.cleanup()
    def _bind(self): return bind(runner_job_path=self.jp,boundary_profile_path=self.pp,probe_report_path=self.rp,attestation_path=self.ap)
    def test_subscription_link(self):
        r=self._bind();self.assertEqual(r["schema_version"],3);self.assertEqual(r["authentication_mode"],"chatgpt-subscription");self.assertFalse(r["api_key_auth_allowed"])
    def test_candidate_auth_exposure_mismatch_rejected(self):
        v=deepcopy(self.att);v["environment"]["candidate_auth_exposed"]=True;self.ap.write_text(json.dumps(v),encoding="utf-8")
        with self.assertRaises(ValueError):self._bind()
    def test_control_home_path_mismatch_rejected(self):
        v=deepcopy(self.att);v["paths"]["control_codex_home"]=v["paths"]["real_home"]+"/other";self.ap.write_text(json.dumps(v),encoding="utf-8")
        with self.assertRaises(ValueError):self._bind()
    def test_model_mismatch_rejected(self):
        v=deepcopy(self.att);v["versions"]["model"]="other";self.ap.write_text(json.dumps(v),encoding="utf-8")
        with self.assertRaises(ValueError):self._bind()
    def test_api_auth_job_rejected(self):
        v=deepcopy(self.job);v["authentication"]["api_key_auth_allowed"]=True;self.jp.write_text(json.dumps(v),encoding="utf-8")
        with self.assertRaises(ValueError):self._bind()
if __name__=="__main__":unittest.main()
