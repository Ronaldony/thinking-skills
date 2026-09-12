from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_rpc_path_mapping import RpcPathMapper
from tooling.feynman_rpc_path_proxy import _ProxyTelemetry, _docker_mounts, _fixed_error, _map_request_payload, _split_cli


class RpcPathProxyTests(unittest.TestCase):
    def test_windows_volume_spec_splits_from_the_right(self):
        mounts = _docker_mounts([
            "run", "-v", r"C:\DevWorks\candidate:/run/candidate:rw",
            "--volume", r"D:\Temp\home:/run/home:rw",
        ])
        self.assertEqual(mounts, [
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
            {"source": r"D:\Temp\home", "destination": "/run/home", "access": "rw"},
        ])

    def test_cli_requires_explicit_docker_separator(self):
        docker, telemetry, args = _split_cli(["--docker", "docker.exe", "--telemetry-file", "telemetry.json", "--", "run", "image"])
        self.assertEqual(docker, "docker.exe")
        self.assertEqual(str(telemetry), "telemetry.json")
        self.assertEqual(args, ["run", "image"])
        with self.assertRaises(ValueError):
            _split_cli(["--docker", "docker.exe", "run", "image"])

    def test_telemetry_contains_only_fixed_safe_counters(self):
        telemetry = _ProxyTelemetry()
        telemetry.request_seen("fs/readFile")
        telemetry.request_forwarded()
        telemetry.response_seen(-32001)
        telemetry.response_forwarded()
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["request_methods"], {"fs/readFile": 1})
        self.assertEqual(snapshot["response_error_codes"], {"-32001": 1})
        self.assertEqual(snapshot["requests_forwarded"], 1)
        self.assertNotIn("path", json.dumps(snapshot))
        self.assertNotIn("id", json.dumps(snapshot))

    def test_mapping_error_response_contains_no_rejected_value(self):
        payload = _fixed_error(7)
        message = json.loads(payload)
        self.assertEqual(message, {
            "jsonrpc": "2.0",
            "error": {"code": -32001, "message": "RPC path mapping rejected"},
            "id": 7,
        })
        self.assertNotIn("C:\\", payload.decode("utf-8"))

    def test_mapping_rejection_returns_to_client_not_child(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({"jsonrpc": "2.0", "id": 9, "method": "fs/readFile", "params": {"path": "file:///C:/Users/wotmd/private.txt"}}).encode("utf-8")
        child_payload, client_error = _map_request_payload(mapper, raw)
        self.assertIsNone(child_payload)
        self.assertEqual(json.loads(client_error), {
            "jsonrpc": "2.0",
            "error": {"code": -32001, "message": "RPC path mapping rejected"},
            "id": 9,
        })

    def test_probe_policy_forces_one_byte_candidate_read(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({
            "jsonrpc": "2.0", "id": 3, "method": "fs/readFile",
            "params": {"path": r"C:\DevWorks\candidate\candidate.py", "offset": 99, "len": 999},
        }).encode("utf-8")
        child_payload, client_error = _map_request_payload(
            mapper, raw, read_limit=1,
            allowed_methods=frozenset({"initialize", "initialized", "fs/readFile"}),
            allowed_path="/run/candidate/candidate.py",
        )
        self.assertIsNone(client_error)
        request = json.loads(child_payload)
        self.assertEqual(request["params"]["path"], r"/run/candidate/candidate.py")
        self.assertEqual(request["params"]["offset"], 0)
        self.assertEqual(request["params"]["len"], 1)

    def test_probe_policy_rejects_non_filesystem_method(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({"jsonrpc": "2.0", "id": 4, "method": "process/start", "params": {}}).encode("utf-8")
        child_payload, client_error = _map_request_payload(
            mapper, raw, read_limit=1,
            allowed_methods=frozenset({"initialize", "initialized", "fs/readFile"}),
            allowed_path="/run/candidate/candidate.py",
        )
        self.assertIsNone(child_payload)
        self.assertEqual(json.loads(client_error)["error"], {
            "code": -32001, "message": "RPC path mapping rejected",
        })

    def test_probe_policy_allows_candidate_mount_metadata_only(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        policy = frozenset({"initialize", "initialized", "environmentConfig/read", "fs/getMetadata", "fs/readFile"})
        raw = json.dumps({
            "jsonrpc": "2.0", "id": 5, "method": "fs/getMetadata",
            "params": {"path": r"C:\DevWorks\candidate\test_candidate.py"},
        }).encode("utf-8")
        child_payload, client_error = _map_request_payload(
            mapper, raw, read_limit=1, allowed_methods=policy,
            allowed_path="/run/candidate/candidate.py",
        )
        self.assertIsNone(client_error)
        self.assertEqual(json.loads(child_payload)["params"]["path"], "/run/candidate/test_candidate.py")


if __name__ == "__main__":
    unittest.main()
