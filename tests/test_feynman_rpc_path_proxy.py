from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_rpc_path_mapping import RpcPathMapper
from tooling import feynman_rpc_path_proxy as proxy_module
from tooling.feynman_rpc_path_proxy import (
    _ProxyTelemetry, _docker_mounts, _fixed_error, _map_request_payload,
    _map_request_payload_with_reason, _split_cli, _write_telemetry,
)


class RpcPathProxyTests(unittest.TestCase):
    def test_proxy_joins_parent_reader_when_child_stdout_ends_first(self):
        reader_started = threading.Event()
        reader_finished = threading.Event()
        release_reader = threading.Event()

        def delayed_parent_lines(_stop):
            reader_started.set()
            try:
                release_reader.wait(timeout=0.5)
            finally:
                reader_finished.set()
            if False:
                yield b""

        try:
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                telemetry = root / "telemetry.json"
                with patch.object(
                    proxy_module, "_parent_stdin_lines", side_effect=delayed_parent_lines
                ):
                    exit_code = proxy_module.run_proxy(
                        sys.executable,
                        ["-c", "import time,sys; time.sleep(0.1); sys.exit(7)",
                         "-v", f"{root}:/run/candidate:rw"],
                        telemetry,
                    )
                self.assertTrue(reader_started.wait(timeout=1))
                self.assertTrue(reader_finished.is_set())
                self.assertEqual(exit_code, 7)
                self.assertEqual(
                    json.loads(telemetry.read_text(encoding="utf-8"))["child_exit_code"],
                    7,
                )
        finally:
            release_reader.set()
            reader_finished.wait(timeout=2)

    def test_proxy_drains_healthy_child_after_parent_stdin_closes(self):
        fixture = ROOT / "tests" / "feynman_subscription_lifecycle_fixture.py"
        proxy = ROOT / "tooling" / "feynman_rpc_path_proxy.py"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            telemetry = root / "telemetry.json"
            docker_args = [
                "-B", str(fixture), "proxy-child", "-v",
                f"{root}:/run/candidate:rw",
            ]
            process = subprocess.Popen(
                [sys.executable, "-B", str(proxy), "--docker", sys.executable,
                 "--telemetry-file", str(telemetry), "--", *docker_args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", env={
                    key: os.environ[key]
                    for key in ("PATH", "SystemRoot", "WINDIR", "ComSpec", "PATHEXT", "TEMP", "TMP")
                    if key in os.environ
                },
            )
            input_lines = "\n".join([
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "thread/start", "params": {}}),
            ]) + "\n"
            stdout, stderr = process.communicate(input_lines, timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            messages = [json.loads(line) for line in stdout.splitlines()]
            self.assertEqual([message["id"] for message in messages], [1, 2])
            value = json.loads(telemetry.read_text(encoding="utf-8"))
            self.assertEqual(value["requests_seen"], 3)
            self.assertEqual(value["requests_forwarded"], 3)
            self.assertEqual(value["responses_seen"], 2)
            self.assertEqual(value["responses_forwarded"], 2)
            self.assertEqual(value["responses_matched"], 2)
            self.assertEqual(value["responses_unmatched"], 0)
            self.assertEqual(value["pending_request_ids"], 0)
            self.assertEqual(value["child_exit_code"], 0)

    def test_proxy_exits_when_child_ends_while_parent_stdin_is_open(self):
        fixture = ROOT / "tests" / "feynman_subscription_lifecycle_fixture.py"
        proxy = ROOT / "tooling" / "feynman_rpc_path_proxy.py"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            telemetry = root / "telemetry.json"
            process = subprocess.Popen(
                [sys.executable, "-B", str(proxy), "--docker", sys.executable,
                 "--telemetry-file", str(telemetry), "--", "-B", str(fixture),
                 "proxy-child-exit", "-v", f"{root}:/run/candidate:rw"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", env={
                    key: os.environ[key]
                    for key in ("PATH", "SystemRoot", "WINDIR", "ComSpec", "PATHEXT", "TEMP", "TMP")
                    if key in os.environ
                },
            )
            assert process.stdin is not None
            process.stdin.write(json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {},
            }) + "\n")
            process.stdin.flush()
            # Production cleanup is bounded at 15 seconds when a child EOF
            # cannot wake the platform pipe reader; it must still terminate.
            try:
                process.wait(timeout=20)
                self.assertEqual(process.returncode, 7)
                value = json.loads(telemetry.read_text(encoding="utf-8"))
                self.assertEqual(value["child_exit_code"], 7)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()

    def test_telemetry_writer_failure_forces_nonzero_proxy_exit(self):
        fixture = ROOT / "tests" / "feynman_subscription_lifecycle_fixture.py"
        requests = [
            json.dumps({"jsonrpc": "2.0", "id": 1,
                        "method": "initialize", "params": {}}).encode() + b"\n",
            json.dumps({"jsonrpc": "2.0", "method": "initialized",
                        "params": {}}).encode() + b"\n",
            json.dumps({"jsonrpc": "2.0", "id": 2,
                        "method": "thread/start", "params": {}}).encode() + b"\n",
        ]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            telemetry = root / "telemetry.json"
            original_write = proxy_module._write_telemetry
            write_calls: list[int] = []
            output: list[bytes] = []

            def fail_after_initial(path, value):
                write_calls.append(1)
                if len(write_calls) >= 2:
                    raise OSError("synthetic telemetry storage failure")
                original_write(path, value)

            def parent_lines(_stop):
                yield from requests

            with patch.object(proxy_module, "_parent_stdin_lines", side_effect=parent_lines), \
                    patch.object(proxy_module, "_write_telemetry", side_effect=fail_after_initial), \
                    patch.object(proxy_module, "_write_stdout",
                                 side_effect=lambda _lock, payload: output.append(payload)):
                exit_code = proxy_module.run_proxy(
                    sys.executable,
                    ["-B", str(fixture), "proxy-child", "-v",
                     f"{root}:/run/candidate:rw"],
                    telemetry,
                )

            self.assertGreaterEqual(len(write_calls), 2)
            self.assertNotEqual(exit_code, 0)

    def test_telemetry_write_replaces_atomically_without_temp_residue(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "telemetry.json"
            _write_telemetry(path, _ProxyTelemetry())
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value["schema_version"], 3)
            self.assertEqual(list(Path(raw).glob(".telemetry.json.*.tmp")), [])

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
        telemetry.request_rejected(
            malformed=False, method="fs/walk", reason="host-path-outside-declared-mount")
        telemetry.request_forwarded()
        telemetry.response_seen(-32001)
        telemetry.response_forwarded()
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["request_methods"], {"fs/readFile": 1})
        self.assertEqual(snapshot["request_mapping_rejection_methods"], {"fs/walk": 1})
        self.assertEqual(snapshot["request_mapping_rejection_reasons"],
                         {"host-path-outside-declared-mount": 1})
        self.assertEqual(snapshot["request_mapping_rejection_method_reasons"], {
            "fs/walk": {"host-path-outside-declared-mount": 1},
        })
        self.assertEqual(snapshot["request_mapping_rejection_method_reason_fields"], {
            "fs/walk": {"host-path-outside-declared-mount": {"unknown": 1}},
        })
        self.assertEqual(snapshot["response_error_codes"], {"-32001": 1})
        self.assertEqual(snapshot["requests_forwarded"], 1)
        serialized = json.dumps(snapshot)
        self.assertNotIn('"path"', serialized)
        self.assertNotIn('"id"', serialized)

    def test_telemetry_bounds_unknown_methods_and_correlates_responses(self):
        telemetry = _ProxyTelemetry()
        telemetry.request_seen("SYNTHETIC_PRIVATE_METHOD")
        telemetry.response_seen(matched=True)
        telemetry.response_seen(matched=False)
        telemetry.response_seen(notification=True)
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["request_methods"], {"unknown": 1})
        self.assertEqual(snapshot["responses_matched"], 1)
        self.assertEqual(snapshot["responses_unmatched"], 1)
        self.assertEqual(snapshot["notifications_seen"], 1)
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(snapshot))

    def test_rejection_pair_does_not_retain_unknown_method_text(self):
        telemetry = _ProxyTelemetry()
        telemetry.request_rejected(
            malformed=False, method="SYNTHETIC_PRIVATE_METHOD",
            reason="container-path-outside-declared-mount")
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["request_mapping_rejection_methods"], {"unknown": 1})
        self.assertEqual(snapshot["request_mapping_rejection_method_reasons"], {
            "unknown": {"container-path-outside-declared-mount": 1},
        })
        self.assertEqual(snapshot["request_mapping_rejection_method_reason_fields"], {
            "unknown": {"container-path-outside-declared-mount": {"unknown": 1}},
        })
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(snapshot))

    def test_mapping_error_response_contains_no_rejected_value(self):
        payload = _fixed_error(7)
        message = json.loads(payload)
        self.assertEqual(message, {
            "jsonrpc": "2.0",
            "error": {"code": -32001, "message": "RPC path mapping rejected"},
            "id": 7,
        })
        self.assertNotIn("C:\\", payload.decode("utf-8"))

    def test_mapping_error_does_not_echo_non_scalar_request_id(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({
            "jsonrpc": "2.0", "id": {"private": "SYNTHETIC_PRIVATE_ID"},
            "method": "fs/getMetadata",
            "params": {"path": r"C:\DevWorks\candidate\..\private.txt"},
        }).encode("utf-8")
        child, error, reason, field = _map_request_payload_with_reason(mapper, raw)
        self.assertIsNone(child)
        self.assertIsNotNone(error)
        self.assertEqual(reason, "host-path-traversal")
        self.assertEqual(field, "path")
        self.assertNotIn("SYNTHETIC_PRIVATE_ID", error.decode("utf-8"))
        self.assertNotIn("id", json.loads(error))

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

    def test_mapping_rejection_reason_does_not_retain_path(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({
            "jsonrpc": "2.0", "id": 10, "method": "fs/getMetadata",
            "params": {"path": "file:///C:/Users/wotmd/private.txt"},
        }).encode("utf-8")
        child, error, reason, field = _map_request_payload_with_reason(mapper, raw)
        self.assertIsNone(child)
        self.assertIsNotNone(error)
        self.assertEqual(reason, "host-path-outside-declared-mount")
        self.assertEqual(field, "path")
        self.assertNotIn("Users", reason)

    def test_declared_path_field_type_has_fixed_rejection_reason(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({
            "jsonrpc": "2.0", "id": 14, "method": "fs/getMetadata",
            "params": {"path": None},
        }).encode("utf-8")
        child, error, reason, field = _map_request_payload_with_reason(mapper, raw)
        self.assertIsNone(child)
        self.assertIsNotNone(error)
        self.assertEqual(reason, "invalid-path-field-type")
        self.assertEqual(field, "path")

    def test_container_namespace_rejection_reason_is_distinct(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({
            "jsonrpc": "2.0", "id": 12, "method": "fs/getMetadata",
            "params": {"path": "file:///var/private.txt"},
        }).encode("utf-8")
        child, error, reason, field = _map_request_payload_with_reason(mapper, raw)
        self.assertIsNone(child)
        self.assertIsNotNone(error)
        self.assertEqual(reason, "container-path-outside-declared-mount")
        self.assertEqual(field, "path")

    def test_raw_posix_path_stays_in_container_namespace(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({
            "jsonrpc": "2.0", "id": 13, "method": "fs/getMetadata",
            "params": {"path": "/var/private.txt"},
        }).encode("utf-8")
        child, error, reason, field = _map_request_payload_with_reason(mapper, raw)
        self.assertIsNone(child)
        self.assertIsNotNone(error)
        self.assertEqual(reason, "container-path-outside-declared-mount")
        self.assertEqual(field, "path")

    def test_config_path_shape_has_fixed_rejection_reason(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({
            "jsonrpc": "2.0", "id": 11, "method": "environmentConfig/read",
            "params": {"cwd": r"C:\DevWorks\candidate", "configPaths": [r"C:\DevWorks\candidate\config.toml"]},
        }).encode("utf-8")
        child, error, reason, field = _map_request_payload_with_reason(mapper, raw)
        self.assertIsNone(child)
        self.assertIsNotNone(error)
        self.assertEqual(reason, "invalid-path-array-shape")
        self.assertEqual(field, "configPaths")

    def test_relative_environment_config_path_is_bounded_to_candidate(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({
            "jsonrpc": "2.0", "id": 16, "method": "environmentConfig/read",
            "params": {"cwd": "/run/candidate", "configPaths": [["config.toml"]]},
        }).encode("utf-8")
        child, error, reason, field = _map_request_payload_with_reason(mapper, raw)
        self.assertIsNotNone(child)
        self.assertIsNone(error)
        self.assertIsNone(reason)
        self.assertIsNone(field)
        self.assertEqual(json.loads(child)["params"]["configPaths"], [["/run/candidate/config.toml"]])

    def test_host_traversal_has_specific_rejection_reason(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({
            "jsonrpc": "2.0", "id": 17, "method": "fs/getMetadata",
            "params": {"path": r"C:\DevWorks\candidate\..\private.txt"},
        }).encode("utf-8")
        child, error, reason, field = _map_request_payload_with_reason(mapper, raw)
        self.assertIsNone(child)
        self.assertIsNotNone(error)
        self.assertEqual(reason, "host-path-traversal")
        self.assertEqual(field, "path")

    def test_container_traversal_has_specific_rejection_reason(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({
            "jsonrpc": "2.0", "id": 18, "method": "fs/getMetadata",
            "params": {"path": "/run/candidate/../private.txt"},
        }).encode("utf-8")
        child, error, reason, field = _map_request_payload_with_reason(mapper, raw)
        self.assertIsNone(child)
        self.assertIsNotNone(error)
        self.assertEqual(reason, "container-path-traversal")
        self.assertEqual(field, "path")

    def test_config_cwd_namespace_rejection_identifies_cwd_field(self):
        mapper = RpcPathMapper.from_mounts([
            {"source": r"C:\DevWorks\candidate", "destination": "/run/candidate", "access": "rw"},
        ])
        raw = json.dumps({
            "jsonrpc": "2.0", "id": 15, "method": "environmentConfig/read",
            "params": {"cwd": "/var/private", "configPaths": [], "requirementsPaths": []},
        }).encode("utf-8")
        child, error, reason, field = _map_request_payload_with_reason(mapper, raw)
        self.assertIsNone(child)
        self.assertIsNotNone(error)
        self.assertEqual(reason, "container-path-outside-declared-mount")
        self.assertEqual(field, "cwd")

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
