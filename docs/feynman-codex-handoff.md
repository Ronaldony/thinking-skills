# Feynman 작업 인계 — 로컬 Codex용

> 최우선: [LOG-067](feynman-work-log/LOG-067-raw-posix-namespace-mapping-fix-20260913.md).
> 승인된 추가 진단은 `-32603`, 모델 생성 0회다. 거부 이유 container 2 / host 4 /
> invalid-host 1은 예외 분기별 집계다. raw POSIX도 host 분기로 떨어지는 로컬
> 재현이 있어 실제 namespace 확정 증거가 아니다. method와 reason도 개별
> 요청으로 연결되지 않는다. 새 -03 산출물의 schema 검증과 정리는 완료됐다.
> 다음은 config 경로 생성 계약의 오프라인 분석이며 단순 재실행·mount 확대는
> 하지 않는다. raw POSIX 경로의 host fallback 재해석 결함을 고쳤고 전체
> 373 tests/11 skipped가 통과했다. 수정 후 startup 재검증은 별도 승인 없이는
> 실행하지 않는다. 아래 과거 안내보다 이 문단과 LOG-067을 우선한다.

> 최신: [LOG-065](feynman-work-log/LOG-065-namespace-rejection-reason-split-20260913.md).
> rejection reason telemetry와 ephemeral `thread/start` 진단기를 구현했다. 첫
> model-free run은 `-32603`, thread/turn/model 0, mapping rejection 0이었다.
> environment-native cwd `/run/candidate` 보정 후 승인된 model-free startup 1회를
> 실행했지만 `-32603`으로 막혔다. request rejection은
> `environmentConfig/read:1` (`invalid-host-path`), `fs/getMetadata:6`
> (`outside-declared-mount`)이다. thread/turn/model generation은 0회, child exit
> 0, response mapping rejection 0이다. generic metadata reason을
> `host-path-outside-declared-mount`와 `container-path-outside-declared-mount`로
> 세분화했고 전체 372 tests/11 skipped가 통과했다. 추가 외부 실행은 새 승인 없이는
> 하지 말고, 다음에는 이 namespace별 분포만 확인하라.
> 아래 과거 표기는 역사 기록이며 이 안내가 우선한다.

> 최신: [LOG-062](feynman-work-log/LOG-062-luna-config-metadata-rejections-20260913.md).
> 승인된 Luna 1회는 gate 통과 후 exit 1, trace 0바이트다. request 거부는
> config 1건/metadata 8건이고 fs/walk는 0건이다. 모델 서비스 요청 자체의
> 부재까지 증명하지는 않는다. 전체 SHA 조회에서 확인한 Linux CI fixture
> 실패도 보정했다. 다음은 model-free config/metadata 원인 분류다.
> 아래의 '최신' 표현은 과거 checkpoint이며 이 안내가 우선한다.

작성일: 2026-09-09 (Asia/Seoul). 이 문서는 개발 담당 Codex의 인계 자료다. 평가 대상 candidate에게 전달하지 않는다.

