# LOG-015 — ChatGPT-subscription smoke executor implementation and stabilization

- **시각(KST)**: 2026-09-09 12:25 전후
- **저장소**: `Ronaldony/thinking-skills`
- **브랜치**: `feat/feynman-thinking-v0.5-draft`
- **PR**: #1 `feat: add Feynman thinking skill research preview`
- **PR 정책**: open / draft / not merged 유지
- **이번 phase 시작 feature head**: `826fffcee93bd0c964068a328fdf505d7dc22b61`
- **executor 코드/CI 검증 head**: `ace864f6e69f746426453a31df564abd41a755b9`
- **staging 최종 검증 commit**: `371d72343e1f6d9aa116b62eb15703dc3d52a93f`

## 1. 이 phase의 목적

API path를 폐기하고 ChatGPT-subscription Codex authentication 경계까지 구조를 준비한 뒤에도 사람이 실제 smoke를 실행하려면 여러 저수준 명령을 직접 조합해야 했다.

기존 human handoff는 대략 다음이었다.

```text
interactive ChatGPT login
  → auth gate
  → subscription structural preflight
  → 사람이 직접 codex exec flags 구성
  → trace 저장 위치 직접 선택
  → 이후 lineage pipeline
```

이 상태는 두 가지 위험이 있었다.

1. **실행 drift**: 사람마다 `codex exec` flags, sandbox, model, web search, prompt 전달 방식, output 위치가 달라질 수 있다.
2. **보안 drift**: ambient process env, API-key-like env, 기존 user config, project-local `.codex`, control session path가 우연히 candidate 실행에 섞일 수 있다.

따라서 이번 phase의 목표는 사람 개입을 **ChatGPT interactive login 자체**로 좁히고, 그 이후 한 frozen smoke job의 실행을 canonical executor로 자동화하는 것이었다.

이 executor는 behavioral evaluation runner가 아니다. 오직 `tools-10 × {baseline, feynman-v05} × repeat 1` integration smoke에서 plumbing을 검증하기 위한 것이다.

## 2. 공식 Codex contract를 확인한 이유

실행기를 만들기 전에 현재 Codex CLI contract가 다음 기능을 지원하는지 확인했다.

- non-interactive `codex exec`
- JSONL output via `--json`
- saved CLI authentication reuse
- explicit working directory (`--cd` / `-C`)
- explicit model (`--model` / `-m`)
- ephemeral run (`--ephemeral`)
- strict config validation (`--strict-config`)
- skip git repository requirement for controlled fixture (`--skip-git-repo-check`)
- sandbox / approval controls
- web search configuration

이 기능이 없었다면 subscription-based automated smoke는 API 없이 안정적으로 구현하기 어려웠다.

## 3. 새로 발견한 재현성 위험 — reasoning effort

executor 설계 중 기존 runner-job v3가 다음은 고정하지만:

```text
model
codex_cli
```

**model reasoning effort를 artifact에 고정하지 않는다는 문제**를 발견했다.

Codex configuration은 reasoning effort 설정을 지원하므로, behavioral comparison에서 이를 고정하지 않으면 다음이 섞일 수 있다.

```text
skill condition effect
+ model reasoning effort difference
+ product/model default drift
```

이것은 FYN-08의 인과 해석을 손상시키는 실제 confounder다.

### 이번 phase의 결정

현재 단계는 performance inference가 금지된 **integration smoke**이므로 runner-job schema를 즉시 다시 올리지 않았다.

대신 smoke spec 자체를 v2로 올리고 다음을 명시적으로 동결했다.

```json
"model_reasoning_effort_policy": "model-default"
```

이 값은 smoke result에도 기록한다.

의미:

- 이번 two-job smoke에서는 model default를 의도적으로 사용한다.
- 이는 plumbing validation에만 허용된다.
- **four-condition behavioral pilot 전에 explicit reasoning effort를 versioned runner/result contract에 결속하는 새 migration이 필수**다.
- `model-default` smoke 결과를 performance comparison에 사용하면 안 된다.

## 4. 구현된 executor

새 파일:

`tooling/feynman_subscription_smoke_exec.py`

### 허용 scope

executor는 다음 contract 외에는 fail closed 한다.

```text
purpose: integration-only-chatgpt-subscription-smoke
case: tools-10
conditions: baseline | feynman-v05
repeat: 1
followup: false
auth: chatgpt-subscription / codex-session
api_key_auth_allowed: false
analysis_use: not-for-skill-performance-inference
reasoning policy: model-default
```

frozen plan은 정확히 2개 job을 포함해야 한다.

### 실행 전 검증

executor는 실제 Codex model turn 전 다음을 검사한다.

