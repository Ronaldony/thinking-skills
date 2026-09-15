# LOG-110 — model-free remote child direct/proxy 차등 검증

## 상태

- 작업 ID: `NEXT-05 / model-free-remote-child-differential`
- 시각: 2026-09-15 KST
- 저장소/브랜치: `Ronaldony/thinking-skills` / `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `c7a0820b594bcb8820636319c6cc04a20c0c1788`
- 기존 dirty 상태: `.tmp/`, 사용자 PNG 2개, `LOG-099` untracked. 모두 보존했다.
- 적용 가능한 `AGENTS.md`: 없음
- 최종 상태: `DONE (model-free evidence ready; subscription startup remains blocked)`

이번 단계의 목적은 실제 ChatGPT 구독 startup을 반복하는 것이 아니라,
canonical Docker remote child가 Windows path proxy를 거칠 때의 lifecycle을
direct와 비교하는 것이다. Codex App Server, 구독 인증, 모델, candidate 평가,
control login home은 사용하지 않았다.

## 안전 경계

- OpenAI Platform API/API key 인증을 사용하지 않았다.
- 기존 `CODEX_HOME`/구독 로그인 파일·토큰·쿠키 및 그 내용은 읽지 않았다.
- 별도의 비어 있는 disposable Docker config만 사용했다.
- child stdout/stderr와 JSON-RPC payload는 bounded in-memory sample로만
  분류하고 report에는 fixed counter/boolean만 저장했다.
- 전체 환경변수, host path, credentials, thread ID, instruction source는
  출력·저장하지 않았다. candidate/evaluator/control-home mount도 확대하지
  않았다.
- 실제 구독 startup/model turn/smoke/baseline/EVAL-01/02는 0회다.

## 현재 상태 및 contract 대조

실행한 명령:

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
git log -5 --oneline --decorate
rg --files -g AGENTS.md
```

관찰:

- branch/HEAD는 위 상태와 일치했고 tracked 변경은 없었다. 새 파일과 이 로그만
  작업 대상으로 추가했다.
- `AGENTS.md`는 발견되지 않았다.
- `feynman_remote_exec_environment.expected_docker_args()`를 직접 사용해
  현재 generator contract를 재사용했다.
- pinned image는
  `sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6`다.
- 네 mount destination은 `/run/candidate`, `/run/home`, `/run/codex`,
  `/run/temp`; network는 `none`; rootfs는 read-only; user는 `1000:1000`;
  writable tmpfs는 `/tmp`다.
- 기존 production proxy는 child stderr를 `subprocess.DEVNULL`로 버린다. 새
  fixture direct 경로는 bounded drain을 하고, proxy 경로는 이 visibility
  제한을 `proxy-child-stderr-discarded-by-current-proxy`로 report한다.

## 구현

추가 파일:

- `tooling/feynman_remote_child_diagnostic.py`
  - Docker access/image identity를 먼저 확인한다.
  - unique name preflight 후 exact `container create → start`와 marker/cleanup을
    확인한다.
  - 같은 canonical generator argv를 direct Docker와 path proxy에 전달한다.
  - 설치 버전에서 확인된 remote exec-server
    `initialize.params.clientName` 계약만 1회 보내고, response ID 1,
    result/error code, malformed/non-JSON, unexpected ID를 fixed counter로
    분류한다. App Server `clientInfo`/`thread/start`는 흉내 내지 않는다.
  - stdout/stderr를 계속 drain하고 timeout/kill/wait를 bounded하게 처리한다.
  - proxy telemetry는 기존 v3 validator와 `_proxy_telemetry_ready()`로
    재검증한다.
  - 새 fixture root와 빈 Docker config만 사용하고 report는 mount 밖의 새 파일로
    제한한다.

- `evals/feynman-thinking/remote-child-differential.schema.json`
  - model-free report v1의 fixed stage, comparison, telemetry, privacy contract.

- `tests/test_feynman_remote_child_diagnostic.py`
  - JSON-RPC contract, duplicate/error, bounded drain/stderr flood, v3 telemetry
    validation, canonical mount/name, input fail-closed, lifecycle skip,
    schema regression.

## 결함 재현과 최소 수정

### 1) name preflight 관찰 결함

