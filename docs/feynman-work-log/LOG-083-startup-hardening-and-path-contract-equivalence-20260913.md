# LOG-083 — Startup lifecycle hardening and native path contract equivalence

Date: 2026-09-13 KST. Repository: `Ronaldony/thinking-skills`.
Branch: `feat/feynman-thinking-v0.5-draft`.

## Scope and safety boundary

This unit implemented the approved Windows/Docker startup-blocker plan. It did
not run the real subscription startup diagnostic, authentication check, model
turn, smoke evaluation, baseline, retry, Terra/Sol fallback, or any Platform
API/API-key path. The protected ChatGPT subscription login home was not read,
modified, copied, or uploaded. The two user PNG files remained untracked and
were not staged. The development conversation and handoff documents were not
sent to any candidate or model.

At the start, `git status --short` showed only the pre-existing user PNGs and
the current implementation files. The branch was at `7561ba5` and the remote
had the same commit. Docker was used only for a network-disabled, temporary
fixture with a pinned remote-boundary image.

## Root cause found in the path probe

The first version of the new offline path-contract probe was intentionally
run once to expose its behavior. It sent `initialize`, `initialized`, and all
follow-up messages in one burst, and used `environmentConfig/read`,
`fs/canonicalize`, and `fs/walk` as if they were the direct exec-server
fixture contract. Direct Linux and Windows proxy peers both returned only
response id `1`; both exited `0`, had no malformed lines, and had the same
response shape. Because expected ids `2..5` were absent, the result was
correctly `rpc-path-contract-blocked` (exit `1`). This was not evidence that
Windows path mapping failed, and the unchanged probe was not repeated.

The correction used the already established exec-server lifecycle and method
contract: wait for the initialize response, then send the initialized
notification and each subsequent request only after the previous response.
The fixture requests are `fs/getMetadata`, `fs/readFile`, and `process/start`,
which exercise candidate file selection and remote `cwd` without a model or
credential. The acceptance check now also rejects a pair of matching error
responses and requires `process/exited` with exit code `0` and
`sandboxDenied=false`.

The public App Server contract separately documents JSON-RPC request/response
id correlation, the initialize/initialized lifecycle, version-specific schema
generation, and native path syntax for remote instruction sources:
https://learn.chatgpt.com/docs/app-server . This unit therefore does not
promote the offline exec-server result into proof that App Server
`thread/start` has succeeded.

## Code changes and reasons

1. `tooling/feynman_subscription_startup_diagnostic.py`

   - Added schema-v3 instruction-source allowlisting under `/run/candidate`
     and `/run/codex`; outside, relative, Windows, traversal, query, and
     fragment forms fail closed.
   - Required proxy telemetry schema v3, zero request/response mapping
     rejection, and child exit code exactly `0` before telemetry is ready.
   - Added `cleanup_verified` to the result and made startup readiness require
     it and the instruction-source allowlist.
   - Moved the 15-second cleanup deadline into `finally`, so delayed startup
     cannot consume the cleanup budget.
   - `StartupDiagnosticError` now carries the observed initialize state. The
     failure artifact no longer infers initialization success from an error
     string.

2. `tooling/feynman_rpc_path_proxy.py`

   - Changed telemetry persistence to a flush/fsync/atomic-replace sequence.
   - Updated pending request counts at registration and response correlation,
     not only during final cleanup.
   - Drained parent stdin with bounded Windows named-pipe polling (and POSIX
     select), made relay threads daemonized, and kept child/reader cleanup
     bounded when the child exits while the parent stdin remains open.
   - Bumped telemetry to schema v3.

3. `tooling/feynman_rpc_path_contract_probe.py`

   - Added a safe, pinned-image direct-vs-proxy Docker comparison probe.
   - It uses temporary candidate/home/codex/temp mounts, network `none`,
     read-only rootfs, `1000:1000`, cap drop, no-new-privileges, and `/tmp`
     tmpfs. It stores only structural roles, statuses, counters, and hashes.
   - It does not preserve file contents, raw stderr, request payloads, paths,
     credentials, or model input.

4. Tests and schema

   - Added lifecycle fixture coverage for nonzero child exit and proxy exit
     while parent stdin is open.
   - Added instruction-source, telemetry, atomic-write, and probe-shape tests.
   - Bumped `subscription-startup-diagnostic.schema.json` to v3 and required
     the new checks.

## Commands and observations

Focused regression after the changes:

```powershell
python -B -W error::ResourceWarning -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_rpc_compatibility -q
```

Result: `Ran 61 tests in 0.704s`, `OK`; no `ResourceWarning`.

The corrected offline Docker probe was then run once after the probe contract
was changed:

```powershell
$taskOutput = 'C:\DevWorks\thinking-skills\.tmp\rpc-path-contract-20260913-final.json'
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_rpc_path_contract_probe `
  --docker 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' `
  --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' `
  --image 'sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6' `
  --proxy 'C:\DevWorks\thinking-skills\tooling\feynman_rpc_path_proxy.py' `
  --output $taskOutput --timeout 45
```

Result: `rpc-path-contract-equivalent`, exit `0`.

| Check | Direct Linux peer | Windows path proxy peer |
|---|---:|---:|
| response ids | `1,2,3,4` | `1,2,3,4` |
| response status | all `result` | all `result` |
| notifications | `1` | `1` |
| `process/exited` code | `0` | `0` |
| `sandboxDenied` | `false` | `false` |
| malformed lines | `0` | `0` |
| peer exit code | `0` | `0` |
| request/response shape | same | same |

The safe report was preserved at
`.tmp/rpc-path-contract-20260913-final.json`. The earlier blocked report and
the sequential intermediate report were also preserved there as diagnostic
evidence. No temporary Docker container remains from the probe.

Syntax, whitespace, full regression, and schema checks:

```powershell
python -B -m py_compile tooling/feynman_subscription_startup_diagnostic.py tooling/feynman_rpc_path_contract_probe.py tooling/feynman_rpc_path_proxy.py
git diff --check
python -B -W error::ResourceWarning -m unittest discover -s tests
python -c "from pathlib import Path; import json; from jsonschema import Draft202012Validator; files=sorted(Path('evals').rglob('*.schema.json')); [Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; print(f'schema_files={len(files)} errors=0')"
```

Results:

- full suite: `Ran 419 tests in 13.923s`, `OK (skipped=11)`;
- schema validation: `schema_files=17 errors=0`;
- compile and `git diff --check`: exit `0`;
- the 11 skips remain host-capability/Windows/Node/Docker/symlink conditions;
  they are not counted as Docker or model compatibility success.

## Commit and push

Implementation commit:

```text
b1a1904 fix: harden startup lifecycle and path probe
```

It contains the code, tests, schema, and probe. User PNGs and `.tmp` evidence
were not included. The documentation checkpoint and remote push are the next
operation after this log is added; main merge and force push are excluded.

## Remaining boundary and next action

The offline Windows-to-Linux exec-server path contract is green for the pinned
fixture. This does not resolve the prior real App Server `thread/start`
`-32603 remote-environment-error`, because that requires the separate
subscription startup lifecycle. The new gate is now stricter and will not
accept incomplete telemetry, nonzero child exit, unapproved instruction
sources, or unverified cleanup.

No further automatic startup or model execution is authorized in this unit.
The next human boundary is one explicitly chosen real subscription startup
diagnostic using the new final gate. If it passes, the already approved
conditioned Luna smoke can be considered; if it fails, do not retry or
fallback automatically. Baseline evaluation remains unstarted.
