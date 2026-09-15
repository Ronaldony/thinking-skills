# LOG-034 — Docker cleanup and native RPC next step

Date: 2026-09-12 KST. Repository: `Ronaldony/thinking-skills`.
Branch: `feat/feynman-thinking-v0.5-draft`. Start HEAD: `27e94d3`.
Start working tree: clean. No applicable `AGENTS.md` was found in the prior
checkpoint. OpenAI Platform API/API keys and authentication contents were not
used or inspected.

## Container cleanup

The exact failed-smoke diagnostic container was resolved before deletion:

```powershell
docker --config <empty-config> ps -a `
  --filter 'name=^/feynman-tool-subscription-gpt-5.6-luna-20260910-ordinal-1-feynman-v05$' `
  --format '{{.ID}}|{{.Names}}|{{.Status}}|{{.Image}}'
```

Observed one exact match: ID prefix `668bf46c6745`, state `Exited (0)`, image
`feynman-codex-remote:local`. Its required inspect/RPC classification evidence
was already recorded in LOG-033. The following exact deletion succeeded:

```powershell
docker --config <empty-config> rm `
  feynman-tool-subscription-gpt-5.6-luna-20260910-ordinal-1-feynman-v05
```

A follow-up `docker ps -a --filter name=feynman` found three exited native
boundary diagnostic containers from three days earlier. Each used the same
local evaluation image and had no running process. They were removed by exact
name:

```powershell
docker --config <empty-config> rm `
  feynman-tool-native-windows-boundary-check-25271eded3634474a8b6fcf0de352668 `
  feynman-tool-native-windows-boundary-check-3ec58b9fb6f542cd8328658947607879 `
  feynman-tool-native-windows-boundary-check
```

All three deletions succeeded. Final `docker ps -a --filter name=feynman`
returned no entries. Images, volumes, working directories, evaluation artifacts,
dedicated control home, and non-Feynman containers were not removed. Deleted
container metadata/logs are not recoverable from Docker; the non-sensitive
findings needed for continuation remain in LOG-031 and LOG-033.

## Evidence checked for the next step

Repository search did not find a hand-written exec-server request fixture or
protocol field mapping. The existing native canary validates Docker mounts and
container paths, but not the Codex control-to-exec-server RPC path values.

The official Codex configuration reference was searched for `include_local`,
`environments.toml`, and `path mapping`; no documented native path-mapping field
was found. Therefore the next implementation should not invent an unsupported
configuration key.

## Next implementation unit

Build a model-free protocol compatibility preflight before changing the real
executor:

1. Capture only JSON-RPC method names, field names, URI platform classes, response
   codes, and counts from the existing synthetic/mock Codex reference path. Do
   not store prompts, file contents, host paths, auth data, or arbitrary strings.
2. Replay the minimum initialize, candidate-file read, and command-spawn sequence
   against the real Linux `codex exec-server` container on Windows.
3. Require the probe to demonstrate that every candidate path arriving at Linux
   is under `/run/candidate` and that the skill is discoverable under
   `/run/candidate/.agents/skills/feynman-thinking`.
4. If current Codex exposes a supported path-map facility, bind it to the four
   validated runner-job mounts. Otherwise implement a field-specific stdio proxy
   that converts only declared URI/path fields under those roots, rejects paths
   outside the mount map, preserves all other JSON values byte-for-byte where
   possible, and never logs payload contents.
5. Add Windows mapping, traversal/rejection, response mapping, and privacy tests;
   then run the model-free probe. Only after it passes should ordinal 1 be rerun.

Acceptance criteria for this unit are: zero Windows file URI rejection on Linux,
candidate fixture read succeeds, a harmless command executes in the declared
container workspace, Feynman skill discovery succeeds, undeclared paths fail
closed, and no model request occurs. Ordinal 2 baseline remains unstarted until
the repaired ordinal 1 completes its actual task and evidence lineage.

Commit/push status at file creation: pending. Main merge and force push are not
performed.

## Storage confirmation

`git diff --check` completed without a whitespace error. This log was committed
as `8c1f2b0` (`docs: record Docker cleanup and RPC next step`) and pushed to
`origin/feat/feynman-thinking-v0.5-draft`. The exact remote HEAD and final clean
working-tree state are verified in the documentation follow-up commit.
