# feynman-thinking 작업 상태

기준: 2026-09-09, `feat/feynman-thinking-v0.5-draft` research preview.

이 문서는 구현 상태와 행동 성능 주장을 분리해 기록한다. 체크가 되어 있다는 이유만으로 실제 모델 성능, 인과적 스킬 효과, 배포 안전성이 입증됐다고 해석하지 않는다.

> **정책 변경:** OpenAI Platform API-key 기반 실행 경로는 프로젝트의 현재 정책에서 폐기됐다. `LOG-008`, `LOG-010`, `LOG-011`, `LOG-012`의 API/credential 관련 다음 행동은 역사 기록일 뿐이며 새 실행에는 적용하지 않는다. 정본 전환 기록은 `LOG-013-api-retirement-subscription-pivot.md`부터 시작한다.

| ID | 상태 | 현재 근거 | 남은 조건 |
|---|---|---|---|
| FYN-01 기존 감사 재검증 | **완료** | pinned v0.4.0 구조 결함 재현 코드/문서 | 실제 과거 모델 결과 재채점은 별개 |
| FYN-02 역할·설계 확정 | **완료** | v0.5.0-draft SKILL + references | 행동 평가 후 규칙 축소 가능 |
| FYN-03 `thinking-skills` 통합 | **완료(draft)** | feature branch + draft PR + runtime allowlist | 병합은 행동 검증 뒤 |
| FYN-04 평가 격리 | **부분 완료 — subscription auth boundary 직전까지 구조 검증** | boundary/canary/inspect + remote exec/patch + protected `control_codex_home` + ChatGPT subscription auth gate + subscription preflight | trusted local/self-hosted control plane에서 실제 ChatGPT 로그인과 two-job smoke 필요 |
| FYN-05 실행 증거/합격 판정 연결 | **완료(구조 v4)** | frozen plan → runner-job v3 → profile/probe → attestation v3 → runner-job-link v3 + trace → evidence → review v2 → gate → analysis-result v4 | 실제 model run의 semantic/human review 결과 필요 |
| FYN-06 자동 검사/회귀 | **완료(구조)** | 249-unit diagnostic + 7개 active workflow 모두 green | 실제 subscription-authenticated run regression은 FYN-08에서 추가 |
| FYN-07 평가 데이터 보강 | **개발 세트 완료** | 18 public-development cases, 20 predefined hard failures, controls | 독립 작성 held-out final set 필요 |
| FYN-08 통제된 신·구 비교 | **미실행** | frozen conditions + v4 result/aggregate + two-job subscription smoke spec/preflight/auth gate 준비 | 실제 subscription-authenticated smoke, 반복 pilot, semantic review 필요 |
| FYN-09 실패 분석/규칙 축소 | **대기** | ablation 원칙 사전등록 | FYN-08 결과 필요 |
| FYN-10 검토·버전 확정·배포 | **대기** | draft PR 유지 | FYN-08/09 및 held-out 결과 필요 |

## 현재 canonical 인증 계약

새 runner-job schema v3의 인증 객체는 다음으로 고정한다.

```json
{
  "mode": "chatgpt-subscription",
  "control_plane_auth_source": "codex-session",
  "api_key_auth_allowed": false,
  "candidate_auth_exposed": false,
  "candidate_tool_auth_env_keys": [],
  "candidate_readable_auth_paths": [],
  "auth_command_arguments": []
}
```

핵심 경계:

```text
trusted local/self-hosted control plane
  └─ protected control_codex_home
       └─ ChatGPT-authenticated Codex session
                    │
                    │ stdio remote environment
                    ▼
          candidate Docker tool boundary
          - candidate 전용 codex_home
          - closed-network case: network none
          - control auth env 없음
          - control auth path mount 없음
```

`control_codex_home`은 evaluator/source/real-home과 함께 보호 영역이며 candidate-owned `candidate_dir`, `ephemeral_home`, `codex_home`, `temp_dir`와 겹칠 수 없다. 평가 코드의 구조 preflight는 `control_codex_home` 내부 credential 파일을 열거나 hash/copy/serialize하지 않는다.

## API 경로 폐기 범위

새 canonical 실행에서는 다음을 허용하지 않는다.

