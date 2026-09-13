# LOG-061 — Request-mapping method diagnostics and fs/walk contract

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 대상: model-free native Windows→Linux RPC proxy
- 선행 blocker: [LOG-060](LOG-060-luna-model-turn-request-mapping-blocker-20260913.md)
- 실제 model turn: 실행하지 않음
- OpenAI Platform API/API key: 사용하지 않음

## 목적

LOG-060의 승인된 Luna model-turn 1회는 모델 요청 전에 startup RPC 18건 중
9건이 request mapping에서 거부되어 exit 1로 종료됐다. raw request payload와
stderr는 보존하지 않았기 때문에, 이번 단계에서는 경계를 넓히거나 같은 모델
명령을 반복하지 않고 다음 두 가지만 model-free로 확인했다.

1. `fs/walk.path`가 선언된 candidate mount 내부에서 Windows native path 또는
   file URI를 Linux container path로 매핑하는지 확인한다.
2. request mapping rejection을 method별 payload-free counter로 기록해, 이후
   승인된 실행에서 `environmentConfig/read`, `fs/canonicalize`,
   `fs/getMetadata`, `fs/walk` 중 어느 method가 차단되는지 구분한다.

## 구현 변경

### 1. `fs/walk` path contract 추가

`tooling/feynman_rpc_path_mapping.py`의 field-specific request allowlist에
`fs/walk: path`를 추가했다. 임의 JSON 문자열이나 command argument를 rewrite하지
않으며, 기존 Docker declared mount 밖의 path와 traversal은 계속 fail-closed다.

### 2. method별 rejection counter 추가

`tooling/feynman_rpc_path_proxy.py`의 안전한 telemetry에
`request_mapping_rejection_methods`를 추가했다. method 이름과 고정 counter만
기록하며 path, URI, request payload, token, 환경변수 값은 기록하지 않는다.

### 3. 고정 discovery case 추가

`tooling/feynman_rpc_discovery_diagnostic.py`에 candidate mount 내부의 고정
`walk-candidate` case를 추가했다. ordinary mode에서는 mapping 전달 여부를
확인하고, guarded mode에서는 현재 bounded allowlist에 없는 method가 정책상
차단되는지 확인한다. 이 diagnostic은 `model_requests=0`이다.

## 실제 명령

먼저 관련 회귀 테스트를 실행했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_rpc_discovery_diagnostic tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_path_proxy
```

결과:

```text
Ran 26 tests in 0.013s
OK
```

그 다음 기존 Luna evaluator job/profile과 protected control home의 canonical
remote environment를 사용해, 새 output path에 model-free discovery diagnostic를
정확히 1회 실행했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_rpc_discovery_diagnostic --job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote 'C:\Users\wotmd\.codex-feynman-eval\environments.toml' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --output 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\rpc-discovery-diagnostic-20260913-fswalk.json'
```

## 관찰 결과

진단 report:

- `schema_version=1`
- `model_requests=0`
- `payloads_preserved=false`
- ordinary/guarded 모두 `initialize`는 `environmentInfo`, `sessionId`를 반환
- ordinary `walk-candidate`: `error_code=-32602`, `missing_field=options`
- guarded `walk-candidate`: `error_code=-32001`
- 양 mode의 Docker child exit code: `0`

ordinary telemetry:

```json
{
  "requests_seen": 14,
  "requests_forwarded": 13,
  "request_mapping_rejections": 1,
  "request_mapping_rejection_methods": {"environmentConfig/read": 1},
  "response_mapping_rejections": 0,
  "child_exit_code": 0
}
```

즉 ordinary `fs/walk`는 request mapping에서 거부되지 않고 remote child까지
전달됐다. remote server가 반환한 `options` 누락은 synthetic request schema의
문제이며 Windows path mapping 실패가 아니다.

guarded telemetry:

```json
{
  "requests_seen": 14,
  "requests_forwarded": 10,
  "request_mapping_rejections": 4,
  "request_mapping_rejection_methods": {
    "environmentConfig/read": 2,
    "fs/canonicalize": 1,
    "fs/walk": 1
  },
  "probe_policy_rejections": 2,
  "response_mapping_rejections": 0,
  "child_exit_code": 0
}
```

guarded `fs/walk` 거부는 candidate read 범위를 넓히지 않도록 설정한 method
allowlist의 의도된 결과다. ordinary와 guarded 모두 응답 역매핑 거부는 0건이다.

## 판단

- `fs/walk.path`를 field-specific allowlist에 추가한 변경은 candidate mount
  내부 fixed request로 확인됐다.
- guarded allowlist를 확장하지 않았으므로 읽기 경계는 그대로다.
- LOG-060의 실제 9건에 대해 이제 향후 실행에서 method별 rejection을 기록할
  수 있지만, 당시 payload-free artifact에는 새 counter가 없으므로 9건의
  개별 path와 단일 원인을 소급 확정하지 않는다.
- 이번 결과는 auth 성공, Luna entitlement, 실제 model response, candidate
  tool-use, Feynman 효과성의 증거가 아니다.
- 새 Luna/Terra/Sol model-turn, baseline, frozen evaluation은 실행하지 않았다.

## 검증 범위

현재 변경 기준 전체 회귀 테스트도 실행했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_*.py'
```

결과:

```text
Ran 364 tests in 14.468s
OK (skipped=11)
```

## 미완료와 다음 행동

미완료:

- 이전 Luna startup 9건의 개별 rejected path 확정
- 실제 Luna model response 및 candidate tool-use
- Terra/Sol 실행과 baseline 비교
- Feynman behavioral evaluation 및 held-out 판정

다음 개발 행동은 현재 변경을 commit/push하고 CI 가시성을 확인하는 것이다.
그 뒤 새 model-turn은 자동으로 실행하지 않는다. 실제 Luna 재시도나 다른 모델
실행은 이 method-level gate를 반영한 새 command를 별도로 검토하고 사용자가
명시 승인한 경우에만 진행한다. 실제 평가 시작 전에는 structural preflight와
auth gate를 다시 통과해야 하며, auth gate 성공과 Windows/Docker 실행기 호환성은
서로 다른 판정으로 기록한다.

## 저장 상태

- 이 로그 작성 시점의 구현 변경은 아직 commit 전이다.
- 사용자 제공 PNG 2개는 untracked로 보존하고 stage하지 않는다.
- main merge와 force push는 하지 않는다.
