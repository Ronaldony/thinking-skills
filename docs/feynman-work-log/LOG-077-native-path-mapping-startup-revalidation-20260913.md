# LOG-077 — Native Windows path-mapping 보정 후 startup 재검증

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 작업 성격: native Windows path-mapping migration 후 model-free startup gate 재검증
- OpenAI Platform API/API key: 사용하지 않음
- protected control home: `C:\Users\wotmd\.codex-feynman-eval` 보존
- actual model turn/baseline/evaluation: 0회
- 사용자 PNG 2개: untracked 상태로 보존하고 stage하지 않음

## 목표와 제한

Docker Desktop recovery 이후 `thread/start` startup gate를 재검증했다. 인증 상태와
startup, evaluator/Docker compatibility를 분리해 기록한다. 모든 startup probe는
`initialize`/`initialized`와 ephemeral `thread/start`만 보냈고 `turn/start`, prompt,
모델 생성, baseline 전달은 수행하지 않았다. 로그인 파일·토큰·전체 환경변수·원문
request/response/stderr는 읽어 출력하거나 artifact에 보존하지 않았다.

## 사전 확인

실행한 명령:

```powershell
rg --files -g 'AGENTS.md'
git status --short --branch
git log -5 --oneline
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}|{{.Containers}}|{{.Images}}|{{.Driver}}|{{.OperatingSystem}}'
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' run --rm --network none --entrypoint codex 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --version
& 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --version
```

관찰:

- 적용되는 `AGENTS.md`는 없었다.
- branch는 feature branch이며 시작 시 원격과 동기화돼 있었다. 사용자 PNG 2개만
  untracked였다.
- Docker: `29.7.2|linux|aarch64|0|14|overlayfs|Docker Desktop`.
- 고정 image: `linux|arm64`, Codex CLI `0.154.0`; host Codex CLI도 `0.154.0`.
- 고정 binding의 실제 위치는 `C:\DevWorks\feynman-full-runner-binding-20260913-01`이다.
  이전 probe 명령에 잘못 들어간 `C:\Users\wotmd\...` 경로는 존재하지 않아 입력
  검증에서 종료됐으며, auth 또는 Docker 실패가 아니었다.

## 코드 변경

1. `tooling/feynman_rpc_path_mapping.py`

   Codex 0.154.0의 executor-internal `environmentConfig/read`에서 관찰된 상대
   `configPaths`/`requirementsPaths`를 일반 Windows host path로 분류하지 않고,
   traversal·backslash가 없는 POSIX 상대경로에 한해 `/run/candidate`에 고정했다.
   절대 host/container path와 `file:` URI의 기존 allowlist 및 fail-closed 동작은
   유지했다. 이는 실제 payload를 저장하지 않은 상태에서 `-12`/`-13`의 field별
   rejection을 근거로 한 좁은 호환성 보정이며 mount 범위를 넓히지 않는다.

2. `tooling/feynman_subscription_startup_diagnostic.py`

   - optional `thread/start.cwd`를 생략해 App Server local cwd가 remote discovery에
     섞이지 않게 했다. `ThreadStartParams`에 없는 `environments`와
     `runtimeWorkspaceRoots`는 계속 넣지 않는다.
   - probe process의 local config에 `project_root_markers=[]`와
     `project_doc_max_bytes=0`를 transient override로 추가했다. 이 override는
     startup probe에만 적용되고 실제 smoke executor의 candidate/skip-git contract를
     바꾸지 않는다.
   - 현재 공식 schema에 있는 `thread/environment/connected` notification을 bounded
     safe set에 추가했다. peer가 보내는 임의 method 이름은 여전히 `unknown`이다.
   - 입력 검증, wiring, process write/cleanup 실패는 고정 label만 남기도록 보강했다.
     원문 예외·경로·stderr는 보존하지 않는다.

3. 회귀 테스트

   `environmentConfig/read` 상대경로·traversal·ambiguous path, native/container
   namespace, startup parameter omission, modern environment notification을
   검증하는 테스트를 추가/갱신했다.

## 외부 실행 기록

기존 `-09`부터 `-14`까지의 결과는 path-boundary 보정 과정의 연속 기록이다.
`-09`는 `-32603` 및 path rejection을 보였고, `-10`/`-11`은 local discovery와
host-path rejection을 분리했으며, `-12`는 상대 `requirementsPaths`, `-13`은
상대 `configPaths`를 노출했다. `-14`에서 다음과 같이 path boundary가 처음으로
green이 됐다.

