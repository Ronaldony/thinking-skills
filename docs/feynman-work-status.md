# feynman-thinking 작업 상태

최신 실행 checkpoint: 2026-09-12, `feat/feynman-thinking-v0.5-draft` research preview.

현재 재개 지점은 [LOG-041](feynman-work-log/LOG-041-remote-tool-telemetry-and-preflight-20260912.md)이다.
전용 홈 인증, native Docker 경계, ordinal 1 구조 검사 및 실제 모델 턴은 통과했다.
field-specific Windows→Linux RPC proxy, `/tmp` 초기화 수정, 그리고 documented
`initialize`→`initialized`→`fs/readFile`→`process/start` preflight도 통과했다.
그러나 repaired ordinal 1 `feynman-v05` trace에는 candidate tool event가 0개였다. fixture/test를
서술한 final answer는 trusted execution evidence가 아니므로 execution-required task
성공으로 승격할 수 없다. result schema v2가 이 상태를
`blocked-no-candidate-tool-call`로 명시한다. frozen evaluation과 분리된 fixed
filesystem tool-discovery probe는 현재 Codex 0.154.0에서 실제 실행됐지만,
`tool-use-not-observed`였다. trace에는 completed candidate tool item이 0개인데
고정 `PROBE_TOOL_USED` 텍스트만 있어 실행 증거가 아니다. response-vs-trace 불일치
verdict 보강은 구현·회귀 검증됐다. raw probe trace는 이제 임시 control 영역에서만
집계되고, host RPC proxy는 payload-free method/count/error telemetry를 기록한다.
새 telemetry를 사용한 실제 model probe는 추가 byte 전송 승인 경계에서 중단됐으며,
model-free native Docker/RPC preflight는 통과했다. baseline은 아직 실행하지 않는다.

이 문서는 구현 상태와 행동 성능 주장을 분리해 기록한다. 구조 검사나 integration smoke가 성공하더라도 실제 Feynman skill의 인과적 성능 향상으로 해석하지 않는다.

> **정책:** OpenAI Platform API/API-key 기반 실행은 폐기됐다. 현재 canonical real-run 경로는 **ChatGPT subscription으로 로그인된 Codex session**만 사용한다. `LOG-008`, `LOG-010`, `LOG-011`, `LOG-012`의 API-era 다음 행동은 역사 감사용이다. 전환 기록은 `LOG-013`~`LOG-015`를 따른다.

| ID | 상태 | 현재 근거 | 남은 조건 |
|---|---|---|---|
| FYN-01 기존 감사 재검증 | **완료** | pinned v0.4.0 구조 결함 재현 코드/문서 | 실제 과거 모델 결과 재채점은 별개 |
| FYN-02 역할·설계 확정 | **완료** | v0.5.0-draft runtime + references | 행동 평가 후 규칙 축소 가능 |
| FYN-03 `thinking-skills` 통합 | **완료(draft)** | feature branch + draft PR + runtime allowlist | 병합은 행동 검증 뒤 |
| FYN-04 평가 격리 | **부분 완료 — candidate read/spawn model-free 검증** | Docker/Codex remote boundary + protected `control_codex_home` + auth gate + RPC preflight | repaired ordinal-1 smoke와 two-job smoke 필요 |
| FYN-05 실행 증거/합격 판정 연결 | **완료(구조 v4)** | runner-job v3 → attestation v3 → link v3 + trace/evidence/review/gate → result v4 | 실제 model run lineage 필요 |
| FYN-06 자동 검사/회귀 | **완료(구조)** | 261-unit diagnostic + 7 active workflows green | 실제 subscription-backed smoke artifact는 FYN-08에서 추가 |
| FYN-07 평가 데이터 보강 | **개발 세트 완료** | 18 public-development cases, 20 hard failures | independent held-out final set 필요 |
| FYN-08 통제된 신·구 비교 | **미실행** | frozen 4 conditions + two-job smoke launcher 준비 | 실제 smoke 후, explicit reasoning-effort contract migration 후 pilot |
| FYN-09 실패 분석/규칙 축소 | **대기** | ablation 원칙 사전등록 | FYN-08 결과 필요 |
| FYN-10 검토·버전 확정·배포 | **대기** | draft PR 유지 | FYN-08/09 + held-out 결과 필요 |

## 현재 canonical 인증 계약

runner-job schema v3:

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

구조:

```text
trusted local/self-hosted control plane
  └─ protected control_codex_home
       └─ ChatGPT-authenticated Codex session
                    │
                    │ stdio remote environment
                    ▼
          candidate Docker exec-server
          - candidate 전용 codex_home
          - closed case: network none
          - control auth env/path/argv 없음
```