- `OPENAI_API_KEY` 기반 runner authentication
- OpenAI Platform API billing을 평가 전제조건으로 두는 것
- runner-job / attestation / link / result에 credential env-key 이름을 기록하는 구조
- candidate tool env/file/argv에 control authentication material을 전달하는 것
- 과거 API-specific real-model control config / pre-auth workflow를 새 실행에 사용하는 것

과거 Git history와 LOG-008/010~012는 감사 가능성을 위해 삭제하지 않는다. 그러나 새 실행의 입력이나 절차로 재사용하지 않는다.

로컬 mock-model CI는 외부 OpenAI API를 호출하지 않는다. transport 회귀검사용 synthetic 값은 `MOCK_MODEL_TOKEN`이라는 mock 전용 이름만 사용한다. subscription-readiness CI는 두 remote mock workflow에 `OPENAI_API_KEY`가 다시 등장하면 실패하도록 고정했다.

## FYN-04 세부 상태

### 완료된 부분

- candidate/evaluator/source/real-HOME 경계 계약
- protected `control_codex_home` 추가 및 candidate-owned roots와 overlap 차단
- candidate tool environment secret-like key 차단
- `boundary-profile.json` schema/validator
- inside-boundary read/write/env/network canary recorder
- evaluator-side host post-verifier
- control-plane TCP reachability reference
- mount-namespace `ENOENT`를 host fixture와 교차검증하는 규칙
- Docker profile raw SHA → probe artifact → report → attestation 연결
- Docker inspect/profile consistency validator
- runner-job schema **v3** / builder / strict validator
- runner-attestation schema **v3**
- pre-run runner job → post-run attestation linkage artifact schema **v3**
- canonical Codex remote `environments.toml` generator/validator (`include_local=false`)
- 실제 Docker tool-process reference canary 성공
- Codex CLI 포함 동일 boundary profile reference 성공
- credential-free local mock `exec_command` E2E reference 성공
- bundled patch-capable metadata 기반 local mock `apply_patch → exec_command` E2E reference 성공
- `analysis-result.schema.json` **v4** + v4-only canonical aggregator
- `subscription-smoke-spec.json` 고정:
  - `tools-10`
  - `baseline`, `feynman-v05`
  - 각 1회
  - `chatgpt-subscription` / `codex-session`
  - API-key auth 금지
  - 성능 추론 금지
- `feynman_subscription_run_preflight.py`:
  - frozen plan/job/task/profile/remote environment/skill exposure 검증
  - control session contents를 읽지 않음
  - 성공 verdict `ready-for-local-chatgpt-session-check`
- `feynman_subscription_auth_gate.py`:
  - 새 dedicated control `CODEX_HOME` 준비
  - `forced_login_method="chatgpt"`
  - `codex login status`를 scrubbed environment에서 실행
  - raw status output과 account identifier를 artifact에 보존하지 않음
  - credential 파일을 gate가 직접 읽지 않음
  - 성공 verdict `chatgpt-subscription-authenticated`
- canonical human handoff: `docs/feynman-subscription-local-smoke.md`

### 아직 완료하지 않은 부분

- trusted local/self-hosted control plane에서 intended ChatGPT subscription으로 Codex interactive login
- auth gate의 실제 `chatgpt-subscription-authenticated` 결과
- 실제 subscription-backed model turn 성공
- `tools-10 × {baseline, feynman-v05}` two-job integration smoke
- 실제 run마다 same-profile boundary canary/report 생성
- runner-attestation v3 + runner-job-link v3 생성
- 실제 trace → evidence → semantic review → gate → analysis-result v4 생성
- 실제 multi-turn model run의 same-thread continuity 검증

중요: structural/mock reference 성공은 **runner와 boundary 구조의 실행 가능성**을 보여주지만, 실제 ChatGPT subscription session, 모델 entitlement, 제품-side rollout, rate/usage limit, 모델 품질을 입증하지 않는다.

## FYN-05 세부 상태 — analysis-result v4

canonical analysis chain:

```text
frozen plan
  → runner-job.json v3 (pre-run)
  → boundary profile/probe + subscription-authenticated model/tool execution
  → runner-attestation.json v3 (post-run)
  → runner-job-link.json v3

trace
  → evidence
  → review bundle
  → semantic review v2
  → grade gate

두 경로
  → analysis-result.json v4
  → canonical aggregate (v4 result only)
```