1. raw smoke-spec SHA가 frozen plan과 동일
2. subscription structural preflight 성공
3. runner-job의 exact job scope
4. protected control `CODEX_HOME` 존재
5. control `config.toml`이 auth gate의 canonical config와 byte-for-byte 동일
6. remote environment path가 정확히 `<control_codex_home>/environments.toml`
7. ChatGPT subscription auth gate 성공
8. authenticated Codex CLI version == runner-job Codex CLI version
9. runner-job model ID가 nonempty이고 `mock*`이 아님
10. candidate workspace에 project-local `.codex`가 없음
11. evaluator dir와 control `CODEX_HOME`이 disjoint
12. output dir가 evaluator 아래의 새 directory
13. ambient API/auth env가 없음
14. `GITHUB_ACTIONS=true`가 아님

### 금지 ambient auth env

다음 중 하나라도 executor invocation process에 존재하면 실행을 거부한다.

```text
OPENAI_API_KEY
CODEX_API_KEY
CODEX_ACCESS_TOKEN
```

이 검사는 값의 내용을 읽기 위한 것이 아니라 **API/token-based execution path가 ambient environment로 되살아나는 것을 막기 위한 것**이다.

### GitHub Actions real-run 금지

실제 ChatGPT account-authenticated smoke는 GitHub-hosted Actions에서 실행하지 못하게 한다.

```text
GITHUB_ACTIONS=true → fail closed
```

이유:

- 개인 ChatGPT login session을 hosted CI로 복사하지 않는다.
- user-account auth state를 Actions secret/artifact로 바꾸는 우회를 금지한다.
- 실제 model turn은 trusted local/self-hosted control plane에서만 실행한다.

CI에서는 fake Codex executable과 mocked auth/preflight로 executor contract만 검증한다.

## 5. canonical Codex invocation

executor는 low-level invocation을 코드로 고정한다.

개념적으로:

```text
codex exec
  --json
  --ephemeral
  --strict-config
  --ignore-rules
  --skip-git-repo-check
  --ask-for-approval never
  --sandbox workspace-write
  --model <runner-job model>
  --cd <candidate_dir>
  -c web_search="disabled"
  -c hide_agent_reasoning=true
  -c show_raw_agent_reasoning=false
  -c check_for_update_on_startup=false
  -
```

candidate `task.txt`의 정확한 bytes를 stdin으로 전달한다.

중요:

- control process env는 scrubbed allowlist만 전달한다.
- raw user environment를 상속하지 않는다.
- remote environment의 `include_local=false`가 이미 structural preflight에서 검증된다.
- candidate shell/filesystem tool execution은 기존 Docker remote exec-server boundary를 사용한다.

## 6. executor output / privacy contract

새 schema:

`evals/feynman-thinking/subscription-smoke-exec-result.schema.json`

schema version: **1**

성공 verdict:

```text
subscription-codex-smoke-exec-completed
```

보존하는 evaluator-side output:

```text
codex-trace.jsonl
candidate-final.txt
subscription-exec-result.json
```

result는 다음을 기록한다.

- exact run/job
- requested model
- Codex CLI version
- `model_reasoning_effort = model-default`
- auth gate coarse verdict
- noninteractive/sandbox/web-search execution controls
- thread ID
- event count
- reported token usage if available
- frozen plan/spec/job/profile/environment/task/trace/final SHA-256
- privacy flags

### 저장하지 않는 것

- credential/session file contents
- auth token values
- raw `codex login status`
- raw process environment
- raw stderr
- stderr SHA
- control `CODEX_HOME` contents

Codex stderr는 process memory에서 성공/실패 처리에만 사용하고 artifact로 persist하지 않는다. 성공 result에는 `stderr_nonempty: boolean`만 남긴다.

## 7. 실패 promotion 규칙

다음은 result로 promote하지 않는다.

- Codex nonzero exit
- trace JSON parse failure
- `error` event
- `turn.failed` event
- thread ID가 정확히 하나가 아님
- completed agent message 없음

실패 trace는 debugging/evaluator evidence로 남을 수 있지만 `subscription-exec-result.json` 성공 artifact를 생성하지 않는다.

## 8. smoke spec v2

변경 파일:

`evals/feynman-thinking/subscription-smoke-spec.json`

변경:

```text
schema_version: 1 → 2
+ model_reasoning_effort_policy: model-default
```

`tooling/feynman_subscription_smoke_plan.py`도 spec v2와 reasoning policy를 검증하고 frozen plan에 동일 필드를 기록한다.

`tests/test_feynman_subscription_smoke_plan.py`는 reasoning-policy drift를 거부한다.

## 9. 테스트 설계

새 테스트:

`tests/test_feynman_subscription_smoke_exec.py`

fake Codex executable을 사용해 실제 subprocess 경계를 통과한다.

검사하는 주요 항목:

