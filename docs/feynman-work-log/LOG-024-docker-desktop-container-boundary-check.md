# LOG-024 — Docker Desktop container boundary check

- **시각(KST)**: 2026-09-09 18:55 이후
- **저장소**: `Ronaldony/thinking-skills`
- **브랜치**: `feat/feynman-thinking-v0.5-draft`
- **시작 HEAD**: `3fe5173151dea115a4cc65f4fc79f1c04608399e`
- **목적**: 사용자가 설치·실행한 Docker Desktop의 daemon, Linux container, Codex remote image, Windows host→POSIX container boundary를 모델 호출 없이 확인한다.
- **정책**: OpenAI Platform API/API key를 사용하지 않음. ChatGPT login home·token·auth file은 읽지 않음. 실제 model smoke는 아직 시작하지 않음.

## 1. 시작 상태 / DONE

- branch는 `feat/feynman-thinking-v0.5-draft`, working tree는 clean이었다.
- Docker Desktop 프로세스가 실행 중이었다.
- `docker` 명령은 현재 Codex PowerShell process PATH에 없었지만, per-user 설치 경로의 Docker CLI executable을 발견했다.
- 사용자/시스템 PATH를 전체 출력하지 않고 Docker 문자열을 포함한 항목 개수만 확인했다. 두 scope 모두 등록 항목은 0개였다.

## 2. daemon 확인 / PASS

실행한 명령(설치 경로는 공개 로그에서 축약):

```powershell
<DockerDesktop>\resources\bin\docker.exe version --format 'client={{.Client.Version}} server={{.Server.Version}} os={{.Server.Os}} arch={{.Server.Arch}}'
<DockerDesktop>\resources\bin\docker.exe info --format 'server={{.ServerVersion}} os={{.OSType}} arch={{.Architecture}} containers={{.Containers}} images={{.Images}}'
```

처음 sandbox 환경에서는 Docker named pipe와 user Docker config 접근이 거부됐다. credential 내용을 읽지 않고 Docker CLI daemon check만 권한 확장으로 실행했다.

결과:

- client/server `29.7.2`
- server OS `linux`
- server architecture `aarch64`
- `docker version` exit `0`
- `docker info` exit `0`
- daemon 연결 성공

## 3. public Linux container 확인 / PASS

사용자 Docker credential config를 사용하지 않기 위해 비어 있는 임시 `DOCKER_CONFIG` directory를 지정했다. 첫 시도는 user config가 참조하는 `docker-credential-desktop` helper가 현재 PATH에 없어 실패했다.

첫 시도 관찰:

- `docker pull python:3.12-slim`: exit `1`
- 원인: `docker-credential-desktop` executable not found in current process PATH
- user config/auth file 내용은 읽거나 출력하지 않았다.

수정된 확인 명령:

```powershell
$env:DOCKER_CONFIG = <new empty temporary directory>
<DockerDesktop>\resources\bin\docker.exe pull python:3.12-slim
<DockerDesktop>\resources\bin\docker.exe run --rm --network none python:3.12-slim python --version
```

결과:

- public image pull exit `0`
- image digest: `sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea`
- network-none container 실행 exit `0`
- container Python `3.12.14`
- 임시 Docker config directory는 정리했다.

## 4. Codex remote image 확인 / PASS

저장소 remote-exec reference workflow의 image recipe를 따라 `node:22-bookworm-slim` 기반 임시 Dockerfile로 공식 `@openai/codex@0.153.4` image를 build했다. build context와 Dockerfile은 임시 경로에서 사용 후 삭제했다. 모델 요청과 login credential은 사용하지 않았다.

실행한 명령 요약:

```powershell
<DockerDesktop>\resources\bin\docker.exe build \
  --build-arg CODEX_PACKAGE_VERSION=0.153.4 \
  -t feynman-codex-remote:local <temporary-build-context>
<DockerDesktop>\resources\bin\docker.exe run --rm --network none \
  feynman-codex-remote:local codex --version
<DockerDesktop>\resources\bin\docker.exe run --rm --network none \
  feynman-codex-remote:local codex exec-server --help
```

결과:

