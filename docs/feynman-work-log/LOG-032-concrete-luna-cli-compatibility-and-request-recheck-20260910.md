# LOG-032 — concrete `gpt-5.6-luna` binding and CLI/request recheck

## 1. Scope and safety boundary

This log records the first continuation after the operator supplied the concrete model ID `gpt-5.6-luna`.

- Repository: `Ronaldony/thinking-skills`
- Branch: `feat/feynman-thinking-v0.5-draft`
- Control home: existing `C:\Users\wotmd\.codex-feynman-eval`
- Authentication: ChatGPT subscription / Codex session only
- OpenAI Platform API and API keys: not used
- Login files, token contents, raw auth status, and full environment variables: not read or preserved
- Existing native preflight artifact: preserved
- New run artifact: `C:\DevWorks\feynman-smoke-gpt-5.6-luna-20260910-01`

The new artifact was generated separately because the previous native artifact was transient and was not overwritten. The baseline job's first generated JSON had a typo in one `codex_home` path; it was moved to `runner-job-invalid-path.json` and preserved, then regenerated with the correct path.

## 2. Concrete model binding

Commands:

```powershell
python -X utf8 tooling\feynman_subscription_smoke_plan.py --root C:\DevWorks\thinking-skills --spec evals\feynman-thinking\subscription-smoke-spec.json --output C:\DevWorks\feynman-smoke-gpt-5.6-luna-20260910-01\frozen-subscription-smoke-plan.json
python -X utf8 tooling\feynman_condition_workspace.py --root C:\DevWorks\thinking-skills --case tools-10 --condition feynman-v05 --candidate-dir C:\DevWorks\feynman-smoke-gpt-5.6-luna-20260910-01\ordinal-1-feynman-v05\candidate --evaluator-dir C:\DevWorks\feynman-smoke-gpt-5.6-luna-20260910-01\ordinal-1-feynman-v05\evaluator
python -X utf8 tooling\feynman_condition_workspace.py --root C:\DevWorks\thinking-skills --case tools-10 --condition baseline --candidate-dir C:\DevWorks\feynman-smoke-gpt-5.6-luna-20260910-01\ordinal-2-baseline\candidate --evaluator-dir C:\DevWorks\feynman-smoke-gpt-5.6-luna-20260910-01\ordinal-2-baseline\evaluator
```

Both runner jobs were regenerated with:

```text
versions.model = gpt-5.6-luna
versions.codex_cli = codex-cli 0.153.4
```

The frozen plan remains the exact two-job `tools-10 × {feynman-v05, baseline} × 1` integration smoke. The model binding is runner metadata; it does not turn this plumbing smoke into a behavioral comparison.

## 3. Pre-execution checks

Ordinal 1 was selected for the first real attempt.

Commands and observations:

```text
feynman_remote_exec_environment.py ... --output C:\Users\wotmd\.codex-feynman-eval\environments.toml
→ remote-exec-environment-valid

feynman_runner_job_validate.py ...
→ runner-job-valid

feynman_subscription_run_preflight.py ...
→ ready-for-local-chatgpt-session-check
```

The structural preflight reported:

- model `gpt-5.6-luna`
- frozen-plan job match
- exact candidate task bytes
- valid native Windows-to-Linux boundary profile
- valid canonical remote environment
- valid Feynman runtime preflight
- protected control `CODEX_HOME`

The same-profile native canary reported:

```text
native-boundary-canary-passed
docker-inspect-matches-profile
path_namespace=container
image_id=sha256:dab903a5999b1d3165a70de99147029809fa26d3cb1881b7c7790aac185a4726
```

The dedicated ChatGPT auth gate reported:

```text
chatgpt-subscription-authenticated
codex_cli=codex-cli 0.153.4
raw_status_output_preserved=false
credential_files_read_by_gate=false
```

No model request was made by these checks.

## 4. First actual request and diagnosis

The canonical executor was run once for ordinal 1 with `--model gpt-5.6-luna`. It failed with exit code 2 and an empty `codex-trace.jsonl`; the executor intentionally did not preserve raw stderr.

A read-only `codex exec --help` probe using the complete executor option shape showed:

- current CLI supports `--approve-for-me`
- current `codex exec` does not list the legacy `--ask-for-approval` option

The executor was therefore minimally changed from:

```text
--ask-for-approval never
```

to:

```text
--approve-for-me
```

This is a CLI compatibility fix, not an authentication or model-selection change.

The focused executor tests passed after the change:

```text
Ran 13 tests in 0.720s
OK
```

A second ordinal-1 attempt in a new output directory still failed with exit code 2. To separate model request availability from the remote environment, a neutral read-only probe was run with `--ignore-user-config`, no candidate task, and the exact model ID. It produced only coarse in-memory diagnostics:

```text
thread.started → turn.started → error → turn.failed
exit_code=1
stderr_class=service-transient
```

The probe did not preserve or print the error message, and its output is not evaluation evidence. This establishes that the model string passes CLI parsing and reaches a ChatGPT model turn, but the neutral request did not complete. It does not prove that the account lacks `gpt-5.6-luna` entitlement, and it does not validate the Docker remote environment.

Because the concrete model request did not complete, ordinal 2 baseline was not started and no behavioral comparison or Feynman-effect claim was made.

## 5. Verification and repository state

Completed after the compatibility change:

```text
python -X utf8 -m unittest tests.test_feynman_subscription_smoke_exec
→ Ran 13 tests ... OK

python -X utf8 -m py_compile tooling\feynman_subscription_smoke_exec.py tests\test_feynman_subscription_smoke_exec.py
→ exit 0

git diff --check
→ no whitespace error
```

The temporary diagnostic scripts were removed. The production change is limited to the current Codex CLI approval flag and its regression assertion.

## 6. Commit/push and incomplete work

At log creation, the CLI compatibility change and this log are pending commit/push on the feature branch. Main merge and force push are not performed.

Still incomplete:

1. Determine why the neutral ChatGPT subscription request is `service-transient` without exposing raw auth/session data.
2. Obtain one completed `gpt-5.6-luna` model turn through the canonical executor.
3. Run ordinal 2 baseline only after ordinal 1 execution handling is resolved.
4. Generate post-run boundary canaries, runner attestation/link, evidence, review, gate, and analysis-result lineage.

Next action after commit/push is a bounded service/request diagnosis or a later single retry under the same selected model; do not switch to the Platform API or substitute another model.
