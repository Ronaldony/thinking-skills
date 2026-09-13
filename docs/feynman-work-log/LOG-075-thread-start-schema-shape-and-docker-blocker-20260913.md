# LOG-075 — thread/start schema 보정 및 Docker Engine blocker

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `16537c7 docs: record startup telemetry absence`
- 시작 dirty 상태: 사용자 PNG 2개 untracked; 보존하고 stage하지 않음
- 작업 성격: 미완료 startup 원인 분리, Codex 0.154.0 request-shape 보정, 실행 전 환경 blocker 진단
- OpenAI Platform API/API key: 사용하지 않음
- actual turn/model/baseline/evaluation: 0회
- 보호된 로그인 홈: `C:\Users\wotmd\.codex-feynman-eval` 보존; 인증 파일·token·전체 환경변수 미출력

## 목적

미완료 항목인 `thread/start` 차단과 Windows/Docker full-runner 호환성 미확인을
서로 섞지 않고 원인을 분리한다. 먼저 설치된 Codex 0.154.0의 version-specific
`ThreadStartParams`와 현재 probe payload를 비교하고, 로컬 보정 후 model-free startup
재검증을 시도한다. 실제 model turn이나 평가 실행은 대상이 아니다.

## Codex 0.154.0 schema 확인

공식 App Server 문서는 `initialize` 후 `thread/start`를 호출하는 lifecycle과 version-
specific JSON Schema 생성을 안내한다. 또한 remote environment의 instruction path는
source environment의 native absolute path를 사용한다고 설명한다.

```powershell
$schemaDir = Join-Path (Get-Location) '.tmp\\codex-app-server-schema-0.154.0-check'
New-Item -ItemType Directory -Path $schemaDir -Force | Out-Null
& 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' app-server generate-json-schema --out $schemaDir
```

생성 schema를 raw payload 없이 Python으로 요약했다.

```text
has_ThreadStartParams=True
thread_start_keys=['approvalPolicy', 'approvalsReviewer', 'baseInstructions', 'config', 'cwd', 'developerInstructions', 'ephemeral', 'model', 'modelProvider', 'personality', 'sandbox', 'serviceName', 'serviceTier', 'sessionStartSource', 'threadSource']
thread_start_required=[]
environment_fields_present=False
SandboxMode includes workspace-write
```

확인 결과 현재 `_thread_start_params()`가 보내던 `environments`와
`runtimeWorkspaceRoots`는 0.154.0 `ThreadStartParams`에 없다. 반면 `sandbox`의
`workspace-write`는 생성 schema의 `SandboxMode`에 존재한다. 따라서 문제는 sandbox
표기 자체가 아니라, probe가 protocol에 없는 환경 배열 필드를 임의로 추가한 것이다.

## 로컬 보정

다음 파일을 수정했다.

- `tooling/feynman_subscription_startup_diagnostic.py`
- `tests/test_feynman_subscription_startup_diagnostic.py`

`thread/start` payload를 다음 5개 고정 필드로 제한했다.

```text
model / cwd / approvalPolicy / sandbox / ephemeral
```

remote environment 선택은 canonical `environments.toml`의 configured environment와
native `cwd`에 맡기며, `thread/start` payload 안에서 `environments`나
`runtimeWorkspaceRoots`를 제조하지 않는다. 테스트는 정확한 key set과 두 unsupported
field의 부재를 고정한다. 기존 telemetry 부재 보정도 유지해, 실행 후 proxy telemetry가
없을 때 성공이나 rejection 0으로 오판하지 않는다.

## 실행 전 precondition 확인

새 `-08` report와 telemetry 경로는 모두 존재하지 않았다.

```text
{"report_exists":false,"telemetry_exists":false}
```

canonical remote environment 구조 검증은 통과했다.

```text
remote_environment_verdict=remote-exec-environment-valid include_local=false environment_id=candidate
```

