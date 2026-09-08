# feynman-thinking 작업 상태

기준: 2026-09-08, `feat/feynman-thinking-v0.5-draft` research preview.

이 문서는 구현 상태를 성능 주장과 분리해 기록한다. 체크가 되어 있다는 이유만으로 실제 모델 성능 또는 배포 안전성이 입증됐다고 해석하지 않는다.

| ID | 상태 | 현재 근거 | 남은 조건 |
|---|---|---|---|
| FYN-01 기존 감사 재검증 | **완료** | pinned v0.4.0 구조 결함 재현 코드/문서 | 실제 과거 모델 결과의 재채점은 별개 |
| FYN-02 역할·설계 확정 | **완료** | v0.5.0-draft SKILL + references | 행동 평가 후 규칙 축소 가능 |
| FYN-03 `thinking-skills` 통합 | **완료(draft)** | feature branch + draft PR + runtime allowlist | 병합은 성능 검증 뒤 |
| FYN-04 평가 격리 | **부분 완료 — pre-auth real-run readiness까지 검증** | boundary/canary/inspect + remote exec/patch + synthetic-auth + two-job real-run readiness E2E | 실제 외부 model-service credential/응답 + 실제 평가 run에서 동일 계약 재검증 필요 |
| FYN-05 실행 증거/합격 판정 연결 | **완료(구조 v3)** | frozen plan → runner-job v2 → profile/probe → attestation v2 → runner-job-link v2 + trace → evidence → review v2 → gate → analysis-result v3 | 실제 semantic judge/human review 결과 필요 |
| FYN-06 자동 검사/회귀 | **완료(구조)** | 310-unit diagnostic + 8개 structural/reference workflows | 실제 external model-run regression은 FYN-08에서 추가 |
| FYN-07 평가 데이터 보강 | **개발 세트 완료** | 18 public-development cases, 20 predefined hard failures, controls | 독립 작성 held-out final set 필요 |
| FYN-08 통제된 신·구 비교 | **미실행** | frozen plan/conditions/result-v3/aggregator-v3 + integration-only smoke spec/readiness 준비 | authorized external model control plane, real requests, repeats, semantic review 필요 |
| FYN-09 실패 분석/규칙 축소 | **대기** | ablation 원칙만 사전등록 | FYN-08 결과 필요 |
| FYN-10 검토·버전 확정·배포 | **대기** | draft PR 유지 | FYN-08/09 및 held-out 결과 필요 |

## FYN-04 세부 상태

### 완료된 부분

- candidate/evaluator/source/real-HOME 경계 계약
- candidate tool environment secret-like key 차단 계약
- `boundary-profile.json` schema/validator
- inside-boundary read/write/env/network canary recorder
- evaluator-side host post-verifier
- control-plane TCP reachability reference
- mount-namespace `ENOENT`를 host fixture와 교차검증하는 규칙
- Docker profile raw SHA → probe artifact → report → attestation 연결
- Docker inspect/profile consistency validator
- runner-job schema v2/builder/strict validator
- pre-run runner job → post-run attestation linkage artifact schema v2
- canonical Codex remote `environments.toml` generator/validator (`include_local=false`)
- 실제 Docker tool-process reference canary 성공
- Codex CLI가 포함된 동일 boundary profile reference 성공
- credential-free remote `exec_command` E2E reference 성공
- bundled patch-capable metadata 기반 remote `apply_patch → exec_command` E2E reference 성공
- synthetic bearer control-plane-only auth separation reference 성공
- `analysis-result.schema.json` v3 + v3-only canonical aggregator
- `real-run-readiness.schema.json` + credential-free readiness preflight
- integration-only real-model smoke spec 고정:
  - `tools-10`
  - `baseline`, `feynman-v05`
  - 각 1회
  - 성능 추론 금지
- **실제 GitHub runner에서 two-job pre-auth readiness E2E 성공**
  - bundled model metadata id: `gpt-6-astra`
  - Codex: `codex-cli 0.153.4`
  - ordinal 1: `feynman-v05`, expected skill=`feynman-thinking`, runtime digest 존재
  - ordinal 2: `baseline`, expected skills empty, runtime digest null
  - 두 job 모두 `ready-for-control-plane-auth`
  - credential env-key 이름=`OPENAI_API_KEY`
  - `credential_value_used=false`
  - `external_model_request_sent=false`
  - candidate auth exposed=false

### 아직 완료하지 않은 부분

- 승인된 실제 외부 model-service credential/account access를 control-plane 전용으로 설정
- `gpt-6-astra`가 해당 실제 account에서 사용 가능한지 실제 요청으로 확인
- 실제 external model request/response 성공
- 실제 run마다 boundary canary/report + runner-attestation v2 + runner-job-link v2를 새로 보존
- 실제 trace → evidence → semantic review → gate → analysis-result v3 생성
- 행동 평가에 실제 사용되는 모든 candidate-accessible tool 유형의 boundary regression
- 실제 multi-turn model run에서 same-thread continuity 검증