첫 fixture 호출 결과는 `container-create`, `name_available=false`였다. 이는
container 존재와 `ps` 조회 실패를 구분하지 못하는 새 진단기의 결함이었다.
독립적인 한정 확인 결과는 다음과 같았다.

```text
docker ps -a (empty config): exit=0;items=0;text_chars=0;elapsed_ms=99
diagnostic _container_absent(...): True
```

수정:

- `container_presence()`를 `available / occupied / unavailable`로 분리했다.
- Docker access/image inspect 실패 시 후속 create/run을 호출하지 않게 했다.
- 모든 Docker subprocess에 disposable config 기반 safe environment를 전달했다.

### 2) generator 이름과 cleanup 이름 불일치

두 번째 fixture 호출에서 access/image는 성공했고 create process도 exit 0,
stdout 65 bytes였지만 inspect/cleanup은 unavailable/absent였다. 고정 관찰은
다음과 같다.

```text
access=True; image=True; name_available=True; name_check=available;
create_process_started=True; create_exit=0; create_cleanup=absent
```

원인은 generator가 run-id `remote-child-...`에서 실제 Docker 이름
`feynman-tool-remote-child-...`를 만드는데 diagnostic이 원래 run-id로
inspect/remove한 것이었다.

수정:

- canonical argv의 `--name` 다음 값을 읽는 `_name_from_args()`를 추가했다.
- preflight/inspect/start/cleanup에 generator가 실제로 만든 이름만 사용했다.

stale 정리 전에는 생성 도구 prefix를 read-only로 확인했다.

```text
matched=1;valid_owned_prefix=1;unexpected=0
removed=1;rm_successes=1;remaining=0
```

검증된 `feynman-tool-remote-child-[12 hex]-lifecycle` 1개만 회수했고,
전체 prune/다른 container/Desktop 종료는 하지 않았다.

### 3) report schema producer 결함

canonical name 수정 후 세 번째 fixture는 Docker lifecycle과 direct/proxy child가
실제로 성공해 CLI verdict는 ready였지만 schema 검증은
`'skipped' is a required property`로 실패했다. 성공 반환에 `skipped=false`가
없었던 producer 결함이다.

수정:

- 정상 `_run_rpc_variant()`에도 `skipped=false`를 명시했다.
- success/blocked report shape를 schema validator 회귀로 고정했다.

## 최종 model-free 실행

schema 수정 후 네 번째 fixture를 새 disposable root로 실행했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_remote_child_diagnostic `
  --docker 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' `
  --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' `
  --path-proxy 'C:\DevWorks\thinking-skills\tooling\feynman_rpc_path_proxy.py' `
  --fixture-root 'C:\Users\wotmd\AppData\Local\Temp\feynman-remote-child-differential-20260915-04' `
  --output 'C:\Users\wotmd\AppData\Local\Temp\feynman-remote-child-differential-20260915-04.json' `
  --timeout 30
```

CLI 결과:

```text
verdict=remote-child-differential-ready
failure_stage=null
report_written=true
```

report는 다음에 보존했다.

```text
C:\Users\wotmd\AppData\Local\Temp\feynman-remote-child-differential-20260915-04.json
```

proxy telemetry sidecar는 report 이름 뒤에 `.proxy-telemetry.json`을 붙인 새
파일이다. 최종 고정 관찰은 다음과 같다.

```text
access=True; image=True; create=True; start=True;
direct=True; proxy=True; direct_exit=0; proxy_exit=0;
direct_init=1; proxy_init=1; proxy_telemetry_complete=True;
proxy_telemetry_correlated=True; direct_cleanup=True; proxy_cleanup=True;
comparison=True;
proxy stderr visibility=proxy-child-stderr-discarded-by-current-proxy
```

최종 report는 repository schema로 검증했다.

```text
schema=valid;verdict=remote-child-differential-ready;failure_stage=None
```

직접/ proxy는 같은 canonical image/security/mount/env/child argv contract를
사용하며 unique container name만 다르다. `docker_args_semantically_equal`와
`mount_destinations_equal`는 true다. response payload는 저장하지 않았다.

## FIX-01~07 상태