```text
request_methods={environmentConfig/read:1, fs/canonicalize:1, fs/getMetadata:1, fs/walk:1, initialize:1, initialized:1}
requests_seen=6
requests_forwarded=6
request_mapping_rejections=0
responses_seen=5
responses_forwarded=5
response_mapping_rejections=0
child_exit_code=0
```

그 뒤 `-15`~`-23`은 다음의 진단 입력/계측 확인이었다. 새 경로를 사용했고 자동
재시도는 하지 않았다. response-shape 계측은 기존 proxy lifecycle에 불필요한
회귀 가능성이 있어 제거했다. `-23`에서 line-72 고정 label로 binding 경로 누락을
확정했고, 원인은 `C:\Users\wotmd\...`와 실제 `C:\DevWorks\...`의 불일치였다.

유효한 최종 명령(`-24`, 정확히 1회):

```powershell
& 'C:\Users\wotmd\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe' -Command '& "C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe" -m tooling.feynman_subscription_startup_diagnostic --runner-job "C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json" --boundary-profile "C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json" --remote-environment "C:\Users\wotmd\.codex-feynman-eval\environments.toml" --binding "C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json" --codex-bin "C:\Users\wotmd\AppData\Roaming\npm\codex.cmd" --node-bin "C:\Program Files\nodejs\node.exe" --adapter "C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs" --docker-bin "C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe" --docker-config "C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config" --docker-image-id "sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a" --telemetry "C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-24-rpc.json" --output "C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-24.json" --timeout-seconds 60'
```

종료 코드는 `0`이며, report/telemetry 모두 생성됐다. payload-free 결과:

```text
verdict=subscription-startup-thread-blocked
thread_started=false
error_code=-32603
error_category=remote-environment-error
initialize_completed=true
turn_requests_sent=0
model_generation_requests_sent=0
proxy_telemetry_status=available
request_mapping_rejections=0
responses_seen=5
responses_forwarded=5
response_mapping_rejections=0
child_exit_code=0
notification_methods={unknown:1}
```

report의 privacy flags는 request/response payload, thread id, instruction source
path, raw stderr, credential direct read, control-home serialization 모두 `false`다.

## 판정

- Docker engine/image 실행, Codex version parity, control-plane initialize, child
  reap은 통과했다.
- Native Windows path mapping은 `environmentConfig/read`, `fs/canonicalize`,
  `fs/getMetadata`, `fs/walk`의 관찰된 startup sequence에서 rejection 0으로
  통과했다.
- 그러나 App Server `thread/start`는 계속 `-32603 remote-environment-error`다.
  remote child는 6개 request를 모두 받고 5개 response를 모두 반환했으므로,
  남은 blocker는 path mapper가 아니라 0.154.0 App Server와 remote exec-server의
  environment startup/response lifecycle contract다. `notification_methods`의
  `unknown:1`은 payload를 보존하지 않았으므로 특정 method로 단정하지 않는다.
- 따라서 auth gate가 통과했다는 사실만으로 evaluator compatibility 또는 실제
  model evaluation이 준비됐다고 판정하지 않는다. 실제 model turn, baseline,
  Feynman candidate, Terra/Sol fallback은 실행하지 않았다.

## 검증 범위

실행한 검증:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_rpc_path_mapping tests.test_feynman_subscription_startup_diagnostic -q
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m compileall -q tooling tests
git diff --check
```

현재 targeted 검증은 `44 tests OK`, compileall exit `0`, diff check exit `0`이며,
modern notification 테스트 추가 후 full suite를 다시 실행한다. 공식 기준은
[Codex App Server 문서](https://learn.chatgpt.com/docs/app-server)의
initialize/initialized → thread/start lifecycle와 version-specific schema 원칙이다.

## 커밋·push와 미완료

- 이 로그 작성 시점에는 code/docs commit과 push가 아직 남아 있다.
- commit 후 feature branch에만 normal push한다. main merge와 force push는 하지 않는다.
- 실제 evaluator/Docker compatibility의 최종 green은 `thread/start` blocker 때문에
  미완료다.
- 다음 행동은 full unit/schema validation과 로그 pointer 갱신, commit/push receipt
  기록이다. 추가 startup 반복이나 실제 model turn은 이 blocker가 해결되고 별도
  승인될 때까지 수행하지 않는다.