Docker 읽기 전용 확인 명령:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}|{{.Containers}}|{{.Images}}|{{.Driver}}|{{.OperatingSystem}}'
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' image inspect 'feynman-codex-remote:local' --format '{{.Id}}|{{.Os}}|{{.Architecture}}|{{json .Config.Entrypoint}}|{{json .Config.Cmd}}'
```

두 명령 모두 다음 고정 오류로 실패했다.

```text
Error response from daemon: Docker Desktop is unable to start
```

Docker backend/frontend 프로세스는 존재하고 응답 상태는 true였지만 Engine named pipe는
사용할 수 없었다. `docker desktop status`는 설치된 CLI 0.154.0 환경에서 지원되지
않았다. WSL 기반 여부를 확인하기 위해 다음 제한 진단도 실행했다.

```powershell
$p=Start-Process -FilePath 'C:\Windows\System32\wsl.exe' -ArgumentList '--status' -NoNewWindow -PassThru
if(-not $p.WaitForExit(5000)){ $p.Kill(); $p.WaitForExit(); 'wsl_status=timeout' }
```

결과는 `wsl_status=timeout`이었다. Windows service 조회에서는 `hns`, `vmcompute`,
`WslService`가 Running이었지만, 서비스가 Running이라는 사실만으로 Docker Linux
Engine의 정상 응답을 증명하지 못한다.

이 precondition 실패 때문에 수정된 `thread/start` payload로 `-08` model-free startup를
실행하지 않았다. Docker 장애와 request-shape 수정 효과를 섞지 않기 위한 중단이다.

## 검증

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_feynman_subscription_startup_diagnostic.py' -v
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -v
```

결과:

- targeted: `7 tests OK`
- full: `386 tests OK, 11 skipped`
- version-specific generated schema에서 unsupported environment fields 부재 확인
- 작업 중 생성한 schema 임시 디렉터리는 정확한 workspace 경로를 확인한 뒤 제거
- auth gate·turn/start·model generation·baseline·evaluation: 0회

## 원인 판정

- `thread/start`의 이전 blocker에는 protocol shape 결함이 있었다. `environments`와
  `runtimeWorkspaceRoots`는 Codex 0.154.0 schema에 없는 필드이며, 이를 제거하는
  로컬 수정은 완료했다.
- 현재 Windows/Docker blocker는 별도다. Docker daemon이 시작되지 않고 WSL status도
  응답하지 않아, full-runner의 실제 container mount/tool compatibility는 아직 검증할
  수 없다.
- 따라서 이번 단계에서 `thread/start`가 수정 후 성공했다고 주장하지 않는다. -08은
  실행하지 않았기 때문이다.
- 인증 파일·token·전체 환경변수·control home 내용은 읽거나 출력하지 않았다. 기존
  ChatGPT subscription login 상태도 재로그인하지 않았다.

## 미완료 및 다음 행동

- 남은 단일 사람 개입: Docker Desktop UI에서 Engine을 정상화한 뒤 `docker info`가
  server 정보를 반환하는지 확인해야 한다. 재로그인이나 인증 파일 전달은 필요하지 않다.
- Engine이 정상화되면, 현재 수정 commit 기준으로 `-08` model-free startup diagnostic
  정확히 1회를 새 승인 후 실행한다. 이때도 turn/model은 시작하지 않는다.
- `-08`에서 `thread/start`가 성공하고 proxy telemetry가 생성된 뒤에만 Windows/Docker
  full-runner compatibility를 별도 model-free gate로 판정한다.
- 실제 model turn, Luna/Terra/Sol fallback, baseline, frozen evaluation은 계속 보류한다.
- main merge와 force push는 하지 않는다.

## 저장 상태

- 구현·테스트·인계 문서·이 로그는 commit `3824581 fix: align startup thread request with codex schema`로 저장했다.
- `origin/feat/feynman-thinking-v0.5-draft`에 일반 push했고 원격 SHA는
  `3824581ce98c0160f64b0c8c51e2eaf80cff70ee`다.
- 해당 SHA의 마지막 CI 조회에서는 `validate-feynman-codex-reference`,
  `validate-feynman-docker-reference`, `validate-feynman-remote-exec-reference`,
  `validate-feynman-remote-patch-reference`가 `completed / success`였고,
  `validate-feynman`, `validate-feynman-subscription-readiness`,
  `validate-feynman-unit-diagnostic`는 `queued`였다.
- 사용자 PNG 2개는 untracked로 보존했고 stage하지 않았다.

이 문서는 개발 담당 Codex용 작업 로그이며 baseline candidate나 평가 prompt로 전달하지
않는다.