> 최신 상태(2026-09-13)는 [LOG-061](feynman-work-log/LOG-061-request-mapping-method-diagnostics-20260913.md)을 우선한다.
> model-free discovery diagnostic에서 ordinary `fs/walk` candidate path는
> Windows→Linux mapping 후 child까지 전달됐고 server의 synthetic `options`
> 누락 오류를 반환했다. guarded mode는 bounded allowlist에 따라 `fs/walk`를
> 거부했다. method별 payload-free rejection counter를 추가했고 전체
> `364 tests OK, 11 skipped`다. 새 model-turn/retry/fallback은 실행하지 않는다.
>
> 직전 상태는 [LOG-060](feynman-work-log/LOG-060-luna-model-turn-request-mapping-blocker-20260913.md)다.
> LOG-059 control-plane gate는 통과했지만 승인된 새 Luna model-turn 1회는 모델 요청
> 전에 startup filesystem/config request mapping 9건이 거부되어 exit 1/0-byte trace로
> 끝났다. Docker child exit 0, response mapping rejection 0이므로 남은 문제는
> request-side native Windows path allowlist다. 자동 retry/fallback하지 말고 먼저
> per-method rejection을 model-free로 진단하라.
>
> 직전 상태는 [LOG-059](feynman-work-log/LOG-059-control-plane-environment-info-path-fix-20260913.md)이다.
> LOG-058의 Luna exit 1/0-byte trace 뒤 model-free control-plane `environment/info`
> 진단으로 Linux remote cwd를 Windows host mount로 역매핑하던 결함을 보정했다.
> exact full-runner/skill override handoff는 remote connect 및 response mapping
> rejection 0으로 통과했고 model/thread/turn/tool 호출은 0회였다. executor는 이
> gate를 auth/model 앞에 fail-closed로 둔다. 실제 model request는 실행하지 않았고,
> 새 Luna model-turn은 별도 명시 승인 없이는 시작하지 않는다.
>
> 직전 상태는 [LOG-058](feynman-work-log/LOG-058-luna-model-turn-failed-20260913.md)이다.
> 승인된 Luna model-turn은 preflight/auth 후 `codex exec` exit 1로 종료됐고
> trace는 0바이트였다. 자동 retry는 하지 않았으며 model/tool-use 증거는 없다.
> 정확한 상태와 다음 결정 지점은 LOG-058이다.
>
> 이전 checkpoint는 [LOG-056](feynman-work-log/LOG-056-subscription-executor-wiring-preflight-20260913.md)이다.
> canonical executor가 required full-runner 입력을 검증한 뒤 two-pass App Server
> skill discovery와 transient skill-disable override를 같은 command builder에
> 자동 연결한다. Luna/Terra/Sol 모두 `subscription-executor-wiring-ready`를
> 만들었고 full-runner 13개·transient 1개 override, MCP 3개, model/auth 0회를
> 확인했다. `358 tests OK, 11 skipped`다. 실제 auth gate와 model turn은 아직
> 별도 승인 지점이다.
> `feynman_subscription_smoke_exec.py`의 실제 Codex command 조립을 공용 builder로
> 연결하고, LOG-053의 two-pass skill isolation과 full-runner override가 세 모델의
> model-free 실행에서 builder에 들어가는 것을 확인했다. full-runner override 13개,
> transient skill-disable 1개, MCP 3개가 검증됐다. Schema 개수 상수 오류를 13으로
> 보정했고 전체 회귀는 `354 tests OK, 11 skipped`다. 모델·인증 호출은 0회다.
> 다음은 실제 executor 호출부가 binding/adapter/Docker 입력 없이는 fail-closed하도록
> 연결하는 일이며 실제 model smoke/baseline은 아직 시작하지 않는다.
> LOG-052 full-runner binding에 연결된 Luna/Terra/Sol candidate에서 exact
> `feynman-thinking` skill exposure, fixed MCP 3-tool catalog, network-disabled
> test 시작과 source 불변성을 model-free로 검증했다. 빈 disposable Codex home에도
> 주변 skill 7개가 노출되어, 첫 discovery 결과를 두 번째 App Server 프로세스의
> transient disable override로 바꾸는 fail-closed 방식을 적용했다. 모델·인증
> 호출은 0회였다. 다음은 이 격리와 full-runner override를 실제 smoke executor의
> 명령 생성 경로에 model-free로 결속하는 단계다. 실제 model smoke와 baseline은
> 아직 시작하지 않는다.
>
> 이전 [LOG-051](feynman-work-log/LOG-051-full-runner-mcp-contract-model-free-20260913.md):
> 새 승인 아래 Luna 비평가 probe를 정확히 1회 실행했고 실제 trace에서 완료된
> `mcp_tool_call` 1개를 관찰했다. 자동 재시도는 없었다. 이는 bounded 1-byte
> diagnostic tool의 model-facing 노출 성공이며 full evaluation runner나 성능
> 검증 성공은 아니다. 이후 full-runner 3-tool MCP contract의 model-free Docker 및
> Codex catalog preflight와 existing tools-10 artifact chain 결속까지 통과했다.
> 상세 결속 결과는 LOG-052이며, 당시 다음 단계였던 model-free skill/command
> wiring은 LOG-053에서 완료됐다.
> [LOG-051](feynman-work-log/LOG-051-full-runner-mcp-contract-model-free-20260913.md)은
> Python runtime 누락을 확인하고 새 local image를 검증한 상세 기록이다.
> 이전 [LOG-049](feynman-work-log/LOG-049-transient-mcp-exec-preflight-20260913.md)에서
> protected control home의 파일을 수정하지 않는 `codex exec --ignore-user-config`
> transient MCP 경로를 구현했고, 실제 실행 전 Luna의 전체 model-free gate를
> `ready-for-subscription-tool-use-probe`로 통과했다. 당시 미실행이던 probe는 위
> LOG-050에서 승인된 1회로 완료했다.
> 이후 [LOG-048](feynman-work-log/LOG-048-remote-container-mcp-catalog-20260913.md)에서
> 동일 Docker runtime의 격리 `/run/codex` MCP catalog도 model-free로 확인했다.
> LOG-047에서 one-byte diagnostic MCP adapter와 blank-home App Server catalog
> 노출을 model-free로 확인했지만 canonical remote exec/model tool-use는 아직
> 검증하지 않았다.
> 세 모델의 별도 작업 자료/동일 버전 환경을 준비했고 byte-response 경계 결함을
> 발견해 fail-closed로 보강했다. 실제 모델 호출은 추가하지 않았다. 아래는 최초
> 인계와 LOG-045의 역사 기록이며 현재 재개 조건은 새 compatibility 문서에 있다.
> 아래 auth gate 미확인 서술은 최초 인계 당시 기록이다. 현재 인증과 Docker/RPC의
> 일부 경로는 확인됐지만 metadata 보정 후 마지막 승인 probe도 tool-use에 실패했다.
> 사용자 지시로 진단을 종료했다. 자동 model retry와 baseline 실행은 하지 않는다.

