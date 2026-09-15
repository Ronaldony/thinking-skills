# LOG-018 — Windows dedicated CODEX_HOME missing before auth-gate verification

- **시각(KST)**: 2026-09-09
- **저장소**: `Ronaldony/thinking-skills`
- **브랜치**: `feat/feynman-thinking-v0.5-draft`
- **PR**: #1 draft 유지
- **관련 단계**: FYN-04 / ChatGPT-subscription auth gate

## 1. 관찰된 현상

Windows PowerShell에서 다음 canonical auth-gate check 계열 명령을 실행했을 때 전용 `control CODEX_HOME` 디렉터리가 존재하지 않는다는 오류가 발생했다.

```text
error: control CODEX_HOME must be an existing directory
```

사용자 로컬 식별자나 실제 계정/credential/session 값은 이 로그에 기록하지 않는다.

## 2. 원인 판단

이 실패는 ChatGPT authentication 자체의 실패 증거가 아니다.

현재 확정 가능한 것은 다음이다.

- auth gate는 아직 login status 검증 단계까지 도달하지 못했다.
- canonical 평가용 dedicated control `CODEX_HOME`이 지정 경로에 존재하지 않았다.
- 앞선 사용자의 `Codex 로그인 완료` 보고는 일반/default Codex home에서 수행됐을 가능성이 있지만, 이 로그에서는 실제 저장 위치를 추정 사실로 확정하지 않는다.
- canonical 평가 계약은 일반 사용자 Codex home을 그대로 재사용하거나 credential 파일을 복사하는 대신, 새 dedicated control home을 `prepare`로 생성한 후 그 home을 명시해 interactive ChatGPT login을 수행하도록 요구한다.

## 3. 정본 복구 절차 — Windows PowerShell

프로젝트 root에서 평가 전용 home을 새로 준비한다.

```powershell
$env:CONTROL_CODEX_HOME = Join-Path $HOME ".codex-feynman-eval"
python tooling/feynman_subscription_auth_gate.py prepare --control-codex-home "$env:CONTROL_CODEX_HOME"
```

그 전용 home으로 Codex interactive login을 수행한다.

```powershell
$env:CODEX_HOME = $env:CONTROL_CODEX_HOME
codex login
```

로그인 완료 후 auth gate를 실행한다.

```powershell
python tooling/feynman_subscription_auth_gate.py check --control-codex-home "$env:CONTROL_CODEX_HOME" --codex-bin codex --output "$env:TEMP\feynman-subscription-auth-gate.json"
```

기대 verdict:

```text
chatgpt-subscription-authenticated
```

## 4. 금지 사항

- 기본 Codex home의 credential/session 파일을 dedicated home으로 수동 복사하지 않는다.
- credential/token/session 내용을 GitHub, 채팅, artifact에 붙여넣지 않는다.
- API key 또는 `OPENAI_API_KEY` 경로를 대안으로 사용하지 않는다.
- `prepare`가 기존 경로를 거부하면 임의로 덮어쓰지 말고 원인을 확인한다.

## 5. 현재 상태

- **operator login report**: 있음.
- **canonical dedicated control home 존재 확인**: 실패.
- **auth gate `chatgpt-subscription-authenticated` 실제 검증**: 아직 없음.
- **actual subscription-backed model turn**: 아직 없음.
- **API 사용**: 없음 / 금지 유지.

다음 재개 조건은 dedicated control home 생성 → 해당 home으로 ChatGPT Codex login → auth gate success다.
