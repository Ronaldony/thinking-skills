# LOG-022 — Windows auth gate local revalidation and executor boundary audit

- **시각(KST)**: 2026-09-09 18:19 이후
- **저장소**: `Ronaldony/thinking-skills`
- **브랜치**: `feat/feynman-thinking-v0.5-draft`
- **목적**: 사용자 Windows PC에서 최신 auth-gate 수정의 실제 성공 여부를 확인하고, 인증 성공과 실제 smoke executor/Docker 호환성을 분리 진단한다.
- **정책**: OpenAI Platform API/API key를 사용하지 않음. ChatGPT subscription Codex session만 대상으로 함. 로그인 파일·토큰·전체 환경변수는 읽거나 출력하지 않음.

## 1. 시작 상태 / STARTED

- 적용되는 저장소 `AGENTS.md`를 재귀 조회했으나 존재하지 않았다. 전역 설정이나 기존 AGENTS 파일은 변경하지 않았다.
- 시작 branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `3c3f726f376c2b7e4bbade398fb18bc5744297d4`
- 시작 `git status --short`: clean
- 시작 `origin/feat/feynman-thinking-v0.5-draft`: 시작 HEAD와 동일
- 사용자 지정 인계 자료와 `LOG-019`, `LOG-020`, 그리고 후속으로 `LOG-021`을 읽었다.
- 기존 전용 `CODEX_HOME`은 존재 여부만 확인했다. `prepare` 재실행, 로그인 재실행, credential 복사/열람을 하지 않았다.

실행한 명령의 민감정보 제거 요약:

```powershell
Get-ChildItem -Force -Name
Get-ChildItem -Path . -Filter AGENTS.md -Recurse -File
git status --short --branch
git log -5 --oneline --decorate
python --version
Get-Command codex -All | Select-Object Name,CommandType,Source,Path
codex --version
python -c "import shutil; print(shutil.which('codex'))"
```

관찰:

- Python `3.12.10`.
- PowerShell이 확인한 Codex 경로는 npm `codex.ps1`/`codex.cmd`/shim과 별도 OpenAI `codex.exe`였다.
- Python `shutil.which('codex')`는 npm `codex.CMD`를 선택했다.
- 일반 `codex --version`: `codex-cli 0.153.4`, exit `0`.
- 전용 평가 홈: directory exists.
- 검사한 auth 관련 환경변수는 presence만 확인했으며 `OPENAI_API_KEY`, `CODEX_API_KEY`, `CODEX_ACCESS_TOKEN`은 모두 absent였다. 값은 읽거나 출력하지 않았다.

## 2. 최신 auth gate 직접 실행 / FAILED then FIXED

### 2.1 수정 전 현장 재현

실행한 명령:

```powershell
$controlHome = Join-Path $HOME '.codex-feynman-eval'
$report = Join-Path $env:TEMP ('feynman-auth-gate-' + [guid]::NewGuid().ToString('N') + '.json')
python tooling/feynman_subscription_auth_gate.py check `
  --control-codex-home "$controlHome" `
  --codex-bin codex `
  --output "$report"
```

관찰:

- exit `2`.
- auth method verdict 전에 Python `subprocess` reader thread가 `UnicodeDecodeError: 'cp949' codec can't decode ...`로 종료되었다.
- 뒤따른 gate 오류는 `Codex login status did not identify ChatGPT authentication`이었다. 이는 raw status가 비어/손상된 결과이지, 로그인 상태가 ChatGPT가 아니었다는 증거가 아니다.
- 같은 control home과 Codex를 raw-byte subprocess로 별도 진단했다. `codex`/`.cmd`/`.exe` 세 경로 모두 `--version` exit `0`, `codex-cli 0.153.4`, `login status` exit `0`이었다. status 원문은 출력·저장하지 않고 ChatGPT 표지 존재 여부만 메모리에서 확인했다.
- 따라서 재현된 원인은 Windows locale `cp949`와 Codex UTF-8 child output 사이의 gate decode 경계였다. launcher 또는 subscription auth 실패로 단정하지 않았다.

### 2.2 최소 수정

수정 파일:

- `tooling/feynman_subscription_auth_gate.py`
  - version/status subprocess에 `encoding="utf-8", errors="replace"`를 명시했다.
  - 기존 scrubbed environment, forced ChatGPT policy, raw status 미보존 계약은 유지했다.
- `tests/test_feynman_subscription_auth_gate.py`
  - subprocess 호출이 UTF-8 decode 계약을 사용하는 회귀 테스트를 추가했다.

수정 이유: Windows의 기본 cp949에 의존하지 않고 Codex CLI의 UTF-8 output을 coarse classification에만 사용하기 위해서다. `errors="replace"`는 원문을 artifact로 보존하지 않으며, gate 반환값에도 status text를 넣지 않는다.

### 2.3 수정 후 auth gate / DONE

동일한 전용 home을 보존해 새 임시 report filename으로 실행했다.

관찰:

- exit `0`.
- verdict: `chatgpt-subscription-authenticated`.
- Codex CLI: `codex-cli 0.153.4`.
- `raw_status_output_preserved=False`.
- `credential_files_read_by_gate=False`.
- child environment는 Windows launch allowlist만 포함했다: `HOME`, `USERPROFILE`, `CODEX_HOME`, `PATH`, `TEMP`, `TMP`, `TMPDIR`, 그리고 존재하는 `SystemRoot`, `ComSpec`, `PATHEXT`, `WINDIR`.
- report는 새 임시 파일로 생성됐고 기존 증거를 덮어쓰지 않았다. report 내용과 account identifier는 채팅/로그에 복사하지 않았다.

이 결과는 이 로컬 Windows PC의 실제 Codex subprocess와 기존 전용 session을 사용한 **auth gate 성공 증거**다. 모델 요청이나 smoke executor 성공 증거가 아니다.

## 3. 실제 executor의 모델 없는 감사 / DONE-PARTIAL

인계에서 지적된 executor gap을 확인하고 최소 호환성 수정을 적용했다.

수정 파일:

- `tooling/feynman_subscription_smoke_exec.py`
  - `_resolve_executable()`이 Windows `\\` 경로도 explicit path로 인식하도록 했다.
  - Windows에서는 POSIX executable-bit 검사를 요구하지 않도록 auth gate와 동일한 의미로 정렬했다.
  - `_safe_exec_env()`에 Windows 최소 launch allowlist와 case-insensitive source-env lookup을 추가했다.
  - executor child stdin/stderr에 `encoding="utf-8", errors="replace"`를 명시했다.
  - candidate Docker 환경에 전달되는 remote `env -i` 계약이나 control home mount 정책은 변경하지 않았다.
- `tests/test_feynman_subscription_smoke_exec.py`
  - Windows executor allowlist 회귀 테스트를 추가했다.

검증:

```powershell
python -m unittest `
  tests.test_feynman_subscription_auth_gate.SubscriptionAuthGateTests.test_check_decodes_codex_output_as_utf8 `
  tests.test_feynman_subscription_auth_gate.SubscriptionAuthGateTests.test_windows_safe_env_keeps_only_launch_requirements `
  tests.test_feynman_subscription_auth_gate.SubscriptionAuthGateTests.test_windows_safe_env_falls_back_to_existing_parent_for_temp `
  tests.test_feynman_subscription_smoke_exec.SubscriptionSmokeExecTests.test_windows_safe_exec_env_keeps_launch_requirements_only `
  tests.test_feynman_subscription_smoke_exec.SubscriptionSmokeExecSchemaTests.test_schema_tracks_privacy_and_reasoning_policy
