# feynman-thinking 작업 상태

기준: 2026-09-08, `feat/feynman-thinking-v0.5-draft` research preview.

이 문서는 구현 상태를 성능 주장과 분리해 기록한다. 체크가 되어 있다는 이유만으로 실제 모델 성능 또는 배포 안전성이 입증됐다고 해석하지 않는다.

| ID | 상태 | 현재 근거 | 남은 조건 |
|---|---|---|---|
| FYN-01 기존 감사 재검증 | **완료** | pinned v0.4.0 구조 결함 재현 코드/문서 | 실제 과거 모델 결과의 재채점은 별개 |
| FYN-02 역할·설계 확정 | **완료** | v0.5.0-draft SKILL + references | 행동 평가 후 규칙 축소 가능 |
| FYN-03 `thinking-skills` 통합 | **완료(draft)** | feature branch + draft PR + runtime allowlist | 병합은 성능 검증 뒤 |
| FYN-04 평가 격리 | **부분 완료 — mock E2E reference 통과** | boundary profile/canary/inspect + Codex frontend → network-none stdio exec-server → mock model 왕복 | 실제 외부 model-service 인증/응답 + 실제 평가 run에서 같은 계약 통과 필요 |
| FYN-05 실행 증거/합격 판정 연결 | **완료(구조)** | trace → evidence → review v2 → gate → result hash chain | 실제 semantic judge/human review 필요 |
| FYN-06 자동 검사/회귀 | **완료(구조)** | unit tests + structural/Docker/Codex/mock-remote-exec reference workflows | 실제 model-run regression은 FYN-08 이후 추가 |
| FYN-07 평가 데이터 보강 | **개발 세트 완료** | 18 public-development cases, 20 predefined hard failures, controls | 독립 작성 held-out final set 필요 |
| FYN-08 통제된 신·구 비교 | **미실행** | frozen plan/conditions/aggregator 준비 | authorized external model control plane, repeats, semantic review 필요 |
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
- Docker inspect/profile consistency validator
- runner job schema/builder/strict validator
- pre-run runner job → post-run attestation linkage artifact
- canonical Codex remote `environments.toml` generator/validator (`include_local=false`)
- 실제 Docker tool-process reference canary 성공 이력
- Codex CLI가 포함된 동일 boundary profile reference 성공
- **credential-free mock model end-to-end reference 성공**
  - control/tool Codex 버전 동일
  - control-plane mock Responses endpoint 접근 성공
  - shell command는 `--network none` Docker `codex exec-server --listen stdio`에서 실행
  - remote candidate marker 실제 생성
  - control-plane endpoint에 대한 remote tool 연결 차단
  - control plane dummy `OPENAI_API_KEY`가 remote tool env에 전파되지 않음
  - tool output이 두 번째 model request로 실제 반환됨
  - final agent message까지 왕복
  - Docker inspect/profile 일치
- `remote-exec-reference-result` schema + 원본 evidence 재검증/content digest 결속

### 아직 완료하지 않은 부분

- 승인된 실제 외부 model-service credential을 control-plane 전용으로 설정
- 실제 외부 model request/response가 동일 remote tool architecture에서 성공하는지 확인
- 실제 평가 run에서 boundary canary + runner attestation + runner-job link 보존
- 행동 평가에서 사용 가능한 모든 tool 유형이 local/protected path로 우회하지 않는지 필요한 범위의 추가 regression
- 실제 multi-turn model run에서 same-thread continuity 검증

중요: mock reference 성공은 **transport/tool-boundary architecture의 실행 가능성**을 입증하지만 실제 model-service 인증의 안전성이나 모델 품질을 입증하지 않는다.

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

## 사람 개입이 처음 필요한 지점

현재 남은 작업 중 첫 외부 권한 의존 단계는 **실제 model-service 인증 설정**이다.

사람/runner 운영자가 해야 하는 것은 secret 값을 채팅이나 repository에 쓰는 일이 아니라, 승인된 secret store 또는 인증 메커니즘에서 **control-plane 전용 credential**을 사용할 수 있게 하는 것이다. candidate tool env/file/argv에는 credential을 전달하지 않는다.

이 인증 설정 전까지의 runner/job/profile/mock E2E 검증은 자동화로 진행 가능하다.

## 다음 실행 순서

```text
[완료] mock model control-plane → stdio remote tool boundary E2E
  → 실제 model-service control-plane 인증 설정  ← 첫 사람/권한 개입 지점
  → 동일 boundary profile inspect + canary
  → 1~2개 public-development smoke run
  → runner-job / attestation / trace / result linkage 확인
  → four-condition public-development pilot
  → pilot 분산/비용으로 final 기준 고정
  → independent held-out 작성/동결
  → four-condition final comparison
  → failure + ablation analysis
  → merge/revise/drop 결정
```
