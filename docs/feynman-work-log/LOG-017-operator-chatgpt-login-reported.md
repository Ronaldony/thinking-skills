# LOG-017 — operator-reported ChatGPT Codex login

- **시각(KST)**: 2026-09-09 14:05
- **저장소**: `Ronaldony/thinking-skills`
- **브랜치**: `feat/feynman-thinking-v0.5-draft`
- **PR**: #1, open / draft / not merged 유지
- **직전 checkpoint head**: `a35724f811fd237b5f8d7c7858e5fcdd84f42bde`

## 1. 사용자 보고

사용자가 대화에서 다음 상태를 보고했다.

> `ChatGPT Codex 로그인 완료`

이 보고는 현재 프로젝트의 사람 인증 경계에서 요구했던 interactive ChatGPT login을 사용자가 수행했다는 의미로 취급한다.

## 2. 아직 검증된 사실로 올리지 않는 항목

이 대화 세션은 사용자의 trusted local/self-hosted machine의 filesystem, `CODEX_HOME`, Codex process에 직접 접근할 수 없다. 따라서 사용자 보고만으로 다음을 `verified`로 기록하지 않는다.

- dedicated `control_codex_home`이 실제로 사용됐는지;
- `forced_login_method="chatgpt"` config가 정확히 적용됐는지;
- `codex login status`가 ChatGPT authentication을 보고하는지;
- 로그인된 account/workspace에서 frozen smoke model을 사용할 수 있는지;
- 실제 subscription-backed model turn이 성공하는지.

이 항목은 `tooling/feynman_subscription_auth_gate.py check`와 실제 smoke executor evidence가 있어야 검증 완료로 승격한다.

## 3. 현재 상태 분류

```text
human interactive login:
  operator-reported-complete

auth gate verification:
  pending-local-execution

actual subscription model turn:
  not-yet-run

behavioral performance claim:
  none
```

## 4. 다음 로컬 검증

정본 auth gate:

```bash
python tooling/feynman_subscription_auth_gate.py check \
  --control-codex-home "$CONTROL_CODEX_HOME" \
  --codex-bin codex \
  --output /tmp/feynman-subscription-auth-gate.json
```

필수 성공 verdict:

```text
chatgpt-subscription-authenticated
```

이 gate는 credential file 내용을 직접 읽거나 raw `codex login status` output을 artifact에 저장하지 않는다.

## 5. 보안 경계

사용자는 다음 정보를 대화나 GitHub에 붙여넣지 않는다.

- auth/session token 값;
- credential file 내용;
- 전체 `control_codex_home` 내용;
- raw auth status에 account 식별자가 포함될 경우 그 원문.

후속 대화에는 coarse verdict만 전달하면 충분하다.

## 6. 다음 smoke 범위는 변경 없음

Auth gate가 실제로 green이 된 뒤에도 첫 실행은 성능 비교가 아니라 integration-only smoke다.

```text
case: tools-10
conditions:
  - baseline
  - feynman-v05
repeats: 1 each
authentication: ChatGPT subscription / Codex session
analysis use: not-for-skill-performance-inference
model reasoning effort policy: model-default
```

두 job 차이를 Feynman skill effect로 해석하지 않는다.

## 7. 재개 규칙

다음 세션/turn은 다음 순서로 읽는다.

1. `LOG-017-operator-chatgpt-login-reported.md`
2. `LOG-016-post-executor-checkpoint.md`
3. `LOG-015-subscription-smoke-executor.md`

사용자가 auth gate 성공을 보고하면 실제 session secret을 요구하지 말고, coarse verdict를 기준으로 subscription smoke 실행 단계로 진행한다.
