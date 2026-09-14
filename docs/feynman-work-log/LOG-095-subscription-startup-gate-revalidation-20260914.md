# LOG-095 — canonical control-home startup gate 재검증 결과 (2026-09-14)

## 상태

- 작업 ID: LOG-095 / 상태: BLOCKED
- 저장소: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `271ece64939407390572c8b09cccbb3e0ea82802`
- 사용자 요청: 승인된 실제 ChatGPT 구독 model-free startup diagnostic 1회
- 모델 turn/evaluation: 0회

## 목적과 범위

Docker runtime/path contract와 최신 full-runner binding이 현재 코드와 일치하는지
확인한 뒤, 기존 `C:\Users\wotmd\.codex-feynman-eval`을 변경하지 않고 실제
Codex App Server의 `initialize`와 `thread/start`만 1회 검증했다. `turn/start`,
prompt, model generation, baseline/Feynman 평가, API key 경로는 사용하지 않았다.

앞선 잘못된 입력 실행은 유효 startup과 구분한다. evaluator 복사본 environment
경로와 stale binding 때문에 사전 검증에서 멈췄고 Codex/Docker subprocess를 시작하지
않았다. canonical control-home 경로로 `validate-only`가 통과한 뒤 유효 startup
실행을 1회 수행했으며, 유효 실행 실패 후 자동 재시도는 하지 않았다.

## 1. 입력 진단 및 model-free 보정

처음 기존 `gpt-5.6-luna-full-runner-binding.json`을 현재 validator에 넣자 다음과
같이 거부됐다.

```text
ValueError: full-runner binding implementation lineage drift
```

이것은 auth/Docker 실패가 아니라 이전 candidate·adapter 구현 digest에 묶인
binding을 현재 코드에 재사용한 입력 계보 오류다. 기존 binding은 보존했다.

이미지 역할도 분리했다.

- remote boundary/profile image: `sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6`
- full-runner tool image: `sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a`

full-runner Docker preflight 명령:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_full_runner_docker_preflight --node-bin 'C:\Program Files\nodejs\node.exe' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --output 'C:\DevWorks\thinking-skills\.tmp\feynman-full-runner-docker-preflight-20260914-v2.json'
```

결과: exit 0, `full-runner-mcp-docker-preflight-passed`, model calls 0.

빈 disposable Codex home와 현재 Luna candidate로 catalog preflight도 실행했다.
첫 PowerShell 시도는 `New-Item -LiteralPath`라는 로컬 명령 조립 오류였고 실제
preflight 전에 중단됐다. `-Path`로 보정한 실행은 exit 0,
`full-runner-mcp-contract-ready`, model calls 0이었다.

현재 candidate와 preflight digest를 결속한 새 binding을 덮어쓰기 없이 생성했다.

```text
C:\DevWorks\thinking-skills\.tmp\gpt-5.6-luna-full-runner-binding-20260914-v2.json
verdict: full-runner-mcp-artifact-chain-bound
model_calls: 0
authentication_used: false
```

evaluator 복사본 `...\evaluator\environments.toml`은 구조적으로 유효했지만
실행기 정책상 다음 오류로 거부됐다.

```text
ValueError: remote environment must be the canonical control CODEX_HOME/environments.toml
```

runner job의 canonical 경로인 `C:\Users\wotmd\.codex-feynman-eval\environments.toml`
을 사용했다. 기존 control home의 존재만 확인했으며 파일 내용을 읽거나 복사하지
않았다. canonical 경로로 `validate-only`는 다음과 같이 통과했다.

```text
verdict: subscription-checkpoint-valid
binding_valid: true
subprocesses_started: 0
authentication_material_present: false
```

## 2. 실제 startup diagnostic 1회

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_subscription_startup_diagnostic --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote-environment 'C:\Users\wotmd\.codex-feynman-eval\environments.toml' --binding 'C:\DevWorks\thinking-skills\.tmp\gpt-5.6-luna-full-runner-binding-20260914-v2.json' --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --telemetry 'C:\DevWorks\thinking-skills\.tmp\startup-diagnostic-20260914-v4-telemetry.json' --output 'C:\DevWorks\thinking-skills\.tmp\startup-diagnostic-20260914-v4.json' --timeout-seconds 60
```

