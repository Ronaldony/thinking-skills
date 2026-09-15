# LOG-027 — Native Windows final canary diagnostic and Docker create blocker

작성일: 2026-09-09 (Asia/Seoul)

## 범위와 시작 상태

이번 작업은 LOG-026의 다음 행동인 생성된 native Windows smoke artifact에 대한 같은 프로필 Docker inspect canary 재검증을 진행한 것이다. 구조적 preflight 이후의 실제 model request, candidate container start, Codex remote exec, 의미 평가, auth file/token inspection은 시작하지 않았다.

적용 저장소/브랜치:

- C:\DevWorks\thinking-skills
- feat/feynman-thinking-v0.5-draft
- 시작 HEAD: 6ac5f4a (docs: finalize native Windows smoke log)
- 시작 working tree: clean
- shell: Windows PowerShell
- OS boundary: native Windows control plane + Docker Desktop Linux backend

기존 평가 전용 C:\Users\wotmd\.codex-feynman-eval은 보존했다. 이번 작업에서도 로그인 파일·토큰·auth status 원문·전체 환경변수·계정 식별 정보를 읽거나 출력하지 않았다. OpenAI Platform API/API key 경로는 사용하지 않았다. 개발 대화와 handoff 문서는 baseline candidate에 전달하지 않았다.

## 1. Concrete model 문서 확인

실행한 명령/확인:

    Get-Content C:\Users\wotmd\.codex\skills\.system\openai-docs\SKILL.md
    OpenAI 공식 Codex 모델 문서 확인: https://learn.chatgpt.com/docs/models

관찰:

- 공식 문서는 CLI에서 `--model`/`-m`으로 concrete model을 지정할 수 있다고 설명하지만, 모델 availability는 rollout·로그인 상태·client에 의존한다.
- 이번 로컬 계정의 실제 configured default model ID를 auth/session 내용에서 추출하지 않았다.
- 따라서 LOG-026의 `model-default`는 여전히 구조적 artifact metadata placeholder이며, executor에 넘길 concrete model ID 확정으로 간주하지 않는다.

## 2. Docker CLI와 이미지 읽기 전용 재확인

사용자 Docker config/helper를 읽지 않도록 다음 빈 설정 경로를 사용했다.

    C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config

샌드박스 안에서 실행한 읽기 전용 호출:

    & C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe --config C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config version --format '{{.Server.Version}}|{{.Server.Os}}|{{.Server.Arch}}'
    & C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe --config C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config image inspect feynman-codex-remote:local --format '{{.Id}}'

결과:

    permission denied while trying to connect to the Docker API at npipe:////./pipe/docker_engine

named pipe 권한 문제인지 Docker Desktop server 문제인지 분리하기 위해, 동일한 읽기 전용 두 명령만 권한 승인된 호스트 호출로 재실행했다.

결과:

    29.7.2|linux|arm64
    sha256:dab903a5999b1d3165a70de99147029809fa26d3cb1881b7c7790aac185a4726

이는 Docker Desktop server와 `feynman-codex-remote:local` 이미지 metadata가 응답함을 확인하지만, container create가 정상이라는 뜻은 아니다.

## 3. Final artifact create canary 시도

대상 artifact root:

    C:\DevWorks\feynman-smoke-preflight-native-6c6849e8feee4155a10e261ec175927b

대상 environment:

    ordinal-1-feynman-v05\remote-environment.toml

먼저 TOML의 `run` 첫 인자를 `create`로 치환해야 inspect용 argv가 된다는 점을 확인했다. 앞선 잘못된 진단 호출은 `docker create run ...` 형태가 되어 Docker가 `run`을 image로 해석하는 경로였다. 이 호출의 진단 client는 식별 후 중단했다. 이 오류를 성공이나 artifact failure로 기록하지 않았다.

이후 TOML에서 읽은 canonical 인자를 그대로 사용해, model이나 Codex를 시작하지 않는 정확한 create canary를 한 번 실행했다.

핵심 argv 계약:

    create --name feynman-tool-subscription-preflight-20260909-ordinal-1-feynman-v05
    --network none --cap-drop ALL --security-opt no-new-privileges --read-only --user 1000:1000
    --tmpfs /tmp:rw,nosuid,nodev
    C:\DevWorks\feynman-smoke-preflight-native-6c6849e8feee4155a10e261ec175927b\ordinal-1-feynman-v05\candidate:/run/candidate:rw
    C:\DevWorks\feynman-smoke-preflight-native-6c6849e8feee4155a10e261ec175927b\ordinal-1-feynman-v05\ephemeral-home:/run/home:rw
    C:\DevWorks\feynman-smoke-preflight-native-6c6849e8feee4155a10e261ec175927b\ordinal-1-feynman-v05\candidate-codex-home:/run/codex:rw
    C:\DevWorks\feynman-smoke-preflight-native-6c6849e8feee4155a10e261ec175927b\ordinal-1-feynman-v05\candidate-temp:/run/temp:rw
    --workdir /run/candidate feynman-codex-remote:local
    env -i HOME=/run/home CODEX_HOME=/run/codex PATH=/usr/local/bin:/usr/bin:/bin
    PYTHONDONTWRITEBYTECODE=1 TMPDIR=/run/temp codex exec-server --listen stdio