- image inspect 성공: Linux `arm64`
- local image ID: `sha256:dab903a5999b1d3165a70de99147029809fa26d3cb1881b7c7790aac185a4726`
- network-none remote image `codex --version`: `codex-cli 0.153.4`, exit `0`
- `codex exec-server --help`: exit `0`, stdio listen 옵션 확인

## 5. 실제 Windows host→POSIX Docker boundary / PASS

Windows TEMP 아래의 새 ephemeral directory 네 개를 만들고, Docker에서 다음 explicit destination으로 매핑했다.

```text
candidate      → /run/candidate
candidate home → /run/home
tool Codex home→ /run/codex
tool temp      → /run/temp
```

container는 다음 reference controls로 생성했다.

```text
--network none
--cap-drop ALL
--security-opt no-new-privileges
--read-only
--user 1000:1000
--tmpfs /tmp:rw,nosuid,nodev
env -i HOME=/run/home CODEX_HOME=/run/codex PATH=... TMPDIR=/run/temp ...
```

실행 결과:

- `docker create`: exit `0`
- 저장소 `tooling/feynman_docker_reference_inspect.py` pre-start 검증: `docker-inspect-matches-profile`, exit `0`
- container start: exit `0`
- 내부 Codex version: `codex-cli 0.153.4`
- post-start inspect 검증: `docker-inspect-matches-profile`, exit `0`
- ephemeral container, host directories, temporary Docker config, inspect artifacts는 정리했다.

한 번에 실행한 임시 PowerShell 검증 script는 `$home` 예약 변수 충돌로 Docker 단계 전에 실패했다. `$candidateHome`으로 이름을 고친 뒤 재실행했으며, 첫 실패에서는 container나 credential에 접근하지 않았다.

## 6. 인증/평가와의 경계 / NOT STARTED

이번 작업으로 확인된 것은 Docker backend와 model-free remote container boundary뿐이다.

```text
Windows auth gate: PASS (LOG-022)
Docker daemon/container: PASS
Codex remote image/version/exec-server help: PASS
actual subscription model turn: NOT STARTED
canonical subscription smoke executor: NOT STARTED
behavioral evaluation: NOT STARTED
```

현재 repository generator에는 여전히 다음 계약 문제가 있다.

- `runner-job.schema.json`과 boundary profile v1은 path를 POSIX 기준으로 검증한다.
- `runner_job_validate.py`는 profile writable mount와 candidate host path가 동일하다고 가정한다.
- `feynman_remote_exec_environment.py`는 host path를 container destination/workdir로 그대로 사용한다.
- 따라서 방금 검증한 explicit Windows→`/run/...` mapping은 Docker 수준에서는 성공했지만, 현재 canonical artifact generator가 Windows native job에서 자동으로 생성하지는 않는다.
- Windows local executor의 scrubbed env PATH에도 Docker CLI 디렉터리가 자동 포함되지 않는다. 현재 설치 상태에서는 canonical executor 실행 전에 Docker CLI 경로가 child PATH에 있어야 한다.

이 문제를 임의의 schema migration이나 credential 복사로 우회하지 않았다.

## 7. 저장 상태 / PENDING

- 코드 변경 없음.
- 추가한 파일: 이 LOG-024 하나.
- Docker local image는 model-free reference 검증을 위해 로컬 daemon에 남아 있다. repository에는 추가하지 않았다.
- model/API/key/credential: 사용하지 않음.
- main merge/force push: 하지 않음.
- 다음 commit/push: 이 로그만 non-force로 저장할 예정.

## 8. 미완료 사항과 다음 한 행동

미완료:

1. Windows native path를 runner-job/profile/remote-environment 전체에서 안전하게 표현하는 canonical mapping contract.
2. canonical executor가 Docker CLI absolute path 또는 명시적 child PATH를 사용하는 방식.
3. 실제 subscription smoke artifacts 생성, structural preflight, executor, post-run lineage.

**다음 한 행동**: native Windows host mapping을 지원하는 schema/tooling migration을 별도 설계할지, POSIX 경로를 제공하는 Linux/self-hosted control plane을 사용할지 사용자 방향을 정한다. 그 선택 전에는 모델 평가나 credential 이동을 시작하지 않는다.
