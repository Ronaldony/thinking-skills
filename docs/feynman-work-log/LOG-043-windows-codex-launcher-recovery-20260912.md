# LOG-043 — Windows Codex launcher recovery before guarded probe

- 시각(KST): 2026-09-12
- 시작 HEAD: `6793848`
- branch: `feat/feynman-thinking-v0.5-draft`
- shell/OS: Windows PowerShell / Windows
- 목적: read-scope-guarded fixed probe가 model turn 전에 실패한 Windows launcher
  문제를 진단·수정한다.

## 실제 시도와 분리된 실패 단계

1. 첫 두 실행 시도는 `eval-plan.json`이라는 존재하지 않는 파일명을 사용했다.
   실제 frozen plan은 `frozen-subscription-smoke-plan.json`이다. 두 시도는
   plan validation에서 exit 2로 끝났고 auth/model/Docker를 시작하지 않았다.
2. 확인된 frozen plan으로 실행한 다음 시도는 `WinError 193`으로 종료됐다.
   probe output/result/control temp 생성 상태를 확인했으며 model result는 없었다.
   이 오류는 candidate/model failure가 아니라 Python `subprocess`에 Windows
   `codex.ps1`을 executable로 전달한 launcher 형식 오류다.

`Get-Command codex -All`의 안전한 launcher inventory에서는 npm
`codex.ps1`, 같은 directory의 `codex.cmd`, npm `codex`, desktop `codex.exe`가
확인됐다. `codex.cmd --version`은 exit 0, `codex-cli 0.154.0`이었다. 로그인
파일·token·raw auth status·전체 환경변수는 읽거나 기록하지 않았다.

## 수정

`tooling/feynman_subscription_smoke_exec.py::_resolve_executable()`은 Windows에서
명시 `.ps1` launcher가 입력되면 동일 경로의 regular `.cmd` companion만
선택한다. companion이 없거나 symlink이면 고정 `ValueError`로 멈춘다. 따라서
PowerShell script를 Win32 executable처럼 시작하지 않는다.

이 수정 뒤 exact frozen plan probe는 output directory 생성 전 다시 `WinError 193`으로
끝났다. probe의 순서상 이는 auth gate의 version/status subprocess임을 확인했다.
`tooling/feynman_subscription_auth_gate.py::_resolve_executable()`에도 같은
`.ps1 → .cmd` policy를 적용했다. canonical executor와 auth gate의 launcher
정책이 다시 일치한다.

## 검증

```powershell
python -m unittest tests.test_feynman_subscription_auth_gate tests.test_feynman_subscription_smoke_exec tests.test_feynman_subscription_tool_use_probe
python -m unittest discover -s tests -p 'test_*.py'
codex.cmd --version
python tooling/feynman_subscription_auth_gate.py check --control-codex-home <dedicated control home> --codex-bin <npm codex.ps1>
git diff --check
```

- prior targeted resolver set: 27 tests, exit 0, OK
- targeted after auth-gate resolver: 32 tests, 1 skipped, exit 0, OK
- full after auth-gate resolver: 305 tests, 10 skipped, exit 0, OK
- actual npm `codex.cmd --version`: exit 0, `codex-cli 0.154.0`
- actual dedicated-home auth gate: `chatgpt-subscription-authenticated`,
  `codex-cli 0.154.0`; raw status/account/token은 보존하지 않음
- model request: 이 log 작성 시점까지 0회

## 다음 실행

새 evaluator-owned output directory에서 exact
`frozen-subscription-smoke-plan.json`과 기존 `codex.ps1` argument를 사용한다.
auth gate와 executor resolver가 모두 `codex.cmd`를 선택하므로 command surface는
고정되고, read-scope policy (`candidate.py`, offset 0, len 1, fs/readFile only)는
유지된다. 이 한 실행이 실패하면 자동 반복하지 않는다.

## 저장 상태

- 이 log 작성 시점: launcher fix/log commit 및 push pending
- baseline/Feynman evaluation은 시작하지 않음
