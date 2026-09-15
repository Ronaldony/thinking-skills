# LOG-116 — Model-free remote-child differential green after Docker recovery (2026-09-16)

## 상태와 범위

- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작/종료 HEAD: `b2d52d75a202ac3e8194e765ac7c0cace7560a3f`
- 코드 변경: 없음
- actual ChatGPT subscription startup: 0회
- model smoke/fallback: 0회
- OpenAI Platform API/API key, 로그인 파일·토큰·전체 환경변수: 사용·출력하지 않음

기존 `.tmp/`, 사용자 PNG 2개, `LOG-099`, evaluator 자료와 로그인 홈은 수정·삭제·stage하지
않았다. Docker stderr 원문과 child request/response payload는 읽거나 보존하지 않았다.

## Docker readiness

사용자가 Docker Engine 정상화를 알린 뒤 명시된 empty diagnostic config로 read-only
readiness를 확인했다.

```text
29.7.2|linux|aarch64|0|14|overlayfs|Docker Desktop
```

## 입력 오류와 보정

첫 differential 호출은 disposable `-07` fixture root를 호출자가 미리 만든 상태에서
실행되어 input validation으로 중단됐다.

```text
verdict=remote-child-differential-invalid-input
failure_stage=input-validation
error_code=input-validation
report_written=false
```

이 실행은 Docker image/container/App Server를 시작하지 않았고 report도 생성하지 않았다.
코드 계약상 `--fixture-root`는 존재하지 않는 새 경로여야 하므로, 기존 evidence를 덮지
않는 새 미존재 `-08` 경로로 보정했다. 같은 실패를 그대로 반복하지 않았다.

## Model-free differential 실행

다음 명령을 새 disposable output으로 정확히 1회 실행했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_remote_child_diagnostic --docker 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --path-proxy 'C:\DevWorks\thinking-skills\tooling\feynman_rpc_path_proxy.py' --fixture-root 'C:\Users\wotmd\AppData\Local\Temp\feynman-remote-child-differential-20260915-08' --output 'C:\Users\wotmd\AppData\Local\Temp\feynman-remote-child-differential-20260915-08.json' --timeout 30
```

report:

```text
C:\Users\wotmd\AppData\Local\Temp\feynman-remote-child-differential-20260915-08.json
verdict=remote-child-differential-ready
failure_stage=null
```

검증한 payload-free 결과:

- Docker access, pinned image inspect, container create/start: 모두 passed
- 네 native mount destination 및 direct/proxy Docker args semantic equivalence: true
- direct initialize: success 1, exit 0
- proxy initialize: success 1, exit 0
- initialize result equivalence/startup equivalence: true
- proxy telemetry: available/schema-valid/complete, responses matched 1, unmatched 0,
  pending 0, mapping clean/correlated true, child exit 0
- child stderr: bytes 0, nonempty false, truncated false, read_error false, drained true
- cleanup: verified
- report JSON Schema: `remote_child_report_schema=valid`
- privacy: request/response payload, host path, raw stderr 모두 보존하지 않음;
  credential files/control home read false

## 현재 판단과 다음 경계

LOG-110에서 통과했던 model-free differential이 Docker recovery 후 새 `-08` 경로에서도
재현됐다. 따라서 Docker access/image/create/start, 네 native mount, direct/proxy child
initialize, telemetry v3 correlation과 cleanup 경계는 green으로 기록한다. 이 결과는
App Server 내부 `initialize`/`thread/start` 호환성이나 실제 subscription startup을
증명하지 않는다.

최종 regression은 코드 변경이 없으므로 직전 receipt를 따른다: `510 tests OK,
11 skipped`, ResourceWarning 없음, JSON Schema 19개 errors=0.

다음 정보는 실제 ChatGPT subscription startup에서만 얻을 수 있다. LOG-109의 1회 startup
승인은 이미 사용됐으므로, 별도 승인이 없으면 실행하지 않는다. 승인되면 정확히 1회
startup diagnostic만 수행하고, `thread/start` 오류·timeout·cleanup/telemetry 불완전·turn
또는 model request 발생 시 즉시 중단한다. 실패 후 retry/fallback/model smoke는 하지 않는다.
