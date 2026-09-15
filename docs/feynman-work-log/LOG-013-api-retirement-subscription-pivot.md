# LOG-013 — API path retirement and ChatGPT-subscription Codex pivot

Date: 2026-09-09 (Asia/Seoul)
Repository: `Ronaldony/thinking-skills`
Branch: `feat/feynman-thinking-v0.5-draft`
Pre-pivot checkpoint: `c1961b25c19e8540f2cacb0a2c7b30841fd2d000`

## User decision

The user explicitly decided:

> API는 절대 쓰지 않을거야, 폐기해.

This changes the canonical execution architecture. The previous next-action sections in LOG-008, LOG-010, LOG-011, and LOG-012 are historical records only and are superseded by this log. They must not be followed for new runs.

## What is retired

The canonical evaluation path no longer permits:

- `OPENAI_API_KEY` as a runner credential contract;
- external OpenAI API billing as an evaluation prerequisite;
- API-key environment-variable names in runner-job / attestation / linkage / result records;
- the API-specific real-model control config and pre-auth readiness workflow.

Historical Git commits and old logs are retained for auditability; deleting history would make the design change harder to review.

## New authentication boundary

Canonical execution uses an already authenticated Codex session backed by the operator's ChatGPT subscription on a trusted local or self-hosted control plane.

The boundary is:

```text
trusted control plane
  protected control_codex_home
  ChatGPT-authenticated Codex session
            |
            | stdio remote environment
            v
  Docker candidate tool boundary
    network: none (for closed-network cases)
    separate candidate codex_home
    no control auth env vars
    no readable control auth paths
    no auth command arguments
```

The evaluation code does not read, copy, hash, serialize, or upload the contents of `control_codex_home`.

## Auth contract v3

Runner-job v3 authentication is fixed to:

```json
{
  "mode": "chatgpt-subscription",
  "control_plane_auth_source": "codex-session",
  "api_key_auth_allowed": false,
  "candidate_auth_exposed": false,
  "candidate_tool_auth_env_keys": [],
  "candidate_readable_auth_paths": [],
  "auth_command_arguments": []
}
```

`control_codex_home` is a protected path and may not overlap candidate-owned roots. The candidate continues to use its own `codex_home`.

## Result versioning decision

Changing authentication semantics without changing result schema would make historical API-auth v3 results indistinguishable from subscription-auth results. To avoid that ambiguity:

- runner-job: v2 -> v3
- runner-attestation: v2 -> v3
- runner-job-link: v2 -> v3
- analysis-result: v3 -> v4
- canonical aggregator accepts analysis-result v4 only

Old versions remain recoverable from Git history; they are not valid inputs for new canonical execution.

## Subscription smoke scope

The first real model execution remains an integration smoke, not a skill-effect estimate:

- case: `tools-10`
- conditions: `baseline`, `feynman-v05`
- repeats: 1 each
- authentication: ChatGPT subscription / Codex session
- execution host: trusted local or self-hosted control plane
- API-key auth: prohibited
- analysis use: `not-for-skill-performance-inference`

The smoke may only establish end-to-end plumbing and boundary integrity.

## Structural readiness semantics

A successful subscription preflight means:

- frozen plan and candidate task bytes agree;
- runner-job v3 agrees with the boundary profile;
- remote stdio environment is canonical;
- candidate skill exposure is correct;
- `control_codex_home` is structurally protected;
- no API-key contract exists in the job;
- preflight did not inspect control-session contents.

It does **not** mean:

- the operator is currently signed into ChatGPT in Codex;
- a model request succeeded;
- the account has a specific model entitlement;
- the Feynman skill improves behavior.

The actual ChatGPT login check occurs only on the trusted execution machine.

## Local mock references

Deterministic local mock-model references remain useful for transport, Docker, patch and evidence regression tests. They do not contact OpenAI, do not incur API billing, and are not behavioral evidence. Any mock bearer used by those tests is synthetic test data only. Active mock workflows should use mock-specific naming rather than `OPENAI_API_KEY` to avoid conflating them with the retired external API path.

## Files introduced/replaced in this phase

Canonical:
- `tooling/feynman_runner_job.py` — subscription runner-job v3
- `tooling/feynman_runner_job_validate.py` — fail-closed v3 validator
- `tooling/feynman_runner_attestation.py` — subscription attestation v3
- `tooling/feynman_runner_job_link.py` — v3 linkage
- `tooling/feynman_eval_result_v4.py`
- `tooling/feynman_eval_aggregate_v4.py`
- canonical result/aggregate wrappers point to v4
- `tooling/feynman_subscription_smoke_plan.py`
- `tooling/feynman_subscription_run_preflight.py`
- subscription smoke/readiness schemas/spec
- `validate-feynman-subscription-readiness` structural CI

Retired from the active tree:
- API-specific real-model control config
- API-specific real-run preflight
- API-specific real-model smoke planner/spec/readiness schema
- API-specific real-run readiness workflow
- associated API-path tests

## Next execution handoff

After structural CI is green, the next human action is **not** to provide an API key.

On a trusted local/self-hosted machine:
1. install/pin the intended Codex CLI version;
2. sign in to Codex with the intended ChatGPT subscription using the supported interactive login flow;
3. keep the authenticated control `CODEX_HOME` outside all candidate mounts;
4. run the two-job subscription smoke through the frozen runner.

Do not copy login/session files into the repository, chat, GitHub artifacts, candidate workspace, candidate HOME, candidate CODEX_HOME, or command arguments.

## Behavioral-claim boundary

No code in this pivot proves Feynman v0.5 is better than baseline/generic/legacy-clean. The PR remains draft until real subscription-authenticated smoke, public-development pilot, independent held-out evaluation, and failure/ablation analysis are complete.