- successful JSONL execution
- prompt exact stdin bytes
- scrubbed environment
- forbidden API/token env
- GitHub Actions real-run refusal
- canonical control config
- exact remote environment path
- smoke-spec SHA binding
- reasoning policy drift refusal
- mock model refusal
- candidate project-local `.codex` refusal
- output containment/new-directory contract
- evaluator/control-home overlap refusal
- authenticated CLI mismatch refusal
- preflight failure refusal
- nonzero exit / failed trace non-promotion
- result schema privacy fields

### 로컬 테스트 중 발견한 사소한 test bug

초기 repo-style local test draft에서 schema file read expression에 괄호 위치 오류가 있었다.

잘못된 형태의 의미:

```text
ROOT / "filename".read_text(...)
```

테스트 코드 자체의 버그였고 executor 로직과 무관했다. 수정 후 로컬 simulated repo에서 executor 관련 **18 tests**가 통과했다.

이 실패는 기능 결함으로 숨기지 않고 기록한다.

## 10. staging branch를 사용한 이유

다중 파일 migration 중 feature PR branch가 반쪽 상태가 되는 것을 피하기 위해 임시 branch를 사용했다.

```text
tmp/feynman-subscription-smoke-executor
```

feature 기준 parent:

`826fffcee93bd0c964068a328fdf505d7dc22b61`

staging에서 executor/spec/schema/tests/workflow를 완성하고 CI를 통과시킨 뒤 최종 tree만 feature branch에 한 atomic commit으로 옮겼다.

## 11. staging CI 실패 #1 — 의도적 guard와 test environment 충돌

초기 staging subscription-readiness:

- workflow: `validate-feynman-subscription-readiness`
- run #23
- run id: `34306799130`
- staging head: `3713dd367acd1bf036a325c5e5955ccb7aa0183d` 직전 executor bundle
- result: **failure**
- unit subset: **81 tests**
- failures: 1 failure + 1 error

정확한 원인:

GitHub Actions 자체가:

```text
GITHUB_ACTIONS=true
```

를 설정한다.

executor의 real-run guard는 이를 의도적으로 거부하므로 fake-Codex success-path test 역시 model subprocess 전에 멈췄다.

그 결과:

- success-path test → expected fake execution 대신 guard error
- failure-trace test → trace 생성 전 guard가 막아 secondary failure

### 판단

**executor의 GitHub Actions 금지 guard를 제거하지 않았다.**

그렇게 하면 실제 account session을 hosted CI에 넣을 수 있는 경로가 다시 생기기 때문이다.

테스트 환경만 명시적으로 격리했다.

최종 staging fix commit:

`371d72343e1f6d9aa116b62eb15703dc3d52a93f`

테스트 `setUp`에서만:

```text
GITHUB_ACTIONS=""
```

로 만든 뒤, 별도 `test_github_actions_is_rejected`에서 다시 `true`를 설정해 실제 guard가 살아 있음을 확인한다.

## 12. staging 최종 검증

최종 staging head:

`371d72343e1f6d9aa116b62eb15703dc3d52a93f`

staging push workflows:

- `validate-feynman-subscription-readiness` run #24 / id `34306889326` — **success**
- `validate-feynman-unit-diagnostic` run #75 / id `34306889411` — **success**
- `validate-feynman` run #432 / id `34306889343` — **success**

따라서 staging에서 safe guard를 완화하지 않고 executor contract가 green임을 확인했다.

## 13. feature branch atomic promotion

검증된 staging tree:

`4d4fda929808b3710b96d047e338af178ce7b521`

이 tree를 feature parent `826fff...`에 직접 연결해 한 commit으로 생성했다.

Feature commit:

`ace864f6e69f746426453a31df564abd41a755b9`

Message:

`feat: add ChatGPT subscription smoke executor`

즉 staging의 여러 중간 commits와 실패 수정 history는 PR branch에 그대로 쌓지 않았고, 최종 검증된 상태만 하나의 atomic change로 PR에 반영했다.

## 14. feature PR 최종 CI

**코드/CI 검증 head:**

`ace864f6e69f746426453a31df564abd41a755b9`

### full unittest diagnostic

- workflow: `validate-feynman-unit-diagnostic`
- run #77
- run id: `34307023264`
- **261 tests**
- **1.111s**
- exit code `0`
- result `OK`
- artifact id `10087004587`
- artifact ZIP SHA-256:
  `31bb6ef2ddece544401d2e7b705e6d2bb88b7112f346bceb2d2eae0e2d6350c8`

이전 stabilized head의 249 tests에서 261 tests로 증가한 것은 executor/spec reasoning-policy 관련 새 regression coverage가 추가됐기 때문이다. test count 자체를 성능 또는 품질 효과로 해석하지 않는다.

