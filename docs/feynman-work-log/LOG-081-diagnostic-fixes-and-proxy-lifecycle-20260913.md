# LOG-081 — 진단기 결함 수정과 proxy lifecycle 재검증

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 선행 로그: [LOG-080](LOG-080-offline-startup-lifecycle-fixture-20260913.md)

## 재검토에서 확인한 문제

LOG-080의 fixture 자체는 통과했지만, production 경로를 다시 검사하면서
다음 결함을 확인했다.

- stderr 저장 한도에 도달하면 child stderr를 더 읽지 않아 pipe backpressure가
  startup timeout을 만들 수 있었다.
- proxy telemetry의 `responses_seen`에 notification이 포함되는데도 모든
  응답을 ID 응답으로 계산해 정상 notification을 실패로 판정했다.
- smoke 결과 생성부가 startup 보고서의 `checks` 아래 값을 최상위에서 읽어
  성공 경로에 `KeyError`가 날 수 있었다.
- telemetry 중첩 method/reason/field key가 문자열 형태만 맞으면 통과했다.
- initialize와 thread/start가 별도 timeout을 사용하고, 실패 artifact가
  initialize 완료 여부를 보존하지 못했다.
- proxy가 정상 parent stdin 수명보다 짧은 30초 join 제한으로 동작해 정상적인
  child response drain을 중단할 수 있었다.

## 수정 내용

- startup/control-plane stderr reader는 최대 256KiB만 메모리에 보관하면서 EOF까지
  계속 소비한다. 원문 stderr는 보고서에 저장하지 않는다.
- telemetry readiness는 notification과 malformed response를 분리하고, 실제
  응답 ID에 대해서만 matched/unmatched를 계산한다. 중첩 telemetry key는 고정
  allowlist로 검사하며 JSON schema에도 같은 제한을 반영했다.
- smoke 결과는 full startup report와 no-full-runner sentinel 양쪽의 공통
  `model_generation_requests_sent` 위치를 안전하게 읽는다.
- startup protocol phase는 하나의 deadline을 공유하고, initialize timeout과
  thread/start timeout을 `initialize-timeout`과 `thread-start-timeout`으로
  구분한다. 종료 정리는 정확한 child tree에 대해 최대 15초로 제한한다.
- proxy는 parent stdin이 살아 있는 동안 유지하고, parent EOF 또는 child worker
  종료 뒤에만 bounded cleanup을 수행한다.

## 실행 명령과 관찰 결과

```powershell
python -B -m unittest tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_subscription_smoke_exec tests.test_feynman_rpc_path_proxy -q
# Ran 61 tests in 1.463s / OK

python -B -W error::ResourceWarning -m unittest tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_rpc_path_proxy tests.test_feynman_subscription_smoke_exec -q
# Ran 61 tests / OK

python -B -m unittest discover -s tests -q
# Ran 410 tests in 13.974s / OK (skipped=11)

python -B -c "import json, pathlib, jsonschema; files=sorted(pathlib.Path('evals/feynman-thinking').glob('*subscription*.schema.json')); [jsonschema.Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; print('subscription_schema_checks=' + str(len(files)) + ' errors=0')"
# subscription_schema_checks=5 errors=0

python -B -m compileall -q tooling tests
git diff --check
# exit code 0
```

별도 proxy subprocess 검증에서는 offline child가 parent EOF 뒤 정상 종료했고,
proxy는 response ID `[1, 2]`, `requests_seen=3`, `requests_forwarded=3`,
`responses_seen=2`, `responses_matched=2`, `responses_unmatched=0`,
`pending_request_ids=0`, `child_exit_code=0`을 기록했다. notification을 포함한
정상 telemetry도 readiness를 통과했고, 임의 중첩 key는 고정 오류로 거부됐다.
synthetic blocked report도 schema 검증에 통과했다.

## 범위와 미완료

이번 변경은 오프라인 코드·subprocess fixture 검증만 수행했다. 실제 Codex
0.154.0 startup은 재실행하지 않았고, auth gate·Luna model turn·baseline·Feynman
evaluation도 실행하지 않았다. 기존 실제 실패는 `initialize` 응답 대기 timeout으로
남아 있으며, 이번 수정은 원인을 확정하는 증거가 아니라 진단기가 그 단계를 정확히
기록하도록 만든 것이다. `11 skipped`는 Windows/Docker 전체 호환성 통과로 해석하지
않는다.

OpenAI Platform API/API key, 로그인 파일·토큰·전체 환경변수는 사용하거나 저장하지
않았다. 기존 control home과 사용자 PNG 2개는 보존했다.
