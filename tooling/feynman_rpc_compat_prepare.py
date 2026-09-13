"""Prepare fresh per-model RPC compatibility fixtures without model/auth calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tooling.feynman_boundary_profile import validate_profile, validate_profile_file
from tooling.feynman_condition_workspace import prepare_condition
from tooling.feynman_eval_plan import write_plan
from tooling.feynman_remote_exec_environment import build_document, render_toml
from tooling.feynman_runner_job import build_job
from tooling.feynman_subscription_models import SUBSCRIPTION_WORK_MODELS
from tooling.feynman_subscription_smoke_plan import build_smoke_plan


def prepare(*, root: Path, profile_path: Path, output: Path, image_id: str,
            codex_cli: str, control_home: Path, real_home: Path) -> dict:
    root, output = root.resolve(), output.absolute()
    if output.is_symlink() or output.exists():
        raise ValueError('compatibility output must be new')
    output = output.resolve()
    protected = (root, real_home.resolve(), control_home.resolve())
    if any(output == p or output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('compatibility output overlaps a protected root')
    profile, _, _ = validate_profile_file(profile_path)
    # Use immutable image ID as the execution reference too, not a movable tag.
    profile = dict(profile, image=image_id, image_id=image_id,
                   scope='fresh model-free RPC compatibility fixture; not performance evidence')
    validate_profile(profile)
    if set(profile['read_write_mounts']) != {'/run/candidate', '/run/home', '/run/codex', '/run/temp'}:
        raise ValueError('compatibility fixture requires native mount destinations')
    output.mkdir()
    new_profile = output / 'boundary-profile.json'
    new_profile.write_text(json.dumps(profile, indent=2) + '\n', encoding='utf-8')
    profile, digest, _ = validate_profile_file(new_profile)
    plan = build_smoke_plan(root, root / 'evals/feynman-thinking/subscription-smoke-spec.json')
    plan_path = output / 'frozen-subscription-smoke-plan.json'
    write_plan(plan, plan_path)
    ordinal = next(j['ordinal'] for j in plan['jobs'] if j['condition'] == 'feynman-v05')
    prepared = []
    for model in SUBSCRIPTION_WORK_MODELS:
        work = output / model
        work.mkdir()
        candidate, evaluator = work / 'candidate', work / 'evaluator'
        prepare_condition(root, 'tools-10', 'feynman-v05', candidate, evaluator)
        for name in ('home', 'codex-home', 'temp'):
            (work / name).mkdir()
        job = build_job(
            plan_path=plan_path, ordinal=ordinal, evaluator_case_path=evaluator / 'case.json',
            boundary_profile_path=new_profile, run_id=output.name + '-' + model,
            model=model, codex_cli=codex_cli, candidate_dir=candidate, evaluator_dir=evaluator,
            source_repo=root, ephemeral_home=work / 'home', codex_home=work / 'codex-home',
            temp_dir=work / 'temp', real_home=real_home, control_codex_home=control_home,
        )
        (evaluator / 'runner-job.json').write_text(json.dumps(job, indent=2) + '\n', encoding='utf-8')
        (evaluator / 'environments.toml').write_text(render_toml(build_document(job, profile, digest)), encoding='utf-8')
        prepared.append(model)
    report = {'models': prepared, 'model_calls': 0, 'baseline_prepared': False,
              'account_access_verified': False, 'image_id': image_id,
              'control_cli_contract': codex_cli, 'control_home_modified': False}
    (output / 'preparation-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'profile', 'output', 'control-home', 'real-home'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--codex-cli', required=True)
    args = parser.parse_args()
    try:
        report = prepare(root=args.root, profile_path=args.profile, output=args.output,
                         image_id=args.image_id, codex_cli=args.codex_cli,
                         control_home=args.control_home, real_home=args.real_home)
    except (ValueError, OSError) as exc:
        parser.exit(2, 'error: compatibility preparation failed: ' + type(exc).__name__ + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
