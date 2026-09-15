# LOG-069 — Post-fix startup revalidation remains blocked

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `47c9c60 docs: record declared path field checkpoint`
- 사용자 승인: 수정된 매퍼를 포함한 model-free Windows auth/startup 진단 1회
- 적용 AGENTS.md: ancestor/repo 검색 결과 없음
- 기존 변경: 사용자 PNG 2개 untracked; stage하지 않음
- OpenAI Platform API/API key: 사용하지 않음

## 실행 범위

이번 실행은 기존 ChatGPT 구독 로그인 경로를 통한 Windows startup gate 재검증이다.
`initialize`와 ephemeral `thread/start`만 수행하고 `turn/start`, prompt, 모델 생성,
baseline 또는 실제 평가를 수행하지 않는다. 로그인 파일·토큰·전체 환경변수·원문
stderr·RPC payload는 읽거나 출력하거나 보존하지 않는다.

## 정확한 명령

사전 확인에서 branch가 원격과 동기화됐고 runner job, boundary profile, protected
remote environment, Codex CLI, Docker CLI, Python, Node, full-runner binding이
모두 존재함을 확인했다. 진단은 새 report/telemetry 경로로 1회 실행했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_subscription_startup_diagnostic --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote-environment 'C:\Users\wotmd\.codex-feynman-eval\environments.toml' --binding 'C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json' --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --telemetry 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-04-rpc.json' --output 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-04.json' --timeout-seconds 60
```

종료 code는 0이며, 프로그램이 안전한 요약 verdict를 출력했다. 이는 Codex
subprocess가 정상 종료했다는 뜻이지 startup gate가 통과했다는 뜻이 아니다.

## 관찰 결과

```text
verdict: subscription-startup-thread-blocked
thread_started: false
error_code: -32603
error_category: remote-environment-error
turn_requests_sent: 0
model_generation_requests_sent: 0
request_mapping_rejection_methods:
  environmentConfig/read: 1
  fs/getMetadata: 6
request_mapping_rejection_reasons:
  container-path-outside-declared-mount: 2
  host-path-outside-declared-mount: 4
  invalid-host-path: 1
```

안전 telemetry에서 requests seen/forwarded/rejected는 `12/5/7`, responses
seen/forwarded는 `4/4`, response mapping rejection은 `0`, child exit code는 `0`이었다.
수정 전 `-03`과 같은 rejection 분포가 다시 관찰됐으므로 scalar path field
fail-closed 보강만으로 remote startup 문제가 해결되지 않았음은 확인됐다.
그러나 telemetry는 method별·reason별 주변 집계이며 특정 rejected path를
서로 결합하지 않으므로, 실제 경로 하나의 mount 허용 필요성을 추측하지 않는다.

## artifact 및 보안 확인

- report: `C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-04.json`
- telemetry: 같은 evaluator의 `startup-diagnostic-20260913-04-rpc.json`
- report 크기: 1,964 bytes; telemetry 크기: 892 bytes
- report schema validation: `0` errors, schema version `1`
- `initialize_completed=true`, `process_tree_reaped=true`
- `turn_requests_sent=0`, `model_generation_requests_sent=0`
- response mapping rejection: `0`
- credential file direct read, control-home serialization, payload preservation,
  raw stderr preservation, thread ID preservation: 모두 `false`
- Feynman Docker container postcheck: 0개

artifact에는 고정된 안전 요약만 남아 있으며 실제 rejected path, auth 상태 원문,
instruction source path, thread ID는 포함하지 않는다.

## 판정

인증 gate가 성공했다고 판정할 수 없다. 이번 결과는 `-32603` remote environment
startup block이며, Docker child 자체는 exit 0이고 proxy response mapping도
거부하지 않았다. 따라서 문제 범위는 Windows control process가 remote
environment discovery 중 보낸 path request와 declared mount/namespace 계약의
불일치로 좁혀지지만, 특정 경로나 특정 mount를 허용해야 한다는 결론은 내리지
않는다.

인증 검사를 통과하지 못했으므로 실제 model-facing tool catalog, model turn,
Terra/Sol 세션, baseline 및 Feynman 평가를 시작하지 않았다. 사용자에게
재로그인이나 같은 명령의 무작정 반복을 요구하지 않는다.

## 저장 상태와 다음 행동

이번 실행 전 코드는 구현 commit `70592c4`와 문서 checkpoint `47c9c60`에 저장되어
있고, 둘 다 feature branch에 push됐다. `47c9c60`의 GitHub Actions 7개 workflow도
모두 `completed / success`로 확인했다. 이 로그와 재개 포인터 갱신은 별도
문서-only checkpoint로 저장한다.

미완료 사항은 remote discovery 요청의 실제 namespace/field 계약을 payload 없이
더 정밀하게 분리하는 model-free 분석과, 그 결과를 반영한 별도 startup 재검증이다.
새로운 model run이나 baseline은 이 선행 조건이 통과하기 전까지 금지한다. main
merge와 force push는 하지 않는다.
