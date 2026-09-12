from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_rpc_path_mapping import RpcPathMapper, RpcPathMappingError, map_json_line


class RpcPathMappingTests(unittest.TestCase):
    def setUp(self):
        self.mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\smoke\candidate", "destination": "/run/candidate", "access": "rw"},
            {"source": r"C:\DevWorks\smoke\home", "destination": "/run/home", "access": "rw"},
        ])

    def test_windows_file_uri_maps_to_container_file_uri(self):
        self.assertEqual(
            self.mapper.host_to_container("file:///C:/DevWorks/smoke/candidate/.agents/skills/feynman-thinking/SKILL.md"),
            "file:///run/candidate/.agents/skills/feynman-thinking/SKILL.md",
        )

    def test_request_maps_only_declared_method_field(self):
        message = {
            "jsonrpc": "2.0", "id": 1, "method": "command/exec",
            "params": {"cwd": r"C:\DevWorks\smoke\candidate", "command": ["cat", r"C:\DevWorks\smoke\candidate\task.txt"]},
        }
        mapped = self.mapper.map_request(message)
        self.assertEqual(mapped["params"]["cwd"], "/run/candidate")
        self.assertEqual(mapped["params"]["command"][1], r"C:\DevWorks\smoke\candidate\task.txt")

    def test_process_exec_maps_cwd(self):
        message = {"method": "process/exec", "params": {"cwd": "file:///C:/DevWorks/smoke/candidate"}}
        self.assertEqual(self.mapper.map_request(message)["params"]["cwd"], "file:///run/candidate")

    def test_process_start_maps_windows_cwd_and_preserves_container_uri(self):
        host = {"method": "process/start", "params": {"cwd": "file:///C:/DevWorks/smoke/candidate"}}
        container = {"method": "process/start", "params": {"cwd": "file:///run/candidate"}}
        self.assertEqual(self.mapper.map_request(host)["params"]["cwd"], "file:///run/candidate")
        self.assertEqual(self.mapper.map_request(container), container)

    def test_container_raw_path_is_preserved_only_under_a_declared_mount(self):
        self.assertEqual(self.mapper.host_to_container("/run/candidate/x.txt"), "/run/candidate/x.txt")
        with self.assertRaises(RpcPathMappingError):
            self.mapper.host_to_container("file:///etc/passwd")

    def test_file_read_and_resource_requests_map_their_declared_field(self):
        for method, field in (("fs/readFile", "path"), ("fs/writeFile", "path"), ("resources/read", "uri")):
            with self.subTest(method=method):
                message = {"method": method, "params": {field: "file:///C:/DevWorks/smoke/candidate/x.txt"}}
                self.assertEqual(self.mapper.map_request(message)["params"][field], "file:///run/candidate/x.txt")

    def test_unknown_method_is_unchanged(self):
        message = {"method": "unknown/path", "params": {"path": "file:///C:/DevWorks/smoke/candidate/x.txt"}}
        self.assertEqual(self.mapper.map_request(message), message)

    def test_outside_mount_and_traversal_are_rejected(self):
        with self.assertRaises(RpcPathMappingError):
            self.mapper.host_to_container("file:///C:/Users/wotmd/secret.txt")
        with self.assertRaises(RpcPathMappingError):
            self.mapper.container_to_host("/run/candidate/../home/secret.txt")

    def test_response_maps_container_file_uri_back_to_host(self):
        message = {"jsonrpc": "2.0", "id": 1, "result": {"path": "file:///run/candidate/x.txt", "text": "safe"}}
        mapped = self.mapper.map_response(message)
        self.assertEqual(mapped["result"]["path"], "file:///C:/DevWorks/smoke/candidate/x.txt")
        self.assertEqual(mapped["result"]["text"], "safe")

    def test_json_line_does_not_rewrite_arbitrary_strings(self):
        line = json.dumps({"method": "resources/read", "params": {"uri": "file:///C:/DevWorks/smoke/candidate/x.txt", "note": "C:\\DevWorks\\smoke\\candidate"}})
        mapped = json.loads(map_json_line(self.mapper, line))
        self.assertEqual(mapped["params"]["uri"], "file:///run/candidate/x.txt")
        self.assertEqual(mapped["params"]["note"], r"C:\DevWorks\smoke\candidate")


if __name__ == "__main__":
    unittest.main()
