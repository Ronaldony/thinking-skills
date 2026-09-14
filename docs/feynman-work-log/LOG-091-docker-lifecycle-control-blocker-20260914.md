# LOG-091 — Docker container lifecycle control 재현과 외부 blocker 확정 (2026-09-14)

## 상태

- 작업 ID: LOG-091 / 상태: DONE (원인 분리), BLOCKED (Docker container lifecycle)
- 저장소: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `74cb3acfb1e9a0365ec985a28a25384e07007f9a`
- 인증·모델·candidate payload·보호된 구독 로그인 홈은 사용하지 않았다.

## 이번 단계의 목적

`LOG-090`의 runtime probe가 사용하는 보안 옵션 조합 때문에 create가 멈췄을 가능성을 분리했다. 같은 pinned image와 같은 local Docker named pipe를 사용하되 probe 전용 cap/security/read-only/tmpfs/user/network 옵션을 제거한 최소 `docker create` control을 고유 name·label로 1회 실행했다.

## 실행과 관찰

로컬 image 목록 확인:

```powershell
docker --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --host 'npipe:////./pipe/docker_engine' images --format '{{.Repository}}|{{.Tag}}|{{.ID}}'
```

결과: pinned image와 같은 repository의 local tags, `python:3.12-slim`, `node:22-bookworm-slim`이 조회됐다. 처음 사용한 `.Architecture` template은 `images` formatter에 없는 필드라 실패했으며, 이를 수정한 위 명령으로 재확인했다. 이 조사 오류는 Docker lifecycle 결과로 해석하지 않았다.

최소 control:

```powershell
$controlCode = @'
import json, re, subprocess, uuid
exe = r'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
cfg = r'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config'
host = 'npipe:////./pipe/docker_engine'
name = 'feynman-control-' + uuid.uuid4().hex[:12]
label = 'com.openai.feynman.control=fixture-' + uuid.uuid4().hex[:8]
command = [exe, '--config', cfg, '--host', host, 'create', '--name', name, '--label', label, '--entrypoint', '/bin/echo', 'sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6', 'FEYNMAN_CONTROL_OK']
result = {'case': 'minimal-create-control', 'timeout_seconds': 10}
try:
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=10)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        out, err = proc.communicate(timeout=5)
    result.update({'cli_exit_code': proc.returncode, 'timed_out': timed_out, 'stdout_bytes': len(out), 'stderr_bytes': len(err), 'container_id_format': bool(re.fullmatch(rb'[0-9a-f]{12,64}\r?\n?', out))})
except Exception as exc:
    result.update({'launcher_error_type': type(exc).__name__})
print(json.dumps(result))
'@
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -c $controlCode
```

실제 control은 pinned image, `--entrypoint /bin/echo`, 단순 marker, 고유 name·label만 사용했다. 결과:

```json
{"case":"minimal-create-control","timeout_seconds":10,"cli_exit_code":1,"timed_out":true,"stdout_bytes":0,"stderr_bytes":0,"container_id_format":false,"cleanup_error_type":"TimeoutExpired","absent_after_cleanup":false}
```

그 뒤 probe가 만든 label 범위만 대상으로 남은 control container를 조회·정리했다.

```powershell
docker --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --host 'npipe:////./pipe/docker_engine' ps -a --filter label=com.openai.feynman.control --format '{{.Names}}'
```

결과: list 또는 cleanup이 8초 timeout됐다. 따라서 해당 control container가 남아 있는지 확인할 수 없다. 다른 container에는 접근하지 않았고 broad prune/remove도 하지 않았다. Docker backend가 다시 응답할 때 `com.openai.feynman.control` label 범위만 확인해야 한다.

## 원인 판단

- `docker info`, image inspect, CLI help, endpoint metadata는 응답한다.
- probe의 hardening 옵션을 제거한 최소 create도 timeout된다.
- create 실패 직후의 label 제한 `ps`도 timeout된다.
- 그러므로 현재 evidence는 image entrypoint/node/Codex, path mapping, `--read-only`, `--cap-drop`, `--tmpfs`, `--user`, `--network` 중 하나로 원인을 특정하지 않는다.
- 가장 좁은 확정 범위는 Docker client가 metadata 요청에는 응답을 받지만 container lifecycle create/list API에서 제때 응답을 받지 못한다는 것이다. Docker Desktop 내부 backend/containerd 원인은 이 저장소 코드만으로 확정할 수 없다.

## 코드·검증 상태

직전 변경에서 runtime probe는 timeout·presence unavailable·cleanup 미확인을 성공으로 승격하지 않으며, path probe는 fixture 값·response namespace 차이를 검출하도록 보강됐다. 집중 `33 tests OK`, 전체 `441 tests OK, 11 skipped`, schema `17 errors=0`, compile·diff check를 통과했다.

수정 후 runtime probe artifact:

- `.tmp/docker-runtime-probe-20260914-v4.json`
- verdict `docker-runtime-blocked`
- failure stage `container-create`
- 30초 timeout, stdout/stderr `0/0`, `container_id_observed=false`

같은 create 입력은 추가로 반복하지 않았다. path contract 실제 Docker 비교, 구독 startup, auth gate, Luna smoke, model evaluation도 실행하지 않았다.

## 다음 행동

사람이 수행할 외부 복구 범위는 Docker Desktop backend/container lifecycle 응답을 정상화하고, 이후 고유 label `com.openai.feynman.control` 범위의 잔존 container만 확인·정리하는 것이다. broad prune, Docker context 전환, 로그인 변경은 필요 조건으로 가정하지 않는다.

환경이 정상화됐다는 증거가 생기면 수정된 runtime probe를 1회 실행한다. `container-create → container-start → node version → exec-server initialize` 중 최초 실패에서 멈추고, initialize 성공 전에는 path contract·subscription startup·모델 실행으로 진행하지 않는다.

## 커밋·push

- 이 로그와 최신 상태 문서는 후속 문서 commit으로 기록한다.
- `.tmp/`와 사용자 PNG 2개는 stage하지 않는다.
- main merge와 force push는 하지 않는다.
