# LOG-072 — Startup revalidation paired-cause checkpoint

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `bc0aa6f docs: record canonical remote binding verification`
- 시작 dirty 상태: 사용자 PNG 2개 untracked; 보존하고 stage하지 않음
- 작업 성격: 승인된 model-free startup diagnostic 결과 확인 및 오프라인 RPC 계약 회귀 보강
- 외부 startup/model 실행: 사용자 승인으로 startup diagnostic 정확히 1회 수행; model/turn/evaluation 없음
- OpenAI Platform API/API key: 사용하지 않음
- 기존 평가 전용 로그인 홈: `C:\Users\wotmd\.codex-feynman-eval` 보존; 내용·토큰·전체 환경변수 출력 없음

## 목적

LOG-071에서 현재 repository의 attribution proxy가 canonical remote binding에 실제로
연결된 것을 확인했다. 그 후 사용자 승인으로 `method→reason→field`가 포함된
model-free startup diagnostic을 정확히 1회 실행했다. 이번 checkpoint의 목적은
새 payload-free telemetry가 remote startup blocker를 얼마나 좁혔는지 확인하고,
그 결과를 실제 모델 평가와 분리해 기록하는 것이다.

## 실제 외부 명령과 관찰

다음 명령을 Windows PowerShell에서 실행했다. `--thread/start`까지만 허용된
startup diagnostic이며 prompt, `turn/start`, model generation, MCP candidate
evaluation을 포함하지 않는다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_subscription_startup_diagnostic --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote-environment 'C:\Users\wotmd\.codex-feynman-eval\environments.toml' --binding 'C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json' --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --telemetry 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-05-rpc.json' --output 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-05.json' --timeout-seconds 60
```

종료 코드는 `0`이었다. 안전하게 요약된 stdout은 다음과 같다.

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
request_mapping_rejection_method_reasons:
  environmentConfig/read:
    invalid-host-path: 1
  fs/getMetadata:
    container-path-outside-declared-mount: 2
    host-path-outside-declared-mount: 4
request_mapping_rejection_method_reason_fields:
  environmentConfig/read:
    invalid-host-path:
      configPaths: 1
  fs/getMetadata:
    container-path-outside-declared-mount:
      path: 2
    host-path-outside-declared-mount:
      path: 4
```

이번 결과로 처음으로 method, fixed reason, declared field를 함께 연결할 수 있게
됐다. raw request path, request id, response body는 보존하지 않았다.

## 산출물 및 안전 검증

생성 산출물:

- report: `C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-05.json`
- payload-free telemetry: `C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-05-rpc.json`

안전 후처리 명령은 report JSON만 읽고 fixed labels와 크기만 출력했다.

```powershell
@'
import json
from pathlib import Path
from jsonschema import Draft202012Validator
report = Path(r'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-05.json')
telemetry = Path(r'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-05-rpc.json')
schema = Path('evals/feynman-thinking/subscription-startup-diagnostic.schema.json')
data = json.loads(report.read_text(encoding='utf-8'))
errors = list(Draft202012Validator(json.loads(schema.read_text(encoding='utf-8'))).iter_errors(data))
print('report_schema_errors=', len(errors))
print('report_bytes=', report.stat().st_size)
print('telemetry_bytes=', telemetry.stat().st_size)
checks = data.get('checks', {})
print('checks=', {k: checks.get(k) for k in ('thread_started','error_code','error_category','initialize_completed','turn_requests_sent','model_generation_requests_sent','process_tree_reaped')})
print('privacy=', data.get('privacy'))
print('paired=', data.get('proxy_telemetry', {}).get('request_mapping_rejection_method_reasons'))
print('paired_fields=', data.get('proxy_telemetry', {}).get('request_mapping_rejection_method_reason_fields'))
'@ | & 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -
```

관찰:

```text
report_schema_errors= 0
report_bytes= 2617
telemetry_bytes= 1497
checks= {'thread_started': False, 'error_code': -32603, 'error_category': 'remote-environment-error', 'initialize_completed': True, 'turn_requests_sent': 0, 'model_generation_requests_sent': 0, 'process_tree_reaped': True}
privacy= {'request_or_response_payload_preserved': False, 'thread_id_preserved': False, 'instruction_source_paths_preserved': False, 'raw_stderr_preserved': False, 'credential_files_directly_read_by_probe': False, 'control_home_contents_serialized': False}
paired= {'environmentConfig/read': {'invalid-host-path': 1}, 'fs/getMetadata': {'container-path-outside-declared-mount': 2, 'host-path-outside-declared-mount': 4}}
paired_fields= {'environmentConfig/read': {'invalid-host-path': {'configPaths': 1}}, 'fs/getMetadata': {'container-path-outside-declared-mount': {'path': 2}, 'host-path-outside-declared-mount': {'path': 4}}}
```

Docker 잔여 feynman container는 `docker ps -a --filter name=feynman`에서 출력되지
않았다. 이 실행의 child process는 report상 reap되었다.

