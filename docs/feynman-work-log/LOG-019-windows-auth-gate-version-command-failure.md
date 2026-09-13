# LOG-019 — Windows auth gate `Codex version command failed`

- **시각(KST)**: 2026-09-09 16:48 이후
- **저장소**: `Ronaldony/thinking-skills`
- **브랜치**: `feat/feynman-thinking-v0.5-draft`
- **PR**: #1, open/draft/not merged 유지
- **사용자 환경**: Windows PowerShell

## 1. 관찰된 실패

사용자가 dedicated control `CODEX_HOME`을 만든 뒤 다음 canonical auth gate를 실행했다.

```powershell
python tooling/feynman_subscription_auth_gate.py check `
  --control-codex-home "$env:CONTROL_CODEX_HOME" `
  --codex-bin codex `
  --output "$env:TEMP\feynman-subscription-auth-gate.json"
```

결과:

```text
error: Codex version command failed
```

이 결과는 ChatGPT auth method 실패를 의미하지 않는다. 현재 gate는 login-status 검사 전에 먼저 `codex --version`을 실행하고, 그 subprocess가 nonzero를 반환했을 때 이 오류를 낸다.

## 2. 코드 감사 결과

`tooling/feynman_subscription_auth_gate.py::_safe_env()`는 현재 모든 플랫폼에서 child environment를 다음 네 값으로만 축소한다.

```text
HOME
CODEX_HOME
PATH
TMPDIR
```

문제점:

1. Windows PowerShell 세션에는 일반적으로 `TMPDIR`이 없으므로 fallback `/tmp`가 들어간다.
2. Windows command/batch 실행에 필요한 `SystemRoot`, `ComSpec`, `PATHEXT`를 제거한다.
3. Windows temp conventions인 `TEMP`, `TMP`도 제거한다.
4. npm 설치의 Codex CLI가 `codex.cmd` shim이면 위 환경 축소가 `cmd.exe`/Node shim 실행을 깨뜨릴 수 있다.
5. 기존 auth-gate unit tests는 POSIX `/bin/sh` fake executable만 사용하므로 Windows launch contract를 전혀 검증하지 않는다.

따라서 현재 가장 합리적인 원인은 **Windows unsupported가 아니라 auth gate의 cross-platform subprocess environment bug**다.

## 3. 외부 사실 확인

2026-09-09 기준 OpenAI Help Center는 Codex를 Windows에서 지원하며, Windows Codex CLI에서 `codex doctor` 진단도 제공한다고 설명한다. 따라서 이 실패를 Windows 미지원으로 해석하지 않는다.

## 4. 수정 원칙

- API-key execution 금지 정책은 유지한다.
- credential/session file 내용은 계속 읽지 않는다.
- raw login-status/account identifier는 계속 artifact에 저장하지 않는다.
- 전체 parent environment를 상속하지 않는다.
- Windows에서 process launch에 필요한 최소 시스템 변수만 allowlist한다.
- Windows temp path는 `TEMP`/`TMP` 기반 실제 Windows path를 사용한다.
- `.cmd`/`.bat` executable은 Windows command interpreter를 통한 명시적 launch path를 검증 가능하게 만든다.
- POSIX behavior는 기존 의미를 유지한다.

## 5. 현재 상태

- 실제 auth gate 성공: **아직 아님**
- 실제 subscription-backed model turn: **아직 아님**
- 사용자 로그인 보고: 있음
- 현재 blocker: Windows에서 auth gate가 Codex version subprocess를 정상 실행하도록 코드 수정 필요

이 로그 이후 수정/CI 결과는 후속 로그 또는 이 phase의 checkpoint에 연결한다.
