# LOG-033 — Windows smoke resumption and CLI argument conflict

Date: 2026-09-12 KST. Branch: `feat/feynman-thinking-v0.5-draft`.
Start HEAD: `95890bea02177d1430a60691a30cfa55633ceabc`; working tree clean.
No applicable AGENTS.md found at drive, parent, repository, or repository descendants.

## Scope and observations

Read resume prompt, handoff, LOG-019/020/031/032, local smoke runbook,
auth gate, executor, remote environment generator, native canary and executor tests.
The app usage tool reported 0% used in the weekly Codex window. This is the app
account view, not proof that the dedicated evaluation login has quota available.
No reset, credit redemption, model substitution, or API-key authentication used.

Public command aliases below redact the personal user directory only:

```powershell
$runRoot = 'C:\DevWorks\feynman-smoke-gpt-5.6-luna-20260910-01'
$ordinalRoot = "$runRoot\ordinal-1-feynman-v05"
$controlHome = '<user>\.codex-feynman-eval'
$codexBin = '<user>\AppData\Local\OpenAI\Codex\bin\ce5c3815ab7ed349\codex.exe'
$dockerBin = '<user>\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
$tempRoot = '<user>\AppData\Local\Temp'
```

Actual commands (aliases expanded to absolute paths when executed):

```powershell
git status --short --branch
git rev-parse HEAD
Get-Command python,codex,docker -All -ErrorAction SilentlyContinue | Select-Object Name,Source
& $codexBin --version
& $codexBin exec --help
& $codexBin --help
& $dockerBin --config "$tempRoot\feynman-empty-docker-config" info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}'
python -X utf8 tooling/feynman_subscription_auth_gate.py check --control-codex-home $controlHome --codex-bin $codexBin --timeout-seconds 30 --output "$tempRoot\feynman-auth-gate-20260912-01.json"
python -X utf8 tooling/feynman_subscription_run_preflight.py --plan "$runRoot\frozen-subscription-smoke-plan.json" --ordinal 1 --evaluator-case "$ordinalRoot\evaluator\case.json" --runner-job "$ordinalRoot\runner-job.json" --boundary-profile "$runRoot\boundary-profile.json" --remote-environment "$ordinalRoot\remote-environment-staged.toml" --output "$tempRoot\feynman-preflight-20260912-01.json"
python -X utf8 tooling/feynman_native_boundary_canary.py --runner-job "$ordinalRoot\runner-job.json" --boundary-profile "$runRoot\boundary-profile.json" --docker $dockerBin --docker-config "$tempRoot\feynman-empty-docker-config" --output-dir "$tempRoot\feynman-canary-20260912-01" --timeout-seconds 45
```

- Native executable moved since LOG-032; version remains `codex-cli 0.153.4`.
- Docker info first hit sandbox pipe permission denial. Approved escalated read
  returned `29.7.2|linux|aarch64`, exit 0.
- Auth gate: `chatgpt-subscription-authenticated`, exit 0. No credential file read
  by gate and no raw status preserved.
- Structural preflight: `ready-for-local-chatgpt-session-check`, exit 0; exact
  task/plan/job/profile/runtime binding passed for ordinal 1.
- Native canary: `native-boundary-canary-passed`, exit 0, container namespace;
  Docker inspect matches profile. Synthetic temporary canary directory and its
  diagnostic container were cleaned up by the canary tool; reports remain in Temp.

## Canonical attempt and bounded diagnosis

```powershell
python -X utf8 tooling/feynman_remote_exec_environment.py --job "$ordinalRoot\runner-job.json" --boundary-profile "$runRoot\boundary-profile.json" --output "$controlHome\environments.toml"
python -X utf8 tooling/feynman_subscription_smoke_exec.py --plan "$runRoot\frozen-subscription-smoke-plan.json" --smoke-spec evals/feynman-thinking/subscription-smoke-spec.json --ordinal 1 --evaluator-case "$ordinalRoot\evaluator\case.json" --runner-job "$ordinalRoot\runner-job.json" --boundary-profile "$runRoot\boundary-profile.json" --remote-environment "$controlHome\environments.toml" --output-dir "$ordinalRoot\evaluator\subscription-exec-20260912-01" --codex-bin $codexBin --timeout-seconds 180
Move-Item -LiteralPath "$controlHome\environments.toml" -Destination "$tempRoot\feynman-environments-20260912-01.toml"
```

