# LOG-014 — subscription pivot stabilization and post-pause consistency pass

- **시각(KST)**: 2026-09-09 12:01
- **저장소**: `Ronaldony/thinking-skills`
- **브랜치**: `feat/feynman-thinking-v0.5-draft`
- **PR**: #1 `feat: add Feynman thinking skill research preview`
- **PR 정책**: open / draft / not merged 유지
- **이번 안정화 작업 시작 시 branch head**: `16445fe71e34be3923eeb090c7f6f084e713daf3`
- **이번 단계의 코드/CI 검증 기준 head**: `9162506fbb592e8513f8347f755badbe006ac40a`
- **LOG-014 직전 docs head**: `ee01721b66b06c9048f4e5c79a7c2263bc6976bb`

## 1. 이 로그의 목적

사용자가 작업이 멈춘 것 같다고 지적한 뒤 실제 GitHub 상태를 재검증하고, API 폐기 후 남아 있던 semantic/documentation drift를 정리한 과정을 기록한다.

이번 단계는 Feynman skill의 행동 성능을 새로 검증한 단계가 아니다. 목적은 다음 네 가지였다.

1. API-era 이름/설명이 active execution path에 남아 있는지 제거한다.
2. mock transport와 실제 ChatGPT subscription authentication을 명확히 분리한다.
3. 코드와 PR/status 문서가 같은 canonical architecture를 말하게 만든다.
4. 다음 실제 실행에서 사람 개입이 interactive ChatGPT login 하나로 좁아지도록 auth gate/runbook을 정본화한다.

## 2. 중단 확인 시 발견한 불일치

`16445fe71e34be3923eeb090c7f6f084e713daf3`에서 core subscription pivot과 auth gate는 이미 구현되고 active workflow 7개가 green이었다.

하지만 다음이 남아 있었다.

### 2.1 local mock workflow의 API-like 이름

두 local mock workflow는 외부 OpenAI API를 호출하지 않았지만 Codex mock provider에 synthetic token을 주기 위해 여전히 다음 이름을 사용했다.

```text
OPENAI_API_KEY="MOCK_REFERENCE_ONLY_NOT_A_SECRET"
```

기능적으로 실제 API credential은 아니었지만 다음 위험이 있었다.

- 새 프로젝트 정책인 "API는 쓰지 않는다"와 artifact 의미가 충돌해 보임;
- 후속 검토자가 mock bearer와 실제 provider credential을 혼동할 수 있음;
- grep/정적검사 결과에서 API path가 아직 살아 있는 것처럼 보일 수 있음;
- 향후 실제 subscription run과 mock reference의 auth provenance를 잘못 해석할 위험.

따라서 mock token 이름 자체를 별도 namespace로 바꾸는 것이 필요했다.

### 2.2 mock runner-job의 control home binding

remote exec/patch workflow는 실제 mock control Codex를 `$CONTROL_CODEX_HOME`에서 실행했지만 runner-job 생성 시 `--control-codex-home`을 명시하지 않아 기본값인 `real_home/.codex`가 artifact에 기록될 수 있었다.

실행에 사용한 control home과 runner-job의 보호 경로 선언이 다르면 이후 lineage 해석이 부정확해진다. 그래서 실제 mock control home을 runner-job에 직접 bind하도록 수정했다.

### 2.3 상태문서와 PR body가 API-era 상태

`docs/feynman-work-status.md`와 PR #1 body는 여전히 다음 과거 구조를 설명했다.

- `OPENAI_API_KEY`
- `control-plane-only` + environment credential
- runner-job/attestation/link v2
- analysis-result v3
- API-specific real-run readiness
- 실제 model-service credential 설정이 다음 사람 개입이라고 설명

현재 canonical code는 이미 subscription-only v3/v4로 바뀌어 있었으므로 문서가 코드보다 뒤처진 상태였다.

## 3. API retirement pivot의 선행 migration 기록

이번 stabilization은 `LOG-013`의 migration 위에서 진행됐다. 관련 주요 commit과 실패/수정은 다음과 같다.