관찰 결과:

```text
exit code: 1
verdict: subscription-startup-thread-blocked
initialize_completed: true
thread_started: false
error_code: -32603
error_category: remote-environment-error
turn_requests_sent: 0
model_generation_requests_sent: 0
process_tree_reaped: true
cleanup_verified: false
```

payload-free telemetry 결과:

```text
schema: 3
requests_seen/forwarded: 6/6
responses_seen/forwarded: 5/5
responses_matched: 5
responses_unmatched: 0
notifications_seen: 0
pending_request_ids: 0
request_write_failures: 0
request_id_duplicates: 0
request_mapping_rejections: 0
response_mapping_rejections: 0
child_exit_code: null
```

request method counter는 `initialize`, `initialized`, `environmentConfig/read`,
`fs/canonicalize`, `fs/getMetadata`, `fs/walk`만 기록했다. 오류 원문·ID·경로·
payload는 보존하지 않았고 notification은 허용 목록 밖이어서 `unknown: 1`로
제한했다. 실행 후 우리 범위의 Docker label을 확인했으며 control/runtime-probe
잔존 container는 없었다.

## 3. 원인 분석

확정된 사실은 다음과 같다.

1. stale binding과 evaluator environment 경로는 입력 오류였고 보정됐다.
2. full-runner Docker fixture, native path contract, binding lineage, canonical
   checkpoint validation은 통과했다.
3. 실제 App Server는 initialize를 완료했지만 `thread/start`에서 `-32603`을
   반환했다.
4. mapping/write/rejection 계수에는 결함 신호가 없지만 6개 request 중 5개
   response만 관찰됐다. 응답 계약이 완전하다고 볼 수 없다.
5. child 종료 코드가 `null`이어서 cleanup/lifecycle 증거도 green으로 승격할 수
   없다.

따라서 blocker는 인증 gate 자체나 native path mapping으로 확정할 수 없다. 현재
가장 좁은 재현 설명은 **Codex 0.154.0 App Server와 configured remote exec-server
사이의 `thread/start` environment lifecycle/response contract가 완료되지 않는
것**이다. payload-free 정책 때문에 어떤 원격 method가 응답을 누락했는지는 이번
실행만으로 특정할 수 없다. `-32603` 분류도 Codex 공식 원인명이 아니라 local
category다.

## 4. 검증 범위와 미완료

- 완료: 입력 계보 보정, full-runner catalog/Docker preflight, canonical checkpoint
  validation, 실제 startup diagnostic 1회, report/telemetry schema 3 형상 확인,
  Docker cleanup 확인
- 미실행: 별도 auth gate 재검증, `turn/start`, prompt, Luna/Terra/Sol model turn,
  baseline/Feynman 평가, candidate tool use, post-run evidence/grade
- 보호: 기존 control home, 사용자 PNG 2개, 기존 `.tmp` 및 새 `.tmp` artifact 보존
- 금지 경로: OpenAI Platform API/API key, credential dump/copy/upload, main merge,
  force push

## 5. 커밋·push와 다음 행동

이 로그와 최신 재개 문서 갱신 후 문서만 feature branch에 일반 commit/push한다.
새 startup은 같은 증거만으로 반복하지 않는다. 다음 한 행동은 모델 실행이 아니라,
동일한 설치 버전과 synthetic remote fixture에서 `thread/start`의 method별
missing-response와 child-exit publication을 payload 없이 분리 재현하는 offline
diagnostic을 추가하는 것이다. 특정 계약 결함이 확인될 때만 코드 수정과 별도 승인된
startup 판단을 검토한다. 현재 gate가 blocked인 상태에서는 Luna smoke나 baseline을
시작하지 않는다.
