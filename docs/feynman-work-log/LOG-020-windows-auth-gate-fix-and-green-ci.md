# LOG-020 — Windows auth gate fix and green CI

- **시각(KST)**: 2026-09-09 17:10 전후
- **저장소**: `Ronaldony/thinking-skills`
- **브랜치**: `feat/feynman-thinking-v0.5-draft`
- **PR**: #1, open/draft/not merged 유지
- **선행 실패 기록**: `LOG-019-windows-auth-gate-version-command-failure.md`
- **수정 commit**: `b412e9fa807458d428745c5e63a6fccd38885927`

## 1. 문제 재정의

Windows PowerShell에서 dedicated control `CODEX_HOME`을 준비하고 login한 뒤 auth gate `check`를 실행했을 때:

```text
error: Codex version command failed
```

이 오류는 auth-method 검사 전에 `codex --version` subprocess가 nonzero로 끝난 결과였다.

## 2. 원인

기존 `_safe_env()`는 플랫폼 구분 없이 child environment를 다음 네 개로만 축소했다.

```text
HOME
CODEX_HOME
PATH
TMPDIR
```

Windows에서는 다음 문제가 있었다.

- `TMPDIR`이 보통 없으므로 `/tmp`라는 Unix path를 사용;
- `SystemRoot`, `ComSpec`, `PATHEXT`, `WINDIR` 제거;
- `TEMP`, `TMP` 제거;
- npm `codex.cmd`/Node launch가 필요로 할 수 있는 Windows process launch context 제거.

기존 unit tests는 POSIX shell fake만 사용해 이 결함을 발견하지 못했다.

## 3. 수정 내용

`tooling/feynman_subscription_auth_gate.py`:

- `_safe_env()`에 explicit platform branch 추가;
- Windows에서만 최소 launch allowlist 사용:
  - `HOME`
  - `USERPROFILE`
  - `CODEX_HOME`
  - `PATH`
  - `TEMP`
  - `TMP`
  - `TMPDIR`
  - 존재할 경우 `SystemRoot`, `ComSpec`, `PATHEXT`, `WINDIR`
- Windows `TEMP` 우선, 없으면 `TMP`, 둘 다 없으면 existing control-home parent로 fail-safe fallback;
- parent process environment 전체 상속은 계속 금지;
- `OPENAI_API_KEY`, `CODEX_ACCESS_TOKEN`, `APPDATA` 등 불필요/민감한 환경은 복사하지 않음;
- path detection이 `/`뿐 아니라 Windows `\\`도 인식하도록 수정;
- Windows에서는 explicit executable path에 POSIX executable-bit 요구를 적용하지 않음;
- version subprocess 실패 시 raw stderr를 저장하지 않고 exit code만 오류에 포함;
- 성공 auth result에 실제 child environment key allowlist만 기록.

## 4. 테스트 보강

`tests/test_feynman_subscription_auth_gate.py`에 추가:

- POSIX safe-env가 기존 최소 4-key contract를 유지하는지;
- Windows safe-env가 launch 필수값만 보존하는지;
- environment key lookup의 Windows case-insensitive 상황(`Path`) 처리;
- Windows temp fallback;
- API/token/APPDATA가 child env에 복사되지 않는지;
- version failure가 exit code만 노출하고 synthetic raw text를 보존하지 않는지.

## 5. staging 전략

중간 변경을 PR feature branch에 노출하지 않기 위해:

```text
tmp/feynman-windows-auth-gate-fix
```

에서 수정/검증했다.

Staging head:

`760c37c75f19cfee77072214c258b3d3609a250b`

Staging push CI:

- `validate-feynman-unit-diagnostic` — success
- `validate-feynman-subscription-readiness` — success
- `validate-feynman` — success

검증된 staging tree를 feature branch parent `4cc65985...` 위에 single commit으로 재작성했다.

Feature commit:

`b412e9fa807458d428745c5e63a6fccd38885927`

Message:

`fix: support Windows Codex auth gate launch`

## 6. PR-triggered 최종 CI

`b412e9fa807458d428745c5e63a6fccd38885927`에서 active workflow 7개 모두 `completed / success`:

1. `validate-feynman-subscription-readiness` — run #38 / `34327616872`
2. `validate-feynman` — run #445 / `34327616881`
3. `validate-feynman-docker-reference` — run #128 / `34327616926`
4. `validate-feynman-remote-exec-reference` — run #141 / `34327616941`
5. `validate-feynman-codex-reference` — run #118 / `34327616828`
6. `validate-feynman-remote-patch-reference` — run #103 / `34327616875`
7. `validate-feynman-unit-diagnostic` — run #88 / `34327616793`

## 7. 아직 주장할 수 없는 것

이 CI는 Windows 실기기에서 실제 Codex subprocess가 성공했다는 증거가 아니다. Windows branch behavior는 deterministic unit test로 검증했고 기존 Linux references가 회귀하지 않았음을 확인한 것이다.

따라서 다음 실제 증거는 사용자의 Windows machine에서 최신 feature commit을 fetch/pull한 뒤 동일 auth gate command를 다시 실행한 결과다.

성공 목표:

```text
"verdict": "chatgpt-subscription-authenticated"
```

그 전까지 actual subscription auth gate success로 상태를 올리지 않는다.