## 원인 분석

현재 관찰 가능한 blocker는 다음과 같다.

| method | fixed reason | field | count | 의미 |
|---|---|---:|---:|---|
| `environmentConfig/read` | `invalid-host-path` | `configPaths` | 1 | config 경로 그룹의 한 값이 mapper의 host 절대경로·traversal-free 계약을 만족하지 못해 거부됨 |
| `fs/getMetadata` | `container-path-outside-declared-mount` | `path` | 2 | 이미 container namespace로 해석된 경로가 선언된 mount 밖이라 거부됨 |
| `fs/getMetadata` | `host-path-outside-declared-mount` | `path` | 4 | host namespace로 해석된 경로가 선언된 mount 밖이라 거부됨 |

여기서 `invalid-host-path`는 매퍼의 fixed error label이며, 실제 값이 상대경로인지
다른 모호한 형식인지는 raw payload를 보존하지 않으므로 확정하지 않는다. 또한
`fs/getMetadata` 두 namespace reason은 프로토콜이 실제로 어느 namespace를 의도했는지
그 자체를 증명하지 않는다. 따라서 현 단계에서 config path를 `cwd` 기준으로
자동 보정하거나 mount 범위를 넓히는 것은 근거 없는 허용 범위 확대가 된다.

구분해야 할 상태:

- `initialize_completed=true`: Codex App Server와 protocol 초기화는 성공했다.
- `thread_started=false`, `-32603`: 원격 environment discovery 단계에서 thread가
  만들어지기 전에 차단됐다.
- `turn_requests_sent=0`, `model_generation_requests_sent=0`: 실제 모델 평가를
  시작하지 않았다.
- `process_tree_reaped=true`, Docker 잔여 없음: 로컬 child/Docker 정리는 성공했지만
  이것은 remote path compatibility 성공을 뜻하지 않는다.
- auth gate의 standalone 성공 여부와 이번 App Server remote startup 성공 여부는
  별개다. 이번 결과는 후자를 차단한 것이며 login 재수행의 근거가 아니다.

공식 App Server 문서도 `initialize`/`initialized`, `thread/start`, `turn/start`를
분리하고 remote environment instruction source path가 해당 환경의 native absolute
syntax를 사용한다고 설명하지만, 이 저장소에서 관찰된 `environmentConfig/read`
세부 field의 허용 semantics를 정의하지는 않는다. 따라서 이번 checkpoint에서는
공식 문서에 없는 semantics를 추측해 구현하지 않았다.

## 오프라인 계약 보강

실제 startup을 재실행하지 않고 다음 회귀 테스트를 추가했다.

- `configPaths`의 Windows host absolute path가 `/run/candidate`로 매핑되는지
- `requirementsPaths`의 declared container absolute path가 유지되는지
- 두 배열 필드의 relative value가 `host path must be absolute`로 fail-closed 되는지
- non-string group item이 `config path groups must contain only paths`로 거부되는지

실제 명령:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_path_proxy -v
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -v
```

결과:

- targeted RPC tests: `Ran 32 tests ... OK`
- full regression: `Ran 381 tests in 14.165s`, `OK (skipped=11)`

추가 테스트는 mapping contract와 privacy telemetry를 검증했을 뿐, 실제 remote
server가 `configPaths`를 어떤 기준으로 생성해야 하는지를 증명하지 않는다.

## 커밋·push 및 미완료

- 이 문서는 후속 docs-only 저장 커밋 `89e8e3d docs: record paired startup blocker`에
  포함됐다.
- `origin/feat/feynman-thinking-v0.5-draft`는
  `89e8e3d04cd9fd28086d68ab35ea9567223160ff`를 가리키며 push가 확인됐다.
- 이 후속 상태 보정 자체는 아직 별도 commit/push 전이다.
- user PNG 2개는 계속 untracked로 보존한다.
- main merge와 force push는 하지 않는다.
- 현재 branch의 외부 runner 성공 조건은 아직 달성되지 않았다.
- `environmentConfig/read.configPaths` 실제 원문 값과 App Server 내부 생성 규칙은
  payload 비보존 정책과 공개 schema 부재로 미확정이다.
- `fs/getMetadata.path`의 여섯 실제 경로도 같은 이유로 미확정이다.
- actual model turn, candidate tool call, baseline, frozen evaluation은 실행하지
  않았다.

## 다음 한 행동

다음 외부 실행을 자동으로 반복하지 말고, 먼저 이 오프라인 계약과 고정된 telemetry를
검토한 뒤 별도 명시 승인이 있을 때만 새 model-free startup diagnostic 1회를
검토한다. 승인 전에는 mount 확대, config response 제조, 상대경로 자동 보정,
model-turn/baseline 실행을 하지 않는다.

이 문서는 개발 인계용이며 baseline candidate나 평가 prompt로 전달하지 않는다.