## 1. 목표와 이번 재개 범위

목표는 역사적 인물의 사고 방법을 문제 해결 스킬로 만드는 `Ronaldony/thinking-skills`에 리처드 파인만 스킬을 설계·구현·검증하는 것이다. 원본은 `Ronaldony/feynman-thinking` v0.4.0이다. 현재 v0.5.0-draft는 설치·평가 구조를 구현한 research preview이지, 행동 성능이 입증된 릴리스가 아니다.

**full-runner MCP contract와 candidate skill 노출을 existing tools-10
runner-job/profile에 결속하고, transient skill 격리까지 실제 executor command
builder에 연결하는 model-free 목표는 LOG-056에서 완료됐다.** 실제 모델 평가와
baseline은 아직 시작하지 않는다. 다음 사람 개입 지점은 보호된 ChatGPT
subscription auth gate 확인과, 그 성공 후 별도 승인된 model-turn smoke다.

## 2. 확인한 저장소 기준점

| 항목 | 인계 작성 시 확인한 값 |
|---|---|
| 저장소 | `Ronaldony/thinking-skills` |
| 작업 브랜치 | `feat/feynman-thinking-v0.5-draft` |
| PR | #1, open / draft / not merged |
| base | `main` |
| 인계 파일 추가 전 원격 HEAD | `1613abd87b813be2aedfaee5ac360046397ad1ca` |
| Windows auth gate 수정 커밋 | `b412e9fa807458d428745c5e63a6fccd38885927` |
| 최신 선행 작업 로그 | `docs/feynman-work-log/LOG-020-windows-auth-gate-fix-and-green-ci.md` |
| 사용자 환경 | Windows PowerShell, `C:\DevWorks\thinking-skills` |
| 평가 전용 홈의 예정 위치 | `Join-Path $HOME '.codex-feynman-eval'` |

이 HEAD는 **인계 전 기준점**이다. 인계 문서 커밋이나 이후 작업으로 HEAD가 앞으로 이동하는 것이 정상이다. 이 SHA로 reset하지 말고 현재 브랜치와 변경 내역을 확인한다. 로컬 사용자가 수정 커밋을 pull했는지는 아직 확인되지 않았다.

GitHub에 코드가 저장돼 있어도 사용자 로컬 clone에 자동 반영되지는 않는다. 원격 feature branch 저장과 main 병합은 별개다. 마지막 조회의 PR 본문에는 이전 검증 head/261-test 수치가 남아 있으므로 최신 로그·실제 코드·해당 SHA의 CI를 우선한다.

