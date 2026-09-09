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

## Why a dedicated control CODEX_HOME

Codex caches login state under `CODEX_HOME` when file credential storage is selected. A dedicated directory lets the evaluation keep that state outside candidate-owned paths and prevents an ordinary user Codex configuration from silently changing the experiment.

The repository tool creates only this non-secret configuration:

```toml
forced_login_method = "chatgpt"
cli_auth_credentials_store = "file"
```

The forced login policy is important: Codex documents that credentials which do not match a configured login restriction cause Codex to exit. The auth gate also launches `codex login status` from a scrubbed environment and preserves only the coarse `chatgpt-subscription-authenticated` verdict.

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

This is the only required human authentication step. No credential value is sent to the repository or to ChatGPT conversation text.

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

After the auth gate is green, the first real model execution remains:

```text
case: tools-10
conditions:
  - baseline
  - feynman-v05
repeats: 1 each
analysis use: not-for-skill-performance-inference
```

Before each job, rerun `feynman_subscription_run_preflight.py` against that job's exact plan, workspace, boundary profile, and remote environment. The candidate tool environment must use a separate candidate `codex_home`; the dedicated control `CODEX_HOME` is a protected root and must never be mounted into the candidate container.

## 5. Evidence required before any behavioral pilot

Both smoke jobs must produce all of the following before moving to the four-condition public-development pilot:

1. successful ChatGPT-subscription-authenticated model turn;
2. same-profile external boundary canary/report;
3. candidate tool trace with no control authentication exposure;
4. runner-attestation schema v3;
5. recomputed runner-job-link schema v3;
6. evidence/review/gate chain;
7. analysis-result schema v4.

Even if both jobs succeed, do not interpret their response difference as a Feynman skill effect. The smoke only validates the real execution plumbing.

## Cleanup

After the evaluation series is finished, sign out or securely remove the dedicated control home on the trusted machine. Never add it to Git, upload it as an Actions artifact, or mount it into the candidate Docker environment.
