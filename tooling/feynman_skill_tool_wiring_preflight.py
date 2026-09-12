#!/usr/bin/env python3
"""Verify candidate skill discovery and fixed full-runner wiring without a model.

The preflight binds an existing LOG-052 artifact to its runner job/profile,
uses Codex App Server ``skills/list`` plus MCP status discovery, and invokes
only the no-argument fixed test tool.  It does not start a thread or turn,
authenticate, call a model, read the protected control CODEX_HOME, invoke the
write tool, or preserve candidate/test payloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
from typing import Any, Sequence

try:
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_eval_preflight import preflight as filesystem_skill_preflight
    from .feynman_full_runner_contract import (
        FIXED_CANDIDATE_FILE,
        FIXED_TEST_COMMAND,
        SERVER_NAME,
        TEST_TOOL_NAME,
        TOOL_NAMES,
        build_full_runner_override,
    )
    from .feynman_mcp_catalog_preflight import summarize_status
    from .feynman_runner_job_validate import _load as load_job
    from .feynman_runner_job_validate import validate_job
except ImportError:
    from feynman_boundary_profile import validate_profile_file
    from feynman_eval_preflight import preflight as filesystem_skill_preflight
    from feynman_full_runner_contract import (
        FIXED_CANDIDATE_FILE,
        FIXED_TEST_COMMAND,
        SERVER_NAME,
        TEST_TOOL_NAME,
        TOOL_NAMES,
        build_full_runner_override,
    )
    from feynman_mcp_catalog_preflight import summarize_status
    from feynman_runner_job_validate import _load as load_job
    from feynman_runner_job_validate import validate_job


SYSTEM_ENV_KEYS = ("PATH", "SystemRoot", "WINDIR", "ComSpec", "PATHEXT", "TEMP", "TMP")
RETIRED_AUTH_KEYS = ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN")
EXPECTED_BINDING_VERDICT = "full-runner-mcp-artifact-chain-bound"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    absolute = path.expanduser().absolute()
    if absolute.is_symlink() or not absolute.is_file():
        raise ValueError(f"{label} must be a regular file")
    value = json.loads(absolute.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} JSON root must be an object")
    return value


def _directory(path: Path, label: str, *, empty: bool = False) -> Path:
    absolute = path.expanduser().absolute()
    if absolute.is_symlink() or not absolute.is_dir():
        raise ValueError(f"{label} must be an existing directory")
    if empty and any(absolute.iterdir()):
        raise ValueError(f"{label} must be empty")
    return absolute.resolve(strict=True)


def _regular(path: Path, label: str) -> Path:
    absolute = path.expanduser().absolute()
    if absolute.is_symlink() or not absolute.is_file():
        raise ValueError(f"{label} must be a regular file")
    return absolute.resolve(strict=True)


def _inside(root: Path, path: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _safe_env(*, codex_home: Path, candidate_home: Path, temp_dir: Path,
              node_bin: Path | None = None) -> dict[str, str]:
    result = {key: os.environ[key] for key in SYSTEM_ENV_KEYS if os.environ.get(key)}
    if node_bin is not None:
        result["PATH"] = str(node_bin.parent) + os.pathsep + result.get("PATH", "")
    result.update({
        "CODEX_HOME": str(codex_home),
        "HOME": str(candidate_home),
        "USERPROFILE": str(candidate_home),
        "TEMP": str(temp_dir),
        "TMP": str(temp_dir),
        "TMPDIR": str(temp_dir),
    })
    for key in RETIRED_AUTH_KEYS:
        result.pop(key, None)
    return result


def _request(identifier: int, method: str, params: dict[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "id": identifier,
                        "method": method, "params": params}) + "\n").encode()


def _notification(method: str, params: dict[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n").encode()


def _reader(stream: Any, received: queue.Queue[dict[str, Any] | None]) -> None:
    try:
        for line in stream:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                received.put(None)
                continue
            if isinstance(value, dict):
                received.put(value)
    except OSError:
        received.put(None)


def _rpc(process: subprocess.Popen[bytes], received: queue.Queue[dict[str, Any] | None],
         identifier: int, method: str, params: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    assert process.stdin is not None
    process.stdin.write(_request(identifier, method, params))
    process.stdin.flush()
    while True:
        value = received.get(timeout=timeout_seconds)
        if value is None:
            raise ValueError("protocol emitted invalid JSON")
        if value.get("id") == identifier:
            return value


def _close(process: subprocess.Popen[bytes], reader: threading.Thread) -> None:
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=10)
    reader.join(timeout=2)


def _binding_lineage(binding: dict[str, Any], job: dict[str, Any],
                     job_path: Path, profile_sha: str) -> None:
    if binding.get("schema_version") != 1 or binding.get("verdict") != EXPECTED_BINDING_VERDICT:
        raise ValueError("full-runner binding artifact is not canonical")
    info = job["job"]
    expected = {
        "run_id": job["run_id"],
        "case_id": info["case_id"],
        "condition_id": info["condition_id"],
        "model": job["versions"]["model"],
        "codex_cli": job["versions"]["codex_cli"],
    }
    if any(binding.get(field) != value for field, value in expected.items()):
        raise ValueError("full-runner binding identity differs from runner job")
    lineage = binding.get("lineage")
    if not isinstance(lineage, dict):
        raise ValueError("full-runner binding lineage is missing")
    expected_lineage = {
        "runner_job_sha256": _sha(job_path),
        "boundary_profile_sha256": profile_sha,
        "eval_plan_sha256": job["digests"]["eval_plan_sha256"],
        "candidate_prompt_sha256": job["digests"]["candidate_prompt_sha256"],
        "runtime_sha256": job["digests"]["runtime_sha256"],
    }
    if lineage != expected_lineage:
        raise ValueError("full-runner binding lineage drift")
    checks = binding.get("checks")
    if not isinstance(checks, dict) or checks.get("model_calls") != 0 or checks.get("authentication_used") is not False:
        raise ValueError("full-runner binding is not model-free")


def _task_invocation(job: dict[str, Any], candidate: Path) -> dict[str, Any]:
    task = _regular(candidate / "task.txt", "candidate task")
    if _sha(task) != job["digests"]["candidate_prompt_sha256"]:
        raise ValueError("candidate task digest differs from runner job")
    text = task.read_text(encoding="utf-8")
    marker_present = text.startswith("$feynman-thinking")
    expected_skills = job["skills"]["expected_candidate_skills"]
    should_invoke = expected_skills == ["feynman-thinking"]
    if marker_present != should_invoke:
        raise ValueError("candidate task explicit skill marker differs from condition")
    return {
        "prompt_sha256": _sha(task),
        "explicit_marker": "$feynman-thinking" if marker_present else None,
        "explicit_invocation_expected": should_invoke,
        "prompt_payload_preserved": False,
    }


def _classify_skills(result: Any, *, candidate: Path) -> tuple[list[str], list[tuple[str, Path]]]:
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise ValueError("skills/list result has no data list")
    if len(result["data"]) != 1 or not isinstance(result["data"][0], dict):
        raise ValueError("skills/list must return exactly one cwd result")
    entry = result["data"][0]
    skills = entry.get("skills")
    errors = entry.get("errors")
    if not isinstance(skills, list) or not isinstance(errors, list) or errors:
        raise ValueError("skills/list returned invalid skills or discovery errors")
    candidate_root = (candidate / ".agents" / "skills").resolve(strict=False)
    candidate_names: list[str] = []
    non_candidate_enabled: list[tuple[str, Path]] = []
    for skill in skills:
        if not isinstance(skill, dict) or not isinstance(skill.get("name"), str):
            raise ValueError("skills/list returned an invalid skill entry")
        if skill.get("enabled") is False:
            continue
        raw_path = skill.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError("skills/list skill path is missing")
        skill_path = Path(raw_path).expanduser().absolute().resolve(strict=False)
        if _inside(candidate_root, skill_path):
            candidate_names.append(skill["name"])
        else:
            non_candidate_enabled.append((skill["name"], skill_path))
    candidate_names.sort()
    non_candidate_enabled.sort(key=lambda item: (item[0], str(item[1])))
    return candidate_names, non_candidate_enabled


def _summarize_skills(result: Any, *, candidate: Path,
                      expected_names: Sequence[str]) -> dict[str, Any]:
    candidate_names, non_candidate_entries = _classify_skills(result, candidate=candidate)
    non_candidate_enabled = [name for name, _ in non_candidate_entries]
    if candidate_names != sorted(expected_names):
        raise ValueError("App Server candidate skill set differs from runner job")
    if non_candidate_enabled:
        raise ValueError(
            "App Server exposed non-candidate enabled skills: "
            + ", ".join(non_candidate_enabled)
        )
    return {
        "candidate_skill_names": candidate_names,
        "non_candidate_enabled_skill_count": 0,
        "discovery_errors": 0,
        "force_reload": True,
        "skill_paths_preserved": False,
        "descriptions_preserved": False,
    }


def _skill_disable_override(entries: Sequence[tuple[str, Path]]) -> str:
    if not entries:
        raise ValueError("skill disable override requires at least one skill")
    values = ",".join(
        "{path=" + json.dumps(str(path), ensure_ascii=True) + ",enabled=false}"
        for _, path in entries
    )
    return "skills.config=[" + values + "]"


def _app_server_session(*, codex_bin: Path, codex_home: Path, candidate_home: Path,
                        temp_dir: Path, candidate: Path,
                        config_overrides: Sequence[str], timeout_seconds: int,
                        include_mcp: bool) -> tuple[dict[str, Any], dict[str, Any] | None]:
    command = [str(codex_bin), "app-server"]
    for value in config_overrides:
        command.extend(("-c", value))
    command.append("--stdio")
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=_safe_env(codex_home=codex_home, candidate_home=candidate_home,
                      temp_dir=temp_dir), bufsize=0,
    )
    assert process.stdout is not None
    received: queue.Queue[dict[str, Any] | None] = queue.Queue()
    reader = threading.Thread(target=_reader, args=(process.stdout, received), daemon=True)
    reader.start()
    try:
        initialized = _rpc(process, received, 1, "initialize", {
            "clientInfo": {"name": "feynman-skill-tool-wiring-preflight", "version": "0.1.0"},
        }, timeout_seconds)
        if "error" in initialized:
            raise ValueError("App Server initialize failed")
        assert process.stdin is not None
        process.stdin.write(_notification("initialized", {}))
        process.stdin.flush()
        skill_response = _rpc(process, received, 2, "skills/list", {
            "cwds": [str(candidate)], "forceReload": True,
        }, timeout_seconds)
        if "error" in skill_response:
            raise ValueError("App Server skills/list failed")
        catalog = None
        if include_mcp:
            status = _rpc(process, received, 3, "mcpServerStatus/list", {
                "detail": "toolsAndAuthOnly", "limit": 10,
            }, timeout_seconds)
            if "error" in status:
                raise ValueError("App Server MCP status failed")
            catalog = summarize_status(
                status.get("result"), target_tool=TEST_TOOL_NAME, target_tools=TOOL_NAMES)
    finally:
        _close(process, reader)
    if process.returncode != 0:
        raise ValueError("App Server did not exit cleanly")
    return skill_response.get("result", {}), catalog


def _app_server_probe(*, codex_bin: Path, codex_home: Path, candidate_home: Path,
                      temp_dir: Path, candidate: Path, override: Any,
                      expected_skills: Sequence[str], timeout_seconds: int) -> dict[str, Any]:
    initial_skills, _ = _app_server_session(
        codex_bin=codex_bin, codex_home=codex_home,
        candidate_home=candidate_home, temp_dir=temp_dir,
        candidate=candidate, config_overrides=override.values,
        timeout_seconds=timeout_seconds, include_mcp=False,
    )
    initial_candidate_names, non_candidate_entries = _classify_skills(
        initial_skills, candidate=candidate)
    if initial_candidate_names != sorted(expected_skills):
        raise ValueError("initial App Server candidate skill set differs from runner job")
    disabled_names = [name for name, _ in non_candidate_entries]
    final_overrides = list(override.values)
    if non_candidate_entries:
        final_overrides.append(_skill_disable_override(non_candidate_entries))
    final_skills, catalog = _app_server_session(
        codex_bin=codex_bin, codex_home=codex_home,
        candidate_home=candidate_home, temp_dir=temp_dir,
        candidate=candidate, config_overrides=final_overrides,
        timeout_seconds=timeout_seconds, include_mcp=True,
    )
    skill_summary = _summarize_skills(
        final_skills, candidate=candidate, expected_names=expected_skills)
    if catalog is None:
        raise ValueError("App Server MCP catalog was not returned")
    if catalog.get("server_count") != 1:
        raise ValueError("App Server full-runner server count differs")
    server = catalog["servers"][0]
    if (server.get("name") != SERVER_NAME or server.get("tool_names") != sorted(TOOL_NAMES)
            or server.get("tools_error_present") is not False):
        raise ValueError("App Server full-runner tool catalog differs")
    return {
        "initialize_ok": True,
        "skills": {
            **skill_summary,
            "initial_non_candidate_enabled_skill_names": sorted(disabled_names),
            "transiently_disabled_non_candidate_skill_count": len(non_candidate_entries),
            "disable_paths_preserved": False,
            "second_pass_verified": True,
        },
        "mcp": {
            "server_name": server["name"],
            "tool_names": server["tool_names"],
            "tools_error_present": False,
        },
    }


def _fixed_test_probe(*, node_bin: Path, adapter: Path, docker_bin: Path,
                      docker_config: Path, docker_image_id: str, candidate: Path,
                      candidate_home: Path, temp_dir: Path,
                      timeout_seconds: int) -> dict[str, Any]:
    environment = _safe_env(
        codex_home=candidate_home / ".unused-codex-home",
        candidate_home=candidate_home,
        temp_dir=temp_dir,
        node_bin=node_bin,
    )
    environment.update({
        "FEYNMAN_FULL_RUNNER_ROOT": str(candidate),
        "FEYNMAN_FULL_RUNNER_DOCKER": str(docker_bin),
        "FEYNMAN_FULL_RUNNER_DOCKER_CONFIG": str(docker_config),
        "FEYNMAN_FULL_RUNNER_IMAGE": docker_image_id,
    })
    before = _sha(candidate / FIXED_CANDIDATE_FILE)
    process = subprocess.Popen(
        [str(node_bin), str(adapter)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=environment, bufsize=0,
    )
    assert process.stdout is not None
    received: queue.Queue[dict[str, Any] | None] = queue.Queue()
    reader = threading.Thread(target=_reader, args=(process.stdout, received), daemon=True)
    reader.start()
    try:
        initialized = _rpc(process, received, 1, "initialize", {}, timeout_seconds)
        if "error" in initialized:
            raise ValueError("full-runner adapter initialize failed")
        assert process.stdin is not None
        process.stdin.write(_notification("notifications/initialized", {}))
        process.stdin.flush()
        response = _rpc(process, received, 2, "tools/call", {
            "name": TEST_TOOL_NAME, "arguments": {},
        }, max(timeout_seconds, 90))
    finally:
        _close(process, reader)
    after = _sha(candidate / FIXED_CANDIDATE_FILE)
    if process.returncode != 0:
        raise ValueError("full-runner adapter did not exit cleanly")
    content = response.get("result", {}).get("content")
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict):
        raise ValueError("fixed test response payload shape differs")
    try:
        metadata = json.loads(content[0].get("text", ""))
    except json.JSONDecodeError as exc:
        raise ValueError("fixed test response metadata is invalid") from exc
    if not isinstance(metadata, dict):
        raise ValueError("fixed test response metadata must be an object")
    if metadata.get("file") != "test_candidate.py" or metadata.get("networkMode") != "none":
        raise ValueError("fixed test response policy labels differ")
    if metadata.get("started") is not True or metadata.get("timedOut") is not False:
        raise ValueError("fixed test command did not complete")
    if before != after:
        raise ValueError("fixed test command changed candidate.py")
    passed = metadata.get("passed") is True
    result_is_error = response.get("result", {}).get("isError") is True
    if result_is_error == passed:
        raise ValueError("fixed test result error flag differs from pass status")
    return {
        "tool_name": TEST_TOOL_NAME,
        "fixed_command": list(FIXED_TEST_COMMAND),
        "started": True,
        "timed_out": False,
        "exit_code": metadata.get("exitCode"),
        "candidate_test_passed": passed,
        "candidate_test_outcome": "passed" if passed else "failed",
        "candidate_source_unchanged": True,
        "network_mode": "none",
        "raw_stdout_preserved": False,
        "raw_stderr_preserved": False,
        "tool_payload_preserved": False,
        "write_tool_invoked": False,
    }


def run(*, runner_job_path: Path, boundary_profile_path: Path,
        binding_path: Path, codex_bin: Path, codex_home: Path,
        node_bin: Path, adapter: Path, docker_bin: Path, docker_config: Path,
        output: Path, timeout_seconds: int = 30) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise ValueError("wiring preflight output must be new")
    runner_job_path = _regular(runner_job_path, "runner job")
    boundary_profile_path = _regular(boundary_profile_path, "boundary profile")
    binding_path = _regular(binding_path, "full-runner binding")
    codex_bin = _regular(codex_bin, "Codex executable")
    codex_home = _directory(codex_home, "isolated preflight CODEX_HOME", empty=True)
    node_bin = _regular(node_bin, "Node executable")
    adapter = _regular(adapter, "full-runner adapter")
    docker_bin = _regular(docker_bin, "Docker executable")
    docker_config = _directory(docker_config, "Docker config directory")
    job = load_job(runner_job_path)
    profile, profile_sha, _ = validate_profile_file(boundary_profile_path)
    if validate_job(job, profile, profile_sha).get("verdict") != "runner-job-valid":
        raise ValueError("runner job/profile validation failed")
    binding = _json(binding_path, "full-runner binding")
    _binding_lineage(binding, job, runner_job_path, profile_sha)
    candidate = _directory(Path(job["paths"]["candidate_dir"]), "candidate directory")
    candidate_home = _directory(Path(job["paths"]["ephemeral_home"]), "candidate HOME")
    candidate_codex_home = _directory(Path(job["paths"]["codex_home"]), "candidate CODEX_HOME")
    temp_dir = _directory(Path(job["paths"]["temp_dir"]), "candidate temp directory")
    expected_skills = job["skills"]["expected_candidate_skills"]
    filesystem = filesystem_skill_preflight(
        candidate, set(expected_skills), home=candidate_home, codex_home=candidate_codex_home)
    task = _task_invocation(job, candidate)
    full_runner = binding.get("full_runner")
    if not isinstance(full_runner, dict):
        raise ValueError("binding full_runner block is missing")
    docker_image_id = full_runner.get("docker_image_id")
    if not isinstance(docker_image_id, str):
        raise ValueError("binding full-runner image ID is missing")
    override = build_full_runner_override(
        node_bin=node_bin, adapter=adapter, candidate=candidate,
        docker_bin=docker_bin, docker_config=docker_config,
        docker_image_id=docker_image_id,
    )
    expected_override = {
        "server_name": SERVER_NAME,
        "tool_names": list(TOOL_NAMES),
        "adapter_sha256": override.adapter_sha256,
        "docker_image_id": override.docker_image_id,
        "initial_candidate_sha256": override.initial_candidate_sha256,
        "test_sha256": override.test_sha256,
        "fixed_candidate_file": FIXED_CANDIDATE_FILE,
        "fixed_test_command": list(FIXED_TEST_COMMAND),
        "network_mode": "none",
    }
    if any(full_runner.get(field) != value for field, value in expected_override.items()):
        raise ValueError("binding full-runner implementation lineage drift")
    app_server = _app_server_probe(
        codex_bin=codex_bin, codex_home=codex_home,
        candidate_home=candidate_home, temp_dir=temp_dir,
        candidate=candidate, override=override, expected_skills=expected_skills,
        timeout_seconds=timeout_seconds,
    )
    fixed_test = _fixed_test_probe(
        node_bin=node_bin, adapter=adapter, docker_bin=docker_bin,
        docker_config=docker_config, docker_image_id=docker_image_id,
        candidate=candidate, candidate_home=candidate_home, temp_dir=temp_dir,
        timeout_seconds=timeout_seconds,
    )
    result = {
        "schema_version": 1,
        "verdict": "full-runner-skill-tool-wiring-ready",
        "run_id": job["run_id"],
        "case_id": job["job"]["case_id"],
        "condition_id": job["job"]["condition_id"],
        "model": job["versions"]["model"],
        "lineage": {
            "runner_job_sha256": _sha(runner_job_path),
            "boundary_profile_sha256": profile_sha,
            "full_runner_binding_sha256": _sha(binding_path),
            "candidate_prompt_sha256": job["digests"]["candidate_prompt_sha256"],
            "runtime_sha256": job["digests"]["runtime_sha256"],
            "adapter_sha256": override.adapter_sha256,
            "docker_image_id": docker_image_id,
        },
        "checks": {
            "runner_job_profile_valid": True,
            "binding_lineage_valid": True,
            "filesystem_candidate_skill_set_exact": (
                sorted(filesystem["observed_candidate_skills"]) == sorted(expected_skills)),
            "explicit_skill_invocation_bound": True,
            "app_server_candidate_skill_set_exact": True,
            "non_candidate_enabled_skills_absent": True,
            "full_runner_catalog_exact": True,
            "fixed_test_command_started": True,
            "candidate_source_unchanged": True,
            "model_calls": 0,
            "authentication_used": False,
        },
        "skill_exposure": {
            "expected_candidate_skills": list(expected_skills),
            "filesystem_observed_candidate_skills": sorted(filesystem["observed_candidate_skills"]),
            "app_server": app_server["skills"],
            "task_invocation": task,
        },
        "tool_wiring": {
            "mcp": app_server["mcp"],
            "fixed_test": fixed_test,
        },
        "privacy": {
            "model_request_started": False,
            "thread_started": False,
            "turn_started": False,
            "authentication_used": False,
            "control_codex_home_read": False,
            "credential_files_read": False,
            "candidate_prompt_payload_preserved": False,
            "candidate_source_payload_preserved": False,
            "test_output_payload_preserved": False,
        },
        "scope": (
            "model-free candidate skill discovery and fixed full-runner test wiring; "
            "candidate test outcome is diagnostic and is not model or skill performance evidence"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-job", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--codex-bin", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--node-bin", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--docker-bin", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    try:
        result = run(
            runner_job_path=args.runner_job,
            boundary_profile_path=args.boundary_profile,
            binding_path=args.binding,
            codex_bin=args.codex_bin,
            codex_home=args.codex_home,
            node_bin=args.node_bin,
            adapter=args.adapter,
            docker_bin=args.docker_bin,
            docker_config=args.docker_config,
            output=args.output,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError,
            queue.Empty, subprocess.SubprocessError) as exc:
        parser.exit(2, "error: skill/tool wiring preflight failed: " + type(exc).__name__ + "\n")
    print(json.dumps({
        "verdict": result["verdict"],
        "model": result["model"],
        "condition_id": result["condition_id"],
        "candidate_test_outcome": result["tool_wiring"]["fixed_test"]["candidate_test_outcome"],
        "model_calls": result["checks"]["model_calls"],
        "authentication_used": result["checks"]["authentication_used"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
