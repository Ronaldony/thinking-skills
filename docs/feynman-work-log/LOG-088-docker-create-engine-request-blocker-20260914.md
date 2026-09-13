# LOG-088 — Docker create 단계 blocker 분리와 runtime probe v2 (2026-09-14)

## 작업 상태

- 작업 ID: LOG-088 / 상태: DONE (자동 진단·코드 보강), BLOCKED (Docker client→engine container create)
- 저장소: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 기준 HEAD: `7da3b51def382f65117dcbb6f4c7abd215ba805f`
- 보안 범위: pinned image, 임시 output, probe가 생성한 고유 name/label만 사용했다. ChatGPT 구독 홈·토큰·전체 환경변수·API key·candidate payload는 읽거나 출력하지 않았다.

## LOG-087 정정

LOG-087의 `docker run` timeout은 image entrypoint 또는 Docker Desktop 자체 실패를 단정할 근거가 충분하지 않았다. `--rm`이면 container가 inspect 전에 사라질 수 있고, CLI exit `1`은 timeout 뒤 강제 종료된 docker CLI의 상태일 수 있다. 또한 exec-server stdin과 initialize response 계약도 충분히 검증하지 않았다.

## runtime probe v2 구현

`tooling/feynman_docker_runtime_probe.py`를 다음과 같이 보강했다.

- report schema를 v2로 변경했다.
- `--rm`을 제거하고 실행별 고유 label을 붙여 probe가 소유한 container만 inspect/remove한다.
- CLI 종료, timeout, stdin write, stdout/stderr drain·digest·truncation·reader 오류, container 내부 state/exit/OOM, cleanup 상태를 분리한다.
- 출력은 256KiB까지만 메모리에 보존해 marker·version·initialize 구조만 확인하고, 원문은 report에 쓰지 않는다.
- `docker create`와 `docker start -a`를 분리했다. create 성공 후에만 start, node version, exec-server initialize를 진행한다.
- exec-server에는 `-i`를 넣고, response ID `1`의 JSON result가 있어야 initialize 성공으로 인정한다.
- container를 관찰하지 못했거나 소유권·정리 검증이 불완전하면 통과하지 않는다.

회귀에는 foreign label 미보존, 유효 initialize response만 수락, cleanup 불확실성 차단, created state 조건을 추가했다.

## 실제 Docker create 진단 1회

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_docker_runtime_probe --docker 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --image 'sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6' --output 'C:\DevWorks\thinking-skills\.tmp\docker-runtime-probe-20260914-v3.json' --timeout 30
```

artifact: [`docker-runtime-probe-20260914-v3.json`](../../.tmp/docker-runtime-probe-20260914-v3.json)

관찰:

- verdict: `docker-runtime-blocked`
- 최초 실패 단계: `container-create`
- Docker CLI는 30초 timeout 뒤 tree stop으로 종료되어 `cli_exit_code=1`, `cli_stop_verified=true`
- stdout/stderr는 각각 0 byte이며 reader는 정상 drain 완료
- name 기반 inspect는 `available=false`, `inspect_exit_code=1`
- probe가 소유한 container가 관찰되지 않아 cleanup은 `not-observed`, `verified=false`
- `container-start`, node version, exec-server initialize, path contract는 실행하지 않았다.

따라서 현재 증거는 pinned image 안의 entrypoint/node/Codex가 아니라 Docker `create` 요청이 container object를 만들고 관찰 가능한 상태까지 도달하지 못한다는 범위로 한정된다. Docker `info`와 image inspect 성공은 container create 성공을 증명하지 않는다.

## 검증

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -W error::ResourceWarning -m unittest tests.test_feynman_docker_runtime_probe tests.test_feynman_rpc_compatibility -q
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -W error::ResourceWarning -m unittest discover -s tests
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m py_compile tooling/feynman_docker_runtime_probe.py tooling/feynman_rpc_path_contract_probe.py tooling/feynman_rpc_path_proxy.py tooling/feynman_subscription_startup_diagnostic.py tests/feynman_subscription_lifecycle_fixture.py
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -c "from pathlib import Path; import json; from jsonschema import Draft202012Validator; files=sorted(Path('evals').rglob('*.schema.json')); [Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; schema=json.loads(Path('evals/feynman-thinking/subscription-startup-diagnostic.schema.json').read_text(encoding='utf-8')); report=json.loads(Path('.tmp/startup-diagnostic-20260913-v3.json').read_text(encoding='utf-8')); Draft202012Validator(schema).validate(report); print(f'schema_files={len(files)} errors=0 actual_startup_report_errors=0')"
git diff --check
```

결과: focused `24 tests OK`; 전체 `432 tests OK (skipped=11)`; ResourceWarning 없음; schema `17개 errors=0`; actual startup report instance `errors=0`; compile 및 diff check 통과.

## 자동 진행 종료점과 다음 행동

- 코드·fixture·offline Docker 진단·로그·commit/push는 이 단계까지 자동 진행했다.
- Docker Desktop/engine이 create 요청을 완료하지 못하는 외부 상태는 repository 코드로 수정할 수 없다.
- 다음에 필요한 외부 행동은 Docker Desktop backend의 container-create 정상화다. 재시작·WSL 종료·재설치처럼 사용자 환경에 영향을 주는 조치는 자동 실행하지 않는다.
- 환경이 정상화되면 runtime probe v2는 `container-start → node version → exec-server initialize`를 자동으로 계속한다. initialize 성공 전에는 path contract, 실제 subscription startup, Luna smoke를 시작하지 않는다.

## 커밋·push

- 이번 변경은 runtime probe, 회귀 테스트, LOG-088, 최신 인계 문서만 stage한다.
- `.tmp/`와 사용자 PNG 2개는 stage하지 않는다.
- commit·push SHA는 완료 후 이 로그에 기록한다.
