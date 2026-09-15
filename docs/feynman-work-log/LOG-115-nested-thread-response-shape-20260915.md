# LOG-115 — Nested `thread/start` response shape hardening (2026-09-15)

## 상태와 범위

- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `6ce750c50e309dee4b47ecae0ba94aabf53b7e8c`
- 구현 commits: `eb96b30` (`fix: validate nested startup thread shape`),
  `dbce0c7` (`fix: align startup thread fields with schema`)
- actual ChatGPT subscription startup: 0회
- model smoke/fallback: 0회
- OpenAI Platform API/API key, 로그인 파일·토큰·전체 환경변수: 사용·출력하지 않음

기존 `.tmp/`, 사용자 PNG 2개, `LOG-099`, evaluator 자료와 로그인 홈은 수정·삭제·stage하지
않았다. Docker 원문 stderr와 App Server payload 원문도 새 artifact로 보존하지 않았다.

## 재현

Codex 0.154.0 static App Server schema의 `ThreadStartResponse.thread` required fields를
확인했다. nested required 집합은 다음 13개다.

```text
cliVersion, createdAt, cwd, ephemeral, id, modelProvider, preview,
projectId, sessionId, source, status, turns, updatedAt
```

기존 `_thread_summary`는 nested `thread.id`와 `thread.ephemeral`만 확인했다. top-level
성공 envelope는 완전하지만 nested object가 `id`와 `ephemeral`만 가진 synthetic response를
거부해야 한다는 회귀 테스트를 먼저 추가했다.

수정 전 재현 결과:

```text
python -m unittest tests.test_feynman_subscription_startup_diagnostic.SubscriptionStartupDiagnosticTests.test_thread_summary_rejects_incomplete_thread_object
FAIL: StartupDiagnosticError not raised
```

이는 설치된 schema의 required nested shape와 diagnostic의 green 판정 경계가 달랐다는
직접 증거다. 실제 subscription startup이나 model 호출로 재현하지 않았다.

이후 required field의 schema 타입을 다시 대조한 결과 `createdAt`/`updatedAt`는 integer,
`preview`는 string, `source`는 string 또는 object, `status`는 `type`을 가진 object였다.
첫 최소 fixture가 이 계약을 따르지 않는 것도 외부 실행 전에 발견했다. 잘못된 타입을
거부하는 회귀를 추가하고 fixture와 validator를 schema에 맞게 보정했다.

## 최소 수정

`tooling/feynman_subscription_startup_diagnostic.py`의 `_thread_summary`에 nested required
field 집합과 제한된 타입 검사를 추가했다.

- required key가 모두 있는지 fail-closed로 확인한다.
- schema의 scalar/container 계약에 맞춰 timestamp integer, preview string, boolean,
  source/status object shape, nullable project id, turns 배열을 확인한다.
- thread id와 ephemeral 판정, instruction source allowlist의 기존 순서는 유지한다.
- thread id, cwd, model/provider, source path 등 응답 값은 summary/artifact에 보존하지
  않는다.
- offline lifecycle fixture와 startup/smoke synthetic App Server response를 schema-complete
  최소 shape로 갱신했다.

## 검증 영수증

- nested incomplete response 회귀: 수정 전 실패, 수정 후 통과
- nested wrong-type response 회귀: 수정 후 통과
- targeted startup/smoke/proxy/remote differential: `111 tests OK`
- 전체 회귀: `510 tests OK (skipped=11)`
- `ResourceWarning`: 없음 (`python -W error::ResourceWarning -m unittest discover -s tests -p "test_*.py"`)
- JSON Schema: `schema_files=19 errors=0`
- 변경 Python files `py_compile`: 통과
- `git diff --check`: 통과
- 코드 commits: `eb96b30`, `dbce0c7`

## Docker 및 외부 경계

사용자 복구 보고 후 수행한 마지막 model-free Docker differential `-06`은 backend process가
보였음에도 empty/default config의 bounded `docker info`와 `docker version`이 모두 exit 1로
끝났고 `docker-access`에서 중단됐다. image inspect, create/start, direct/proxy initialize,
telemetry와 cleanup은 그 실행에서 재평가하지 않았다. 같은 상태의 differential은 반복하지
않았다.

LOG-109의 실제 ChatGPT startup은 이미 1회 수행됐으며 `initialize` 후
`thread/start -32603 / remote-environment-error`로 실패했다. 새 증거 없이 반복하지 않는다.
actual subscription startup/model smoke는 이번 단계에도 0회이며, 별도 승인이 없으면
실행하지 않는다.

## 다음 한 행동과 사람 개입 지점

새 외부 상태 변화로 `docker info --format '{{.ServerVersion}}'`가 먼저 성공하면 새 disposable
경로에서 model-free remote-child differential을 정확히 1회 실행한다. 다시
`docker-access`로 막히면 Docker Engine readiness 복구가 사람 개입 지점이다.

Docker differential이 녹색이어도 LOG-109의 실제 `thread/start` 원인 확인에는 보호된
ChatGPT subscription startup이 필요하다. 그 지점에서는 정확한 명령, 예상 verdict, 1회
실행 예산과 중단 조건을 먼저 제시하고 별도 승인을 기다린다. startup 실패 시 model,
fallback, 자동 retry는 하지 않는다.
