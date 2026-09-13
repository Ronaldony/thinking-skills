# LOG-089 — Docker runtime 외부 상태 재확인과 probe 회귀 보강 (2026-09-14)

## 작업 상태

- 작업 ID: LOG-089 / 상태: DONE (코드·회귀 검증·기록), BLOCKED (Docker `create` 외부 요청)
- 저장소: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 작업 시작 기준 HEAD: `3d1b36a7a84f76ded3d9a3a19cdb4d06656eae42`
- 보안 범위: Docker client/server metadata, pinned image metadata, repository tests와 기존 `.tmp` artifact만 확인했다. 구독 로그인 홈·토큰·전체 환경변수·API key·candidate payload는 읽거나 출력하지 않았다.

## 이번 단계의 목적

직전 `LOG-088`의 `container-create` timeout이 Docker Desktop 전체 장애인지, 고정 image metadata 문제인지 구분하고, 새 runtime probe가 pipe·출력 폭주·비정상 내부 종료를 성공으로 오판하지 않는지 자동 검증했다. 같은 `docker create` 실제 실행은 반복하지 않았다.

## 외부 Docker 상태 확인

실행한 제한 명령:

```powershell
docker version --format '{{.Client.Version}}|{{.Server.Version}}|{{.Server.Os}}|{{.Server.Arch}}'
docker context ls --format '{{.Name}}|{{.Current}}|{{.DockerEndpoint}}'
Get-Process -Name docker,com.docker.backend -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,Responding
docker --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}|{{.ContainersRunning}}|{{.ContainersPaused}}|{{.ContainersStopped}}|{{.Images}}|{{.Driver}}|{{.OperatingSystem}}'
docker --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' ps -a --no-trunc --format '{{.ID}}|{{.Status}}|{{.Image}}'
docker --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' image inspect 'sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6' --format '{{.Id}}|{{.Os}}|{{.Architecture}}|{{json .Config.Entrypoint}}|{{json .Config.Cmd}}|{{.Size}}'
```

관찰:

- client/server `29.7.2`, server `linux/aarch64`.
- `default`와 `desktop-linux` context가 보였고 `desktop-linux`가 선택돼 있었다.
- `docker`, `com.docker.backend` 프로세스가 응답 상태였다.
- Engine info는 `0 running | 0 paused | 0 stopped | 14 images`, `overlayfs`, `Docker Desktop`이었다.
- 고정 image는 Linux/arm64, entrypoint `docker-entrypoint.sh`, cmd `node`, size `574296192`였다.
- `docker ps -a`에는 출력할 container가 없었다.

이 결과는 Docker Engine 연결·metadata 조회는 정상임을 보여주지만, 고정 image에 대한 `docker create`가 30초 안에 container object를 만들었다는 증거는 아니다. 따라서 원인은 image 내부 entrypoint/node/Codex나 path mapping으로 확대하지 않고, client→engine의 create 요청 처리로 계속 한정한다.

## 코드·회귀 보강

`tests/test_feynman_docker_runtime_probe.py`에 다음 회귀를 추가했다.

- stdout/stderr drain이 전체 바이트·digest는 계산하면서 raw sample을 256 KiB로 제한하고 EOF를 기록하는지 확인.
- 내부 container exit code `7`과 같은 비정상 종료를 `entrypoint-echo` 성공으로 판정하지 않는지 확인.

이는 `tooling/feynman_docker_runtime_probe.py`의 기존 bounded capture, ownership/cleanup, initialize result 검증을 직접 보강하는 테스트이며, 실제 subscription startup·model evaluation은 호출하지 않는다.

## 검증 명령과 결과

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m unittest tests.test_feynman_docker_runtime_probe
```

결과: `8 tests OK`.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m unittest discover -s tests
```

결과: `434 tests OK, 11 skipped`.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m py_compile tooling/feynman_docker_runtime_probe.py tooling/feynman_rpc_path_contract_probe.py tooling/feynman_subscription_startup_diagnostic.py tooling/feynman_subscription_auth_gate.py
```

결과: 통과.

처음 사용한 `scripts/check_feynman_evidence_schema.py` 경로는 이 저장소에 존재하지 않아 실패했다. 이를 schema 결함으로 해석하지 않고, 저장소에 존재하는 17개 schema를 `jsonschema.Draft202012Validator`로 직접 검사하고 기존 startup report instance를 검증하는 명령으로 교정했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -c "from pathlib import Path; import json; from jsonschema import Draft202012Validator; files=sorted(Path('evals').rglob('*.schema.json')); [Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; schema=json.loads(Path('evals/feynman-thinking/subscription-startup-diagnostic.schema.json').read_text(encoding='utf-8')); report=json.loads(Path('.tmp/startup-diagnostic-20260913-v3.json').read_text(encoding='utf-8')); Draft202012Validator(schema).validate(report); print(f'schema_files={len(files)} errors=0 actual_startup_report_errors=0')"
git diff --check
```

결과: `schema_files=17 errors=0 actual_startup_report_errors=0`, diff check 통과. `py_compile`와 테스트는 `ResourceWarning`을 발생시키지 않았다.

## 실행 범위와 차단

- `docker-runtime-probe-20260914-v3.json`의 기존 실제 결과는 `container-create`에서 `docker-runtime-blocked`이며, timeout·CLI exit `1`·stdout/stderr `0/0`·name inspect 불가·cleanup not-observed다.
- 이번 단계에서는 같은 create를 반복하지 않았고, `container-start`, node version, exec-server initialize, path contract, subscription startup, 인증 gate, Luna smoke, 모델 평가는 실행하지 않았다.
- Docker Desktop backend를 재시작하거나 WSL/설치를 변경하는 외부 조치는 자동으로 수행하지 않았다.

## 커밋·push 및 미완료

- 변경: runtime probe 회귀 테스트 2개, 본 로그, 최신 재개 지점 문서 3개.
- `.tmp/`와 사용자 PNG 2개는 stage 대상에서 제외하고 보존한다.
- 커밋·push 상태와 최종 SHA는 후속 receipt commit에 기록한다.
- 미완료: Docker `create` 요청이 실제로 완료되는 환경 증거, 그 이후 start/node/exec-server initialize, Windows path 의미 비교, 실제 subscription startup gate, 조건부 Luna smoke.

## 다음 행동

Docker 외부 상태가 정상화됐다는 새 증거가 있을 때만 runtime probe v2를 1회 실행한다. `container-create → container-start → node version → exec-server initialize` 순서 중 최초 실패에서 멈추며, initialize 성공 전에는 path contract와 subscription/model 실행으로 진행하지 않는다.