Environment generation exit 0. Executor reported child exit 2 (outer process
exit 1); no raw stderr preserved. Trace size was 0 bytes, confirmed with escalated
`Get-Item ... | Select-Object Length` after sandbox access denial. Environment
file move exit 0 restored the control home to its prior unstaged state.

Full executor flags plus `--help` returned help and did not reveal conflicts.
A bounded parser probe used `subprocess.run` with exact argv:

```text
<codexBin> exec --approve-for-me --sandbox workspace-write -
stdin="", capture_output=True, timeout=20
```

Only fixed booleans/exit code were emitted: `exit_code=2`,
`approval_sandbox_conflict=true`, `empty_prompt=false`, `stdout_bytes=0`.
Classification required all of `cannot be used with`, `--approve-for-me`, and
`--sandbox` in captured stderr. Raw stderr was neither printed nor saved.
This reproduces a CLI parsing failure without a prompt/model turn. It explains
the current empty-trace exit 2; it does not resolve the separate historical quota
failure of the neutral probe in LOG-032.

## Fix and validation in progress

Replaced `--approve-for-me` with `-c approval_policy="never"` while retaining
`--sandbox workspace-write`. This restores the frozen non-interactive policy
already recorded in result schema; automatic approval review was not equivalent.
LOG-032's claim that the old option was simply replaced is superseded: root
`codex --help` still lists `--ask-for-approval`, although `exec --help` does not.

Official configuration reference also documents `approval_policy="never"` for
non-interactive use: https://learn.chatgpt.com/docs/config-file/config-reference .
Executor test now checks policy argument/result agreement and absence of the
conflicting automatic-review flag. Tests and corrected-run status follow below.

Commit/push: pending. Baseline, post-run attestation/link/review/gate/result, and
behavioral evaluation remain incomplete. No main merge or force push.

## Corrected run and newly isolated blocker (19:06–19:10 KST)

Added fixed-label stderr classification to the executor so the next nonzero
exit can distinguish argument/configuration/usage/remote errors without printing,
hashing, or saving raw stderr. Unknown errors stay `unclassified`; a label is
diagnostic, not proof of the root cause. Synthetic-secret coverage was added.

```powershell
python -X utf8 -m unittest tests.test_feynman_subscription_smoke_exec
git diff --check
```

First run after policy patch: 13 tests passed. After classification change:
14 tests passed in 0.636s. Whitespace check passed with CRLF warnings only.
Empty-stdin parser probe with `exec -c approval_policy="never" --sandbox
workspace-write -` returned exit 1, `argument_conflict=false`, `empty_prompt=true`,
zero stdout bytes. No model prompt was submitted by this probe.

Repeated the environment generator and canonical executor commands above once
after the confirmed CLI fix, changing only output directory suffix to
`subscription-exec-20260912-02`. Gates ran again inside the executor. Result:

- Exit 0; `subscription-codex-smoke-exec-completed`.
- Requested model `gpt-5.6-luna`, CLI 0.153.4, policy `never`.
- Nine trace events; one completed turn, zero error/failed events.
- Input tokens 249585 (cached 172288), output tokens 1512; these are the CLI's
  reported counts, not an independently audited prompt inventory.
- Final answer explicitly says the task was NOT completed: skill unavailable,
  file access/test execution unavailable, bash spawn denied by policy.
- Trace contains an MCP resource-list call but no `command_execution` event.
- Therefore model transport completion is NOT task/tool/skill success. Do not
  promote this result to a green smoke or claim skill benefit.

The final answer's cause attribution is model testimony. Independent evidence:

```powershell
& $dockerBin --config "$tempRoot\feynman-empty-docker-config" ps -a --filter 'name=feynman-tool-subscription-gpt-5.6-luna-20260910-ordinal-1-feynman-v05' --format '{{.Names}}|{{.Status}}|{{.Image}}'
& $dockerBin --config "$tempRoot\feynman-empty-docker-config" inspect feynman-tool-subscription-gpt-5.6-luna-20260910-ordinal-1-feynman-v05
& $dockerBin --config "$tempRoot\feynman-empty-docker-config" logs feynman-tool-subscription-gpt-5.6-luna-20260910-ordinal-1-feynman-v05
```

Inspect/log subprocess outputs were captured in memory. Only
`verify_reference(profile, payload, expected_mounts=mounts_for_job(job, profile))`
and selected JSON-RPC metadata/error classifications were emitted. The real
execution container exists, exited 0, and its inspect passes the exact profile.
It is preserved for diagnosis. Initialization returned `environmentInfo` and
`sessionId`, followed by 20 RPC errors: 18 code -32600, two code -32602.
All 20 error messages identify a `file:` URI as invalid on Linux. Eight contain
the normalized candidate host path. This confirms host URI/container namespace
incompatibility beyond Docker mount mapping. It does not prove that every other
skill/policy issue will disappear after URI handling is fixed.

Only public path-role names and fixed booleans were emitted by further
classification probes; raw logs are not copied into this repository. A first
path redaction matched the trailing `e:` of `file:` too broadly; corrected
classification used fixed `file:`/`invalid on`/`linux` predicates instead.

```powershell
Move-Item -LiteralPath "$controlHome\environments.toml" -Destination "$tempRoot\feynman-environments-20260912-02.toml"
python -X utf8 tooling/feynman_native_boundary_canary.py --runner-job "$ordinalRoot\runner-job.json" --boundary-profile "$runRoot\boundary-profile.json" --docker $dockerBin --docker-config "$tempRoot\feynman-empty-docker-config" --output-dir "$tempRoot\feynman-canary-post-20260912-02" --timeout-seconds 45
```

Both exit 0. Post-run canary passes; its synthetic directory/container are
cleaned up. Dedicated auth files and config were preserved; generated remote
environment is archived in Temp and no longer staged in control home.

Additional read-only discovery: `codex exec-server --help`, `codex debug --help`,
repository remote reference workflows. Guessed tooling reference filenames and
`scripts/` do not exist; corrected discovery used `rg --files`. A Windows `rg`
path glob `tooling/feynman*` returned error 123, so later searches used real
directories. These search errors did not affect run artifacts.

## Next work and limits

1. Add a model-free Codex RPC path/read/spawn check using the actual native
   control-to-Linux exec-server protocol. Docker canary alone cannot detect this.
2. Resolve Windows file-URI translation and remote skill discovery through a
   supported native configuration or a reviewed, field-specific protocol adapter;
   do not rewrite arbitrary JSON strings or grant broader mounts/permissions.
3. Verify remote candidate skill exposure, fixture read and command execution
   before another model request. Current model-free structural verdict is not
   sufficient to authorize another native smoke with this known defect.
4. Keep ordinal 2 baseline unstarted. Preserve the unsuccessful task response,
   then complete actual per-job evidence/attestation/link/review/gate/result
   lineage after the execution route is repaired. Independent semantic review
   remains pending; no four-condition pilot is authorized by smoke completion.

No new login or Docker installation is required by the current evidence.
OpenAI Docs was consulted for approval configuration; runtime diagnosis above is
based on actual local CLI and candidate server evidence, not inferred from docs.

## Final regression checkpoint

`python -X utf8 -m unittest discover -s tests`: exit 0, 279 tests in 15.846s,
10 skipped. Windows sandbox printed Git global-ignore access warnings; no test
failed. `git diff --check`: exit 0, CRLF conversion warnings only. No new CI
success claim is made. The five changed files are the executor, its test,
this log, status document, and resume prompt; runtime skill contents are unchanged.