### 3.1 initial pivot

Commit:

`8b480c239e81838330eaecd5cd42b81b6e015067`

Message:

`refactor: retire API path for Feynman eval runner`

주요 변화:

- runner-job v2 → **v3**
- runner-attestation v2 → **v3**
- runner-job-link v2 → **v3**
- analysis-result v3 → **v4**
- canonical aggregator는 result v4 only
- auth contract → `chatgpt-subscription` / `codex-session`
- `api_key_auth_allowed=false`
- `control_codex_home` 보호 경계 추가
- API-specific real-model control config/preflight/spec/workflow/tests 제거
- subscription smoke/preflight path 추가

### 3.2 first migration CI failure

Full unit diagnostic:

- workflow: `validate-feynman-unit-diagnostic`
- run #56
- run id: `34256540052`
- conclusion: failure
- artifact id: `10068083051`
- artifact digest: `sha256:a2e0150c74859782f31bf1b90d811b694fefb5502cc80cb4aae9bb2030599887`

정확한 unit failure는 9개였다.

- 8개: `test_feynman_remote_exec_reference_result`가 runner-job v2 fixture를 계속 생성
- 1개: `control_codex_home`이 새 protected root가 됐지만 attestation test fixture의 forbidden-root set에 반영되지 않음

판단:

새 validator를 완화할 문제가 아니었다. test/reference fixture migration 누락이었다.

Fix commit:

`922504635bc2021b1ce1388c0c9c3ae3713faa46`

### 3.3 subscription-readiness false positive

초기 subscription readiness:

- workflow: `validate-feynman-subscription-readiness`
- run #2
- run id: `34256540154`
- conclusion: failure

첫 fixture 수정 후에도 run #4 (`34256984804`)가 실패했다.

원인:

subscription preflight가 retired API text를 **거부하기 위한 sentinel 문자열**로 `api.openai.com` 등을 코드 안에 갖고 있었고, CI grep은 그 방어 코드 자체를 active API path로 오인했다.

판단:

- canonical auth object의 exact equality 검증이 이미 더 강한 구조적 방어였음;
- text sentinel은 중복 방어이면서 CI false positive를 만들었음;
- 따라서 auth 검증을 약화하지 않고 redundant sentinel만 제거.

Fix commit:

`901ed4e326edcf66df57883e234c6cc37a585d62`

### 3.4 ChatGPT subscription auth gate

Commit:

`16445fe71e34be3923eeb090c7f6f084e713daf3`

Message:

`feat: add ChatGPT subscription auth gate`

추가:

- `tooling/feynman_subscription_auth_gate.py`
- `tests/test_feynman_subscription_auth_gate.py`
- `docs/feynman-subscription-local-smoke.md`

Auth gate semantics:

- fresh dedicated control `CODEX_HOME`만 준비;
- config에서 `forced_login_method="chatgpt"` 강제;
- file credential store 사용;
- login 자체는 사람의 interactive browser/device flow;
- `check`는 scrubbed process env에서 `codex login status` 실행;
- raw status output을 artifact에 저장하지 않음;
- credential file 내용을 gate가 직접 읽거나 hash하지 않음;
- 성공 verdict는 coarse `chatgpt-subscription-authenticated`.

`16445fe...`에서 active workflow 7개 모두 success였다.

## 4. 이번 stabilization에서 수행한 실제 변경

### 4.1 remote exec mock token rename + control home binding

Commit:

`208f3ea5dc3579330cca66de575b877912e20126`

Message:

`test: remove API naming from remote exec mock`

변경:

- mock provider `env_key`:
  - before: `OPENAI_API_KEY`
  - after: `MOCK_MODEL_TOKEN`
- synthetic value env:
  - before: `OPENAI_API_KEY=MOCK_REFERENCE_ONLY_NOT_A_SECRET`
  - after: `MOCK_MODEL_TOKEN=MOCK_REFERENCE_ONLY_NOT_A_SECRET`
