from __future__ import annotations
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tooling.feynman_condition_workspace import prepare_condition
from tooling.feynman_eval_plan import build_plan,write_plan
from tooling.feynman_runner_job import build_job
class RunnerJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def _prepare(self,condition="baseline"):
        plan=build_plan(ROOT,case_ids=["mechanism-01"],condition_ids=[condition],repeats=1,seed=0)
        plan_path=self.base/f"plan-{condition}.json";write_plan(plan,plan_path)
        candidate=self.base/f"candidate-{condition}";evaluator=self.base/f"evaluator-{condition}"
        prepare_condition(ROOT,"mechanism-01",condition,candidate,evaluator)
        home=self.base/f"home-{condition}";codex=self.base/f"codex-{condition}";tmp=self.base/f"tmp-{condition}"
        real=self.base/"real-home";control=real/".codex"
        for p in (home,codex,tmp,real,control): p.mkdir(parents=True,exist_ok=True)
        profile={"schema_version":1,"backend":"docker","backend_version":"28.0.4","image":"python:3.12-slim",
          "image_id":"sha256:"+"6"*64,"network_mode":"none","read_only_root":True,"no_new_privileges":True,
          "capabilities":[],"run_as":"1000:1000","read_write_mounts":[str(candidate.resolve()),str(home.resolve()),str(codex.resolve()),str(tmp.resolve())],
          "read_only_mounts":[],"tmpfs_mounts":["/tmp"],"protected_roots_mounted":[],"candidate_env_keys":["HOME","CODEX_HOME","PATH","TMPDIR"],
          "scope":"subscription runner job unit profile"}
        pp=self.base/f"profile-{condition}.json";pp.write_text(json.dumps(profile,sort_keys=True),encoding="utf-8")
        return plan,plan_path,candidate,evaluator,pp,home,codex,tmp,real,control
    def _build(self,condition="baseline",**overrides):
        plan,plan_path,candidate,evaluator,pp,home,codex,tmp,real,control=self._prepare(condition)
        kw=dict(plan_path=plan_path,ordinal=plan["jobs"][0]["ordinal"],evaluator_case_path=evaluator/"case.json",boundary_profile_path=pp,
          run_id=f"run-{condition}",model="test-model",codex_cli="codex test",candidate_dir=candidate,evaluator_dir=evaluator,
          source_repo=ROOT,ephemeral_home=home,codex_home=codex,temp_dir=tmp,real_home=real,control_codex_home=control)
        kw.update(overrides)
        return build_job(**kw)
    def test_baseline_is_subscription_only(self):
        r=self._build();self.assertEqual(r["schema_version"],3);self.assertEqual(r["authentication"],{
          "mode":"chatgpt-subscription","control_plane_auth_source":"codex-session","api_key_auth_allowed":False,
          "candidate_auth_exposed":False,"candidate_tool_auth_env_keys":[],"candidate_readable_auth_paths":[],"auth_command_arguments":[]})
        self.assertNotIn("OPENAI_API_KEY",json.dumps(r));self.assertIn("control_codex_home",r["paths"])
    def test_v05_binds_runtime(self):
        r=self._build("feynman-v05");self.assertEqual(r["skills"]["expected_candidate_skills"],["feynman-thinking"])
        self.assertEqual(r["skills"]["runtime_sha256"],r["digests"]["runtime_sha256"]);self.assertEqual(len(r["skills"]["runtime_sha256"]),64)
    def test_control_home_cannot_overlap_candidate_codex_home(self):
        plan,plan_path,candidate,evaluator,pp,home,codex,tmp,real,control=self._prepare()
        with self.assertRaises(ValueError):
            build_job(plan_path=plan_path,ordinal=1,evaluator_case_path=evaluator/"case.json",boundary_profile_path=pp,run_id="x",model="m",codex_cli="c",
              candidate_dir=candidate,evaluator_dir=evaluator,source_repo=ROOT,ephemeral_home=home,codex_home=codex,temp_dir=tmp,real_home=real,
              control_codex_home=codex/"control")
    def test_secret_like_candidate_env_rejected(self):
        plan,plan_path,candidate,evaluator,pp,home,codex,tmp,real,control=self._prepare()
        profile=json.loads(pp.read_text());profile["candidate_env_keys"].append("OPENAI_API_KEY");pp.write_text(json.dumps(profile),encoding="utf-8")
        with self.assertRaises(ValueError):
            build_job(plan_path=plan_path,ordinal=1,evaluator_case_path=evaluator/"case.json",boundary_profile_path=pp,run_id="x",model="m",codex_cli="c",
              candidate_dir=candidate,evaluator_dir=evaluator,source_repo=ROOT,ephemeral_home=home,codex_home=codex,temp_dir=tmp,real_home=real,control_codex_home=control)
    def test_closed_network_rejects_destinations(self):
        with self.assertRaises(ValueError): self._build(allowed_tool_destinations=["example.invalid"])
    def test_network_required_rejects_none_profile(self):
        with self.assertRaises(ValueError): self._build(case_requires_tool_network=True,allowed_tool_destinations=["example.invalid"])
    def test_tampered_evaluator_prompt_rejected(self):
        plan,plan_path,candidate,evaluator,pp,home,codex,tmp,real,control=self._prepare()
        cp=evaluator/"case.json";v=json.loads(cp.read_text());v["candidate_prompt_sha256"]="f"*64;cp.write_text(json.dumps(v),encoding="utf-8")
        with self.assertRaises(ValueError):
            build_job(plan_path=plan_path,ordinal=1,evaluator_case_path=cp,boundary_profile_path=pp,run_id="x",model="m",codex_cli="c",
              candidate_dir=candidate,evaluator_dir=evaluator,source_repo=ROOT,ephemeral_home=home,codex_home=codex,temp_dir=tmp,real_home=real,control_codex_home=control)
if __name__=="__main__": unittest.main()
