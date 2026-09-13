# LOG-062 — Approved Luna retry: config/metadata rejections and Linux CI fixture fix

- Date: 2026-09-13 KST (runtime telemetry 02:37:15 UTC).
- Repository: `C:\DevWorks\thinking-skills`
- Branch: `feat/feynman-thinking-v0.5-draft`
- Execution code: `12804ef67fdaf6a027c0f29f9143799f350f9e5d`.
- User's “승잉” immediately followed the proposal for one Luna retry; interpreted as approval of that specific run.
- One canonical executor invocation; no automatic retry, other model, baseline, or behavioral evaluation.

## Local checks and scope

Commands: `Get-Location`, `git status --short --branch`, `git rev-parse HEAD`,
`rg --files -g AGENTS.md -g '*subscription_smoke_exec*' -g '*LOG-06*'`.
Explicit ancestor checks of C:\AGENTS.md, C:\DevWorks\AGENTS.md and repository
AGENTS.md found no applicable file. Branch matched origin; only two user PNGs
were untracked. Read the executor gate ordering, LOG-060/061, path mapper/proxy,
and OpenAI Docs skill; this action used the previously verified local execution
contract, with no API integration or new product claim.

`codex.cmd --version` at C:\Users\wotmd\AppData\Roaming\npm returned
`codex-cli 0.154.0`. Docker CLI at
C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe,
with `--config C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config`,
ran `info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}'`:
`29.7.2|linux|aarch64`.
`Test-Path -LiteralPath <output directory below>` returned False.

## Exact approved invocation

PowerShell, working directory C:\DevWorks\thinking-skills:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_subscription_smoke_exec --plan 'C:\DevWorks\feynman-remote-compat-20260912-01\frozen-subscription-smoke-plan.json' --smoke-spec 'C:\DevWorks\thinking-skills\evals\feynman-thinking\subscription-smoke-spec.json' --ordinal 1 --evaluator-case 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\case.json' --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote-environment 'C:\Users\wotmd\.codex-feynman-eval\environments.toml' --output-dir 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\subscription-exec-20260913-luna-04' --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --full-runner-binding 'C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json' --full-runner-node-bin 'C:\Program Files\nodejs\node.exe' --full-runner-adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --full-runner-docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --full-runner-docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --full-runner-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --timeout-seconds 600
```

The existing executor checks structural preflight, full-runner binding and
transient skill isolation, exact control-plane connectivity, ChatGPT subscription
authentication and CLI version before creating the output and invoking Codex.
It reached Codex exec: these prerequisite gates therefore returned successfully.
This inference comes from the inspected fail-closed control flow; separate
persistent preflight/auth reports were not emitted by this invocation.

No auth file/token was read directly, displayed, copied or uploaded. Existing
control-home configuration was unchanged. Only Codex used its saved subscription
login. No API key/Platform API was used. Candidate receives its task and allowed
skill/runtime, not this development log or handoff.

## Outcome and preserved safe telemetry

Tool result: process exit 1, message:

```text
error: Codex exec failed with exit code 1; category=unclassified; raw stderr was not preserved
```

Output directory: evaluator/subscription-exec-20260913-luna-04.
Metadata-only directory listing: codex-trace.jsonl, 0 bytes; no result/final file.
The first sandbox listing was denied; the escalated metadata-only listing
succeeded. No raw trace/stderr was inspected.

Read only evaluator/rpc-proxy-telemetry.json. This is the canonical telemetry
destination and represents the latest invocation; older run counters are
preserved in LOG-060. Its safe values:

```json
{
  "request_methods": {
    "environmentConfig/read": 1,
    "fs/canonicalize": 1,
    "fs/getMetadata": 13,
    "fs/walk": 1,
    "initialize": 1,
    "initialized": 1
  },
  "requests_seen": 18,
  "requests_forwarded": 9,
  "request_mapping_rejections": 9,
  "request_mapping_rejection_methods": {
    "environmentConfig/read": 1,
    "fs/getMetadata": 8
  },
  "response_error_codes": {"-32004": 4},
  "responses_seen": 8,
  "responses_forwarded": 8,
  "response_mapping_rejections": 0,
  "malformed_requests": 0,
  "malformed_responses": 0,
  "probe_policy_rejections": 0,
  "probe_read_limit_applied": 0,
  "probe_response_rejections": 0,
  "child_exit_code": 0
}
```

Docker command with the same executable/config:
`ps -a --filter 'name=feynman-' --format '{{.Names}}|{{.Status}}'`
returned no containers. No deletion was needed.

## What this establishes

All nine rejected requests are now attributed to config (one) and metadata
(eight). fs/walk and fs/canonicalize have zero request-mapping rejections.
The prior remote -32600 response is absent. LOG-061 improved fs/walk mapping but
did not resolve the remaining startup failure.

With malformed and probe-policy counters zero, metadata failures are consistent
with declared-path conversion rejecting out-of-mount or otherwise invalid paths.
Config failure may also involve nested config/requirements path groups. The
specific paths and config shape were not retained; do not assert an exact
directory or identify this as an authentication or model-entitlement failure.

The 0-byte trace proves no recorded model/thread/turn/tool evidence. It does not
prove no request reached a model service. Earlier LOG-060/061 statements that
categorically said “before the model request” were stronger than the evidence;
this log supersedes that wording. Actual skill effectiveness remains untested.

## CI diagnosis and corrective change

Earlier short-SHA queries returned []; this was not reliable proof of absent CI.
The full-SHA command:

```powershell
gh run list --repo Ronaldony/thinking-skills --commit 12804ef67fdaf6a027c0f29f9143799f350f9e5d --limit 20 --json databaseId,status,conclusion,workflowName,headSha
gh run view 34733350670 --repo Ronaldony/thinking-skills --log-failed
gh run view 34733350662 --repo Ronaldony/thinking-skills --log-failed
```

found five successful workflows and two failed workflows: validate-feynman and
validate-feynman-unit-diagnostic. Both failed the same test,
test_telemetry_override_replaces_configured_destination_without_overwrite,
with ValueError: invalid telemetry override path. The fixture used
Path("C:/diagnostics/fresh.json"), which is not absolute under Linux.
This test dates to the control-plane implementation; it is separate from Luna's
runtime config/metadata mapping failure.

Changed only that test to use TemporaryDirectory().resolve(), to supply a native
absolute path. Also verified that an existing override destination is rejected
and configured telemetry remains unchanged. Production boundaries were unchanged.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_subscription_control_plane_preflight
git diff --check
```

Result: 4 tests, OK; whitespace check passed. Previous Windows full-suite result
was 364 total / 11 skipped (353 executed), not 364 executed plus 11 skips.
Linux verification will be checked on the pushed full commit SHA.

## Incomplete and next action

The approved run is consumed; no second model call is authorized by this entry.
Next technical work is a model-free startup reproduction or fixed, value-free
rejection-reason classification for config and metadata, preserving the existing
mount boundary. Adding arbitrary ancestor/home mounts or pretending inaccessible
config is absent is not a justified fix. No re-login is indicated by this run.
New model smoke should follow a concrete correction and passing gates, with
separate authorization if needed.

## Commit/push

Starting head 12804ef was already pushed. This log, current handoff pointers and
the Linux fixture fix will be committed and normally pushed on the existing
feature branch. Record the resulting full SHA and CI evidence in the final
handoff. User PNGs remain untracked. No main merge or force push.