- runner-job generation에:
  - `--control-codex-home "$CONTROL_CODEX_HOME"`
  추가.

이 token은 external provider auth가 아니라 local mock HTTP transport를 움직이기 위한 synthetic test input이다.

### 4.2 remote patch mock token rename + control home binding

Commit:

`97155bb8b0dda2f53ecd6b4002ad435229025679`

Message:

`test: remove API naming from remote patch mock`

remote exec와 동일 정책을 patch-then-exec reference에도 적용했다.

### 4.3 API-name regression guard

Commit:

`9162506fbb592e8513f8347f755badbe006ac40a`

Message:

`test: guard subscription path against API-key mock naming`

`validate-feynman-subscription-readiness`에 새 검사 추가:

- remote exec/patch mock workflow에 `OPENAI_API_KEY`가 존재하면 fail;
- 두 workflow 모두 `MOCK_MODEL_TOKEN`을 사용해야 함;
- 기존 canonical subscription files의 retired credential fields/API endpoint 검사 유지;
- runner schema/spec의 `api_key_auth_allowed=false` 검사 유지.

이로써 "API를 쓰지 않는다"는 정책을 단순 문서가 아니라 CI-enforced contract로 만들었다.

### 4.4 local smoke runbook clarification

Commit:

`5bfe97f3408e9682e40a5d8993ff7e3ae30b2b1a`

`docs/feynman-subscription-local-smoke.md`에 다음 의미를 명시했다.

- `MOCK_MODEL_TOKEN`은 CI local mock transport 전용 synthetic 값;
- ChatGPT authentication과 무관;
- 실제 subscription run auth로 사용해서는 안 됨.

### 4.5 work-status canonicalization

Commit:

`ee01721b66b06c9048f4e5c79a7c2263bc6976bb`

`docs/feynman-work-status.md`를 API-era 설명에서 subscription-only 구조로 전면 교체했다.

정본 상태:

- FYN-04: subscription auth boundary 직전까지 structural complete, 실제 login/smoke pending
- FYN-05: structural **v4**
- FYN-06: 249 units / 7 active workflows green
- FYN-08: 실제 model run 미실행
- 사람 개입: API credential가 아니라 trusted local machine의 interactive ChatGPT login

## 5. 코드/CI 검증 기준점

**검증 head:**

`9162506fbb592e8513f8347f755badbe006ac40a`

### 5.1 full unit diagnostic

- workflow: `validate-feynman-unit-diagnostic`
- run #65
- run id: `34305223014`
- **249 tests**
- **1.149s**
- exit code: `0`
- result: `OK`
- artifact id: `10086395096`
- artifact ZIP digest:
  `sha256:4812686e4e6526103cd46910b4b17efea6331ba9108c6d08c10d383b36d51634`

이전 API-era head의 310 tests보다 test count가 감소했다. 이유는 API-specific control/preauth/synthetic-auth 테스트와 active execution path를 제거했기 때문이다. 단순 test-count 감소를 품질 향상 또는 하락의 직접 지표로 사용하지 않는다.

### 5.2 active workflow — all green

동일 head에서 7개 모두 `completed / success`:

1. `validate-feynman-docker-reference`
   - run #116
   - id `34305223003`
2. `validate-feynman-subscription-readiness`
   - run #12
   - id `34305223012`
3. `validate-feynman-unit-diagnostic`
   - run #65
   - id `34305223014`
4. `validate-feynman-remote-exec-reference`
   - run #126
   - id `34305223113`
5. `validate-feynman-remote-patch-reference`
   - run #88
   - id `34305223094`
6. `validate-feynman-codex-reference`
   - run #106
   - id `34305223107`
7. `validate-feynman`
   - run #422
   - id `34305223043`

특히 remote exec/patch E2E가 `MOCK_MODEL_TOKEN`으로 바뀐 뒤에도 success였으므로 rename이 transport reference를 깨뜨리지 않았음을 확인했다.

## 6. 현재 canonical execution architecture