`control_codex_home`은 evaluator/source/real-home과 함께 보호 영역이며 candidate-owned roots와 겹칠 수 없다. 구조 preflight/auth gate/smoke executor는 credential 파일 내용을 직접 읽거나 serialize하지 않는다.

## API 경로 폐기 범위

새 canonical 실행에서 금지:

- `OPENAI_API_KEY` / API-key runner authentication
- API billing을 평가 전제조건으로 두는 것
- candidate env/file/argv에 control authentication material 전달
- API-era real-model control/preauth workflow 재사용
- hosted GitHub Actions에 개인 ChatGPT session을 복사해 real run 수행

local mock transport는 외부 OpenAI API가 아니며 synthetic 값 `MOCK_MODEL_TOKEN`만 사용한다. subscription-readiness CI는 mock workflows에 `OPENAI_API_KEY`가 다시 나타나면 실패한다.

## subscription smoke contract

`evals/feynman-thinking/subscription-smoke-spec.json`은 현재 **schema v2**다.

```text
case: tools-10
conditions: baseline, feynman-v05
repeat: 1 each
auth: chatgpt-subscription / codex-session
api_key_auth_allowed: false
analysis_use: not-for-skill-performance-inference
model_reasoning_effort_policy: model-default
```

### reasoning-effort 주의

executor 설계 중 기존 runner-job v3가 model/Codex CLI는 고정하지만 **explicit model reasoning effort를 bind하지 않는다는 confounder**를 발견했다.

이번 integration smoke는 성능 추론 금지이므로 `model-default`를 spec/result에 명시적으로 기록해 plumbing test로만 허용한다.

**FYN-08 four-condition behavioral pilot 전에는 반드시 explicit reasoning effort를 새 versioned runner/attestation/link/result contract에 결속해야 한다.** 이 migration 없이는 controlled behavioral comparison을 주장하지 않는다.

## 현재 smoke 실행 도구

### 1. structural preflight

`tooling/feynman_subscription_run_preflight.py`

성공 verdict:

```text
ready-for-local-chatgpt-session-check
```

검증: frozen plan/job/task/profile/remote environment/skill exposure. Control session contents는 읽지 않는다.

### 2. auth gate

`tooling/feynman_subscription_auth_gate.py`

- fresh dedicated `CODEX_HOME` 준비
- `forced_login_method="chatgpt"`
- scrubbed env에서 `codex login status`
- raw status/account identifier 미보존
- credential file 내용 미열람

성공 verdict:

```text
chatgpt-subscription-authenticated
```

### 3. canonical one-job executor

`tooling/feynman_subscription_smoke_exec.py`

성공 verdict:

```text
subscription-codex-smoke-exec-completed
```

executor는 내부적으로 structural preflight + auth gate를 다시 실행하고 다음을 고정/검증한다.

- exact smoke-spec SHA
- tools-10 / baseline|feynman-v05 / repeat1 / single-turn only
- exact runner model + authenticated Codex CLI version
- exact `control_codex_home/config.toml`
- exact `control_codex_home/environments.toml`
- candidate project-local `.codex` 금지
- mock model 금지
- ambient `OPENAI_API_KEY`, `CODEX_API_KEY`, `CODEX_ACCESS_TOKEN` 금지
- `GITHUB_ACTIONS=true` real execution 금지
- scrubbed child environment
- fixed noninteractive `codex exec --json` controls
- web search disabled
- evaluator-owned new output directory
- failed/error trace non-promotion

보존 output:

```text
codex-trace.jsonl
candidate-final.txt
subscription-exec-result.json
```

보존하지 않음:

```text
credential/session contents
raw auth status
raw inherited environment
raw stderr / stderr digest
control CODEX_HOME contents
```

result schema:

`evals/feynman-thinking/subscription-smoke-exec-result.schema.json` v2.  It
separates `subscription-codex-smoke-exec-completed` (the invocation completed)
from `candidate_tool_activity`.  For the execution-required `tools-10` case,
zero completed candidate tool items is
`blocked-no-candidate-tool-call`: it cannot advance to trace evidence,
semantic review, or a performance conclusion.

## executor 성공 뒤에도 필요한 lineage

executor success만으로 integration smoke 완료가 아니다. 각 job에서 이후 반드시:

```text
same-profile actual-run boundary canary/report
→ runner-attestation v3
→ runner-job-link v3
→ trace evidence
→ review bundle
→ semantic review v2
→ grade gate
→ analysis-result v4
```

