# LOG-073 — Startup path rejections not reproduced

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `323f76d docs: record green checkpoint checks`
- 시작 dirty 상태: 사용자 PNG 2개 untracked; 보존하고 stage하지 않음
- 작업 성격: Codex 0.154.0 schema 확인, payload-free 계측 보강, 승인된 model-free startup 진단 1회
- OpenAI Platform API/API key: 사용하지 않음
- actual turn/model/baseline/evaluation: 0회
- 보호된 로그인 홈: `C:\Users\wotmd\.codex-feynman-eval` 보존; 인증 파일·token·전체 환경변수 미출력

## 목적

LOG-072의 `environmentConfig/read.configPaths` invalid-host 1건이 상대경로인지
traversal인지 payload 없이 구분하고, 같은 조건에서 startup blocker가 재현되는지
확인한다. 사용자는 다음 model-free startup diagnostic 1회를 명시 승인했다.
추가 자동 반복과 model turn은 승인 범위에 포함하지 않았다.

## 공식 문서와 version-specific schema 확인

공식 Codex App Server 문서는 다음을 명시한다.

- `initialize`/`initialized`, `thread/start`, `turn/start`는 서로 다른 lifecycle 단계다.
- CLI가 생성하는 JSON Schema는 실행한 Codex version에 종속된다.
- remote environment에서 반환되는 instruction source는 source environment의 native
  absolute path syntax를 사용한다.

공식 문서는 remote exec-host 내부 RPC인 `environmentConfig/read`, `configPaths`,
`requirementsPaths`의 상세 semantics는 정의하지 않는다.

설치된 CLI 확인 및 schema 생성 명령:

```powershell
& 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --version
& 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' app-server generate-json-schema --out 'C:\DevWorks\thinking-skills\.tmp\codex-app-server-schema-0.154.0'
```

관찰:

```text
codex-cli 0.154.0
environmentConfig/read=0
configPaths=0
requirementsPaths=0
```

생성 schema는 공개 App Server protocol만 포함하며 위 remote-host 세 식별자를 포함하지
않았다. 임시 schema 디렉터리는 workspace 내부임을 확인한 뒤 제거했다. 인증·network·
model 호출은 없었다.

## 진단 전 fixed reason 세분화

기존 `invalid-host-path`와 `invalid-container-path`는 각각 absolute 조건 실패와
traversal 조건 실패를 함께 나타냈다. 실제 경로를 보존하지 않고도 두 조건을 구분하도록
다음 fixed reason을 추가했다.

- `host-path-not-absolute`
- `host-path-traversal`
- `container-path-not-absolute`
- `container-path-traversal`

legacy fixed message mapping은 과거 호환을 위해 유지했다. synthetic relative config,
host traversal, container traversal 테스트를 추가했다.

검증:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_path_proxy tests.test_feynman_subscription_startup_diagnostic -v
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -v
```

결과:

- targeted: `40 tests OK`
- full: `384 tests OK, 11 skipped`

저장 상태:

- `415b61d diagnose: split invalid RPC path reasons`
- `origin/feat/feynman-thinking-v0.5-draft`에 push 확인

## 승인 실행 전 precheck

민감한 내용은 출력하지 않고 canonical 구조와 실행 가능성만 확인했다.

```text
binding_verdict= remote-exec-environment-valid
include_local= False
environment_count= 1
proxy_matches_current_repo= True
output_exists= False
telemetry_exists= False
Docker=29.7.2|linux|aarch64|overlayfs
image=sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a|linux|arm64
remote_head=415b61da2208bc81cdb3681bc616bc8541b7bb51
```

## 승인된 startup diagnostic 정확히 1회

실제 명령:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_subscription_startup_diagnostic --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote-environment 'C:\Users\wotmd\.codex-feynman-eval\environments.toml' --binding 'C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json' --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --telemetry 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-06-rpc.json' --output 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-06.json' --timeout-seconds 60
```

종료 코드 `0`, 안전 stdout:

