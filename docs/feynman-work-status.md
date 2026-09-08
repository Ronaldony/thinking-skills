# feynman-thinking 작업 상태

기준: 2026-09-08, `feat/feynman-thinking-v0.5-draft` research preview.

이 문서는 구현 상태를 성능 주장과 분리해 기록한다. 체크가 되어 있다는 이유만으로 실제 모델 성능 또는 배포 안전성이 입증됐다고 해석하지 않는다.

| ID | 상태 | 현재 근거 | 남은 조건 |
|---|---|---|---|
| FYN-01 기존 감사 재검증 | **완료** | pinned v0.4.0 구조 결함 재현 코드/문서 | 실제 과거 모델 결과의 재채점은 별개 |
| FYN-02 역할·설계 확정 | **완료** | v0.5.0-draft SKILL + references | 행동 평가 후 규칙 축소 가능 |
| FYN-03 `thinking-skills` 통합 | **완료(draft)** | feature branch + draft PR + runtime allowlist | 병합은 성능 검증 뒤 |
| FYN-04 평가 격리 | **부분 완료** | boundary profile, canary, host verifier, Docker reference, inspect validators, Codex CLI reference workflow | credential broker + 실제 model request가 같은 경계 계약을 통과해야 완료 |
| FYN-05 실행 증거/합격 판정 연결 | **완료(구조)** | trace → evidence → review v2 → gate → result hash chain | 실제 semantic judge/human review 필요 |
| FYN-06 자동 검사/회귀 | **완료(구조)** | unit tests + structural/Docker/Codex reference workflows | 실제 model-run regression은 FYN-08 이후 추가 |
| FYN-07 평가 데이터 보강 | **개발 세트 완료** | 18 public-development cases, 20 predefined hard failures, controls | 독립 작성 held-out final set 필요 |
| FYN-08 통제된 신·구 비교 | **미실행** | frozen plan/conditions/aggregator 준비 | actual model runner, broker, repeats, semantic review 필요 |
| FYN-09 실패 분석/규칙 축소 | **대기** | ablation 원칙만 사전등록 | FYN-08 결과 필요 |
| FYN-10 검토·버전 확정·배포 | **대기** | draft PR 유지 | FYN-08/09 및 held-out 결과 필요 |

## FYN-04 세부 상태

### 완료된 부분

- candidate/evaluator/source/HOME 경계 계약
- candidate tool environment secret-like key 차단 계약
- `boundary-profile.json` schema/validator
- inside-boundary read/write/env/network canary recorder
- evaluator-side host post-verifier
- control-plane TCP reachability reference
- mount-namespace `ENOENT`를 host fixture와 교차검증하는 규칙
- Docker profile raw SHA → probe artifact → report → attestation → analysis result 연결
- Docker pre-start inspect/profile consistency validator
- runner job schema/builder/strict validator
- pre-run runner job → post-run attestation linkage artifact
- 실제 Docker tool-process reference canary 성공 이력
- Codex CLI가 포함된 동일 boundary profile을 검사하는 reference workflow

### 아직 완료하지 않은 부분

- credential-owning model control-plane broker
- candidate tool process에서 credential file/env/argv가 보이지 않는 실제 model request
- 같은 profile에서 actual `codex exec` 또는 동등한 model request 실행
- broker가 arbitrary proxy가 아님을 검증하는 negative tests
- actual model run의 runner-job → attestation → result linkage artifact 보존

## 성능 주장 상태

현재 **성능 개선 주장은 0개**다.

다음 값은 아직 존재하지 않는다.

- generic 대비 decision correctness 개선량
- critical failure 비열등성
- execution integrity failure rate 비교
- justified revision / retention 개선량
- token / wall-time / tool-call 비용 차이
- held-out 결과

이 값이 나오기 전에는 `feynman-thinking`을 `behaviorally-validated`로 표시하지 않는다.

## 다음 실행 순서

```text
credential broker / model runner
  → 동일 boundary profile inspect + canary
  → public-development pilot
  → pilot 분산/비용으로 final 기준 고정
  → independent held-out 작성/동결
  → four-condition final comparison
  → failure + ablation analysis
  → merge/revise/drop 결정
```