두 conditions 모두 complete lineage가 있어야 smoke 전체가 green이다.

## 최신 코드/CI 검증 상태

**코드/CI 검증 head:** `ace864f6e69f746426453a31df564abd41a755b9`

full unittest diagnostic:

- **261 tests**
- **1.111s**
- exit `0`
- `OK`
- workflow `validate-feynman-unit-diagnostic` run #77 / id `34307023264`
- artifact id `10087004587`
- artifact ZIP SHA-256 `31bb6ef2ddece544401d2e7b705e6d2bb88b7112f346bceb2d2eae0e2d6350c8`

active workflow 7개 모두 success:

1. `validate-feynman-unit-diagnostic` — #77 / `34307023264`
2. `validate-feynman-subscription-readiness` — #26 / `34307023266`
3. `validate-feynman` — #434 / `34307023206`
4. `validate-feynman-remote-patch-reference` — #95 / `34307023214`
5. `validate-feynman-docker-reference` — #120 / `34307023201`
6. `validate-feynman-codex-reference` — #110 / `34307023198`
7. `validate-feynman-remote-exec-reference` — #133 / `34307023203`

이전 249 tests에서 261로 늘어난 것은 subscription smoke executor/spec reasoning-policy 회귀검사가 추가됐기 때문이다. test count 자체는 성능 지표가 아니다.

## executor staging에서 발견한 실패

feature branch에 반쪽 migration을 노출하지 않기 위해 `tmp/feynman-subscription-smoke-executor` staging branch에서 먼저 검증했다.

초기 subscription-readiness run #23 (`34306799130`)은 실패했다. 이유는 executor의 의도적인 `GITHUB_ACTIONS=true` real-run 차단이 fake success test에도 적용됐기 때문이다.

안전장치를 제거하지 않고 test environment에서만 `GITHUB_ACTIONS`를 비우고, 별도 rejection test에서 다시 `true`를 주도록 수정했다.

최종 staging commit `371d72343e1f6d9aa116b62eb15703dc3d52a93f`에서:

- subscription-readiness #24 / `34306889326` success
- unit-diagnostic #75 / `34306889411` success
- validate-feynman #432 / `34306889343` success

그 검증된 tree만 feature branch에 atomic commit `ace864f6...`로 반영했다.

상세: `docs/feynman-work-log/LOG-015-subscription-smoke-executor.md`.

## 성능 주장 상태

현재 **Feynman v0.5 행동 성능 개선 주장: 0개**.

아직 없는 값:

- generic 대비 decision correctness 개선량
- critical failure 비열등성
- execution integrity failure rate 비교
- justified revision/retention 개선량
- token/wall-time/tool-call 비용 차이
- independent held-out 결과

두-job smoke가 성공해도 skill-effect estimate로 쓰지 않는다.

## 현재 사람 개입 경계

필수 human action은 API credential 제공이 아니라 **trusted local/self-hosted machine의 interactive ChatGPT login**이다.

정본 순서:

```text
1. fresh dedicated control CODEX_HOME 준비
2. CODEX_HOME=<dedicated path> codex login
3. intended ChatGPT browser/device login 완료
4. auth gate check
5. exact job artifacts 준비
6. manual codex exec 대신 feynman_subscription_smoke_exec.py 실행
7. post-run canary/attestation/link/evidence chain 완료
```

사람은 session/token 값을 이 채팅이나 GitHub에 전달하지 않는다.

## 다음 실행 순서

```text
[완료] runtime/evaluator isolation
→ [완료] Docker + Codex remote exec/patch references
→ [완료] API path retirement
→ [완료] runner-job v3 / attestation v3 / link v3 / result v4
→ [완료] subscription auth gate + structural preflight
→ [완료] mock token 분리 + API-name CI guard
→ [완료] smoke spec v2 + one-job subscription smoke executor
→ [완료] dedicated ChatGPT subscription auth gate 실검증
→ [부분 완료] ordinal 1 모델 턴 완료, 실제 task는 실패
→ Windows file URI → Linux exec-server RPC 호환성 수정  ← 현재 개발 조건
→ 스킬 탐색/명령 실행을 모델 없이 검증한 뒤 two-job smoke 진행
→ post-run canary + attestation/link + review/result-v4
→ [필수 선행] explicit reasoning-effort execution contract migration
→ four-condition public-development pilot
→ pilot 분산/비용으로 final 기준 고정
→ independent held-out 작성/동결
→ four-condition final comparison
→ failure/ablation
→ merge/revise/drop 결정
```

PR은 계속 **draft / not merged** 상태를 유지한다.