```text
trusted local/self-hosted machine

  dedicated CONTROL_CODEX_HOME
  - forced_login_method = chatgpt
  - ChatGPT subscription login session
  - candidate mounts에 절대 노출하지 않음
           |
           | model/control plane
           |
           +---- stdio ----> Docker candidate exec-server
                              - candidate-only CODEX_HOME
                              - closed cases: network none
                              - no control auth env
                              - no control auth file/path
                              - no auth argv
```

Canonical runner authentication:

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

## 7. 실제 사람 개입 지점

이제 사람에게 필요한 입력은 secret value가 아니다.

필수 human action:

```text
trusted local/self-hosted machine에서
fresh dedicated CONTROL_CODEX_HOME 생성
  → CODEX_HOME=<path> codex login
  → intended ChatGPT subscription으로 interactive login 완료
```

그 뒤에는:

```text
feynman_subscription_auth_gate.py check
```

로 auth method를 coarse verification한다.

사람이 하면 안 되는 것:

- API key 만들기/전달
- session/token 값을 ChatGPT 대화에 붙여넣기
- auth file을 GitHub repo에 commit
- auth file을 Actions artifact로 upload
- control CODEX_HOME을 candidate Docker에 mount
- auth path/value를 runner-job/result에 serialize

## 8. 다음 실제 실행 — integration smoke only

첫 실제 run scope는 변경하지 않는다.

```text
case: tools-10
conditions:
  - baseline
  - feynman-v05
repeats: 1 each
authentication: ChatGPT subscription / Codex session
analysis use: not-for-skill-performance-inference
```

각 job에서 필요한 순서:

1. exact frozen plan/job/workspace 준비
2. subscription structural preflight 재검증
3. auth gate 성공 확인
4. actual subscription-backed model turn
5. same-profile boundary canary/report
6. candidate tool trace 저장
7. runner-attestation v3
8. runner-job-link v3 recompute
9. evidence extraction
10. evaluator review bundle
11. semantic review v2
12. grade gate
13. analysis-result v4
14. 두 smoke job 모두 complete lineage 확인

두 답변의 차이는 skill effect로 해석하지 않는다.

## 9. 아직 검증되지 않은 것

- 실제 ChatGPT subscription-authenticated model turn
- account/plan에서 실제 선택 모델이 사용 가능한지
- 실제 two-job smoke
- four-condition public-development pilot
- independent semantic judge 또는 blinded human review 결과
- independent held-out set/final comparison
- FYN-09 ablation/failure analysis
- FYN-10 merge/revise/drop decision

따라서 행동 성능 개선 주장은 여전히 **0개**다.

## 10. 다음 세션 재개 규칙

새 세션은 다음 순서로 재개한다.

1. **이 `LOG-014`를 먼저 읽는다.**
2. `LOG-013-api-retirement-subscription-pivot.md`를 읽어 API 폐기 결정의 배경을 확인한다.
3. PR #1 head와 draft/open 상태를 확인한다.
4. API key를 요청하거나 생성하지 않는다.
5. `OPENAI_API_KEY`를 active mock/real execution path에 재도입하지 않는다.
6. 실제 login이 아직 안 됐다면 `docs/feynman-subscription-local-smoke.md`의 human handoff에서 시작한다.
7. actual two-job smoke 전에는 four-condition pilot으로 확장하지 않는다.
8. smoke 성공만으로 Feynman v0.5 성능 향상을 주장하지 않는다.
9. 후속 meaningful phase마다 `docs/feynman-work-log/`에 새 상세 로그를 추가한다.

## 11. 현재 stop condition

자동 구조 작업은 ChatGPT subscription login 경계까지 준비돼 있다.

현재 남은 외부 조건은:

> **trusted local/self-hosted control plane에서 사용자가 intended ChatGPT subscription으로 Codex interactive login을 완료하는 것.**

이 작업은 계정 소유자의 권한 행위이므로 저장소 코드가 대신 수행하거나 credential/session을 복사해서 우회해서는 안 된다.