```text
verdict=subscription-startup-thread-blocked
thread_started=false
error_code=-32603
error_category=remote-environment-error
turn_requests_sent=0
model_generation_requests_sent=0
request_mapping_rejection_methods={}
request_mapping_rejection_reasons={}
request_mapping_rejection_method_reasons={}
request_mapping_rejection_method_reason_fields={}
```

산출물:

- `C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-06.json`
- `C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-06-rpc.json`

안전 검증:

```text
report_schema_errors=0
report_bytes=1759
telemetry_bytes=707
initialize_completed=true
thread_started=false
error_code=-32603
turn_requests_sent=0
model_generation_requests_sent=0
process_tree_reaped=true
requests_seen=1
requests_forwarded=1
request_methods={initialize:1}
responses_seen=1
responses_forwarded=1
request_mapping_rejections=0
response_mapping_rejections=0
child_exit_code=0
Docker feynman container 잔여=0
```

privacy flags는 request/response payload, thread id, instruction source paths, raw stderr,
credential file direct read, control home serialization이 모두 `false`다.

## 판정 변경

LOG-072의 path rejection 분포는 이번 실행에서 재현되지 않았다. 이번에는 remote child가
`initialize` 요청 1건과 응답 1건을 정상 전달한 뒤 종료했고, `initialized`,
`environmentConfig/read`, `fs/getMetadata`는 관찰되지 않았다. 따라서 다음을 구분한다.

- path mapper가 LOG-072 blocker를 영구 해결했다고 주장할 수 없다. 이번 code change는
  valid request 흐름을 바꾸지 않고 error label만 세분화했다.
- 이번 `-32603`은 path mapping rejection으로 설명되지 않는다.
- 관찰 가능한 실패 구간은 remote child initialize 응답 이후, App Server가 remote
  environment 연결/thread 환경을 확정하기 전이다.
- Docker child exit 0과 path rejection 0은 thread startup 성공 증거가 아니다.
- 실제 model, tool, baseline, evaluation 결과는 없다.

실행별 차이는 remote startup의 비결정적 연결 상태나 아직 계측되지 않은 App Server
error detail 가능성을 시사하지만, 어느 하나를 원인으로 확정하지 않는다.

## 실행 후 payload-free 진단 보강

`-06` report는 App Server notification 1건을 기록했지만 기존 코드는 임의의 method
문자열을 그대로 보존할 수 있었다. 원문을 출력하지 않고 알려진 lifecycle method만
allowlist하고 나머지는 `unknown`으로 축약하도록 수정했다.

또한 다음 fixed boolean error signals와 error data의 JSON kind만 추가했다.

- environment, exec-server, connection, initialize, exit, closed, timeout
- config, path, not-found
- error data kind: none/boolean/string/number/array/object/other

error message/data 자체는 저장하지 않는다. 새 필드는 schema v1에서 optional로 추가해
LOG-072/-06 같은 기존 artifact도 계속 검증 가능하게 했다.

검증:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_path_proxy -v
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -v
```

결과:

- targeted: `41 tests OK`
- full: `385 tests OK, 11 skipped`
- synthetic private notification/error content 미보존 확인

저장 상태:

- `2ff571d diagnose: bound startup error telemetry`
- `origin/feat/feynman-thinking-v0.5-draft`에 push 확인

## 미완료 및 다음 사람 개입

- `thread/start`는 여전히 통과하지 못했다.
- `-06`의 원문 error message/data와 notification method는 출력·복원하지 않는다.
- 새 fixed error signals는 `-06` 이후 구현됐으므로 아직 실제 실행값이 없다.
- 추가 model-free startup diagnostic은 이번 승인 범위를 벗어나며 자동 실행하지 않는다.
- actual model turn, Luna/Terra/Sol fallback, baseline, frozen evaluation은 계속 금지한다.
- mount 확대, relative config 자동 보정, config response 제조도 현재 증거로 정당화되지
  않는다.

다음 한 행동은 새 fixed error signals를 포함한 model-free startup diagnostic 정확히
1회다. 이는 별도 명시 승인이 있어야 한다. 실패 시 자동 반복하지 않는다.

이 문서는 개발 인계용이며 baseline candidate나 평가 prompt로 전달하지 않는다.
