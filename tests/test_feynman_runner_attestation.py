from __future__ import annotations
from copy import deepcopy
import os
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tooling.feynman_runner_attestation import BOUNDARY_REPORT_PROBES,validate
SHA="a"*64
def probe(method:str="synthetic external-boundary canary"): return {"passed":True,"artifact_sha256":SHA,"method":method}
def attestation(condition:str="baseline"):
    skill=condition in {"legacy-clean","feynman-v05"}
    if os.name == "nt":
        paths={"candidate_dir":r"C:\feynman-test\isolated\candidate","evaluator_dir":r"C:\feynman-test\evaluator\run-1","source_repo":r"C:\feynman-test\source\thinking-skills",
          "ephemeral_home":r"C:\feynman-test\isolated\home","codex_home":r"C:\feynman-test\isolated\codex-home","temp_dir":r"C:\feynman-test\isolated\tmp",
          "real_home":r"C:\feynman-test\home\real-user","control_codex_home":r"C:\feynman-test\home\real-user\.codex"}
        readable=[paths[x] for x in ("candidate_dir","ephemeral_home","codex_home","temp_dir")]
        forbidden=[paths[x] for x in ("evaluator_dir","source_repo","real_home")]
    else:
        paths={"candidate_dir":"/isolated/candidate","evaluator_dir":"/evaluator/run-1","source_repo":"/source/thinking-skills",
          "ephemeral_home":"/isolated/home","codex_home":"/isolated/codex-home","temp_dir":"/isolated/tmp",
          "real_home":"/home/real-user","control_codex_home":"/home/real-user/.codex"}
        readable=["/isolated/candidate","/isolated/home","/isolated/codex-home","/isolated/tmp"]
        forbidden=["/evaluator/run-1","/source/thinking-skills","/home/real-user"]
    return {
      "schema_version":3,"run_id":"run-1","case_id":"mechanism-01","condition_id":condition,
      "boundary":{"backend":"test-container","backend_version":"1","platform":"linux","kernel":"test-kernel","external_enforcement":True,"profile_sha256":SHA},
      "paths":paths,
      "filesystem":{"candidate_readable_data_roots":readable,
        "candidate_writable_roots":readable,
        "platform_runtime_roots":[r"C:\Windows\System32",r"C:\Program Files" ] if os.name == "nt" else ["/usr","/lib"],"forbidden_read_roots":forbidden,
        "forbidden_write_roots":forbidden},
      "network":{"case_requires_tool_network":False,"tool_network":"blocked","control_plane_separate_from_tool_network":True,"allowed_tool_destinations":[]},
      "environment":{"candidate_env_keys":["HOME","CODEX_HOME","PATH","TMPDIR"],"candidate_auth_exposed":False,
        "control_plane_auth_mode":"chatgpt-subscription","control_plane_auth_source":"codex-session","api_key_auth_allowed":False,
        "candidate_tool_auth_env_keys":[],"candidate_readable_auth_paths":[],"auth_command_arguments":[],
        "plugins_enabled":False,"system_skills":[],"expected_candidate_skills":["feynman-thinking"] if skill else [],
        "observed_candidate_skills":["feynman-thinking"] if skill else []},
      "probes":{"candidate_read":probe(),"evaluator_read_denied":probe(),"source_read_denied":probe(),"real_home_read_denied":probe(),
        "candidate_write":probe(),"forbidden_write_denied":probe(),"tool_network_denied":probe(),"ambient_skill_preflight":probe(),"secret_env_scan":probe()},
      "versions":{"codex_cli":"codex-cli test","model":"test-model"},
      "digests":{"eval_plan_sha256":SHA,"runtime_sha256":SHA if skill else None,"candidate_prompt_sha256":SHA,"probe_report_sha256":SHA},
      "limitations":["synthetic unit-test attestation only"]}