## 3. 변경하지 말아야 할 정책

- **OpenAI Platform API 및 API-key 기반 평가 경로는 폐기됐다. 복구하거나 대안으로 제안하지 않는다.** 모델 사용은 공식 Codex의 ChatGPT 구독 로그인만 허용한다. 다른 유료 모델 API나 로컬 HTTP로 우회한 유료 호출도 금지한다.
- `OPENAI_API_KEY`, `CODEX_API_KEY`, `CODEX_ACCESS_TOKEN`을 실행 경로에 주입하지 않는다. 발견 시 값은 출력하지 말고 해당 실행을 차단한다. 공식 Codex의 정상 구독 연결과 저장소 관리를 위한 Git/GitHub 통신은 이 금지와 구분한다.
- 로컬 mock reference의 `MOCK_MODEL_TOKEN`은 합성 테스트 데이터다. 실제 인증이나 모델 성능의 증거가 아니다.
- 로그인 토큰, `auth.json` 내용, 쿠키, session credential을 읽어 출력·복사·해시·커밋·업로드하지 않는다. 전체 환경변수나 control home의 재귀 덤프도 금지한다. 정상 Codex 프로그램이 자신의 인증 상태를 사용하는 것은 허용한다.
- 평가용 `control_codex_home`을 candidate의 mount/env/argv에 노출하지 않는다. candidate/evaluator/source/사용자 HOME 경계를 유지한다.
- 안전장치를 해제해서 검사를 통과시키지 않는다. 전체 환경 상속, 무검토 `shell=True`, 임의의 sandbox 해제, `GITHUB_ACTIONS`를 지워 실제 계정 실행 차단을 우회하는 방법은 사용하지 않는다.
- 이 개발 대화를 baseline 답변 생성에 재사용하지 않는다. 개발 담당 Codex와 평가 candidate는 다른 역할이다. 평가 candidate에는 허용된 스킬·문제·fixture만 제공한다.
- 기존 파일·로컬 변경·다른 브랜치를 덮어쓰거나 삭제하지 않는다. `reset --hard`, `clean -fd`, force push, 무단 merge, 로그인 홈 삭제를 하지 않는다. PR #1의 draft를 유지한다.
- 추가 크레딧 구매·자동충전·유료 서비스 신청은 하지 않는다. 구독 사용 한도에 걸리면 멈추고 기록한다.

## 4. 실제로 어디에서 멈췄는가

사용자 보고의 순서는 다음과 같다.

1. ChatGPT Codex 로그인 완료라고 보고했다. 평가 전용 홈에서의 로그인인지는 당시 검증되지 않았다.
2. PowerShell에서 Bash식/미설정 변수 때문에 `--control-codex-home: expected one argument`가 발생했다.
3. 경로를 직접 주자 전용 디렉터리가 없다는 오류가 발생했다.
4. 전용 홈 준비와 해당 홈 로그인 절차를 안내한 뒤, 마지막으로 받은 실행 결과는 아래였다.

```text
error: Codex version command failed
```

이 오류는 **gate 내부의 `codex --version` subprocess가 nonzero로 종료된 지점**이다. login-status 검사 이전이므로 로그인 실패나 구독 권한 부족으로 단정할 수 없다.

그 뒤 `b412e9f...`에서 auth gate의 Windows 최소 실행 환경과 경로 처리를 보강했다. Windows에서 `SystemRoot`, `ComSpec`, `PATHEXT`, `WINDIR`, `TEMP`, `TMP`, `USERPROFILE` 등을 제한적으로 처리하고, 실패 시 exit code만 보고하도록 수정했다.

**사용자 PC에서 수정 후 성공 결과는 아직 없다.** 이전 대화의 “Windows 구현 결함으로 판단했다”는 표현은 코드에서 확인한 결함과 원인 가설이다. 그것이 사용자 오류의 유일한 원인이었다는 현장 검증은 아직 없다.

## 5. 이번 인계 검토에서 확인한 추가 주의점

### 5.1 auth gate 수정은 실제 executor까지 적용된 것이 아니다

