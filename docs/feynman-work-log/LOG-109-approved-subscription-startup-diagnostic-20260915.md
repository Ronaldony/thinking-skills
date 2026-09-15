# LOG-109 — 승인된 ChatGPT 구독 startup diagnostic 1회

## 상태

- 작업 ID: `NEXT-04 / approved-subscription-startup-diagnostic`
- 시각: 2026-09-15 KST
- 상태: `DONE` (startup gate 차단, 모델 실행 미착수)
- 저장소: `Ronaldony/thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `8718a792639daf91576bbdbba5ac3f00a936dd69`
- 시작 dirty 상태: 기존 보호 대상 `.tmp/`, 사용자 PNG 2개, `LOG-099`가 untracked로 존재; tracked 변경 없음

이번 사용자 승인은 기존 ChatGPT 구독 로그인 홈을 사용하는 startup diagnostic 최대 1회로 해석했다. 모델 turn, Luna smoke, baseline, 재시도, 다른 모델 fallback은 실행하지 않았다.

## 목적과 안전 경계

`initialize → thread/start`의 실제 구독 startup 호환성만 확인했다. 인증 파일·토큰·쿠키·전체 환경변수·control home 내용은 읽거나 출력하거나 복사하지 않았다. Platform API와 API key 경로는 사용하지 않았다. 출력은 evaluator-owned 경로의 sanitized report와 payload-free telemetry만 사용했다.

## 실행 전 확인

### CLI와 출력 경로

실행한 명령:

```powershell
git rev-parse HEAD
git status --short --branch
rg -n --context 2 'checkpoint|validate-only|timeout-seconds|telemetry|runner-job|def main|parse_args' tooling/feynman_subscription_startup_diagnostic.py
```

관찰:

- HEAD와 branch는 위 상태와 일치했다.
- `--checkpoint`와 개별 입력 인자는 혼용할 수 없고, `--validate-only`는 subprocess를 시작하지 않는다.
- 새 report/telemetry 출력 경로는 evaluator 디렉터리 안에서 각각 존재하지 않았다.

### 잘못된 입력의 사전 차단

첫 startup 호출에는 runner job의 evaluator 환경 파일을 `remote-environment`로 넣었다. `run()`은 subprocess 전에 checkpoint 계약을 검사하므로 다음 오류로 중단됐다.

```text
error: startup diagnostic failed: startup-diagnostic-input-invalid-value-error
exit code: 1
```

후속 순수 검증에서 확인한 원인은 다음과 같다.

```text
checkpoint remote environment must be the canonical control CODEX_HOME/environments.toml
```

이 호출은 `from_run_inputs → validate_checkpoint`에서 중단됐고 app server/Codex/Docker subprocess는 시작되지 않았다. 실패 artifact도 생성되지 않았다. 따라서 원격 `thread/start` 실패가 아니라 입력 binding 오류다.

runner job의 path metadata만 대조했다. control home의 내용은 읽지 않았다.

- 제공 경로: evaluator 디렉터리의 `environments.toml`
- canonical 경로: 기존 평가 전용 control home의 `environments.toml`
- 두 경로 모두 존재했지만 계약상 canonical 경로가 아니었다.

보정 후 `--validate-only`를 실행했다.

```text
verdict=subscription-checkpoint-valid
binding_valid=true
input_checks: adapter/binding/boundary_profile/codex_bin/docker_bin/docker_config/node_bin/output/remote_environment/runner_job/telemetry 모두 true
subprocesses_started=0
authentication_material_present=false
exit code=0
```

## 승인된 실제 startup 실행

보정된 canonical control-home environment 경로, 기존 full-runner binding, 고정된 `gpt-5.6-luna`, Docker image digest, 새 evaluator-owned output 경로로 startup diagnostic을 정확히 1회 실행했다. timeout은 60초로 제한했다.

실행한 명령(민감한 자료의 내용은 포함하지 않음):

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_subscription_startup_diagnostic `
  --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' `
  --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' `
  --remote-environment 'C:\Users\wotmd\.codex-feynman-eval\environments.toml' `
  --binding 'C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json' `
  --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' `
  --node-bin 'C:\Program Files\nodejs\node.exe' `
  --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' `
  --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' `
  --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' `
  --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' `
  --telemetry 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260915-v1-rpc.json' `
  --output 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260915-v1.json' `
  --timeout-seconds 60