def boundary_report(value:dict):
    requires=value["network"]["case_requires_tool_network"]
    return {"schema_version":1,"run_id":value["run_id"],"boundary_profile_sha256":value["boundary"]["profile_sha256"],"verdict":"passed",
      "failed_probes":[],"not_required_probes":["tool_network_denied"] if requires else [],"source_artifact_sha256":SHA,"probe_program_sha256":SHA,
      "network_reference_sha256":None if requires else SHA,"observed_env_keys":sorted(value["environment"]["candidate_env_keys"]),
      "probes":{n:deepcopy(value["probes"][n]) for n in BOUNDARY_REPORT_PROBES},"scope":"synthetic normalized boundary report"}
class RunnerAttestationTests(unittest.TestCase):
    def test_baseline_contract_valid(self):
        r=validate(attestation());self.assertEqual(r["verdict"],"contract-valid");self.assertEqual(r["authentication_mode"],"chatgpt-subscription");self.assertFalse(r["api_key_auth_allowed"])
    def test_v05_contract_valid(self): self.assertEqual(validate(attestation("feynman-v05"))["verdict"],"contract-valid")
    def test_old_api_schema_is_rejected(self):
        v=attestation();v["schema_version"]=2
        with self.assertRaises(ValueError): validate(v)
    def test_api_key_auth_flag_is_rejected(self):
        v=attestation();v["environment"]["api_key_auth_allowed"]=True
        with self.assertRaises(ValueError): validate(v)
    def test_wrong_auth_source_is_rejected(self):
        v=attestation();v["environment"]["control_plane_auth_source"]="environment"
        with self.assertRaises(ValueError): validate(v)
    def test_candidate_auth_exposure_is_rejected(self):
        v=attestation();v["environment"]["candidate_auth_exposed"]=True
        with self.assertRaises(ValueError): validate(v)
    def test_control_home_overlap_is_rejected(self):
        v=attestation();v["paths"]["control_codex_home"]="/isolated/codex-home/control"
        with self.assertRaises(ValueError): validate(v)
    def test_secret_like_candidate_env_is_rejected(self):
        v=attestation();v["environment"]["candidate_env_keys"].append("SOME_SECRET")
        with self.assertRaises(ValueError): validate(v)
    def test_verified_report_is_bound(self):
        v=attestation();self.assertTrue(validate(v,probe_report=boundary_report(v),probe_report_sha256=SHA)["probe_report_bound"])
    def test_profile_mismatch_rejected(self):
        v=attestation();r=boundary_report(v);r["boundary_profile_sha256"]="b"*64
        with self.assertRaises(ValueError): validate(v,probe_report=r,probe_report_sha256=SHA)
    def test_network_required_can_skip_denial(self):
        v=attestation();v["network"].update({"case_requires_tool_network":True,"tool_network":"restricted","allowed_tool_destinations":["fixture.invalid"]})
        v["probes"]["tool_network_denied"]["passed"]=False;r=boundary_report(v)
        self.assertTrue(validate(v,probe_report=r,probe_report_sha256=SHA)["probe_report_bound"])
    def test_plugins_fail_closed(self):
        v=attestation();v["environment"]["plugins_enabled"]=True
        with self.assertRaises(ValueError): validate(v)
        self.assertEqual(validate(v,allow_plugins=True)["verdict"],"contract-valid")
    def test_system_skills_explicit(self):
        v=attestation();v["environment"]["system_skills"]=["system-helper"]
        with self.assertRaises(ValueError): validate(v)
        self.assertEqual(validate(v,allowed_system_skills={"system-helper"})["verdict"],"contract-valid")
    def test_skill_set_exact(self):
        v=attestation("feynman-v05");v["environment"]["observed_candidate_skills"]=[]
        with self.assertRaises(ValueError): validate(v)
    def test_no_skill_runtime_rejected(self):
        v=attestation();v["digests"]["runtime_sha256"]=SHA
        with self.assertRaises(ValueError): validate(v)
    def test_failed_canary_rejected(self):
        v=attestation();v["probes"]["evaluator_read_denied"]["passed"]=False
        with self.assertRaises(ValueError): validate(v)
if __name__=="__main__": unittest.main()
