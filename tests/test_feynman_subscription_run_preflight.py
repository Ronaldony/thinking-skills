from __future__ import annotations
from copy import deepcopy
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tooling.feynman_condition_workspace import prepare_condition
from tooling.feynman_eval_plan import build_plan,write_plan
from tooling.feynman_remote_exec_environment import build_files as build_remote
from tooling.feynman_runner_job import build_job
from tooling.feynman_subscription_run_preflight import preflight_files
class SubscriptionPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();b=Path(self.tmp.name);self.b=b
        self.plan=build_plan(ROOT,case_ids=["tools-10"],condition_ids=["baseline"],repeats=1,seed=0);self.planp=b/"plan.json";write_plan(self.plan,self.planp)
        self.candidate=b/"candidate";self.eval=b/"eval";prepare_condition(ROOT,"tools-10","baseline",self.candidate,self.eval)
        self.home=b/"home";self.codex=b/"tool-codex";self.temp=b/"tmpdir";self.real=b/"real-home";self.control=self.real/".codex"
        for p in (self.home,self.codex,self.temp,self.real,self.control):p.mkdir(parents=True,exist_ok=True)
        self.profile={"schema_version":1,"backend":"docker","backend_version":"28","image":"img","image_id":"sha256:"+"6"*64,"network_mode":"none",
          "read_only_root":True,"no_new_privileges":True,"capabilities":[],"run_as":"1000:1000",
          "read_write_mounts":[str(x.resolve()) for x in (self.candidate,self.home,self.codex,self.temp)],"read_only_mounts":[],
          "tmpfs_mounts":["/tmp"],"protected_roots_mounted":[],"candidate_env_keys":["HOME","CODEX_HOME","PATH","TMPDIR"],"scope":"test"}
        self.pp=b/"profile.json";self.pp.write_text(json.dumps(self.profile,sort_keys=True),encoding="utf-8")
        self.job=build_job(plan_path=self.planp,ordinal=1,evaluator_case_path=self.eval/"case.json",boundary_profile_path=self.pp,run_id="run-1",
          model="test-model",codex_cli="codex test",candidate_dir=self.candidate,evaluator_dir=self.eval,source_repo=ROOT,ephemeral_home=self.home,
          codex_home=self.codex,temp_dir=self.temp,real_home=self.real,control_codex_home=self.control)
        self.jp=b/"job.json";self.jp.write_text(json.dumps(self.job),encoding="utf-8")
        self.envp=b/"environments.toml";build_remote(self.jp,self.pp,self.envp)
    def tearDown(self):self.tmp.cleanup()
    def _run(self):return preflight_files(plan_path=self.planp,ordinal=1,evaluator_case_path=self.eval/"case.json",runner_job_path=self.jp,boundary_profile_path=self.pp,remote_environment_path=self.envp)
    def test_ready_without_reading_session_contents(self):
        (self.control/"auth.json").write_text("synthetic-do-not-read",encoding="utf-8")
        r=self._run();self.assertEqual(r["verdict"],"ready-for-local-chatgpt-session-check")
        self.assertFalse(r["authentication"]["control_session_contents_read_by_preflight"]);self.assertFalse(r["authentication"]["api_key_auth_allowed"])
    def test_missing_control_home_rejected(self):
        for p in self.control.iterdir():p.unlink()
        self.control.rmdir()
        with self.assertRaises(ValueError):self._run()
    def test_symlink_control_home_rejected(self):
        for p in self.control.iterdir():p.unlink()
        self.control.rmdir();target=self.real/"other";target.mkdir();self.control.symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):self._run()
    def test_retired_auth_object_rejected(self):
        v=deepcopy(self.job);v["authentication"]["control_plane_credential_env_key"]="RETIRED"
        self.jp.write_text(json.dumps(v),encoding="utf-8")
        with self.assertRaises(ValueError):self._run()
    def test_candidate_task_drift_rejected(self):
        (self.candidate/"task.txt").write_text("drift",encoding="utf-8")
        with self.assertRaises(ValueError):self._run()
if __name__=="__main__":unittest.main()
