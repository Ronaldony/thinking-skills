from __future__ import annotations
from copy import deepcopy
import hashlib,json,os,sys,tempfile,tomllib,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT / "tests"))
from tooling.feynman_remote_exec_environment import build_document,expected_docker_args,render_toml,validate_document
from feynman_test_support import attach_native_mounts,use_native_profile
class RemoteExecEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();b=Path(self.tmp.name)
        self.paths={k:str((b/v).resolve()) for k,v in {"candidate_dir":"candidate","evaluator_dir":"evaluator","source_repo":"source","ephemeral_home":"home","codex_home":"codex","temp_dir":"temp","real_home":"real-home","control_codex_home":"control-codex-home"}.items()}
        self.profile={"schema_version":1,"backend":"docker","backend_version":"28.0.4","image":"feynman-codex-remote:local","image_id":"sha256:"+"8"*64,
          "network_mode":"none","read_only_root":True,"no_new_privileges":True,"capabilities":[],"run_as":"1000:1000",
          "read_write_mounts":[self.paths[x] for x in ("candidate_dir","ephemeral_home","codex_home","temp_dir")],"read_only_mounts":[],
          "tmpfs_mounts":["/tmp"],"protected_roots_mounted":[],"candidate_env_keys":["HOME","CODEX_HOME","PATH","TMPDIR"],"scope":"synthetic stdio remote exec profile"}
        use_native_profile(self.profile,self.paths)
        self.profile_sha=hashlib.sha256(json.dumps(self.profile,sort_keys=True).encode()).hexdigest()
        self.job={"schema_version":3,"run_id":"reference/run 1","job":{"ordinal":1,"case_id":"mechanism-01","condition_id":"baseline","repeat":1,"has_followup":False},
          "versions":{"model":"mock-model","codex_cli":"codex-test"},"paths":deepcopy(self.paths),
          "boundary":{"profile_sha256":self.profile_sha,"backend":"docker","backend_version":"28.0.4","network_mode":"none","candidate_env_keys":deepcopy(self.profile["candidate_env_keys"])},
          "network":{"case_requires_tool_network":False,"tool_network":"blocked","allowed_tool_destinations":[],"control_plane_separate_from_tool_network":True},
          "authentication":{"mode":"chatgpt-subscription","control_plane_auth_source":"codex-session","api_key_auth_allowed":False,"candidate_auth_exposed":False,
             "candidate_tool_auth_env_keys":[],"candidate_readable_auth_paths":[],"auth_command_arguments":[]},
          "skills":{"expected_candidate_skills":[],"runtime_sha256":None},"digests":{"eval_plan_sha256":"1"*64,"candidate_prompt_sha256":"2"*64,"boundary_profile_sha256":self.profile_sha,"runtime_sha256":None},"scope":"synthetic subscription runner job"}
        attach_native_mounts(self.job,self.paths)
    def tearDown(self):self.tmp.cleanup()
    def test_document_disables_local_and_uses_stdio(self):
        d=build_document(deepcopy(self.job),deepcopy(self.profile),self.profile_sha);self.assertFalse(d["include_local"]);args=d["environments"][0]["args"]
        self.assertEqual(args[args.index("--network")+1],"none");self.assertEqual(args[-4:],["codex","exec-server","--listen","stdio"])
        joined=" ".join(args)
        for p in (self.paths["evaluator_dir"],self.paths["source_repo"],self.paths["real_home"],self.paths["control_codex_home"]):self.assertNotIn(p,joined)
    def test_candidate_roots_exact_rw(self):
        joined="\n".join(expected_docker_args(deepcopy(self.job),deepcopy(self.profile)))
        for k,dest in (("candidate_dir","/run/candidate"),("ephemeral_home","/run/home"),("codex_home","/run/codex"),("temp_dir","/run/temp")):
            p=self.paths[k]
            expected=f"{p}:{dest}:rw" if os.name == "nt" else f"{p}:{p}:rw"
            self.assertIn(expected,joined)
    def test_toml_round_trip(self):
        d=build_document(deepcopy(self.job),deepcopy(self.profile),self.profile_sha);parsed=tomllib.loads(render_toml(d))
        self.assertEqual(validate_document(parsed,deepcopy(self.job),deepcopy(self.profile),self.profile_sha)["verdict"],"remote-exec-environment-valid")
    def test_local_reenable_rejected(self):
        d=build_document(deepcopy(self.job),deepcopy(self.profile),self.profile_sha);d["include_local"]=True
        with self.assertRaises(ValueError):validate_document(d,deepcopy(self.job),deepcopy(self.profile),self.profile_sha)
    def test_readonly_host_bind_rejected(self):
        p=deepcopy(self.profile);p["read_only_mounts"]=["/probe/file"]
        with self.assertRaises(ValueError):build_document(deepcopy(self.job),p,self.profile_sha)
    def test_open_network_rejected(self):
        p=deepcopy(self.profile);p["network_mode"]="open";j=deepcopy(self.job);j["boundary"]["network_mode"]="open";j["network"]["tool_network"]="open"
        with self.assertRaises(ValueError):build_document(j,p,self.profile_sha)
    def test_unknown_env_key_rejected(self):
        p=deepcopy(self.profile);p["candidate_env_keys"].append("LANG");j=deepcopy(self.job);j["boundary"]["candidate_env_keys"].append("LANG")
        with self.assertRaises(ValueError):expected_docker_args(j,p)
if __name__=="__main__":unittest.main()