### active workflow 7개 — all success

동일 head에서:

1. `validate-feynman-unit-diagnostic`
   - run #77
   - id `34307023264`
   - success
2. `validate-feynman-subscription-readiness`
   - run #26
   - id `34307023266`
   - success
3. `validate-feynman`
   - run #434
   - id `34307023206`
   - success
4. `validate-feynman-remote-patch-reference`
   - run #95
   - id `34307023214`
   - success
5. `validate-feynman-docker-reference`
   - run #120
   - id `34307023201`
   - success
6. `validate-feynman-codex-reference`
   - run #110
   - id `34307023198`
   - success
7. `validate-feynman-remote-exec-reference`
   - run #133
   - id `34307023203`
   - success

## 15. 현재 사람이 해야 하는 일

사람의 역할은 더 좁아졌다.

### 이전

```text
login
→ auth check
→ preflight
→ codex exec flags 수동 조합
→ trace/final output 직접 관리
```

### 현재

```text
1. fresh dedicated control CODEX_HOME 준비
2. intended ChatGPT subscription으로 interactive codex login
3. auth gate check
4. exact job artifacts 준비 후 feynman_subscription_smoke_exec.py 실행
```

실제 model execution flags, prompt stdin, scrubbed env, trace/final/result output는 executor가 고정한다.

사람은 token/session 값을 제공하지 않는다.

## 16. executor 사용 전에 여전히 필요한 준비

executor는 workspace/profile/job을 생성하는 orchestration 전체를 대신하지 않는다.

각 exact job에 대해 다음 artifacts는 여전히 준비돼 있어야 한다.

```text
frozen subscription smoke plan
condition candidate workspace
evaluator case
runner-job v3
boundary-profile
control CODEX_HOME/environments.toml
```

그 뒤 한 job 실행은 executor가 담당한다.

## 17. executor 성공이 아직 증명하지 않는 것

`subscription-codex-smoke-exec-completed`는 다음을 의미하지 않는다.

- same-profile post-run boundary canary가 성공했다
- runner-attestation v3가 완성됐다
- runner-job-link v3가 완성됐다
- semantic review/gate가 성공했다
- analysis-result v4가 완성됐다
- Feynman skill이 baseline보다 좋다

따라서 executor result는 **actual model/tool execution evidence의 한 단계**일 뿐이다.

## 18. 다음 실제 실행 순서

사람 로그인 후 두 job 각각:

```text
structural preflight
  → auth gate
  → subscription smoke executor
  → same-profile post-run boundary canary/report
  → runner-attestation v3
  → runner-job-link v3
  → evidence extraction
  → review bundle
  → semantic review v2
  → gate
  → analysis-result v4
```

두 job 모두 complete lineage가 확인될 때 integration smoke가 green이다.

## 19. behavioral pilot 전에 추가해야 할 blocker

four-condition FYN-08 pilot 전 반드시:

> **explicit model reasoning effort를 versioned execution contract에 결속해야 한다.**

권장 방향:

- runner-job schema 새 version
- attestation/link/result에도 동일 effort field binding
- condition 전체에서 동일 explicit effort
- aggregate environment consistency에서 effort mismatch → mixed-environment

이 작업 없이 four-condition 결과를 controlled behavioral comparison으로 해석하면 안 된다.

## 20. 현재 claim 상태

Feynman v0.5 행동 성능 개선 주장: **0개**.

이번 phase가 검증한 것은:

- ChatGPT subscription auth 이후 한 smoke job을 API key 없이 deterministic하게 launch할 수 있는 structural executor contract
- privacy/fail-closed behavior
- model-default reasoning policy를 integration-only limitation으로 명시적으로 기록하는 것
- CI에서 executor real-account execution을 금지하면서 fake execution path를 검증하는 것

실제 ChatGPT subscription-backed model turn은 아직 실행하지 않았다.

## 21. 다음 세션 재개 규칙

1. 이 `LOG-015`를 가장 먼저 읽는다.
2. `LOG-014`, `LOG-013`을 이어 읽어 subscription pivot 배경을 확인한다.
3. PR #1 head/draft/open 상태를 확인한다.
4. API key를 요청하거나 사용하지 않는다.
5. actual login이 아직이면 `docs/feynman-subscription-local-smoke.md`에서 시작한다.
6. 실제 smoke에서는 manual `codex exec` command를 구성하지 말고 canonical executor를 사용한다.
7. executor 성공 뒤 post-run canary/attestation/link/evidence chain을 생략하지 않는다.
8. two-job smoke 성공만으로 skill effect를 주장하지 않는다.
9. four-condition pilot 전 explicit reasoning-effort contract migration을 먼저 수행한다.
10. 후속 meaningful phase마다 새 상세 work log를 만든다.