python -m py_compile tooling/feynman_subscription_auth_gate.py tooling/feynman_subscription_smoke_exec.py
```

결과: 5 tests `OK`, compile exit `0`. 이 테스트들은 실제 model turn을 보내지 않았다.

## 4. Docker / WSL / POSIX boundary 판정 / BLOCKED

실행한 확인:

```powershell
Get-Command docker,wsl,codex -All
docker --version
wsl.exe --status
codex exec --help
```

관찰:

- `docker` command는 PATH에서 찾을 수 없었다. Docker version은 실행하지 못했다.
- `wsl.exe`는 존재하지만 `wsl.exe --status`는 exit `0xFFFFFFFF`와 `E_ACCESSDENIED`로 끝났다. WSL distro/backend 사용 가능 상태로 판정하지 않았다.
- Codex `exec --help`는 canonical executor가 요구하는 `--json`, `--ephemeral`, `--strict-config`, `--skip-git-repo-check`, `--sandbox`, `--cd` flag를 제공했다.
- remote generator를 placeholder Windows path로 dry-run했다. 현재 `expected_docker_args()`는 Windows host 문자열을 `-v`의 container destination과 `--workdir`에도 그대로 넣는다.
- boundary profile의 `_absolute_posix()`는 `C:\...`를 absolute POSIX path로 거부한다.

판정:

- auth gate 성공과 Docker tool-boundary 호환성은 별개다.
- native Windows path로 생성한 job을 현재 POSIX/Linux Docker reference에 그대로 연결할 수 있다는 증거는 없다. 오히려 generator/profile contract가 이를 차단하거나 잘못된 container path를 만들 수 있다.
- 이 PC에서는 Docker/WSL backend가 확인되지 않았으므로 actual `feynman_subscription_smoke_exec.py` 실행, candidate tool boundary, post-run canary, attestation/link/evidence chain을 시작하지 않았다.
- 평가 candidate에 개발 대화/인계 문서를 전달하지 않았다.

## 5. 전체 테스트 범위 / KNOWN PLATFORM LIMITATIONS

실행한 명령:

```powershell
python -m unittest discover -s tests
```

결과: `Ran 267 tests`; `FAILED (failures=3, errors=46, skipped=4)`.

주요 관찰된 실패 분류:

- Windows 기본 `cp949`로 UTF-8 fixture를 읽는 기존 테스트의 `UnicodeDecodeError`.
- POSIX `#!/bin/sh` fake Codex를 Windows subprocess로 실행한 `WinError 193`.
- symlink fixture 생성에 필요한 Windows privilege 부재(`WinError 1314`).
- Windows temporary paths가 Linux/POSIX-only boundary profile에 들어가 `absolute POSIX path` 검증에서 거부됨.
- 현재 process의 `.agents\\skills` ancestor가 fixture skill-root contamination으로 관찰됨.
- prompt digest 관련 3 failures는 이번 변경에 원인을 귀속하지 않았으며, 별도 Windows fixture/line-ending 조사 대상으로 남겼다.

이 전체 suite 결과는 auth gate targeted green과 모순되지 않는다. 다만 저장소 전체가 Windows native에서 green이라고 주장할 수 없다. 기존 handoff가 예고한 POSIX fixture 한계를 실제 로컬 결과로 확인했다.

## 6. 저장 상태 / PENDING

- `git diff --check`: exit `0`.
- 변경 의도 파일: auth gate 2개, smoke executor 2개, 이 로그 1개.
- 기존 사용자 변경: 시작 시 clean이었고 보존할 기존 dirty 변경 없음.
- 기존 전용 login home: 보존.
- API key/token: 사용·주입·출력하지 않음.
- local commit: 이 로그 작성 시점에는 아직 생성하지 않음.
- push: 아직 하지 않음.
- main merge / force push: 하지 않음.

## 7. 미완료 사항과 다음 한 행동

미완료:

1. Windows native executor/Docker end-to-end 호환성은 Docker 부재와 WSL access denied로 검증하지 못했다.
2. POSIX remote environment generator의 Windows host-to-container path mapping은 별도 설계/구현이 필요하다. Windows credential을 WSL로 복사하는 방식은 사용하지 않는다.
3. full unittest의 기존 Windows fixture failures는 별도 플랫폼 테스트 정리 없이는 green이 아니다.
4. 실제 smoke, model behavior, post-run boundary evidence, attestation/link/review/gate/result는 모두 pending이다.

**다음 한 행동**: 현재 4개 코드/테스트 변경과 이 로그를 검토한 뒤 feature branch에 non-force commit/push하고 remote SHA를 확인한다. 그 다음 실제 smoke는 Docker가 동작하는 승인된 Linux/WSL2 control plane과 동일 경로 계약이 준비된 경우에만, structural preflight → auth gate → canonical executor 순서로 시작한다. 재로그인은 현재 필요하지 않다.
