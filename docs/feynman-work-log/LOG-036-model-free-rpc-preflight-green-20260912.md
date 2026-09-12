# LOG-036 — Model-free native RPC preflight passed

Date: 2026-09-12 KST. Repository: `Ronaldony/thinking-skills`.
Branch: `feat/feynman-thinking-v0.5-draft`. Start HEAD:
`b923360238a2a21a7b1051454a983cf80331d34f`. The tree was clean at start.
No applicable `AGENTS.md` was found. OpenAI Platform API/API keys, credential
files, token values, full environment output, development handoff material, and
any model prompt were not used.

## Reason for this unit

LOG-035's generic manual probe used incomplete exec-server assumptions. The
current image's embedded symbols and the official OpenAI Codex exec-server
documentation establish the actual lifecycle: `initialize`, `initialized`,
then exec-specific `fs/*` and `process/*` JSON-RPC messages. Filesystem paths
are `file:` URIs; the supported execution method is `process/start`, not the
previously probed `process/exec` stub.

The official source is the OpenAI Codex exec-server README:
https://github.com/openai/codex/blob/main/codex-rs/exec-server/README.md . It
documents `process/start` with `argv`, `cwd`, `env`, `tty`, `pipeStdin`, and
`arg0`; it also documents the required initialization acknowledgement and the
filesystem URI contract. The local image's embedded method/field symbols match
that direction. The public source is an implementation reference; the actual
local image is the compatibility authority for this run.

## Corrections

Updated `tooling/feynman_rpc_path_mapping.py`:

- Added `process/start.cwd` as a declared URI field.
- A Linux `file:///run/...` URI or `/run/...` path already under a declared
  mount is now validated and forwarded unchanged. It is no longer incorrectly
  reinterpreted as a Windows host path.

Updated `tooling/feynman_rpc_path_proxy.py`:

- A mapping rejection now returns the fixed `-32001` error to the control
  client and does not send that response to the Docker child. This prevents an
  invalid client request from corrupting the exec-server protocol stream.

Added `tooling/feynman_rpc_preflight.py`:

- Validates the canonical runner-job/profile/environment document.
- Starts a unique `--rm` model-free Docker container via the normal proxy.
- Uses the documented lifecycle to check candidate task read, Feynman skill
  file read, and a harmless skill readability process.
- Records only fixed result keys/statuses. It does not persist file bytes,
  process output, raw stderr, credentials, or a model request.

## Commands and verification

Focused unit/syntax verification:

```powershell
python -X utf8 -m unittest tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_path_proxy tests.test_feynman_rpc_preflight tests.test_feynman_path_mapping tests.test_feynman_remote_exec_environment
python -m py_compile tooling/feynman_rpc_path_mapping.py tooling/feynman_rpc_path_proxy.py tooling/feynman_rpc_preflight.py
git diff --check
```

Observed: 29 tests passed. Compilation and whitespace checks passed; Windows
Git line-ending/global-ignore warnings were non-fatal.

The canonical environment was generated only in Temp, then consumed by the
preflight and deleted. The dedicated evaluation control home was not modified:

```powershell
python -X utf8 tooling/feynman_remote_exec_environment.py --job <ordinal-1>\runner-job.json --boundary-profile <run-root>\boundary-profile.json --output <temp>\feynman-rpc-preflight-env-20260912.toml
python -X utf8 tooling/feynman_rpc_preflight.py --job <ordinal-1>\runner-job.json --boundary-profile <run-root>\boundary-profile.json --remote-environment <temp>\feynman-rpc-preflight-env-20260912.toml --docker-config <empty-docker-config> --output <temp>\feynman-rpc-preflight-report-20260912.json --timeout-seconds 45
```

Observed verdict: `native-rpc-preflight-passed`.

| Check | Result |
|---|---|
| canonical remote environment | valid; `include_local=false` |
| `initialize` | `environmentInfo` and `sessionId` returned |
| candidate task file read | `dataBase64` result key returned; bytes not retained |
| `feynman-thinking/SKILL.md` read | `dataBase64` result key returned; bytes not retained |
| skill readability process | `process/start` returned; `process/exited` exit code `0` |
| process sandbox denial | `false` |
| host Windows path echo in server response | `false` |
| model/auth/API access | no model request; no credential file read; no API-key env inherited |

The command used a unique `--rm` container name. It left no diagnostic
container, image, volume, candidate artifact, or evaluation-home change behind.

## Scope and next action

This resolves the model-free Windows host-to-Linux exec-server path/read/spawn
gate. It does not prove candidate task quality, semantic correctness, or a
Feynman performance effect. Ordinal 2 baseline remains unstarted.

The next authorized technical action is one repaired ordinal-1
`gpt-5.6-luna` integration smoke through the canonical ChatGPT-subscription
executor, after this code/log checkpoint is committed and pushed. It must use
the existing dedicated login only, preserve the control home, and retain the
executor's no-API-key/no-raw-auth-output protections. Main merge and force push
are not performed.

Commit/push status at log creation: pending.
