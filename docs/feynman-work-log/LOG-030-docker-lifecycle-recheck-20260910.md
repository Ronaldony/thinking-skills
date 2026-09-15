# LOG-030 — Docker lifecycle recheck after Desktop startup

작성일: 2026-09-10 (Asia/Seoul)

## 범위와 시작 상태

이번 작업은 LOG-029에서 남은 Docker Desktop container lifecycle blocker의 재검증이다. 사용자가 Docker Desktop을 설치하고 실행했다고 알려 주었으므로, 저장소 내부 자동 작업을 재개하되 read-only endpoint가 실제 lifecycle까지 회복되었는지를 분리해서 확인했다. lifecycle이 통과하지 않으면 candidate, auth-backed remote exec, 모델 평가를 시작하지 않는 기존 gate를 유지했다.

적용 저장소/브랜치:

- 경로: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `2702b0c` (`fix: make Windows evaluation fixtures portable`)
- 시작 working tree: clean
- shell: Windows PowerShell

이번 turn에도 skill 개발 작업에 해당하므로 다음 지침을 전체 읽었다.

    Get-Content C:\Users\wotmd\.codex\skills\.system\skill-creator\SKILL.md -Encoding UTF8

기존 평가 전용 홈 `C:\Users\wotmd\.codex-feynman-eval`은 보존했다. 로그인 파일·토큰·원문 auth 상태·전체 환경변수·계정 식별 정보는 읽거나 출력하지 않았다. OpenAI Platform API/API key는 사용하지 않았다. 적용되는 `AGENTS.md`는 발견되지 않았다.

## 1. Docker read-only endpoint 확인

사용한 Docker CLI:

    C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe

빈 Docker config를 사용해 사용자 config/helper의 영향을 배제했다.

실행 명령:

    docker --config C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config version --format '{{.Client.Version}}|{{.Server.Version}}|{{.Server.Os}}|{{.Server.Arch}}'

결과:

    29.7.2|29.7.2|linux|arm64

실행 명령:

    docker --config C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config context ls --format '{{.Name}}|{{.Current}}|{{.DockerEndpoint}}'

결과:

    default|true|npipe:////./pipe/docker_engine

backend process 읽기 명령:

    Get-Process -Name DockerDesktop,com.docker.backend,docker -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,StartTime,Responding

관찰:

- `com.docker.backend` 두 process가 존재하고 `Responding=True`였다.
- Docker CLI/server version과 기본 named-pipe context는 응답했다.
- 이 결과는 `/version`, context 조회 및 backend responsiveness만 증명하며 container lifecycle 성공을 증명하지 않는다.

## 2. 최종 native artifact lifecycle 재검증

대상 artifact:

    C:\DevWorks\feynman-smoke-preflight-native-6c6849e8feee4155a10e261ec175927b\ordinal-1-feynman-v05\remote-environment.toml

artifact의 `docker run` argv를 model-free `docker create` argv로 바꾸어 제한 시간 20초로 실행했다. 유지한 주요 경계는 다음과 같다.

- image: `feynman-codex-remote:local`
- `--network none`
- `--cap-drop ALL`
- `--security-opt no-new-privileges`
- `--read-only`
- `--user 1000:1000`
- `/tmp` tmpfs
- host candidate/home/codex/temp → `/run/candidate`, `/run/home`, `/run/codex`, `/run/temp`
- workdir `/run/candidate`
- `env -i` 및 candidate-safe `HOME`, `CODEX_HOME`, `PATH`, `TMPDIR`
- image command는 `codex exec-server --listen stdio`이며 create 단계에서는 실행되지 않는다.

실행은 PowerShell의 `System.Diagnostics.Process`로 수행해 stdout/stderr를 수집하고, 20초 동안 반환하지 않으면 해당 Docker client process만 `Kill(true)`로 종료하도록 했다. 생성 성공 시에만 `inspect`하고 진단용 이름을 `rm -f`하는 흐름이었다.

실제 관찰:

    CREATE_TIMEOUT
    docker_lifecycle=create_unresponsive
    container_created=false

20초 내 `docker create`가 반환하지 않았다. timeout 이후 대상 이름 `feynman-lifecycle-probe-20260910`의 컨테이너를 정리할 필요가 없었다. image 삭제, 기존 컨테이너 삭제, Docker Desktop 재시작/초기화, context 변경은 하지 않았다.

## 3. timeout 이후 부작용 확인

실행 명령:

    docker --config C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}|{{.Containers}}|{{.Images}}|{{.Driver}}|{{.OperatingSystem}}'

결과:

    29.7.2|linux|aarch64|3|4|overlayfs|Docker Desktop

같은 process 목록 명령도 재실행했다. timeout으로 종료한 Docker client는 남아 있지 않았고, backend 두 process만 `Responding=True`로 남았다. `Containers=3`, `Images=4`는 create가 새 컨테이너를 만들지 않았음을 보조적으로 확인한다.

## 4. 판정

현재 상태:

    Docker version/info/context: responsive
    Docker backend process: responsive
    Docker container lifecycle create: unresponsive (20s timeout)
    final native artifact create: incomplete
    auth gate: not rerun in this lifecycle-only check
    model request: not started
    actual evaluation: not started

따라서 현재 blocker는 Docker Desktop의 container lifecycle endpoint partial failure이다. auth gate 실패, native path validator 실패, image mismatch, candidate Codex version failure로 해석하지 않는다. LOG-022의 이전 direct local ChatGPT subscription auth evidence와 LOG-026의 model-free structural preflight evidence는 보존하되 실제 평가 시작 조건으로 과대해석하지 않았다.

## 5. 검증 범위와 미완료 사항

이번 작업에서 확인한 범위:

- Docker CLI/server version
- 기본 Docker context와 named pipe endpoint
- Docker backend process 응답 상태
- 최종 native artifact의 exact profile을 이용한 제한 시간 lifecycle create
- timeout 이후 container/client 잔류 여부

아직 미완료:

1. final artifact `create` 성공
2. container `inspect`, `start`, candidate `codex --version`
3. native same-profile boundary probe
4. auth-backed remote exec 및 smoke answer
5. trace/final, attestation/link, review/gate/result lineage
6. 실제 모델 평가

선행 조건인 `docker create`/`inspect`가 통과하기 전에는 위 2~6을 실행하지 않는다. 다음 행동은 같은 명령을 무한 반복하는 것이 아니라, Docker Desktop host lifecycle endpoint의 복구 또는 상태 점검이 완료된 뒤 final artifact에 대해 한 번 다시 create/inspect하는 것이다. Docker Desktop 재시작이나 초기화가 필요하다면 그것이 사람 개입 경계다.

## 6. Commit/push 상태

이번 lifecycle 진단 자체는 파일을 수정하지 않았고, working tree는 시작 HEAD `2702b0c`에서 clean이었다. 이 기록만 feature branch에 commit/push한다. main merge와 force push는 하지 않는다.