```

결과:

```text
verdict=subscription-startup-thread-blocked
thread_started=false
error_code=-32603
error_category=remote-environment-error
initialize_completed=true
turn_requests_sent=0
model_generation_requests_sent=0
proxy_telemetry_status=available
request_mapping_rejection_methods={}
request_mapping_rejection_reasons={}
exit code=1
```

sanitized report 추가 상태:

- `process_tree_reaped=true`
- `cleanup_verified=false`
- `proxy_telemetry_complete=false`
- `proxy_request_response_correlated=false`
- `request_mapping_clean=true`
- `error_data_kind=none`
- `instruction_sources_present=false`; startup 차단 상태이므로 허용 판정도 false
- notification은 원문을 보존하지 않고 `unknown: 1`로만 집계됨

telemetry의 payload-free 요약:

- schema v3
- `initialize` 요청 1건
- response error code counter는 비어 있음
- child exit code `1`
- request/response mapping rejection 0건

`-32603 / remote-environment-error`는 설치된 실행 경계가 반환한 숫자 오류와 로컬 분류다. 이 결과만으로 path mapping, Docker image, executor protocol 중 하나를 확정하지 않는다. `mapping rejection=0`도 올바른 경로 의미나 원격 환경 성공을 증명하지 않는다.

## 산출물 및 검증

evaluator-owned 산출물:

- startup report: evaluator 실행 디렉터리의 `startup-diagnostic-20260915-v1.json`
- RPC telemetry: 같은 evaluator 디렉터리의 `startup-diagnostic-20260915-v1-rpc.json`

검증 결과:

```text
subscription-startup-diagnostic.schema.json JSON Schema: 통과
report schema_version: 3
report/telemetry credential marker 검사: 없음
raw stderr/request-response payload/thread ID 보존: 없음
```

실행 횟수:

- startup diagnostic: 1회
- 사전 `--validate-only`: 1회 (외부 subprocess 0회)
- 잘못된 입력으로 사전 차단된 run 호출: 1회 (외부 subprocess 0회)
- 모델 turn / model generation: 0회
- Luna smoke / baseline / 평가: 0회
- auth gate 단독 CLI: 0회. 별도 재로그인이나 별도 인증 명령은 실행하지 않았다.

## 판단

확인된 결함은 두 가지다.

1. 실행 명령 조립 단계에서 evaluator environment 파일과 canonical control-home environment 파일을 혼동한 입력 binding 오류가 있었다. canonical 경로로 교정했고 `--validate-only`가 통과했다.
2. 정확한 입력으로 실제 startup을 1회 실행했으나 `initialize` 이후 `thread/start`가 `-32603`으로 차단됐다. 이는 과거와 같은 외부/실행 계약 차단의 재현 증거지만, 현재 증거만으로 하위 원인을 확정할 수 없다.

`cleanup_verified=false`와 telemetry completeness false이므로 gate를 성공으로 승격하지 않는다. 모델 명령은 실행되지 않았다.

## commit / push

이번 실행 자체는 코드 수정이 없었고, 이 로그와 pointer 문서 갱신만 저장한다. main 병합·force push·기존 증거 삭제는 하지 않는다. 문서 commit 후 feature branch에 일반 push하고 remote SHA를 확인한다.

## 미완료 사항과 다음 한 행동

- 미완료: `thread/start -32603`의 구체적 원인, 실제 startup 성공, model smoke, 행동 성능 비교.
- Docker lifecycle과 startup 오류는 하나의 성공으로 합치지 않는다.
- 같은 입력·같은 실패를 새 증거 없이 재실행하지 않는다.
- 다음 한 행동: 모델 없는 범위에서 설치 버전 `thread/start` contract와 remote executor 응답의 최소 구조를 대조하는 새로운 fixture/diagnostic을 설계한다. 추가 구독 startup 또는 모델 실행은 별도 승인 전까지 하지 않는다.
