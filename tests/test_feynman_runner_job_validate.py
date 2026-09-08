from __future__ import annotations
import hashlib,json,sys,tempfile,unittest
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tooling.feynman_runner_job_validate import validate_job
class RunnerJobValidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();b=Path(self.tmp.name)
        self.paths={k:str((b/k).resolve()) for k in ["candidate","evaluator","source","home","codex","tmp","real"]}
        self.paths["control"]=str((b/"real"/".codex").resolve())
        rw=[self.paths[x] for x in ["candidate","home","codex","tmp"]]
        self.profile={"schema_version":1,"backend":"docker","backend_version":"1","image":"img","image_id":"sha256:"+"6"*64,
          "network_mode":"none","read_only_root":True,"no_new_privileges":True,"capabilities":[],"run_as":"1000:1000",
          "read_write_mounts":rw,"read_only_mounts":[],"tmpfs_mounts":["/tmp"],"protected_roots_mounted":[],
          "candidate_env_keys":["HOME","CODEX_HOME","PATH","TMPDIR"],"scope":"test"}
        raw=json.dumps(self.profile,sort_keys=True).encode();self.profile_sha=hashlib.sha256(raw).hexdigest()
        self.job={"schema_version":3,"run_id":"r","job":{"ordinal":1,"case_id":"c","condition_id":"baseline","repeat":1,"has_followup":False},
          "versions":{"model":"m","codex_cli":"c"},"paths":{"candidate_dir":self.paths["candidate"],"evaluator_dir":self.paths["evaluator"],
          "source_repo":self.paths["source"],"ephemeral_home":self.paths["home"],"codex_home":self.paths["codex"],"temp_dir":self.paths["tmp"],
          "real_home":self.paths["real"],"control_codex_home":self.paths["control"]},
          "boundary":{"profile_sha256":self.profile_sha,"backend":"docker","backend_version":"1","network_mode":"none","candidate_env_keys":["CODEX_HOME","HOME","PATH","TMPDIR"]},
          "network":{"case_requires_tool_network":False,"tool_network":"blocked","allowed_tool_destinations":[],"control_plane_separate_from_tool_network":True},
          "authentication":{"mode":"chatgpt-subscription","control_plane_auth_source":"codex-session","api_key_auth_allowed":False,
          "candidate_auth_exposed":False,"candidate_tool_auth_env_keys":[],"candidate_readable_auth_paths":[],"auth_command_arguments":[]},
          "skills":{"expected_candidate_skills":[],"runtime_sha256":None},
          "digests":{"eval_plan_sha256":"a"*64,"candidate_prompt_sha256":"b"*64,"boundary_profile_sha256":self.profile_sha,"runtime_sha256":None},"scope":"test"}
    def tearDown(self): self.tmp.cleanup()
    def test_valid(self): self.assertEqual(validate_job(self.job,self.profile,self.profile_sha)["verdict"],"runner-job-valid")
    def test_v2_rejected(self):
        v=deepcopy(self.job);v["schema_version"]=2
        with self.assertRaises(ValueError): validate_job(v,self.profile,self.profile_sha)
    def test_api_mode_rejected(self):
        v=deepcopy(self.job);v["authentication"]={"mode":"control-plane-only"}
        with self.assertRaises(ValueError): validate_job(v,self.profile,self.profile_sha)
    def test_api_key_text_rejected(self):
        v=deepcopy(self.job);v["scope"]="OPENAI_API_KEY"
        with self.assertRaises(ValueError): validate_job(v,self.profile,self.profile_sha)
    def test_candidate_secret_env_rejected(self):
        v=deepcopy(self.job);p=deepcopy(self.profile);p["candidate_env_keys"].append("SOME_TOKEN");v["boundary"]["candidate_env_keys"].append("SOME_TOKEN")
        with self.assertRaises(ValueError): validate_job(v,p,self.profile_sha)
    def test_control_home_overlap_rejected(self):
        v=deepcopy(self.job);v["paths"]["control_codex_home"]=self.paths["codex"]+"/control"
        with self.assertRaises(ValueError): validate_job(v,self.profile,self.profile_sha)
    def test_profile_mount_drift_rejected(self):
        p=deepcopy(self.profile);p["read_write_mounts"]=p["read_write_mounts"][:-1]
        with self.assertRaises(ValueError): validate_job(self.job,p,self.profile_sha)
    def test_feynman_requires_runtime(self):
        v=deepcopy(self.job);v["job"]["condition_id"]="feynman-v05";v["skills"]["expected_candidate_skills"]=["feynman-thinking"]
        with self.assertRaises(ValueError): validate_job(v,self.profile,self.profile_sha)
if __name__=="__main__": unittest.main()
