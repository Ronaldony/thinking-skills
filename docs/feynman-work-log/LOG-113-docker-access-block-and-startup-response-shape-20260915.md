# LOG-113 — Docker access block and startup response shape hardening (2026-09-15)

## 상태와 범위

- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 구현 commit: `bb2d618` (`fix: validate startup response envelope`)
- actual ChatGPT subscription startup: 0회
- model smoke/fallback: 0회
- OpenAI Platform API/API key와 로그인 파일·토큰·전체 환경변수: 사용·출력하지 않음

기존 `.tmp/`, 사용자 PNG 2개, `LOG-099`, evaluator 자료와 로그인 홈은 수정·삭제·stage하지
않았다. 새 differential report는 기존 증거와 분리된 Temp 경로에만 생성했다.

## Model-free Docker differential 재검증 결과

LOG-112의 proxy 변경을 실제 Docker direct/proxy 경계에서 재검증하기 위해 다음 새 경로로
정확히 1회 실행했다.

```text
C:\Users\wotmd\AppData\Local\Temp\feynman-remote-child-differential-20260915-05
C:\Users\wotmd\AppData\Local\Temp\feynman-remote-child-differential-20260915-05.json
```

결과:

```text
verdict=remote-child-differential-blocked
failure_stage=docker-access
docker-access process_started=true exit_code=1 timed_out=false
stdout_bytes=1 stderr_bytes=202 stderr_drained=true stderr_read_error=false
image-inspect/container-create/container-start/direct/proxy=not-run
```

`docker.exe`와 명시된 empty Docker config 경로는 존재했지만, read-only backend process
check에서 `docker`/`com.docker.backend` 프로세스가 관찰되지 않았다. Docker stderr 원문은
privacy 경계상 읽거나 기록하지 않았다. report는 payload/path/credential-free이며 proxy
telemetry sidecar는 lifecycle 진입 전이라 생성되지 않았다.

이 결과는 LOG-110의 성공을 반증하지 않으며, 이번 변경의 Docker 통합 검증은 외부 Docker
backend가 다시 가용해질 때까지 미완료다. 같은 `docker-access` 입력을 새 상태 변화 없이
재시도하지 않는다. Docker Desktop을 자동 시작·종료하거나 broad cleanup하지 않았다.

## 재현과 최소 수정: App Server `thread/start` 성공 envelope

Codex 0.154.0 static App Server schema의 `ThreadStartResponse` required top-level fields는
`approvalPolicy`, `approvalsReviewer`, `cwd`, `model`, `modelProvider`, `sandbox`,
`thread`다. 기존 `_thread_summary`는 thread id/ephemeral과 instruction source만 검사해
나머지 필드가 없는 synthetic success response를 green으로 허용했다.

먼저 누락 response fixture에 `thread-start-response-shape` 예외를 기대하는 테스트를
추가했고, 수정 전에는 `StartupDiagnosticError`가 발생하지 않아 실패했다.

최소 수정:

- `tooling/feynman_subscription_startup_diagnostic.py`
  - required top-level field 집합과 안전한 scalar/container shape를 fail-closed로 확인한다.
  - 응답의 cwd/model/provider/sandbox/policy 값은 summary나 artifact에 보존하지 않는다.
  - 기존 error classification, ephemeral 판정, instruction-source allowlist는 유지한다.
- offline lifecycle fixture와 smoke/startup synthetic App Server process에 schema-complete
  최소 응답을 넣었다.
- 누락 envelope 회귀 테스트를 추가했다.

## 검증 영수증

- 수정 전 재현: incomplete success response 테스트 실패
- targeted startup/smoke/proxy/remote differential: `109 tests OK`
- 전체 회귀: `508 tests OK (skipped=11)`
- `ResourceWarning`: 없음 (`-W error::ResourceWarning`)
- JSON Schema: `19 files, errors=0`
- 변경 Python files `py_compile`: 통과
- `git diff --check`: 통과

## 다음 경계

Docker backend가 복구되면 새 disposable output으로 model-free remote-child differential을
1회 재실행해 `child_stderr_drained=true`, `child_stderr_read_error=false`, direct/proxy
initialize, cleanup과 새 telemetry shape를 확인한다. Docker access가 다시 실패하면
image/container/App Server 단계로 진행하지 않고 그 결과만 기록한다.

그 다음에도 LOG-109의 실제 `initialize` 성공 후 `thread/start -32603 /
remote-environment-error` 원인은 미확정이다. 실제 subscription startup은 별도 승인 전에는
실행하지 않으며, 승인되더라도 정확한 명령·예상 결과·중단 조건을 먼저 제시하고 startup
실패 시 model/fallback/retry 없이 멈춘다.