`tooling/feynman_subscription_auth_gate.py::_safe_env()`는 Windows 분기를 갖는다. 반면 인계 기준의 `tooling/feynman_subscription_smoke_exec.py::_safe_exec_env()`는 아직 `HOME / CODEX_HOME / PATH / TMPDIR` 네 값만 만든다. gate 성공만으로 Windows의 실제 smoke executor가 동작한다고 판단하지 않는다.

### 5.2 Windows 검증 범위가 제한돼 있다

`tests/test_feynman_subscription_auth_gate.py`의 Windows 검사는 `_safe_env(platform_name='nt', source_env=...)`의 반환값을 검사한다. 실제 subprocess용 fake는 여전히 `#!/bin/sh`다. Linux CI success와 Windows 실기기 실행 성공을 구분한다. Windows에서 전체 suite를 곧바로 실행하면 POSIX fixture 의존 실패가 생길 수 있으므로 이를 제품 버그/플랫폼별 fixture 한계와 나눠 기록한다.

### 5.3 CLI launcher와 Linux 경로 계약은 별도 확인 대상이다

PowerShell이 선택하는 `codex.ps1`/`codex.cmd`/`codex.exe`와 Python `shutil.which('codex')`의 결과가 다를 수 있다. 이 가능성은 **확인할 가설**이지 재현된 추가 버그가 아니다. 설치된 CLI의 실제 경로·종류·버전, Python 호출과 scrubbed 환경 차이를 비밀정보 없이 확인한다.

현재 boundary validator는 POSIX 경로와 Linux Docker 참조 구조를 사용한다. Windows auth gate 성공이 `C:\...` 경로의 Docker end-to-end 지원을 뜻하지 않는다. native Windows 유지와 WSL2/Linux 경로 사용 중 최소 변경으로 가능한 방안을 실제 환경에서 판정한다. WSL 설치·새 로그인·권한 승인이 필요하면 그 지점만 사용자에게 요청한다. Windows의 credential 파일을 WSL로 복사하지 않는다.

## 6. 읽을 자료와 순서

먼저 적용되는 저장소 `AGENTS.md`가 있는지 확인하고 따른다. 인계를 위해 기존 AGENTS.md를 덮어쓰거나 전역 Codex 설정을 변경하지 않는다.

**현재 중단 지점:**

- 이 문서
- `docs/feynman-work-log/LOG-020-windows-auth-gate-fix-and-green-ci.md`
- `docs/feynman-work-log/LOG-019-windows-auth-gate-version-command-failure.md`
- `tooling/feynman_subscription_auth_gate.py`
- `tests/test_feynman_subscription_auth_gate.py`

**실제 smoke 준비 전:**

- `docs/feynman-subscription-local-smoke.md`
- `docs/feynman-work-log/LOG-015-subscription-smoke-executor.md`
- `tooling/feynman_subscription_smoke_exec.py`
- `tooling/feynman_subscription_run_preflight.py`
- `tooling/feynman_remote_exec_environment.py`
- `tooling/feynman_boundary_profile.py`
- `tooling/feynman_runner_job.py` 및 관련 validate/link/attestation 모듈
- `evals/feynman-thinking/subscription-smoke-spec.json`

**프로젝트 전체 맥락이 필요할 때:**

- `docs/feynman-work-status.md`
- `docs/feynman-work-log/LOG-013-api-retirement-subscription-pivot.md`
- `docs/feynman-work-log/LOG-014-subscription-pivot-stabilization.md`
- `skills/feynman-thinking/SKILL.md` 및 references
- `docs/feynman-audit-2026-09-08.md`

LOG-008/010~012의 API 인증 절차는 역사 기록이며 새 작업 지시가 아니다. 모든 로그를 먼저 정독하느라 첫 진단을 지연시키지 않는다.

## 7. 다음 작업: 작은 완료 단위로 진행

### A. 환경과 현재 파일을 확인한다