schema 버전을 올린 이유는 API-auth 결과와 subscription-auth 결과를 동일 schema로 보이게 만들지 않기 위해서다. 과거 v2/v3 result/aggregate는 Git history/legacy module로 감사할 수 있지만 새 primary aggregation에는 넣지 않는다.

canonical aggregator는 model/Codex/runner/runtime뿐 아니라 subscription authentication profile이 섞이면 `mixed-environment`로 차단한다.

## 최신 구조 회귀 상태

**코드/CI 검증 head:** `9162506fbb592e8513f8347f755badbe006ac40a`

full unittest diagnostic:

- **249 tests**
- **1.149s**
- exit code `0`
- `OK`
- workflow: `validate-feynman-unit-diagnostic` run #65, id `34305223014`
- artifact id `10086395096`
- artifact ZIP digest: `sha256:4812686e4e6526103cd46910b4b17efea6331ba9108c6d08c10d383b36d51634`

이전 310 tests보다 개수가 감소한 이유는 API-specific control/preauth/synthetic-auth 테스트와 실행 경로를 canonical tree에서 제거했기 때문이다. 테스트 수 감소 자체를 품질 개선으로 해석하지 않는다.

동일 head에서 active workflow 7개 모두 success:

1. `validate-feynman-docker-reference` — run #116, id `34305223003`
2. `validate-feynman-subscription-readiness` — run #12, id `34305223012`
3. `validate-feynman-unit-diagnostic` — run #65, id `34305223014`
4. `validate-feynman-remote-exec-reference` — run #126, id `34305223113`
5. `validate-feynman-remote-patch-reference` — run #88, id `34305223094`
6. `validate-feynman-codex-reference` — run #106, id `34305223107`
7. `validate-feynman` — run #422, id `34305223043`

`validate-feynman-synthetic-auth-reference`와 `validate-feynman-real-run-readiness`는 API-era 목적 때문에 active workflow 집합에서 제거됐다. 따라서 과거의 "8 workflows"와 현재의 "7 workflows"를 직접적인 품질 증감 지표로 비교하지 않는다.

## 성능 주장 상태

현재 **Feynman v0.5의 행동 성능 개선 주장은 0개**다.

아직 존재하지 않는 값:

- generic 대비 decision correctness 개선량
- critical failure 비열등성
- execution integrity failure rate 비교
- justified revision / retention 개선량
- token / wall-time / tool-call 비용 차이
- independent held-out 결과

두-job integration smoke가 성공하더라도 그 차이는 skill-effect estimate에 사용하지 않는다.

## 현재 사람 개입 경계

필수 사람 개입은 이제 API credential 제공이 아니다. **trusted local/self-hosted machine에서 dedicated control Codex를 ChatGPT subscription으로 interactive login하는 행위**다.

정본 순서:

```text
1. fresh control CODEX_HOME 준비
2. CODEX_HOME=<dedicated path> codex login
3. ChatGPT browser/device login 완료
4. feynman_subscription_auth_gate.py check
5. exact frozen job별 subscription preflight 재검증
6. tools-10 × {baseline, feynman-v05} integration smoke 실행
```

사람은 session/token 값을 이 채팅이나 GitHub에 전달할 필요가 없으며 전달해서도 안 된다. control `CODEX_HOME` 자체도 Git, Actions artifact, candidate mounts에 넣지 않는다.

## 다음 실행 순서

```text
[완료] runtime/evaluator isolation
  → [완료] Docker + Codex remote exec/patch references
  → [완료] API path retirement
  → [완료] runner-job v3 / attestation v3 / link v3 / result v4 migration
  → [완료] subscription smoke spec + structural preflight + auth gate
  → [완료] local mock token naming 분리 + API-name regression guard
  → trusted local control plane에서 ChatGPT subscription login  ← 현재 사람 개입 지점
  → tools-10 × {baseline, feynman-v05} 실제 subscription integration smoke
  → same-profile boundary canary/report + trace
  → attestation v3 / link v3 / evidence / review / gate / result-v4
  → four-condition public-development pilot
  → pilot 분산/비용으로 final 기준 고정
  → independent held-out 작성/동결
  → four-condition final comparison
  → failure + ablation analysis
  → merge/revise/drop 결정
```

PR은 계속 draft 상태를 유지한다.
