# LOG-105 — Docker runtime 복구와 path contract 동등성 재검증

Date: 2026-09-14 KST. Repository: `Ronaldony/thinking-skills`.
Branch: `feat/feynman-thinking-v0.5-draft`.

## 이번 단계의 범위

LOG-104 이후의 다음 필요 작업으로 Docker lifecycle blocker가 실제로 회복됐는지
읽기 전용 확인하고, 회복된 경우에만 고정 offline image의 runtime 및 Windows
direct/proxy path contract를 검증했다. ChatGPT 구독 인증, startup diagnostic,
model command, Luna smoke, baseline/evaluation은 실행하지 않았다.

기존 `C:\Users\wotmd\.codex-feynman-eval`, `.tmp/`, 사용자 PNG 2개,
`LOG-099`는 보존했다. API key·Platform API·credential/token·전체 환경변수는
읽거나 출력하지 않았다. probe는 고정 image, network none, 제한된 fixture와 고유
label만 사용했다.

## Docker 상태 대조

일반 실행 환경에서 읽기 전용 상태 확인:

```powershell
docker --config C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config info --format ...
```

관찰 결과는 `docker_engine` named pipe `permission denied`였다. Docker Desktop
프로세스는 응답 중이었다.

동일한 읽기 전용 `docker info`를 권한 상승 환경에서 1회 확인했다.

```text
29.7.2|linux|aarch64|0|14|overlayfs|Docker Desktop
```

따라서 일반 sandbox의 named-pipe 접근 오류와 Docker Desktop 자체 장애를
구분했다. 이어 고정 image metadata도 1회 확인했다.

```text
sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6|linux|arm64|["docker-entrypoint.sh"]|["node"]
```

## runtime probe 결함 재현과 수정

첫 runtime probe 실행은 다음의 generic 실패였다.

```text
error: Docker runtime probe failed
```

출력 파일도 남지 않아 timeout/OSError와 Docker stage failure를 구분할 수
없었다. 이는 Docker lifecycle 결과가 아니라 probe의 예외·증거 보존 결함이었다.

최소 수정:

- stage 예외를 `docker-cli-timeout`, `docker-access-denied` 등 고정된 비민감
  `error_code`로 보존한다.
- stage와 cleanup 결과를 JSON report에 기록하고, 원문 예외·stderr는 저장하지
  않는다.
- timeout 후 kill/wait가 계속 실패해도 또 다른 예외로 탈출하지 않고
  `cli_stop_verified=false`로 불완전 상태를 반환한다.
- CLI 최종 예외도 `failure_stage`와 안전한 JSON stdout으로 반환한다.
- stage 실패 뒤 probe가 소유한 이름/label만 bounded inspect/remove한다.

합성 회귀:

```text
python -B -W error::ResourceWarning -m unittest tests.test_feynman_docker_runtime_probe -v
Ran 16 tests
OK
```

timeout 예외 report 보존, un-reaped CLI 비성공 판정, 원문 오류 비출력 경계를
확인했다.

## runtime probe 수정 후 실제 결과

수정 후 고정 image runtime probe를 새 output으로 1회 실행했다.

```powershell
python -B -m tooling.feynman_docker_runtime_probe --docker ... --docker-config ... --image sha256:36b6f50b... --output C:\DevWorks\thinking-skills\.tmp\feynman-docker-runtime-probe-20260914-v3.json --timeout 30
```

결과:

```json
{"verdict":"docker-runtime-ready","failure_stage":null,"stage_count":4}
```

각 stage 결과:

- `container-create`: CLI 0, `created`, exit 0, cleanup deferred
- `container-start`: CLI 0, marker 관찰, exit 0, cleanup verified
- `default-node-version`: CLI 0, Node version 관찰, exit 0, cleanup verified
- `exec-server-initialize`: CLI 0, initialize response 관찰, exit 0, cleanup verified

모든 stage의 stdout/stderr drain이 완료됐고 timeout, write error, OOM,
sandboxDenied는 없었다. 따라서 Docker create/start/run과 exec-server initialize
process lifecycle은 현재 권한 상승 실행 경계에서 회복된 것으로 판정한다.