중요: reference/readiness 성공은 **검증한 transport/tool/auth/pre-run architecture의 실행 가능성**을 입증하지만 실제 model-service 인증 성공, account entitlement, rate limit, 모델 품질을 입증하지 않는다.

## FYN-05 세부 상태 — analysis-result v3

canonical analysis chain:

```text
frozen plan
  → runner-job.json v2 (pre-run)
  → boundary profile/probe + model/tool execution
  → runner-attestation.json v2 (post-run)
  → runner-job-link.json v2

trace
  → evidence
  → review bundle
  → semantic review v2
  → grade gate

두 경로
  → analysis-result.json v3
  → canonical aggregate (v3 result only)
```

`feynman_eval_result.py`는 raw runner job과 raw runner-job-link를 모두 필수로 요구한다. saved link를 그대로 믿지 않고 raw profile/probe/attestation에서 다시 계산하며 frozen plan의 ordinal/case/condition/repeat/followup/prompt/plan digest와 runner job을 직접 대조한다.

`analysis-result.schema.json`이 canonical schema v3 형식이다. historical result/aggregate v2 구현은 `*_v2_legacy.py`로만 보존하며 새 primary aggregation에는 넣을 수 없다.

canonical aggregator는 model/Codex/runner/runtime뿐 아니라 **control-plane authentication profile(mode/source/env-key 이름)**이 섞여도 `mixed-environment`로 차단한다.

## 최신 구조 회귀 상태

검증 head: `fed6ff976f827539a829c4087670da58d3439fe9`

full unittest diagnostic:

- **310 tests**
- **1.021s**
- exit code `0`
- `OK`

동일 head에서 다음 8개 workflow 모두 success:

1. `validate-feynman` — run #407, id `34233537435`
2. `validate-feynman-docker-reference` — run #105, id `34233537474`
3. `validate-feynman-codex-reference` — run #95, id `34233537379`
4. `validate-feynman-remote-exec-reference` — run #112, id `34233537478`
5. `validate-feynman-remote-patch-reference` — run #74, id `34233537462`
6. `validate-feynman-synthetic-auth-reference` — run #53, id `34233537400`
7. `validate-feynman-unit-diagnostic` — run #50, id `34233537418`
8. `validate-feynman-real-run-readiness` — run #7, id `34233537420`

pre-auth readiness artifact:

- artifact id `10058836269`
- ZIP SHA-256 `9f3cf4c5e430af52b594b16ee14d034b3a223b22b6c1ad3753987f150c0672d2`
- smoke-plan SHA-256 `d64dc0e685e40b824f5ad973f7d67f92230eeea02d772f9b81b14138844f4884`

세부 이력은 `docs/feynman-work-log/LOG-010-real-run-preauth-readiness.md`에 기록한다.

## 성능 주장 상태

현재 **성능 개선 주장은 0개**다.

아직 존재하지 않는 값:

- generic 대비 decision correctness 개선량
- critical failure 비열등성
- execution integrity failure rate 비교
- justified revision / retention 개선량
- token / wall-time / tool-call 비용 차이
- held-out 결과

integration-only two-job smoke가 실제로 실행되더라도 그 결과는 위 효과 추정에 사용하지 않는다.

## 사람 개입이 처음 필요한 지점

**이제 다음 의미 있는 실행 단계부터 실제 외부 권한이 필요하다.**

사람/runner 운영자가 해야 하는 것은 secret 값을 채팅이나 repository에 쓰는 일이 아니라 승인된 secret store 또는 runner environment에서 **control-plane 전용 model-service credential/account access**를 사용할 수 있게 하는 것이다.

현재 고정 auth contract:

```json
{
  "mode": "control-plane-only",
  "control_plane_credential_source": "environment",
  "control_plane_credential_env_key": "OPENAI_API_KEY"
}
```

여기서 env-key **이름만** artifact에 기록하며 실제 값은 기록하지 않는다. candidate tool env/file/argv에는 credential을 전달하지 않는다.

이 저장소 작업만으로는 실제 credential/account 권한을 만들어낼 수 없으므로 이 지점이 첫 필수 사람/운영 환경 개입이다.

## 다음 실행 순서

```text
[완료] mock exec + remote patch + synthetic-auth boundary references
  → [완료] runner-job ↔ attestation mandatory linkage + analysis-result v3
  → [완료] integration-only real-model smoke spec + two-job pre-auth readiness
  → 실제 model-service control-plane credential/account access 설정  ← 현재 사람 개입 지점
  → tools-10 × {baseline, feynman-v05} 실제 external-model integration smoke
  → 동일 run boundary canary/report
  → runner-attestation v2 / runner-job-link v2
  → trace / evidence / review / gate / result-v3 확인
  → four-condition public-development pilot
  → pilot 분산/비용으로 final 기준 고정
  → independent held-out 작성/동결
  → four-condition final comparison
  → failure + ablation analysis
  → merge/revise/drop 결정
```
