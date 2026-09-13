# LOG-082 — 진단기 증거 공백 보강과 최종 startup evidence 정리

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 선행 로그: [LOG-081](LOG-081-diagnostic-fixes-and-proxy-lifecycle-20260913.md)

## 이번 재검토에서 확인한 원인

직전 결과의 핵심 오류는 `thread/start` 실패 자체와 진단기의 성공 판정을
분리하지 않은 데 있었다. 실제 마지막 startup report에서는 `initialize` 이후
`thread/start`가 `-32603 remote-environment-error`를 반환했지만, proxy가 child
종료 코드를 기록하기 전에 종료되어 raw telemetry의 `child_exit_code`가
`null`이었다. 그런데 기존 readiness 조건은 이 partial telemetry를 완료된
증거처럼 표시했다. 이 때문에 원격 환경 실패와 계측 완료를 한 번에 확정한
것처럼 보이는 잘못된 결과가 생성됐다.

## 구현한 보정

- proxy stderr는 저장 샘플을 최대 256KiB로 제한하되 EOF까지 계속 읽어 pipe
  backpressure를 방지한다.
- notification은 ID 응답과 별도로 집계하고, malformed response·unmatched
  response·pending request를 구분한다.
- telemetry의 중첩 method/reason/field key도 고정 allowlist로 검증한다.
- telemetry snapshot을 child launch 전과 주요 이벤트마다 저장해 App Server가
  proxy를 조기에 종료해도 partial evidence를 보존한다.
- telemetry readiness는 `child_exit_code`가 실제 정수로 기록된 경우에만
  complete로 판정한다. `null`은 schema상 허용되는 미완료 보고서이지만 startup
  통과 증거로는 사용할 수 없다.
- initialize와 thread/start는 하나의 startup deadline을 공유하고, 실패 단계와
  initialize 완료 여부를 artifact에 보존한다.
- smoke 결과는 startup report의 `checks` 아래에 있는
  `model_generation_requests_sent`를 안전하게 읽는다.
- proxy의 정상 parent stdin 수명을 30초 join으로 잘라내지 않고, EOF/worker
  종료 이후에만 bounded cleanup을 수행한다.

## 실제 명령과 관찰 결과

```powershell
python -B -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_subscription_smoke_exec -q
# Ran 62 tests / OK

python -B -W error::ResourceWarning -m unittest tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_rpc_path_proxy tests.test_feynman_subscription_smoke_exec -q
# Ran 62 tests / OK

python -B -m unittest discover -s tests -q
# Ran 411 tests / OK (skipped=11)

python -B -c "import json, pathlib, jsonschema; files=sorted(pathlib.Path('evals/feynman-thinking').glob('*subscription*.schema.json')); [jsonschema.Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; print('subscription_schema_checks=' + str(len(files)) + ' errors=0')"
# subscription_schema_checks=5 errors=0

python -B -m compileall -q tooling tests
git diff --check
# exit code 0; Git only reported expected LF→CRLF working-copy warnings
```

직전 수정 후 허용된 마지막 model-free startup 1회는 다음 명령으로 수행했다.
이것은 인증 재검사나 모델 평가가 아니며, 같은 실행을 반복하지 않았다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_subscription_startup_diagnostic --checkpoint 'C:\DevWorks\thinking-skills\.tmp\feynman-subscription-checkpoint-20260913-final.json' --timeout-seconds 60
```

안전한 표준 출력 결과:

```json
{
  "verdict": "subscription-startup-thread-blocked",
  "thread_started": false,
  "error_code": -32603,
  "error_category": "remote-environment-error",
  "turn_requests_sent": 0,
  "model_generation_requests_sent": 0,
  "proxy_telemetry_status": "available"
}
```

payload-free artifact와 telemetry의 핵심 관찰값은 다음과 같다.

- `initialize_completed=true`
- `thread/start`가 `-32603 remote-environment-error`로 실패
- proxy request 6건 중 6건 forward
- response 5건 중 5건 ID matched
- request/response mapping rejection 0
- write failure 0, unmatched 0, pending 0, malformed 0
- `child_exit_code=null`, 따라서 이 raw telemetry는 최종 complete 증거가 아님
- process tree reap은 성공
- turn/model-generation request 0회

이 결과로 이번 입력에서는 native Windows path mapping이 실패 원인이 아님을
확인했다. `initialize`까지의 전달 계층은 정상이며, 남은 실행 차단점은
App Server와 remote exec-server 사이의 environment lifecycle 처리다. 다만
child exit가 기록되지 않은 telemetry는 완전한 lifecycle 증거가 아니므로, 이를
성공으로 승격하지 않도록 코드와 테스트를 보정했다. 보고서의 `available`은
파일이 존재한다는 뜻이고 `complete`와 동일하지 않다.

## 검증 범위와 미완료 사항

오프라인 lifecycle fixture, proxy subprocess, 진단기·smoke 회귀, ResourceWarning
검사, schema, compileall을 검증했다. 전체 suite의 `11 skipped`는 Windows/Docker
전체 호환성 통과로 해석하지 않는다. 실제 startup은 위의 1회만 수행했으며,
추가 startup·auth 재검증·Luna model-turn·Terra/Sol fallback·baseline·Feynman
평가는 실행하지 않았다. 따라서 Feynman skill 성능 결과가 아니라 실행 호환성
차단 증거만 남아 있다.

다음 작업은 모델을 바꾸거나 자동 반복하는 것이 아니라, 설치된 Codex 0.154.0의
remote environment lifecycle 계약을 오프라인/static 자료와 fixture로 더 좁히는
것이다. 새 startup probe 또는 모델 실행은 새 코드 변경과 명확한 새 증거가 있을
때 별도로 승인해야 한다.

OpenAI Platform API/API key, 로그인 파일·토큰·전체 환경변수는 사용하거나
저장하지 않았다. 기존 평가 전용 ChatGPT control home과 사용자 PNG 2개는
보존했다. 임시 checkpoint/report/telemetry는 검증 후 제거 대상이며, candidate에
개발 대화나 인계 문서를 전달하지 않았다.

## 커밋·push 상태

이 로그와 보정 코드는 현재 작업 묶음으로 커밋·push할 예정이다. 실제 commit
hash와 원격 일치 여부는 push receipt에서 확정한다.