로컬 Windows에 실제 접근할 수 있는 개발 Codex인지 확인한다. cloud/원격 세션이면 사용자 PC와 동일한 세션이라고 가정하지 않는다. 로컬 접근이 없다면 인증 파일을 요구하지 말고 그 한계를 보고한다.

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
python --version
Get-Command codex -All | Select-Object Name, CommandType, Source
codex --version
python -c "import shutil; print(shutil.which('codex'))"
```

원격 상태 확인이 가능하면 fetch 후 비교한다. 로컬 변경이나 브랜치 분기가 있으면 보존하고 원인을 확인한다. 업데이트는 필요한 경우에만 fast-forward로 한다. 원격 URL에 자격증명이 포함될 수 있으므로 검증용 출력은 마스킹한다.

### B. 전용 홈을 보존한 채 gate를 재검증한다

사용자 예정 경로가 실제로 존재하는지 먼저 확인한다. 이미 있는 홈에 `prepare`를 다시 실행하거나 credential을 복사하지 않는다. 다른 경로에서 로그인했다는 증거가 있으면 경로를 임의로 바꾸지 않는다.

```powershell
$controlHome = Join-Path $HOME '.codex-feynman-eval'
if (-not (Test-Path -LiteralPath $controlHome -PathType Container)) {
    throw '평가 전용 홈이 없습니다. 기존 로그인 위치와 prepare 결과를 먼저 확인하세요.'
}
$report = Join-Path $env:TEMP ('feynman-auth-gate-' + [guid]::NewGuid().ToString('N') + '.json')
python tooling/feynman_subscription_auth_gate.py check --control-codex-home "$controlHome" --codex-bin codex --output "$report"
if ($LASTEXITCODE -ne 0) { throw 'Auth gate 실패. 같은 명령을 반복하지 말고 실패 단계를 진단하세요.' }
```

새 출력 파일명을 써서 기존 증거를 덮어쓰지 않는다. 정상 목표는 `chatgpt-subscription-authenticated`다. JSON에는 로컬 경로가 있으므로 공개 로그에는 필요한 판정·버전만 남기고 개인 경로를 마스킹한다.

실패하면 일반 `codex --version`과 gate의 버전 subprocess를 구분한다. 런처 차이, 최소 환경, 출력 인코딩, 인자 전달을 **하나씩** 검사한다. `codex doctor` 같은 추가 명령도 설치된 CLI의 `--help`로 존재 여부를 확인한 후 사용한다. 민감한 진단 원문을 그대로 채팅/로그에 내보내지 않는다.

**A/B 완료:** 성공 verdict 또는 원인·재현·최소 패치·검증 결과가 기록되고 다음 한 행동이 정해진 상태. 사용자 재로그인은 정말 인증이 필요한 경우만 요청한다.

### C. 모델 호출 없이 실제 실행 경로를 확인한다

실행기의 Windows 최소 환경, Python/CLI 버전, 지원 플래그, Docker backend, POSIX path/mount mapping을 먼저 확인한다. 도구가 Linux에 있어야 한다면 Linux Codex/Python/Docker와 별도 정상 구독 로그인이 필요할 수 있음을 명시한다.

기존 plan/workspace/profile/job/environment 생성 도구를 재사용한다. 일반 Codex 옵션을 수동으로 조합해 canonical executor를 우회하지 않는다. 필요한 호환성 패치만 구현하고 관련 회귀 테스트를 추가한다. 환경 설치·권한 변경은 사용자 승인 범위에서만 수행한다.

### D. 조건이 모두 갖춰졌을 때만 최초 실제 smoke를 실행한다

```text
case = tools-10
conditions = baseline, feynman-v05
repeats = 각 1회
authentication = chatgpt-subscription / codex-session
analysis_use = not-for-skill-performance-inference
reasoning policy = model-default (integration smoke에만 허용)
```

실행 직전 해당 환경의 boundary 검사와 auth/preflight가 통과해야 한다. frozen plan의 순서를 지키고 두 job을 넘어 임의로 늘리지 않는다. 실패한 실행도 사용량을 쓸 수 있으므로 모델 요청의 자동 반복/성공 결과만 남기기를 하지 않는다.

각 job에 actual trace/final, same-profile boundary evidence, runner-attestation v3, runner-job-link v3, evidence, review bundle, semantic review v2, grade gate, analysis-result v4를 연결한다. 어느 하나가 없으면 그 단계까지만 완료로 기록한다. 해시 연결 자체는 실행 진위의 독립적인 증명을 대신하지 않는다.

후속 의미 채점에서 개발 담당의 자체 판단을 독립·블라인드 심사라고 부르지 않는다. 독립 검토가 없으면 pending 상태를 남기며 합격을 꾸며내지 않는다.

### E. 실제 성능 비교는 그다음이다

4조건은 `baseline / generic / legacy-clean / feynman-v05`다. pilot 전에 explicit reasoning effort를 plan→runner→attestation→link→result에 일관되게 고정하는 versioned contract 보강이 필요하다. mock, 두-job smoke, 공개 개발 사례를 held-out 성능 근거로 섞지 않는다. 새 인프라 확장보다 파인만 스킬의 실질적 효용 검증을 우선한다.

## 8. 작업 로그와 재개 규칙

`docs/feynman-work-log/`에서 실제 파일 목록을 확인해 다음 번호를 고른다. 이 인계는 LOG-021에 기록한다. 다음 번호를 맹목적으로 덮어쓰지 않는다.

각 작업 단위의 시작과 결과 직후 같은 로그에 다음을 기록한다. 단계가 길면 중간 checkpoint를 추가한다.

```text
작업 ID / 시각(Asia/Seoul) / STARTED·DONE·FAILED·BLOCKED·SKIPPED
목적 / 시작 branch·HEAD / 수정 전 git status
환경: OS·shell·Python·Codex·Docker 버전, real 또는 mock
수행: 실제 실행한 명령(비밀정보 제거), 종료 코드
관찰: 필요한 출력 요약, 재현 조건, 실패 단계
판단: 확인된 원인과 아직 검증할 가설을 구분
변경: 파일과 변경 이유, 유지한 보안 조건
검증: 테스트 명령·개수·성공/실패/skip·환경·CI head·run ID
산출물: 비민감 artifact 경로와 필요 시 해시
저장: local commit SHA / push 여부 / 확인한 remote SHA
남은 문제 / 다음에 실행할 정확한 한 행동 / 사람 개입 필요 이유
```

일반 터미널 출력을 통째로 저장하지 않는다. 계정·토큰·개인 경로를 공개 로그에서 제거한다. 실행 전 예상 결과와 실행 후 관찰을 구분하며 raw credential은 해시도 남기지 않는다.

사용자에게 단계별 진행을 짧게 알리고, 종료 전에 완료·미완료·커밋·push·다음 행동을 보고한다. CI를 무한 polling하지 않는다. 아직 실행 중인 CI는 pending으로 남긴다. 커밋된 코드와 실제 push된 원격 HEAD를 분리해 확인한다.

## 9. 검증된 근거와 한계

2026-09-09 인계 준비 중 GitHub에서 수정 커밋 `b412e9f...`의 다음 PR-triggered CI가 모두 `completed / success`인 것을 다시 조회했다.

| workflow | run ID |
|---|---:|
| validate-feynman-subscription-readiness | 34327616872 |
| validate-feynman | 34327616881 |
| validate-feynman-docker-reference | 34327616926 |
| validate-feynman-remote-exec-reference | 34327616941 |
| validate-feynman-codex-reference | 34327616828 |
| validate-feynman-remote-patch-reference | 34327616875 |
| validate-feynman-unit-diagnostic | 34327616793 |

이 조회는 새 테스트 실행도, Windows 실기기 성공도, 모델 성능 측정도 아니다. 최신
로컬 회귀는 LOG-053의 353 tests이며, 과거 CI 수치는 해당 실행의 역사적 기록으로만 본다.

근거 위치:

- PR: https://github.com/Ronaldony/thinking-skills/pull/1
- 기준 코드: https://github.com/Ronaldony/thinking-skills/tree/1613abd87b813be2aedfaee5ac360046397ad1ca
- 수정: https://github.com/Ronaldony/thinking-skills/commit/b412e9fa807458d428745c5e63a6fccd38885927
- Codex CLI 공식 안내: https://learn.chatgpt.com/docs/codex/cli
- 인증 공식 안내: https://learn.chatgpt.com/docs/auth
- Windows 공식 안내: https://learn.chatgpt.com/docs/windows/windows-sandbox
- AGENTS.md 공식 안내: https://learn.chatgpt.com/docs/agent-configuration/agents-md

공식 문서는 제품 사용법의 근거이지 이 저장소의 성공 증거가 아니다. 현재 설치된 CLI의 help/실제 결과를 함께 확인한다.
