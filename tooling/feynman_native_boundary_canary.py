#!/usr/bin/env python3
"""Run and verify the native Windows Docker boundary canary.

The canary exercises only synthetic file, environment, and network controls.
It reuses the validated runner-job/profile mount contract, starts the supplied
candidate image with the Node probe source passed as an exact eval string, and
keeps evaluator-side marker checks in the host namespace. It never launches a
ChatGPT model or reads control-plane authentication material.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import threading
from typing import Any

try:
    from .feynman_boundary_probe_verify import verify as verify_probe
    from .feynman_boundary_profile import validate_profile_file
    from .feynman_docker_reference_inspect import verify_reference
    from .feynman_network_reference import endpoint_identity
    from .feynman_path_mapping import mounts_for_job
    from .feynman_remote_exec_environment import expected_docker_args
    from .feynman_runner_job_validate import _load as load_job, validate_job_files
except ImportError:
    from feynman_boundary_probe_verify import verify as verify_probe
    from feynman_boundary_profile import validate_profile_file
    from feynman_docker_reference_inspect import verify_reference
    from feynman_network_reference import endpoint_identity
    from feynman_path_mapping import mounts_for_job
    from feynman_remote_exec_environment import expected_docker_args
    from feynman_runner_job_validate import _load as load_job, validate_job_files

CONTAINER_CANARY_ROOT = "/run/candidate/.feynman-boundary-canary"
CONTAINER_PROTECTED_ROOTS = {
    "evaluator": "/run/evaluator",
    "source": "/run/source",
    "real_home": "/run/real-home",
}
MARKERS = {
    "candidate_read": "candidate-marker",
    "evaluator_read": "evaluator-marker",
    "source_read": "source-marker",
    "real_home_read": "real-home-marker",
    "candidate_write": "candidate-write-marker",
    "forbidden_write": "should-not-write",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular(path: Path, label: str) -> Path:
    value = path.expanduser().absolute()
    if value.is_symlink() or not value.is_file():
        raise ValueError(f"{label} must be a regular file: {value}")
    return value.resolve()


def _directory(path: Path, label: str) -> Path:
    value = path.expanduser().absolute()
    if value.is_symlink() or not value.is_dir():
        raise ValueError(f"{label} must be a real directory: {value}")
    return value.resolve()


def _inside(root: Path, child: Path) -> bool:
    return child == root or child.is_relative_to(root)


def _docker_call(docker: Path, config: Path, args: list[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]:
    command = [str(docker), "--config", str(config), *args]
    try:
        return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"docker {args[0]} timed out after {timeout:g}s") from exc


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace").strip()


def _require_success(result: subprocess.CompletedProcess[bytes], operation: str) -> str:
    if result.returncode != 0:
        raise RuntimeError(f"docker {operation} failed with exit code {result.returncode}")
    return _decode(result.stdout)


class _LoopbackListener:
    def __init__(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(8)
        self.socket.settimeout(0.2)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def port(self) -> int:
        return int(self.socket.getsockname()[1])

    def __enter__(self) -> "_LoopbackListener":
        self.thread.start()
        return self

    def _serve(self) -> None:
        while not self.stop.is_set():
            try:
                connection, _ = self.socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            connection.close()

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        self.socket.close()
        self.thread.join(timeout=1.0)


def _write_marker(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(marker, encoding="utf-8")


def _prepare_fixtures(*, candidate_dir: Path, output_dir: Path) -> dict[str, Any]:
    candidate_canary = candidate_dir / ".feynman-boundary-canary"
    if candidate_canary.exists() or candidate_canary.is_symlink():
        raise FileExistsError(f"refusing to overwrite candidate canary directory: {candidate_canary}")
    candidate_canary.mkdir(mode=0o700)

    fixtures = output_dir / "protected-fixtures"
    for name, marker in (
        ("candidate_read", MARKERS["candidate_read"]),
        ("evaluator_read", MARKERS["evaluator_read"]),
        ("source_read", MARKERS["source_read"]),
        ("real_home_read", MARKERS["real_home_read"]),
    ):
        if name == "candidate_read":
            path = candidate_canary / "read-canary.txt"
        else:
            path = fixtures / name.removesuffix("_read") / "read-canary.txt"
        _write_marker(path, marker)

    candidate_write = candidate_canary / "write-canary.txt"
    forbidden_writes = [
        fixtures / "evaluator" / "forbidden-write.txt",
        fixtures / "source" / "forbidden-write.txt",
        fixtures / "real_home" / "forbidden-write.txt",
    ]
    for path in forbidden_writes:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"refusing to overwrite forbidden-write fixture: {path}")

    return {
        "candidate_canary": candidate_canary,
        "candidate_read": candidate_canary / "read-canary.txt",
        "evaluator_read": fixtures / "evaluator" / "read-canary.txt",
        "source_read": fixtures / "source" / "read-canary.txt",
        "real_home_read": fixtures / "real_home" / "read-canary.txt",
        "candidate_write": candidate_write,
        "forbidden_writes": forbidden_writes,
    }


def _native_probe_args(*, job: dict[str, Any], profile: dict[str, Any], profile_sha: str,
                       probe_source: str, probe_sha: str, network_port: int) -> list[str]:
    remote = expected_docker_args(job, profile)
    image_index = remote.index(profile["image"])
    prefix = remote[:image_index + 1]
    tail = remote[image_index + 1:]
    if len(tail) < 3 or tail[0:2] != ["env", "-i"] or "codex" not in tail:
        raise ValueError("canonical remote environment does not expose env -i command tail")
    codex_index = tail.index("codex")
    env_assignments = tail[2:codex_index]
    run_id = f"{job['run_id']}-native-boundary"
    container_artifact = f"{CONTAINER_CANARY_ROOT}/probe-artifact.json"
    container_forbidden = [
        f"{CONTAINER_PROTECTED_ROOTS['evaluator']}/forbidden-write.txt",
        f"{CONTAINER_PROTECTED_ROOTS['source']}/forbidden-write.txt",
        f"{CONTAINER_PROTECTED_ROOTS['real_home']}/forbidden-write.txt",
    ]
    probe = [
        "env", "-i", *env_assignments,
        "/usr/local/bin/node", "--input-type=module", "--eval", probe_source, "--",
        "--run-id", run_id,
        "--boundary-profile-sha256", profile_sha,
        "--program-sha256", probe_sha,
        "--path-namespace", "container",
        "--candidate-read", f"{CONTAINER_CANARY_ROOT}/read-canary.txt",
        "--candidate-read-marker", MARKERS["candidate_read"],
        "--evaluator-read", f"{CONTAINER_PROTECTED_ROOTS['evaluator']}/read-canary.txt",
        "--source-read", f"{CONTAINER_PROTECTED_ROOTS['source']}/read-canary.txt",
        "--real-home-read", f"{CONTAINER_PROTECTED_ROOTS['real_home']}/read-canary.txt",
        "--candidate-write", f"{CONTAINER_CANARY_ROOT}/write-canary.txt",
        "--candidate-write-marker", MARKERS["candidate_write"],
    ]
    for path in container_forbidden:
        probe.extend(["--forbidden-write", path])
    probe.extend([
        "--forbidden-write-marker", MARKERS["forbidden_write"],
        "--network-host", "127.0.0.1",
        "--network-port", str(network_port),
        "--network-timeout", "1.5",
        "--output", container_artifact,
    ])
    return prefix + probe


def run_canary(*, job_path: Path, profile_path: Path, probe_program: Path,
               docker: Path, docker_config: Path, output_dir: Path,
               timeout: float = 60.0) -> dict[str, Any]:
    job_path = _regular(job_path, "runner job")
    profile_path = _regular(profile_path, "boundary profile")
    probe_program = _regular(probe_program, "Node boundary probe")
    docker = _regular(docker, "Docker executable")
    docker_config = _directory(docker_config, "Docker config")
    output_dir = output_dir.expanduser().absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"refusing to overwrite output directory: {output_dir}")
    output_dir.mkdir(parents=True, mode=0o700)

    job = load_job(job_path)
    profile, profile_sha, profile_result = validate_profile_file(profile_path)
    job_result = validate_job_files(job_path, profile_path)
    if job_result.get("verdict") != "runner-job-valid":
        raise ValueError("runner job failed strict validation")
    if profile_result.get("verdict") != "profile-valid":
        raise ValueError("boundary profile failed strict validation")
    paths = job.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("runner job has no paths object")
    candidate_dir = _directory(Path(paths["candidate_dir"]), "candidate directory")
    mounts = mounts_for_job(job, profile)
    probe_source = probe_program.read_text(encoding="utf-8")
    probe_sha = _sha(probe_program)
    container_name = f"feynman-native-boundary-{job['run_id']}"[:120]
    candidate_canary: Path | None = None
    container_created = False
    cleanup_error: Exception | None = None

    with _LoopbackListener() as listener:
        network_reference = {
            "schema_version": 1,
            "host": "127.0.0.1",
            "port": listener.port,
            "reachable_from_control_plane": True,
            "probe_method": "tcp-connect:v1",
            "endpoint_identity_sha256": endpoint_identity("127.0.0.1", listener.port),
        }
        network_reference_path = output_dir / "network-reference.json"
        network_reference_path.write_text(json.dumps(network_reference, indent=2) + "\n", encoding="utf-8")
        fixtures = _prepare_fixtures(candidate_dir=candidate_dir, output_dir=output_dir)
        candidate_canary = fixtures["candidate_canary"]
        source_artifact_path = candidate_canary / "probe-artifact.json"
        probe_report_path = output_dir / "probe-report.json"
        inspect_path = output_dir / "container-inspect.json"
        inspect_check_path = output_dir / "container-inspect-check.json"

        try:
            docker_args = _native_probe_args(
                job=job,
                profile=profile,
                profile_sha=profile_sha,
                probe_source=probe_source,
                probe_sha=probe_sha,
                network_port=listener.port,
            )
            docker_args[0] = "create"
            docker_args[2] = container_name
            created = _docker_call(docker, docker_config, docker_args, timeout=timeout)
            _require_success(created, "create")
            container_created = True

            inspected = _docker_call(docker, docker_config, ["inspect", container_name], timeout=timeout)
            inspect_text = _require_success(inspected, "inspect")
            inspect_path.write_text(inspect_text + "\n", encoding="utf-8")
            inspect_payload = json.loads(inspect_text)
            inspect_result = verify_reference(profile, inspect_payload, expected_mounts=mounts)
            inspect_check_path.write_text(json.dumps(inspect_result, indent=2) + "\n", encoding="utf-8")

            started = _docker_call(docker, docker_config, ["start", "-a", container_name], timeout=timeout)
            _require_success(started, "start")
            if not source_artifact_path.is_file():
                raise ValueError("native boundary probe did not produce an artifact")

            report = verify_probe(
                artifact_path=source_artifact_path,
                expected_run_id=f"{job['run_id']}-native-boundary",
                expected_boundary_profile_sha256=profile_sha,
                probe_program=probe_program,
                candidate_read=fixtures["candidate_read"],
                candidate_read_marker=MARKERS["candidate_read"],
                evaluator_read=fixtures["evaluator_read"],
                evaluator_read_marker=MARKERS["evaluator_read"],
                source_read=fixtures["source_read"],
                source_read_marker=MARKERS["source_read"],
                real_home_read=fixtures["real_home_read"],
                real_home_read_marker=MARKERS["real_home_read"],
                candidate_write=fixtures["candidate_write"],
                candidate_write_marker=MARKERS["candidate_write"],
                forbidden_writes=fixtures["forbidden_writes"],
                container_candidate_read=f"{CONTAINER_CANARY_ROOT}/read-canary.txt",
                container_evaluator_read=f"{CONTAINER_PROTECTED_ROOTS['evaluator']}/read-canary.txt",
                container_source_read=f"{CONTAINER_PROTECTED_ROOTS['source']}/read-canary.txt",
                container_real_home_read=f"{CONTAINER_PROTECTED_ROOTS['real_home']}/read-canary.txt",
                container_candidate_write=f"{CONTAINER_CANARY_ROOT}/write-canary.txt",
                container_forbidden_writes=[
                    f"{CONTAINER_PROTECTED_ROOTS['evaluator']}/forbidden-write.txt",
                    f"{CONTAINER_PROTECTED_ROOTS['source']}/forbidden-write.txt",
                    f"{CONTAINER_PROTECTED_ROOTS['real_home']}/forbidden-write.txt",
                ],
                network_reference=network_reference_path,
                require_network_denied=True,
            )
            probe_report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            artifact_copy = output_dir / "probe-artifact.json"
            shutil.copy2(source_artifact_path, artifact_copy)
            result = {
                "schema_version": 1,
                "verdict": "native-boundary-canary-passed",
                "run_id": job["run_id"],
                "boundary_profile_sha256": profile_sha,
                "image": profile["image"],
                "image_id": profile["image_id"],
                "docker_backend_version": profile["backend_version"],
                "container_name": container_name,
                "container_inspect_verdict": inspect_result["verdict"],
                "probe_report_sha256": _sha(probe_report_path),
                "probe_artifact_sha256": _sha(artifact_copy),
                "path_namespace": "container",
                "scope": "model-free native Windows host-to-Linux boundary canary; no model request",
            }
            (output_dir / "canary-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return result
        finally:
            if container_created:
                try:
                    removed = _docker_call(docker, docker_config, ["rm", "-f", container_name], timeout=timeout)
                    if removed.returncode != 0:
                        cleanup_error = RuntimeError(f"docker rm failed with exit code {removed.returncode}")
                except Exception as exc:  # pragma: no cover - host cleanup failure is reported
                    cleanup_error = exc
            if candidate_canary is not None and _inside(candidate_dir, candidate_canary):
                shutil.rmtree(candidate_canary, ignore_errors=True)
            if cleanup_error is not None:
                raise cleanup_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-job", type=Path, required=True)
    parser.add_argument("--boundary-profile", type=Path, required=True)
    parser.add_argument("--probe-program", type=Path, default=Path(__file__).with_name("feynman_boundary_probe_node.mjs"))
    parser.add_argument("--docker", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    try:
        result = run_canary(
            job_path=args.runner_job,
            profile_path=args.boundary_profile,
            probe_program=args.probe_program,
            docker=args.docker,
            docker_config=args.docker_config,
            output_dir=args.output_dir,
            timeout=args.timeout_seconds,
        )
    except (ValueError, OSError, RuntimeError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
