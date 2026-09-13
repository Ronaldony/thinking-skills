#!/usr/bin/env python3
"""Minimal reproductions from inspected v0.4.0 function bodies; not a full original-repository run.

Source: Ronaldony/feynman-thinking, 1609b8b6909f9ab596c1ecf298fbec4a0c70d6b4.
Relevant functions were manually transcribed from the inspected source response.
Synthetic files and synthetic grades are used. No model, API, or remote repository is modified.
"""
from __future__ import annotations
import hashlib
import json
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Any

GENERATED_PARTS = {"__pycache__", "results", "review", "blind-review"}
DIMENSIONS = ["problem_reframe", "mechanism", "independent_representation", "direct_check",
              "approximation_honesty", "competing_model", "discriminating_test",
              "adverse_evidence_revision", "plain_precise_link", "uncertainty_calibration",
              "actionability", "efficiency"]
FEYNMAN_DIMENSIONS = ["problem_reframe", "independent_representation", "direct_check",
                      "discriminating_test", "adverse_evidence_revision"]
SCORE_VALUE = {"0": 0, "1": 1, "2": 2}
FINDING_VALUE = {"found": 1.0, "partial": 0.5, "missed": 0.0, "contradicted": 0.0}

# The following bodies are transcribed from the inspected original source.
def install_skill(skill_root: Path, workspace: Path) -> None:
    target = workspace / ".agents" / "skills" / skill_root.name
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in GENERATED_PARTS or name.endswith((".pyc", ".pyo"))}
    shutil.copytree(skill_root, target, ignore=ignore)

def run_command(command: list[str], *, cwd: Path | None = None, timeout: int = 15) -> str | None:
    try:
        completed = subprocess.run(command, cwd=str(cwd) if cwd else None,
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    text = (completed.stdout or completed.stderr or "").strip()
    return text or None

def repository_commit(skill_root: Path) -> str | None:
    repository = skill_root.parents[1]
    return run_command(["git", "rev-parse", "HEAD"], cwd=repository)

def skill_digest(skill_root: Path) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in skill_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(skill_root)
        if any(part in GENERATED_PARTS for part in relative.parts):
            continue
        if path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        files.append(path)
    for path in sorted(files, key=lambda item: item.relative_to(skill_root).as_posix()):
        relative = path.relative_to(skill_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()

def validate_and_recompute(grade: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    dimensions = grade.get("dimensions", [])
    by_id: dict[str, dict[str, Any]] = {}
    for item in dimensions:
        dim_id = item.get("id")
        if dim_id in by_id:
            raise ValueError(f"duplicate dimension id: {dim_id}")
        by_id[dim_id] = item
    missing = set(DIMENSIONS) - set(by_id)
    extra = set(by_id) - set(DIMENSIONS)
    if missing or extra:
        raise ValueError(f"dimension mismatch: missing={sorted(missing)}, extra={sorted(extra)}")
    required = set(case["required_behaviors"])
    for dim_id in required:
        if by_id[dim_id].get("score") == "NA":
            raise ValueError(f"required behavior graded NA: {dim_id}")
    applicable = [item for item in by_id.values() if item.get("score") != "NA"]
    general = 0.0 if not applicable else sum(SCORE_VALUE[item["score"]] for item in applicable) / (2 * len(applicable))
    feynman_items = [by_id[dim_id] for dim_id in FEYNMAN_DIMENSIONS if by_id[dim_id].get("score") != "NA"]
    feynman = 0.0 if not feynman_items else sum(SCORE_VALUE[item["score"]] for item in feynman_items) / (2 * len(feynman_items))
    findings = grade.get("expected_findings", [])
    finding_scores = [FINDING_VALUE.get(item.get("status"), 0.0) for item in findings]
    finding_hit_rate = statistics.mean(finding_scores) if finding_scores else 0.0
    hard_failures = [str(item) for item in grade.get("hard_failures", []) if str(item).strip()]
    required_zero = [dim_id for dim_id in required if by_id[dim_id].get("score") == "0"]
    recomputed_pass = not hard_failures and not required_zero
    grade["general_normalized_score"] = round(general, 6)
    grade["feynman_specific_score"] = round(feynman, 6)
    grade["expected_finding_hit_rate"] = round(finding_hit_rate, 6)
    grade["required_zero_dimensions"] = sorted(required_zero)
    grade["overall_pass_recomputed"] = recomputed_pass
    return grade

# Probe setup below is new code, not part of the original repository.
def _init_repo(path: Path, message: str) -> str:
    path.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-q"], ["-c", "user.name=Local Probe", "-c", "user.email=probe@example.invalid",
                  "commit", "--allow-empty", "-qm", message]):
        subprocess.run(["git", "-C", str(path), *args], check=True,
                       capture_output=True, text=True, timeout=10)
    result = run_command(["git", "rev-parse", "HEAD"], cwd=path)
    assert result is not None
    return result

def run_probes() -> dict[str, Any]:
    output: dict[str, Any] = {"scope": "transcribed-function minimal reproductions; synthetic inputs; no LLM runs"}
    with tempfile.TemporaryDirectory(prefix="feynman-legacy-probe-") as tmp:
        base = Path(tmp)
        source = base / "feynman-thinking"
        (source / "evals").mkdir(parents=True)
        (source / ".git").mkdir()
        (source / "SKILL.md").write_text("synthetic runtime\n", encoding="utf-8")
        (source / "evals" / "reasoning-cases.jsonl").write_text(
            '{"id":"probe","expected_findings":["EVALUATOR_ONLY"]}\n', encoding="utf-8")
        (source / ".git" / "config").write_text("synthetic metadata A\n", encoding="utf-8")
        workspace = base / "workspace"
        workspace.mkdir()
        install_skill(source, workspace)
        installed = workspace / ".agents" / "skills" / "feynman-thinking"
        output["evaluator_file_exposed"] = (installed / "evals" / "reasoning-cases.jsonl").is_file()
        output["git_metadata_exposed"] = (installed / ".git" / "config").is_file()
        before = skill_digest(source)
        (source / ".git" / "config").write_text("synthetic metadata B\n", encoding="utf-8")
        output["runtime_digest_changes_on_git_only_change"] = before != skill_digest(source)
        case = {"required_behaviors": DIMENSIONS}
        grade = {
            "overall_pass": False, "hard_failures": [],
            "dimensions": [{"id": key, "score": "1", "rationale": "partial only", "evidence": "synthetic"}
                           for key in DIMENSIONS],
            "expected_findings": [{"finding": "required result", "status": "missed", "evidence": "none"}],
            "general_normalized_score": 0.0, "feynman_specific_score": 0.0,
            "confidence": "low", "summary": "synthetic grade; no candidate model was run"}
        result = validate_and_recompute(grade, case)
        output["partial_behavior_zero_findings"] = {
            "overall_pass_recomputed": result["overall_pass_recomputed"],
            "general_normalized_score": result["general_normalized_score"],
            "expected_finding_hit_rate": result["expected_finding_hit_rate"]}
        if shutil.which("git"):
            outer = base / "outer"
            outer_sha = _init_repo(outer, "outer synthetic repository")
            inner = outer / "holder" / "feynman-thinking"
            inner_sha = _init_repo(inner, "inner synthetic repository")
            observed = repository_commit(inner)
            output["wrong_commit_root"] = {"matches_outer": observed == outer_sha,
                                            "matches_actual_skill_repository": observed == inner_sha}
        else:
            output["wrong_commit_root"] = {"skipped": "git unavailable"}
    return output

if __name__ == "__main__":
    print(json.dumps(run_probes(), ensure_ascii=False, indent=2))