## path contract 재현과 수정

Docker runtime이 회복된 뒤 Windows proxy/direct path probe를 실행했다.

1. 첫 실행은 direct/proxy process exit 0이었으나 request/response shape가
   false였다. response digest는 같았고 mismatch ID는 initialize ID 1 하나였다.
2. role count 진단을 추가해 ID 1의 `outside-declared-mount` 4개를 확인했다.
   request mismatch는 `/usr/local/bin:/usr/bin:/bin` PATH 문자열을 단일 경로로
   오인한 결과였다.
3. PATH 오인을 막고 fixture Docker command에 `--workdir /run/candidate`를
   명시했지만 initialize에 system path 3개가 남았다.
4. 구조 위치 요약으로 실제 필드를 확정했다:
   `result.environmentInfo.shell.path`, `tempDir`,
   `temporaryDirectories[0]`. 모두 고정 실행환경 경로였고 direct/proxy 값은
   동일했다.
5. 임의 외부 path는 계속 comparable하지 않게 두고, 위의 정확한 구조 위치만
   `system/shell` 또는 `system/temp`로 분류했다. raw path와 payload는 report에
   기록하지 않았다.

path comparator 회귀:

```text
python -B -W error::ResourceWarning -m unittest tests.test_feynman_rpc_compatibility -q
Ran 32 tests
OK
```

수정 후 고정 fixture path probe를 새 output으로 1회 실행했다.

```text
rpc-path-contract-equivalent
direct_exit_code: 0
proxy_exit_code: 0
request_shapes_match: true
response_shapes_match: true
response_namespace_shapes_match: true
response_shape_matches_by_id: 1..7 all true
direct/proxy process_exit_codes: 0
direct/proxy sandbox_denied: False
direct/proxy stderr_drained: true
```

보고서는
`.tmp/feynman-path-contract-20260914-v6.json`에 보존했다. 이는 Windows
proxy와 Linux direct fixture의 path 의미 동등성 증거이며, 실제 구독 startup
호환성이나 model 실행 성공을 뜻하지 않는다.

## 최종 코드 검증

```text
python -B -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -q
Ran 486 tests in 16.009s
OK (skipped=11)

schema_files=17 errors=0
py_compile=ok
git diff --check=0
```

Git 전역 ignore 파일 접근 warning은 `C:\Users\wotmd/.config/git/ignore`
permission denied였으며, 테스트 실패나 ResourceWarning은 아니었다.

## 실행 횟수와 남은 경계

- 일반 sandbox `docker info`: 1회, named-pipe permission denied
- 권한 상승 `docker info`: 1회, 성공
- 권한 상승 image inspect: 1회, 성공
- runtime probe: generic failure 1회, 수정 후 ready 1회
- path probe: 수정 전/진단용 blocked output v2~v5 4회, 최종 v6 equivalent 1회
- 실제 Docker lifecycle 최종 상태: runtime ready, path contract equivalent
- 실제 ChatGPT 구독 auth/startup: 0회
- 실제 model/turn/smoke/evaluation: 0회

Docker와 path contract의 offline 관문은 통과했지만, 과거 `thread/start -32603`
외부 계약 문제는 독립적으로 미확정이다. 구독 startup은 최신 사용자 승인과
최종 startup gate 선행 조건을 확인한 뒤 별도 1회로 판단하며, 이번 단계에서는
실행하지 않았다. Terra/Sol fallback, baseline, EVAL-01/02도 실행하지 않았다.

## commit/push 상태

이 로그 작성 시점에는 runtime/path probe 코드와 회귀 테스트가 working tree에
있으며 아직 commit/push하지 않았다. 다음 단계는 이 변경과 본 로그를 명시적으로
stage해 feature branch에 일반 commit/push하고, 별도 receipt에 SHA를 기록하는
것이다. `.tmp/`, PNG 2개, `LOG-099`는 stage 대상이 아니다.
