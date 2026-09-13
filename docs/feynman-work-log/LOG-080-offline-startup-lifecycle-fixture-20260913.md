# LOG-080 — 오프라인 startup lifecycle fixture와 timeout 원인 분리

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 선행 로그: [LOG-079](LOG-079-implementation-commit-push-receipt-20260913.md)

## 목적

실제 ChatGPT 구독 로그인, 보호된 `CODEX_HOME`, Docker, API key, 모델을
사용하지 않고 `initialize` → `initialized` → `thread/start` 수명주기를
재현했다. 목적은 실제 startup의 `initialize` timeout과 원격 lifecycle의
`thread/start` 오류를 같은 실패로 취급하지 않는지 검증하는 것이다.

## 구현

- `tests/feynman_subscription_lifecycle_fixture.py`
  - 고정된 JSON-RPC 응답만 내보내는 offline peer다.
  - `healthy`, `initialize-timeout`, `thread-start-error`,
    `wrong-response-id` 네 시나리오를 제공한다.
  - `turn/start`가 도착하면 오류로 답하므로 startup 진단이 model turn을
    보내지 않았는지 테스트 경계에서 확인할 수 있다.
- `tests/test_feynman_subscription_startup_diagnostic.py`
  - 실제 Python subprocess로 fixture를 시작하고 diagnostic의 JSONL reader,
    timeout, response-ID matching, payload-free thread summary를 검증한다.
  - 정상 시나리오에서 ephemeral thread와 `instructionSources`가 확인되고
    child는 stdin 종료 후 exit 0으로 정리된다.

## 실제 명령과 관찰 결과

```powershell
python -B -m unittest tests.test_feynman_subscription_startup_diagnostic -q
# Ran 17 tests in 0.307s / OK

python -B -m unittest discover -s tests -q
# Ran 403 tests in 13.361s / OK (skipped=11)

python -B -c "import json, pathlib, jsonschema; files=sorted(pathlib.Path('evals/feynman-thinking').glob('*subscription*.schema.json')); errors=[]; [jsonschema.Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; print('subscription_schema_checks=' + str(len(files)) + ' errors=0')"
# subscription_schema_checks=5 errors=0

python -B -m compileall -q tooling tests
git diff --check
# exit code 0
```

관찰한 분류는 다음과 같다.

| fixture 시나리오 | 관찰 결과 | 의미 |
|---|---|---|
| `healthy` | initialize 성공, ephemeral thread/start 성공, child exit 0 | client lifecycle 정상 |
| `initialize-timeout` | `thread-start-timeout` | initialize 응답 부재를 client timeout으로 분류 |
| `thread-start-error` | initialize는 성공, `-32603`, `remote-environment-error` | initialize timeout과 별개의 원격 lifecycle 오류 |
| `wrong-response-id` | ID 99 응답을 무시하고 ID 2를 선택 | 요청별 응답 대응을 ID로 검증 |

모든 시나리오에서 model generation과 `turn/start`는 0회다. 이 fixture의
통과는 실제 App Server나 Docker 호환성의 증거가 아니며, 실제 Windows/Docker
startup은 LOG-078/079의 `initialize` 응답 대기 timeout으로 여전히 blocked다.
따라서 같은 실제 startup을 반복하거나 Luna smoke를 시작하지 않았다.

## commit·push 및 미완료

이번 변경은 기존 feature branch에만 문서와 테스트 fixture로 기록한다. main
merge와 force push는 하지 않는다. 사용자 PNG와 보호된 ChatGPT control home은
변경하지 않는다.

다음 원인 규명은 fixture가 증명한 경계를 이용해, 실제 Codex 0.154.0의
`initialize` 단계에서 child/stdio/remote environment handoff 중 어디까지
도달했는지를 기존 payload-free telemetry로 확인하는 것이다. startup gate가
통과하기 전에는 auth 재검증, model turn, baseline/Feynman evaluation을
실행하지 않는다.
