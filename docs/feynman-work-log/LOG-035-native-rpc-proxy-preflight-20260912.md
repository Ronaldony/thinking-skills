# LOG-035 — Native RPC proxy and model-free preflight

Date: 2026-09-12 KST. Repository: `Ronaldony/thinking-skills`.
Branch: `feat/feynman-thinking-v0.5-draft`. Start HEAD:
`afcedbb375f9ea861912108f3da541ec3b627b23`. The working tree contained only
the new RPC path-mapping files from the preceding uncommitted checkpoint;
existing user changes were preserved. No applicable `AGENTS.md` was found.
OpenAI Platform API/API keys, login files, token material, full environment
output, and development handoff content were not used as evaluation input.

## Purpose and scope

LOG-034 identified that the real Linux `exec-server` rejected Windows `file:`
URIs before a useful candidate tool call. The implementation unit here was a
field-specific native Windows stdio proxy, plus a model-free live preflight.
The proxy must map only declared RPC path fields under the four validated
candidate-owned mounts. It must not rewrite arbitrary command arguments,
arbitrary strings, prompts, file contents, or authentication values.

No baseline job, Feynman behavioral evaluation, or additional model request was
started. The dedicated ChatGPT subscription evaluation home was not modified
by this work.

## Implementation

Added `tooling/feynman_rpc_path_mapping.py`:

- Windows host sources map to Linux `/run/candidate`, `/run/home`,
  `/run/codex`, and `/run/temp` using the validated runner-job mount map.
- Windows `file:` URIs and raw absolute host paths are supported for declared
  request fields only: `command/exec.cwd`, `process/exec.cwd`,
  `fs/readFile.path`, `fs/writeFile.path`, and `resources/read.uri`.
- Response `cwd`, `path`, and `uri` fields map back to the host namespace.
- Outside-root, traversal, non-local URI, query, and fragment cases fail
  closed. Non-path JSON values remain unchanged; unchanged JSON lines are
  forwarded in their original form.

Added `tooling/feynman_rpc_path_proxy.py`:

- Parses the exact `-v source:destination:access` values from the generated
  Docker command, splitting from the right so Windows drive letters remain
  intact.
- Starts the declared Docker child with stdin/stdout pipes and relays JSONL in
  both directions without logging payloads.
- Converts mapping failures into a fixed `RPC path mapping rejected` error with
  no rejected path echo; raw subprocess diagnostics are not persisted.

Updated `tooling/feynman_remote_exec_environment.py`:

- The generated Codex environment now runs the host Python interpreter and the
  field-specific proxy, which starts Docker as its child.
- Removed Docker `--workdir /run/candidate`. The candidate workspace is not a
  Git repository, while this exec-server build requires its process startup
  directory to remain the image default. RPC `cwd` values are still mapped to
  `/run/candidate` by the proxy.
- Kept the four writable bind mounts and the read-only rootfs. Changed the
  container `TMPDIR` assignment from `/run/temp` to `/tmp`, the declared
  writable tmpfs. On this image, `/run/temp` caused exec-server to exit before
  RPC initialization even when the mount was present; `/tmp` produced a normal
  initialization response. The `/run/temp` mount remains in the boundary
  contract and is not broadened or removed.

## Commands and observations

Focused regression and syntax checks:

```powershell
python -X utf8 -m unittest tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_path_proxy tests.test_feynman_path_mapping tests.test_feynman_remote_exec_environment
python -m py_compile tooling/feynman_rpc_path_mapping.py tooling/feynman_rpc_path_proxy.py tooling/feynman_remote_exec_environment.py
git diff --check
```

Observed: 38 focused tests passed before the final environment tweak; after the
tweak, 24 affected tests passed. Compilation and whitespace checks passed;
Git emitted only existing Windows global-ignore/line-ending warnings.

The canonical environment was generated to a temporary file, not written into
the dedicated control home:

```powershell
python -X utf8 tooling/feynman_remote_exec_environment.py --job <ordinal-1>\runner-job.json --boundary-profile <run-root>\boundary-profile.json --output <temp>\feynman-rpc-proxy-env-20260912.toml
```

The generator returned `remote-exec-environment-valid`, `include_local=false`,
the expected image and mount contract, and a proxy program/argument document.

The following model-free Docker matrix used unique temporary container names
and sent only the JSON-RPC `initialize` request. The fixed result was measured
as stdout/stderr byte counts and exit status; no raw output was preserved.

| Variant | stdout bytes | stderr bytes | Interpretation |
| --- | ---: | ---: | --- |
| all four mounts, `TMPDIR=/run/temp` | 0 | 0 | no RPC initialization |
| remove candidate mount | 462 | 0 | initialization returned |
| remove home mount | 462 | 0 | initialization returned |
| remove codex mount | 462 | 131 | initialization returned with diagnostic |
| remove temp mount | 0 | 0 | no RPC initialization |
| all mounts, `TMPDIR=/tmp` | 452 | 0 | initialization returned |

This isolated the environment variable, not a need to remove the temp mount.
An additional mount-permission probe under uid `1000` returned fixed markers for
uid, candidate readability/writability, and codex readability; mount access was
not the blocker.

The actual proxy was then launched from the generated document with a unique
Docker container name. After initialization, the observed response had id 1,
result keys `environmentInfo` and `sessionId`, and no Windows host path echo.
Sequential model-free requests produced:

- `fs/readFile` with a Windows `file:` URI: server response code `-32600` in
  one contract probe, with no Linux file-URI rejection. A later raw-path probe
  reached the server as `-32602`; this is a request-shape issue, not a mapper
  rejection.
- `process/exec` with mapped candidate cwd: server response code `-32601`,
  matching the image's fixed “stub does not implement process/exec yet”
  capability response.
- No model request, prompt, candidate answer, or auth material was involved.

The proxy therefore proves the Windows-to-Linux URI namespace conversion and
safe rejection boundary, but it does not yet meet the stronger acceptance
criteria of successful candidate-file read and harmless command execution.
The current image's `process/exec` stub and the unresolved exact `fs/readFile`
parameter contract remain blockers for a green remote-tool preflight.

## Cleanup and verification scope

The matrix/probe created only temporary Feynman diagnostic containers. They were
removed by exact container names after the observations. The follow-up Docker
listing showed no remaining containers whose name matched `feynman` at the
cleanup point. No image, volume, source artifact, dedicated auth home, or
non-Feynman container was deleted.

Full repository regression:

```powershell
python -X utf8 -m unittest discover -s tests
```

Observed: 290 tests passed, 10 skipped. No model turn was started. This is a
repository regression result, not an evaluation or CI result.

## Commit/push and next action

At this log's creation, code, tests, and this log are pending commit/push. The
next action is to review/stage these files, commit them on the feature branch,
push to `origin/feat/feynman-thinking-v0.5-draft`, and verify the remote SHA and
clean working tree. After that, do not rerun the model. The next technical unit
is to identify the supported `fs/readFile` request schema and an exec-server
version/mode that implements harmless command execution, then rerun only the
model-free preflight. Baseline remains unstarted.

Main merge and force push were not performed.