권한 승인된 Docker 호출 결과:

- 60초 이상 stdout/stderr 없이 create client가 정지했다.
- Ctrl+C로 해당 진단 client만 중단했다.
- 대상 이름으로 `docker ps -a`를 읽기 전용 조회했을 때 남은 container가 없었다.
- container start, `codex exec-server`, `codex --version`, model request는 실행되지 않았다.

추가로 image만 대상으로 하는 단순 create diagnostic도 응답하지 않았다.

    docker create --name feynman-native-local-image-diagnostic feynman-codex-remote:local true

이 역시 container를 생성하지 못한 채 client가 정지했고, 식별한 진단 process만 중단했다. Docker Desktop 관련 process는 읽기 전용으로 확인했으며 Docker Desktop service, image, 기존 exited container는 재시작·삭제·변경하지 않았다.

현재 판정:

    final artifact same-profile Docker create/inspect canary = incomplete

이는 auth gate failure, path mapping validation failure, candidate/model failure로 판정하지 않는다. 읽기 전용 `version`/`image inspect`는 성공하지만 create/ps API 요청이 정지하는 Docker Desktop 응답성 문제로 한정한다.

## 4. Native path mapping 후속 계약 audit

확인한 파일:

- tooling/feynman_path_mapping.py
- tooling/feynman_remote_exec_environment.py
- tooling/feynman_boundary_probe.py
- tooling/feynman_boundary_probe_verify.py
- tooling/feynman_runner_attestation.py
- tests/test_feynman_path_mapping.py
- tests/test_feynman_boundary_probe.py

관찰:

- runner job과 remote environment는 native Windows host source를 `/run/candidate`, `/run/home`, `/run/codex`, `/run/temp` Linux destination으로 분리한다.
- boundary probe artifact의 각 observation은 `path` 문자열 하나만 기록하고, verifier는 그 문자열이 evaluator-side `Path.absolute()`와 같아야 한다고 검사한다.
- 기존 GitHub reference workflow는 probe script를 `/probe/feynman_boundary_probe.py`에 read-only bind하고, probe 대상 path도 POSIX identity namespace를 전제로 한다.
- native profile의 remote executor는 undeclared read-only host bind를 거부하고 probe script를 candidate image에 포함하지 않으므로, native same-profile probe를 현재 v1 verifier에 억지로 연결하면 Windows host path와 Linux container path를 잘못 같은 값으로 비교할 위험이 있다.

수정 이유/결정:

- Docker create가 확인되지 않은 상태에서 probe schema, attestation, workflow를 추측으로 넓게 수정하지 않았다.
- 다음 구현은 host source ↔ container destination과 protected sentinel의 명시적 namespace contract를 정한 뒤, probe artifact schema·verifier·attestation·workflow·회귀 테스트를 함께 변경해야 한다.
- 따라서 이번 log에서는 이 항목을 “native migration의 후속 설계/구현 pending”으로 남기며, 현재 preflight 통과를 실제 boundary evidence로 승격하지 않는다.

## 5. 증거 범위 표

통과/확인:

- LOG-022의 이전 direct local auth gate: ChatGPT subscription auth contract 통과
- LOG-026의 model-free structural preflight: 두 ordinal 모두 `ready-for-local-chatgpt-session-check`
- LOG-025의 별도 native host-to-Linux mapping canary: 당시 임시 container create/inspect/start/version 통과
- 이번 turn의 Docker server/image 읽기 전용 확인: 29.7.2, linux/arm64, expected image digest

이번 turn에서 통과하지 못했거나 실행하지 않은 것:

- LOG-026에서 생성한 최종 artifact의 same-profile create/inspect
- native same-profile boundary probe report
- candidate remote exec 및 Codex version inside final artifact
- concrete subscription model request
- smoke answer, trace/final, attestation v3, runner-job-link v3, review/gate/result v4

## 6. Commit/push 상태

이번 log 작성 전 확인:

    git status --short --branch

결과:

    ## feat/feynman-thinking-v0.5-draft...origin/feat/feynman-thinking-v0.5-draft

LOG-027은 이번 진단 기록을 위한 유일한 저장소 변경이다. 다음 검증 후 이 log만 별도 commit/push하며, main merge와 force push는 하지 않는다. 기존 코드·브랜치 변경과 평가 전용 login home은 보존한다.

## 미완료 사항과 다음 행동

미완료:

1. Docker Desktop의 read-only API 응답과 create/ps API 정지 원인을 호스트 Docker Desktop 상태에서 분리 진단해야 한다.
2. native path mapping을 boundary probe/attestation까지 확장하는 명시적 path namespace contract가 필요하다.
3. concrete model ID와 job별 안전한 remote environment staging은 실제 실행 직전에 확정해야 한다.
4. auth gate는 이번 turn에 재실행하지 않았으며, 기존 LOG-022 evidence와 이번 structural preflight를 혼동하지 않아야 한다.

다음 한 행동은 Docker Desktop service/image/container를 삭제하거나 재설정하지 않고, create endpoint가 정상 응답하는지 호스트 상태를 확인한 뒤 final artifact create/inspect만 재검증하는 것이다. 그 전까지 actual model evaluation은 시작하지 않는다.
