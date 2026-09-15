# LOG-112 — remote proxy child-stderr bounded counters (2026-09-15)

## 상태와 범위

- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- base: `872da3b58fba06f362109f61274d2c4adcc31a6f`
- 구현 commit: `13b02cfd2e260363fc48651a30e60d6c19013d56`
- 범위: Windows 순수 코드·fixture 회귀와 기존 artifact/schema 검증만 수행했다.
- OpenAI Platform API/API key, 로그인 파일·토큰·전체 환경변수는 사용·출력하지 않았다.
- 실제 ChatGPT subscription startup과 model smoke는 이번 단계에 0회다.

`.tmp/`, 사용자 PNG 2개, `LOG-099`, evaluator 자료와 기존 로그인 홈은 수정·삭제·stage하지
않았다. 개발 대화와 인계 문서를 candidate/instruction source로 전달하지 않았다.

## 재현

LOG-111에서 production RPC proxy가 child stderr를 `DEVNULL`로 버려 실제 startup 하위
원인 분류에 관찰 공백이 남아 있었다. 먼저 proxy fixture에 큰 synthetic stderr를 쓰는
실패 테스트를 추가했다. 수정 전에는 telemetry에 child-stderr evidence가 없어
`KeyError: child_stderr_bytes`가 발생했다. 이 fixture는 Docker, Codex App Server,
구독 인증 또는 모델을 호출하지 않는다.

## 최소 수정

- `tooling/feynman_rpc_path_proxy.py`
  - child stderr를 `PIPE`로 받고 daemon drain worker가 EOF까지 소비하도록 했다.
  - 원문·sample·path는 보존하지 않고 `child_stderr_bytes`, `nonempty`, `truncated`,
    `read_error`, `drained`의 고정 scalar만 telemetry에 기록한다.
  - cleanup deadline 안에서 drain worker를 join하고, 남으면 stream을 닫은 뒤 다시 join한다.
  - synthetic/legacy v3 snapshot은 기존 필드 shape으로 계속 읽을 수 있게 했다.
- `tooling/feynman_subscription_startup_diagnostic.py`와
  `tooling/feynman_subscription_smoke_exec.py`
  - optional child-stderr field의 전체 집합과 scalar shape만 허용한다.
  - 새 shape는 `drained=true`, `read_error=false`일 때만 startup gate evidence로
    승격한다. 기존 legacy v3 shape은 backward-compatible하게 허용한다.
- `tooling/feynman_remote_child_diagnostic.py`
  - differential report에 bounded child-stderr counters를 노출하고 proxy visibility를
    `proxy-child-stderr-bounded-counters`로 구분한다.
- 두 JSON Schema에 새 optional fields와 새 visibility enum을 추가했다. 기존 required
  fields는 바꾸지 않아 보존된 이전 report도 계속 검증 가능하다.
- child stderr 원문은 telemetry/report에 저장하지 않으며 기존 privacy flag
  `raw_stderr_preserved=false` 의미를 유지한다.

## 검증 영수증

- targeted regression: `108 tests`, `OK`
- full regression: `507 tests`, `OK (skipped=11)`
- `ResourceWarning`: 없음 (`python -W error::ResourceWarning ...`)
- JSON Schema: `19 files, errors=0`
- 보존된 startup report instance:
  - `startup-diagnostic-20260913-v3.json`: `errors=0`
  - `startup-diagnostic-20260914-v4.json`: `errors=0`
- 변경 Python files `py_compile`: 통과
- staged/working diff `--check`: 통과
- 새 stderr privacy fixture: 원문 marker가 telemetry에 없고 bytes/nonempty/drained
  counters만 기록됨

## 남은 경계

LOG-109의 실제 subscription startup 1회는 여전히 `initialize` 성공 뒤
`thread/start -32603 / remote-environment-error`로 종료된 유일한 실제 증거다. 이번
수정은 production proxy가 child stderr를 버리지 않도록 했지만, App Server 내부
remote-environment envelope와 `thread/start` 원인을 확정하지는 않는다. 새 증거 없는
동일 startup 재실행은 하지 않았다.

실제 subscription startup 또는 model smoke가 필요해지는 순간에는 별도 승인 후 정확한
명령·예상 결과·중단 조건을 먼저 제시하고, startup이 실패하면 model/fallback 없이
그 지점에서 멈춘다. 현재는 그 경계에 도달하지 않았으므로 실행하지 않는다.
