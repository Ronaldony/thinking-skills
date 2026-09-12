# Feynman evaluation — ChatGPT-subscription local smoke handoff

This runbook is the canonical human handoff after the API path was retired.
It is deliberately limited to a trusted local or self-hosted control plane.

## Policy

- OpenAI Platform API-key authentication is not part of this evaluation path.
- The control Codex must authenticate through the operator's ChatGPT subscription.
- The candidate Docker/tool environment must not receive the control Codex login state.
- The first real run is only the frozen two-job `tools-10` integration smoke. It is not evidence of skill benefit.
- Do not commit, paste, upload, hash, or copy Codex session credential contents into repository artifacts or chat.
- `MOCK_MODEL_TOKEN`, when seen in CI, is synthetic local mock transport data only. It is unrelated to ChatGPT authentication and must never be used as real-run authentication.
- Do not manually reconstruct the `codex exec` command for the real smoke. Use the repository's canonical smoke executor.

## Why a dedicated control CODEX_HOME

Codex caches login state under `CODEX_HOME` when file credential storage is selected. A dedicated directory lets the evaluation keep that state outside candidate-owned paths and prevents an ordinary user Codex configuration from silently changing the experiment.

The repository tool creates only this non-secret configuration:

```toml
forced_login_method = "chatgpt"
cli_auth_credentials_store = "file"
```

The forced login policy is important: credentials that do not match the configured login method are rejected by Codex. The auth gate launches `codex login status` from a scrubbed environment and preserves only the coarse `chatgpt-subscription-authenticated` verdict.

## 1. Prepare a fresh control home

Choose a path outside every candidate workspace. Example:

```bash
CONTROL_CODEX_HOME="$HOME/.codex-feynman-eval"
python tooling/feynman_subscription_auth_gate.py prepare \
  --control-codex-home "$CONTROL_CODEX_HOME"
```

`prepare` intentionally refuses to reuse an existing directory. This prevents accidental mixing with an unrelated Codex session or configuration.

## 2. Human ChatGPT login

Run the supported interactive Codex login flow on the trusted machine:

```bash
CODEX_HOME="$CONTROL_CODEX_HOME" codex login
```

Complete the ChatGPT browser login. Do not use any API-key login option.

For a headless trusted machine, the supported device-code flow can be used when available:

```bash
CODEX_HOME="$CONTROL_CODEX_HOME" codex login --device-auth
```

This is the only authentication step that requires a human. No credential value is sent to the repository or to ChatGPT conversation text.

## 3. Verify the authentication method without preserving account details

```bash
python tooling/feynman_subscription_auth_gate.py check \
  --control-codex-home "$CONTROL_CODEX_HOME" \
  --codex-bin codex \
  --output /tmp/feynman-subscription-auth-gate.json
```

Expected verdict:

```text
chatgpt-subscription-authenticated
```

The gate does not open credential files. It captures `codex login status` only in process memory, checks that the active method identifies ChatGPT, and omits the raw status text from its result so account identifiers are not persisted.

## 4. Frozen first real run

The smoke spec is schema v2 and remains frozen to:

```text
case: tools-10
conditions:
  - baseline
  - feynman-v05
repeats: 1 each
authentication: ChatGPT subscription / Codex session
analysis use: not-for-skill-performance-inference
model reasoning effort policy: model-default
```

`model-default` is intentionally permitted **only for integration plumbing validation**. It is not sufficiently controlled for the four-condition behavioral pilot. Before FYN-08 behavioral comparison, an explicit reasoning effort must be bound into a new versioned runner/attestation/link/result contract.

For each condition, first prepare the exact frozen artifacts using the existing plan/workspace/profile/job/remote-environment tooling:

```text
subscription smoke plan
candidate workspace
evaluator case
runner-job v3
boundary profile
$CONTROL_CODEX_HOME/environments.toml
```

The runner-job must bind the same dedicated control `CODEX_HOME`, while the candidate uses its own separate candidate `codex_home`.

### Native Windows path mapping

On a native Windows control plane, `runner-job.paths` contains the real host
directories. Those strings are not valid Linux container workdirs. The job's
`boundary.mounts` therefore binds each host source to a canonical POSIX
destination:

```text
candidate_dir   -> /run/candidate
ephemeral_home  -> /run/home
codex_home      -> /run/codex
temp_dir        -> /run/temp
```

The boundary profile's `read_write_mounts` lists the container destinations;
the runner job carries the host `source` values and access mode. The generated
remote environment uses the container destinations for `HOME`, `CODEX_HOME`,
`TMPDIR`, and `--workdir`, while Docker receives the separate Windows source
paths. Do not hand-edit a `C:\...:C:\...` identity mount for a Linux image.
The compatibility identity mapping in old POSIX fixtures is not a native
Windows execution contract.

## 5. Execute one frozen job with the canonical executor

Do not manually assemble Codex flags. Run:

```bash
python tooling/feynman_subscription_smoke_exec.py \
  --plan <frozen-subscription-smoke-plan.json> \
  --smoke-spec evals/feynman-thinking/subscription-smoke-spec.json \
  --ordinal <job-ordinal> \
  --evaluator-case <evaluator-dir>/case.json \
  --runner-job <runner-job.json> \
  --boundary-profile <boundary-profile.json> \
  --remote-environment "$CONTROL_CODEX_HOME/environments.toml" \
  --output-dir <evaluator-dir>/subscription-exec-<run-id> \
  --codex-bin codex
```

The executor itself re-runs the structural preflight and auth gate, verifies the frozen smoke-spec hash, checks the requested model and Codex CLI version, rejects API/token-based ambient authentication, and launches the exact `task.txt` through a fixed non-interactive Codex configuration.

Successful executor output includes:

```text
codex-trace.jsonl
candidate-final.txt
subscription-exec-result.json
```

The Codex-process completion verdict is:

```text
subscription-codex-smoke-exec-completed
```

This says only that the fixed Codex invocation completed.  Result schema v2
also records `candidate_tool_activity`.  For `tools-10`, a
`candidate-tool-use-not-observed` / `blocked-no-candidate-tool-call` result
must not advance to post-run evidence extraction or semantic review: a final
answer that describes a test is not trusted execution evidence.  Conversely,
`candidate-tool-use-observed` only makes trace-evidence extraction eligible;
it does not prove that the requested test ran or passed.

The executor deliberately refuses real account-authenticated execution when `GITHUB_ACTIONS=true`. Use a trusted local or self-hosted control plane; do not copy the control login session into GitHub Actions.

## 6. What the executor protects

The executor fails closed if, among other things:

- the smoke scope differs from `tools-10 × {baseline, feynman-v05} × 1`;
- the plan is not byte-bound to the supplied smoke spec;
- the control config differs from the auth-gate config;
- the remote environment is not exactly `CONTROL_CODEX_HOME/environments.toml`;
- auth gate or structural preflight fails;
- runner-job and authenticated Codex CLI versions differ;
- the requested model is a mock model;
- the candidate contains project-local `.codex` config;
- `OPENAI_API_KEY`, `CODEX_API_KEY`, or `CODEX_ACCESS_TOKEN` is ambient;
- the output directory is not a new evaluator-owned directory;
- Codex returns nonzero, an error event, a failed turn, no single thread ID, or no completed agent answer.

It also records the count and stable type labels of completed candidate tool
items, without preserving tool arguments, command text, tool output, or
process environment.  A zero count is a non-promotion outcome for an
execution-required case, even when the Codex process itself completed.

The executor does not read credential files and does not preserve raw auth-status text, raw process environment, raw stderr, or control `CODEX_HOME` contents.

## 7. Post-run evidence remains mandatory

An executor success is **not yet a green integration smoke**. For each job, continue with:

1. same-profile external boundary canary/report for the actual run;
2. runner-attestation schema v3;
3. recomputed runner-job-link schema v3;
4. trace evidence extraction;
5. evaluator review bundle;
6. semantic review v2;
7. grade gate;
8. analysis-result schema v4.

Only when both `baseline` and `feynman-v05` smoke jobs have complete lineage is the integration smoke complete.

## 8. One-time tool-discovery diagnostic

If a structurally healthy execution-required smoke has zero completed candidate
tool items, do not repeat its frozen evaluation command. The separate
`tooling/feynman_subscription_tool_use_probe.py` may run once against the
already-mounted repaired `tools-10 / feynman-v05` fixture after the structural,
version, Docker security, and transient MCP catalog gates. Run
`--preflight-only` first; it stops before auth/model use. The live probe uses
`--ignore-user-config` so the protected control home remains the auth source but
its `config.toml` is not loaded. Its fixed no-argument bounded MCP tool reads at
most one byte of evaluator-selected `candidate.py`; it does not send `task.txt`,
a rubric, evaluator evidence, or development context.

The probe distinguishes `tool-use-observed` from `tool-use-not-observed` using
only completed trace item counts/types. It also records whether the fixed
response claimed `PROBE_TOOL_USED` without a matching trace; text claims never
override missing tool evidence. Neither result is Feynman-skill
performance evidence, test evidence, or permission to start baseline. Treat
it only as a control-plane diagnosis, then record the result before deciding
whether a new frozen evaluation contract is warranted.

## 8. Claims prohibited after the smoke

Even if both jobs succeed:

- do not estimate Feynman skill effect from the two answers;
- do not call the public-development smoke held-out evidence;
- do not call the skill behaviorally validated;
- do not start the four-condition behavioral pilot before explicit reasoning effort is frozen in the execution contract.

The smoke validates real execution plumbing, not comparative skill quality.

## Cleanup

After the evaluation series is finished, sign out or securely remove the dedicated control home on the trusted machine. Never add it to Git, upload it as an Actions artifact, or mount it into the candidate Docker environment.
