# LOG-087 — Docker runtime 단계별 실행과 첫 단계 blocker (2026-09-14)

## 작업 상태

- 작업 ID: LOG-087 / 상태: DONE (runtime probe 구현·검증), BLOCKED (Docker run/container 생성)
- 저장소: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 기준 HEAD: `2802dc82e1cb17fca7d199db8e219a945d76845a15`
- 보안 범위: pinned image와 Docker Desktop API, 고정 임시 이름·임시 출력만 사용했다. 인증 홈·토큰·전체 환경변수·API key·candidate payload는 읽거나 출력하지 않았다.

## 목적

LOG-086에서 exec-server initialize보다 앞선 Docker peer 정체가 확인됐다. 이번 작업은 `entrypoint echo → 기본 node → exec-server initialize`를 단계별로 실행해 Docker CLI, container 생성, image process, RPC initialize 중 최초 blocker를 분리하는 것이 목적이다.

## 구현

새 [runtime probe](../../tooling/feynman_docker_runtime_probe.py)는 다음을 구현한다.

- 고정 image digest, 네트워크 차단, `cap-drop ALL`, read-only root, `1000:1000` 사용자 조건을 공통 적용
- 각 container에 probe 전용 이름을 부여하고, timeout 시 해당 이름만 inspect/remove
- Docker CLI 종료 코드와 container state/exit/OOM 상태를 별도 필드로 기록
- stdout/stderr는 원문을 저장하지 않고 바이트 수와 digest만 기록
- 첫 단계가 실패하면 후속 node·exec-server 단계를 실행하지 않음
- 기존 output 덮어쓰기와 비고정 image를 subprocess 실행 전에 차단

관련 회귀 테스트는 고정 state allowlist, 민감한 state 문자열 제거, 기존 output 입력 차단을 확인한다.

## 검증 명령과 결과

### runtime probe 회귀

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m py_compile tooling/feynman_docker_runtime_probe.py tests/test_feynman_docker_runtime_probe.py
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -W error::ResourceWarning -m unittest tests.test_feynman_docker_runtime_probe tests.test_feynman_rpc_compatibility -q
git diff --check
```

결과: `21 tests`, `OK`; compile 및 diff check 통과.

### 실제 Docker runtime probe

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_docker_runtime_probe --docker 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --image 'sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6' --output 'C:\DevWorks\thinking-skills\.tmp\docker-runtime-probe-20260914-v1.json' --timeout 5
```

artifact: [`docker-runtime-probe-20260914-v1.json`](../../.tmp/docker-runtime-probe-20260914-v1.json)

관찰:

- verdict: `docker-runtime-blocked`
- 최초 실패 단계: `entrypoint-echo`
- `cli_exit_code=1`, `timed_out=true`, stdout/stderr bytes `0/0`
- container inspect: `available=false`, `inspect_exit_code=1`
- `cleanup_exit_code=null`
- stage count `1`; 기본 node와 exec-server initialize는 실행하지 않음

이 결과는 Docker daemon의 `info`와 image metadata를 읽을 수 있다는 사실과 분리된다. 현재 범위에서 확정되는 것은 Docker `run`이 가장 단순한 image process를 완료하지 못했고, container state도 조회하지 못했다는 점이다. image 내부 node 또는 exec-server의 RPC 의미 문제로 해석할 수 있는 응답은 아직 없다.

### 누적 전체 검증

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -W error::ResourceWarning -m unittest discover -s tests
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m py_compile tooling/feynman_docker_runtime_probe.py tooling/feynman_rpc_path_contract_probe.py tooling/feynman_rpc_path_proxy.py tooling/feynman_subscription_startup_diagnostic.py tests/feynman_subscription_lifecycle_fixture.py
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -c "from pathlib import Path; import json; from jsonschema import Draft202012Validator; files=sorted(Path('evals').rglob('*.schema.json')); [Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; schema=json.loads(Path('evals/feynman-thinking/subscription-startup-diagnostic.schema.json').read_text(encoding='utf-8')); report=json.loads(Path('.tmp/startup-diagnostic-20260913-v3.json').read_text(encoding='utf-8')); Draft202012Validator(schema).validate(report); print(f'schema_files={len(files)} errors=0 actual_startup_report_errors=0')"
git diff --check
```

결과: 전체 `429 tests`, `OK (skipped=11)`; compile 및 diff check 통과; schema `17개 errors=0`; actual startup report instance `errors=0`; ResourceWarning 없음. Docker runtime probe는 인증·모델·평가를 사용하지 않았다.

## 미완료 사항과 다음 행동

- Docker `run`이 container 생성 전에 지연되는지, Docker Desktop backend가 container start를 지연하는지는 현재 API 관찰만으로 확정하지 못했다.
- 다음 실행은 동일 명령 반복이 아니라 Docker Desktop의 제한된 `run` 상태 진단 또는 사용자 측 Docker Desktop 재시작/상태 확인 이후에만 의미가 있다.
- runtime probe가 `entrypoint-echo`를 통과하면 새 output으로 node 단계와 exec-server initialize를 순서대로 수행한다.
- exec-server initialize가 통과한 뒤에만 path contract를 다시 해석한다. 실제 구독 startup·인증·Luna smoke는 그 이후 경계에서 별도로 판단한다.

## 커밋·push

- 이번 변경은 runtime probe, 회귀 테스트, LOG-087, 최신 인계 문서만 stage한다.
- `.tmp/`와 사용자 PNG 2개는 stage하지 않는다.
- 명시된 6개 tracked 파일만 stage했고 `.tmp/`와 사용자 PNG 2개는 보존했다.
- 커밋: `f08f6b5c3af27df4c32a940605799081bcbb16d7` (`feat: add Docker runtime stage probe`)
- `git push origin feat/feynman-thinking-v0.5-draft` 성공.
- push 후 local HEAD와 `refs/remotes/origin/feat/feynman-thinking-v0.5-draft`가 모두 `f08f6b5c3af27df4c32a940605799081bcbb16d7`로 일치했다.
- main merge와 force push는 하지 않았다.
