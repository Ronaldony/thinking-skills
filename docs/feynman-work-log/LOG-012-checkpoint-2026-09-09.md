# LOG-012 — current GitHub checkpoint before external credential handoff

- **시각(KST)**: 2026-09-09 00:23
- **저장소**: `Ronaldony/thinking-skills`
- **브랜치**: `feat/feynman-thinking-v0.5-draft`
- **PR**: #1 `feat: add Feynman thinking skill research preview`
- **PR 상태**: open / draft / not merged
- **체크포인트 직전 branch head**: `1095b7f8e0a31485fe64c26803ff0d7f32b1ca20`
- **코드/reference 최종 검증 head**: `fed6ff976f827539a829c4087670da58d3439fe9`

## 이 체크포인트의 목적

현재까지 완료된 구현·문서·작업 로그가 GitHub branch에 저장됐음을 명시하고, 세션이 중단되어도 이 파일과 `LOG-011`만으로 정확히 재개할 수 있게 한다.

이 문서는 성능 결과를 새로 주장하지 않는다. 현재 단계는 **실제 external model-service credential/account를 사용하기 직전**이다.

## 저장된 주요 구현

### runtime / skill

- `skills/feynman-thinking/` v0.5.0-draft runtime
- explicit runtime allowlist와 runtime digest
- evidence map / protocol / handoff contract
- implicit invocation 비활성화 research-preview 정책

### evaluation separation

- candidate/evaluator workspace 분리
- public-development 18 cases / evaluator-only rubrics
- 20 predefined hard failures
- baseline / generic / legacy-clean / feynman-v05 frozen conditions
- sanitized pinned legacy runtime

### external boundary

- boundary-profile schema/validator
- inside-boundary read/write/env/network canary
- evaluator-side host verifier
- network reference generator
- Docker inspect/profile consistency 검증
- namespace-hidden `ENOENT` + host fixture cross-check

### remote Codex/tool architecture

- host-side control-plane Codex
- Docker `--network none` stdio `codex exec-server --listen stdio`
- canonical `environments.toml` generator/validator
- remote `exec_command` reference E2E
- remote `apply_patch` reference E2E

### authentication architecture

현재 정본:

```json
{
  "mode": "control-plane-only",
  "control_plane_credential_source": "environment",
  "control_plane_credential_env_key": "OPENAI_API_KEY",
  "candidate_tool_auth_env_keys": [],
  "candidate_readable_credential_files": [],
  "credential_command_arguments": []
}
```

credential 값은 repository/artifact/result에 저장하지 않는다.

synthetic-auth reference에서 control-plane bearer는 존재하지만 candidate tool env/file/argv 및 보존 artifact exact-byte scan에는 나타나지 않는 경로를 검증했다.

### run lineage / analysis chain

```text
frozen plan
  → runner-job.json v2
  → boundary profile / probe
  → runner-attestation.json v2
  → runner-job-link.json v2

trace
  → evidence
  → review bundle
  → semantic review v2
  → grade gate

두 경로
  → analysis-result.json v3
  → v3-only aggregator
```

canonical analysis result는 raw runner-job과 raw runner-job-link를 필수 입력으로 요구하며 saved link를 raw inputs에서 다시 계산한다.

historical result/aggregate v2 코드는 `*_v2_legacy.py`로 보존된다.

### pre-auth real-run readiness

저장된 구성:

- `evals/feynman-thinking/real-model-smoke-spec.json`
- `tooling/feynman_real_smoke_plan.py`
- `evals/feynman-thinking/real-run-readiness.schema.json`
- `tooling/feynman_real_run_preflight.py`
- `.github/workflows/validate-feynman-real-run-readiness.yml`

고정된 첫 actual integration smoke:

```text
case: tools-10
conditions:
  - baseline
  - feynman-v05
repeats: 1 each
analysis use: not-for-skill-performance-inference
```

## 최신 검증 결과

`fed6ff976f827539a829c4087670da58d3439fe9` 기준:

- full unittest: **310 tests / OK**
- `validate-feynman`: success
- `validate-feynman-docker-reference`: success
- `validate-feynman-codex-reference`: success
- `validate-feynman-remote-exec-reference`: success
- `validate-feynman-remote-patch-reference`: success
- `validate-feynman-synthetic-auth-reference`: success
- `validate-feynman-unit-diagnostic`: success
- `validate-feynman-real-run-readiness`: success

pre-auth readiness artifact:

- workflow run id: `34233537420`
- artifact id: `10058836269`
- artifact ZIP SHA-256: `9f3cf4c5e430af52b594b16ee14d034b3a223b22b6c1ad3753987f150c0672d2`
- smoke-plan SHA-256: `d64dc0e685e40b824f5ad973f7d67f92230eeea02d772f9b81b14138844f4884`
- model metadata id selected by installed Codex: `gpt-6-astra`
- Codex: `codex-cli 0.153.4`
- baseline and feynman-v05 jobs both reached `ready-for-control-plane-auth`
- `credential_value_used=false`
- `external_model_request_sent=false`
- `candidate_auth_exposed=false`

## 현재 정확한 중단 지점

자동화 가능한 credential-free 준비는 완료됐다.

다음 missing input:

```text
operator-controlled control-plane model-service credential/account access
```

기본 env-key 이름은 `OPENAI_API_KEY`이며, **값은 채팅이나 GitHub에 저장하지 않는다.**

실제 credential이 승인된 runner/secret store에 설정된 후 `LOG-011`의 순서대로 two-job integration smoke부터 실행한다.

## 재개 규칙

다음 세션에서 작업을 재개할 때:

1. 이 체크포인트 파일과 `LOG-011-human-handoff-after-preauth.md`를 먼저 읽는다.
2. PR #1의 최신 head가 이 체크포인트 이후 이동했는지 확인한다.
3. credential 값 자체는 요청하거나 기록하지 않는다.
4. 실제 model-service integration smoke 전에는 Feynman skill 성능 향상을 주장하지 않는다.
5. smoke 성공 전에는 four-condition pilot으로 확대하지 않는다.
6. 모든 후속 변경/실패/CI 결과를 `docs/feynman-work-log/`에 새 LOG 번호로 기록한다.
