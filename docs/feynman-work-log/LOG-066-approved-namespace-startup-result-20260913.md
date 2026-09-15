# LOG-066 — Approved namespace diagnostic: result and interpretation limits

- Date: 2026-09-13 KST; repository `C:\DevWorks\thinking-skills`.
- Branch: `feat/feynman-thinking-v0.5-draft`.
- Execution code: `33c0730f2096d3f2cda94be688529f3d79f11bc7`.
- User approved exactly one additional namespace-instrumented model-free startup.
- One invocation; no automatic repeat, turn/start, model evaluation or fallback.

## Local checks and exact invocation

`git status --short --branch` showed the feature branch synchronized with origin,
with only the two pre-existing user PNGs untracked. `rg -n 'path is outside|outside-declared'
tooling/feynman_rpc_path_proxy.py` confirmed the two new labels. `Test-Path` for
both `startup-diagnostic-20260913-03.json` and `startup-diagnostic-20260913-03-rpc.json`
in the evaluator directory returned False. Explicit ancestor AGENTS.md checks and
`rg --files -g AGENTS.md` found no applicable file (rg exit 1 means no match).

PowerShell working directory: `C:\DevWorks\thinking-skills`.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_subscription_startup_diagnostic --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote-environment 'C:\Users\wotmd\.codex-feynman-eval\environments.toml' --binding 'C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json' --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --telemetry 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-03-rpc.json' --output 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-03.json' --timeout-seconds 45
```

The shell command returned exit 0 because the diagnostic successfully produced
its report; this is NOT a successful startup verdict.

## Observed result

```json
{
  "verdict": "subscription-startup-thread-blocked",
  "thread_started": false,
  "error_code": -32603,
  "error_category": "remote-environment-error",
  "turn_requests_sent": 0,
  "model_generation_requests_sent": 0,
  "request_mapping_rejection_methods": {
    "environmentConfig/read": 1,
    "fs/getMetadata": 6
  },
  "request_mapping_rejection_reasons": {
    "container-path-outside-declared-mount": 2,
    "host-path-outside-declared-mount": 4,
    "invalid-host-path": 1
  }
}
```

Safe artifact fields: initialize completed true; process tree reaped true;
requests seen/forwarded/rejected 12/5/7; request methods initialize 1,
initialized 1, environmentConfig/read 1, fs/getMetadata 9; responses seen/forwarded
4/4, response mapping rejection 0, response error codes `-32004:3`, child exit 0.
Do not assign a meaning to the remote -32004 code without the versioned contract.
All recorded privacy flags remained false. No credentials, tokens, raw stderr or
RPC payloads were displayed, copied or uploaded. Only official Codex used the
existing ChatGPT login; no Platform API or API key was used. Development/handoff
documents were not placed in the candidate. No fresh independent auth gate was
run: this result does not by itself establish current authentication success.

`docker.exe --config C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config
ps -a --filter 'name=feynman-' --format '{{.Names}}|{{.Status}}'` with the executable
above returned no containers, exit 0. No manual deletion was necessary.

## Artifact validation and offline diagnosis

Read only the report's fixed checks, privacy and proxy_telemetry fields via
`Get-Content -Raw | ConvertFrom-Json`. Checked jsonschema availability using
`python.exe -c 'import importlib.util; print(importlib.util.find_spec("jsonschema") is not None)'`.
It was already installed; no dependency installation was performed.

Validated the actual report against the checked-in schema with Python's
`jsonschema.Draft202012Validator.check_schema(schema)` and
`Draft202012Validator(schema).validate(report)`: `artifact_schema_valid=True`.
Both schema and report were decoded from their exact JSON paths; no output
artifact was rewritten.

Read `tooling/feynman_rpc_path_mapping.py` lines 117 onward and LOG-065. The
mapper's `host_to_container` catches a raw POSIX container-path rejection and
then tries `_host_to_container_path`. Consequently, the labels identify an
exception branch, not reliably the original request's namespace.

Executed this offline fixture (no Codex, Docker, authentication or filesystem
probe launched):

```python
import json
from tooling.feynman_rpc_path_mapping import RpcPathMapper
from tooling.feynman_rpc_path_proxy import _map_request_payload_with_reason
mapper = RpcPathMapper.from_mounts([
    {"source": "C:/fixture/candidate", "destination": "/run/candidate"}
])
cases = [
    ("raw-posix", "fs/getMetadata", {"path": "/var/private.txt"}),
    ("uri-posix", "fs/getMetadata", {"path": "file:///var/private.txt"}),
    ("raw-windows", "fs/getMetadata", {"path": "C:/private/example"}),
    ("relative-config", "environmentConfig/read", {"cwd": "/run/candidate", "configPaths": [["relative"]]}),
    ("traversal-config", "environmentConfig/read", {"cwd": "/run/candidate", "configPaths": [["/run/candidate/../home/config.toml"]]}),
]
print(json.dumps([
    {"fixture": name, "reason": _map_request_payload_with_reason(
        mapper, json.dumps({"id": 1, "method": method, "params": params}).encode()
    )[2]} for name, method, params in cases
]))
```

Results: raw-posix and raw-windows BOTH yielded
`host-path-outside-declared-mount`; uri-posix yielded
`container-path-outside-declared-mount`; relative-config and traversal-config
BOTH yielded `invalid-host-path`. All fixtures used synthetic values.

The method and reason counters are separate marginal counts, not paired events.
They cannot establish that the invalid path belongs to config or that each
out-of-mount path belongs to metadata. Earlier LOG-064/065 prose and responses
implied these assignments too strongly. This log supersedes those inferences.
The exact rejected path/field was never retained and cannot be reconstructed.

## Decision and next work

The runtime remains blocked at remote startup, with seven request-side mapping
rejections observed. Their exact causal relation to -32603 is not fully proven.
The previous claim that one namespace diagnostic would conclusively distinguish
host mount shortage from container allowlist shortage was too strong. Repeating
the same probe cannot remove the demonstrated classification ambiguity.

Next: inspect the versioned config-path construction contract and reproduce its
raw/URI, relative and traversal forms offline. Determine intended resolution
rules before changing path mapping. Keep the four existing mounts and deny
undeclared paths; do not invent missing config responses or add home/ancestor
mounts. A future integration run must follow a concrete, tested correction and
remain within an explicit execution authorization. No additional external run is
requested or performed by this checkpoint. Skill effectiveness remains untested.

This turn changes documentation only. The existing 372 total / 11 skipped test
result is historical; no new full-suite result is claimed. `git diff --check`
will validate the documentation change before commit. An initial search named
nonexistent pyproject.toml/requirements* paths and emitted lookup errors; it did
not affect execution or change files.

## Commit/push

The result and interpretation corrections were committed as
`a2f1e753df6ea6fcfa87ff28cdf3a6513f2a45ec` and pushed normally with
`git push origin feat/feynman-thinking-v0.5-draft` (33c0730..a2f1e75).

```powershell
$diagnosticSha = git rev-parse HEAD
gh run list --repo Ronaldony/thinking-skills --commit $diagnosticSha --limit 20 --json databaseId,workflowName,status,conclusion
git status --short --branch
```

All seven workflows for that exact SHA completed successfully. Run IDs:
34736432353 (subscription-readiness), 34736432345 (validate-feynman),
34736432354 (docker-reference), 34736432360 (unit-diagnostic),
34736432349 (remote-patch-reference), 34736432359 (remote-exec-reference),
34736432368 (codex-reference). These CI checks do not validate live subscription
startup or model behavior. Status showed the feature branch synchronized with
origin, with only the two user PNGs untracked.

This CI receipt is a subsequent documentation-only commit, not part of the SHA
whose CI results are recorded above. No main merge or force push.