| 항목 | 이번 단계 판단 |
|---|---|
| FIX-01 | 기해결. smoke TEMP-output 경계와 consumer 회귀가 green이다. |
| FIX-02 | 기해결. bounded cleanup 회귀와 새 create/start/direct/proxy cleanup이 green이다. |
| FIX-03 | 기해결. incremental/final v3 telemetry consumer와 새 telemetry 재검증이 green이다. |
| FIX-04 | 기해결. incomplete child exit/mapping/correlation을 성공으로 승격하지 않는 gate와 schema가 green이다. |
| FIX-05 | 기해결·범위 제한. 네 POSIX destination을 direct/proxy에 동일 전달하고 child initialize를 통과했다. App Server의 숨은 path semantics까지 증명하지는 않는다. |
| FIX-06 | 기해결. preparation/startup/smoke wiring regression이 green이며 실제 smoke 설정은 변경하지 않았다. |
| FIX-07 | 기해결·범위 제한. Docker/Codex integration은 opt-in/skipped로 분리했고 새 fixture는 bounded external boundary만 실행했다. 11 skipped는 호환성 성공이 아니다. |

## 검증

실행한 명령과 결과:

```text
python -m unittest tests.test_feynman_remote_child_diagnostic
  -> 최종 14 tests OK

python -m unittest tests.test_feynman_remote_child_diagnostic tests.test_feynman_rpc_path_proxy tests.test_feynman_docker_runtime_probe tests.test_feynman_remote_exec_environment tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_subscription_smoke_exec
  -> 125 tests OK

python -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py'
  -> 501 tests OK, skipped=11, ResourceWarning 없음

final suite skip summary
  -> 503 tests, failures=0, errors=0, skipped=11

schema validation
  -> 19 files, errors=0

git diff --check
  -> 오류 없음
```

11 skipped는 Windows FIFO/symlink privilege·ambient skill root 영향 10개와
명시적 `FEYNMAN_RUN_DOCKER_INTEGRATION=1` opt-in이 필요한 native
Docker/Codex catalog 1개다. skip을 호환성 통과로 세지 않았다. 테스트 중 나온
`C:\Users\wotmd\.config\git\ignore` permission warning은 git global ignore
읽기 경고이며 test failure가 아니다.

최종 Docker prefix read-only 확인:

```text
matched=0;owned_prefix_remaining=0;unexpected=0
```

## 해석과 미완료

이번 단계로 확정된 것:

1. pinned remote image의 Docker access/image identity가 정상이다.
2. 네 bind mount, read-only/no-network/security 옵션의 create/start가 정상이다.
3. 같은 canonical child를 direct Docker와 Windows path proxy에 전달하면
   설치 버전 remote exec-server가 `clientName` initialize에 응답하고 정상
   종료한다.
4. proxy v3 request/response correlation, mapping clean, child exit, cleanup이
   완전하다.

아직 확정하지 않은 것:

1. LOG-109의 실제 App Server `thread/start -32603 / remote-environment-error`
   하위 원인은 미확정이다. 실제 구독 startup을 재실행하지 않았다.
2. 새 fixture는 App Server가 remote child에 보내는 내부 initialize envelope를
   관찰하지 않는다. `clientInfo`와 `clientName`을 같은 계약으로 취급하지
   않는다. 이번 ready를 `thread/start` ready로 승격하지 않는다.
3. current production proxy는 child stderr를 DEVNULL로 버리므로 protected
   startup report에서 child stderr 원인을 볼 수 없다. 이 observability gap을
   기록했을 뿐 stderr 원문 저장이나 경계 약화는 하지 않았다.
4. 실제 모델 실행 호환성·Feynman 행동 성능·baseline 비교는 검증하지 않았다.

다음 행동은 자동 실행하지 않는다. 추가 startup 실행 예산과 승인 범위를 확인한
뒤에만, 설치된 Codex 0.154.0 App Server가 remote child에 보내는 실제 내부
initialize/environment lifecycle을 payload 없이 분류하는 별도 진단을 검토한다.
같은 실패 반복, 모델 fallback, mount 확대, Linux control-plane 전환은 하지 않는다.

## commit / push

이 로그 작성 시점에는 코드/schema/test/pointer가 아직 commit/push 전이다.
기존 `.tmp/`, 사용자 PNG 2개, `LOG-099`는 stage하지 않는다. feature branch에만
일반 commit/push하고 main merge/force push는 하지 않는다.
