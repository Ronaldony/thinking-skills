# LOG-016 — post-executor GitHub checkpoint

- **날짜(KST)**: 2026-09-09
- **저장소**: `Ronaldony/thinking-skills`
- **브랜치**: `feat/feynman-thinking-v0.5-draft`
- **PR**: #1 `feat: add Feynman thinking skill research preview`
- **PR 정책**: open / draft / not merged 유지
- **executor 코드/CI 검증 head**: `ace864f6e69f746426453a31df564abd41a755b9`
- **LOG-015 commit**: `d171811944cfef47ce3ae2cd8428dc1058bed945`
- **canonical handoff update**: `b4a391e46ea3d7d0f2ae723d61b6630bdaa55243`
- **work-status update**: `c1cbfbf65c64b7fb81166402fecc89f3d41391d2`

## 1. 체크포인트 목적

`LOG-015`에서 구현/검증한 ChatGPT-subscription one-job smoke executor를 canonical human handoff, project work status, PR body까지 일치시킨 뒤 세션이 끊겨도 정확히 재개할 수 있도록 현재 상태를 고정한다.

이 체크포인트는 실제 ChatGPT subscription-backed model run을 실행한 기록이 아니다. 실제 account login은 여전히 사람 소유의 trusted local/self-hosted control plane에서만 수행한다.

## 2. 현재 canonical smoke launcher

새 executor:

`tooling/feynman_subscription_smoke_exec.py`

smoke spec:

`evals/feynman-thinking/subscription-smoke-spec.json` **schema v2**

execution result schema:

`evals/feynman-thinking/subscription-smoke-exec-result.schema.json` **v1**

frozen smoke:

```text
case: tools-10
conditions: baseline, feynman-v05
repeat: 1 each
auth: chatgpt-subscription / codex-session
api-key auth: prohibited
analysis use: not-for-skill-performance-inference
reasoning effort policy: model-default
```

`model-default`는 integration plumbing test에만 허용된다. behavioral pilot 전 explicit reasoning effort를 새 versioned execution contract에 bind해야 한다.

## 3. executor code CI baseline

Validated code head:

`ace864f6e69f746426453a31df564abd41a755b9`

full unittest:

- 261 tests
- 1.111s
- exit 0
- OK
- workflow `validate-feynman-unit-diagnostic` #77
- run id `34307023264`
- artifact id `10087004587`
- artifact ZIP SHA-256 `31bb6ef2ddece544401d2e7b705e6d2bb88b7112f346bceb2d2eae0e2d6350c8`

동일 head active workflow 7개 모두 success:

1. unit diagnostic #77 / `34307023264`
2. subscription readiness #26 / `34307023266`
3. validate-feynman #434 / `34307023206`
4. remote patch #95 / `34307023214`
5. Docker reference #120 / `34307023201`
6. Codex reference #110 / `34307023198`
7. remote exec #133 / `34307023203`

## 4. handoff 문서 변경 후 재검증

`docs/feynman-subscription-local-smoke.md`를 manual Codex command handoff에서 canonical executor handoff로 갱신한 commit:

`b4a391e46ea3d7d0f2ae723d61b6630bdaa55243`

이 문서 commit에서도 active workflow 7개가 전부 success했다.

- subscription-readiness #29 / `34307256044`
- unit-diagnostic #79 / `34307256111`
- validate-feynman #436 / `34307256056`
- Docker reference #122 / `34307256109`
- remote exec #135 / `34307256040`
- Codex reference #112 / `34307256046`
- remote patch #97 / `34307256087`

따라서 canonical handoff text가 repository regression contract를 깨뜨리지 않는다.

## 5. PR body 동기화

PR #1 body를 다음 최신 상태로 교체했다.

- API/API key execution prohibited
- ChatGPT subscription / Codex session canonical auth
- runner/attestation/link v3, result v4
- smoke spec v2
- one-job subscription smoke executor
- executor privacy/fail-closed rules
- 261-test / 7-workflow code baseline
- actual model run 미실행 명시
- behavioral pilot 전 explicit reasoning-effort contract migration blocker

PR은 계속 draft로 유지하고 merge하지 않았다.

## 6. 현재 사람이 해야 하는 일

더 이상 사람이 `codex exec` flags를 직접 조합할 필요가 없다.

남은 사람 인증 행위:

```text
trusted local/self-hosted machine
  → fresh dedicated CONTROL_CODEX_HOME prepare
  → CODEX_HOME=<path> codex login
  → intended ChatGPT account/subscription으로 interactive login
  → auth gate check
```

이후 exact job artifacts가 준비되면 한 job 실제 실행은 `feynman_subscription_smoke_exec.py`로 수행한다.

사람이 제공하면 안 되는 것:

- API key
- ChatGPT/Codex session/token raw value
- auth file contents
- control CODEX_HOME archive

## 7. executor 성공 뒤 남은 자동 pipeline

각 smoke job:

```text
subscription smoke executor
→ same-profile actual-run boundary canary/report
→ runner-attestation v3
→ runner-job-link v3
→ evidence extraction
→ review bundle
→ semantic review v2
→ grade gate
→ analysis-result v4
```

두 job 모두 complete lineage가 있어야 integration smoke가 완료된다.

## 8. 의도적 stop condition

현재 자동 구현은 **실제 ChatGPT account login 경계**까지 진행됐다.

이 경계는 기술 미완성이 아니라 계정 소유자의 interactive authorization boundary다. 저장소 코드나 ChatGPT 대화가 이를 대신 수행하거나 session credential을 복사해 우회하면 안 된다.

따라서 actual model smoke를 진행하기 전 필요한 외부 상태는 하나다.

> trusted local/self-hosted control Codex에서 intended ChatGPT subscription login 완료.

사용자는 secret을 보내지 말고 로그인 준비가 끝났다는 사실만 전달하면 된다.

## 9. 다음 세션 재개 순서

1. `LOG-016` 읽기.
2. `LOG-015` 읽기 — executor 설계/실패/CI 상세.
3. `LOG-014` → `LOG-013` 순서로 subscription pivot 배경 확인.
4. PR #1 head와 draft/open/not-merged 상태 확인.
5. API key를 요청/사용하지 않음.
6. actual login 미완료면 `docs/feynman-subscription-local-smoke.md`부터 시작.
7. actual smoke에서 manual Codex invocation을 만들지 않고 canonical executor 사용.
8. executor success만으로 smoke 완료 처리하지 않음.
9. two-job smoke 성공만으로 skill effect 주장하지 않음.
10. four-condition behavioral pilot 전에 explicit reasoning-effort contract migration 수행.
11. 후속 meaningful phase마다 `docs/feynman-work-log/`에 새 로그 작성.
