# LOG-031 — Native boundary and auth gates passed

작성일: 2026-09-10 (Asia/Seoul)

## 범위와 시작 상태

이번 작업은 Docker Desktop 정상화 이후 수행한 model-free 선행 검증이다. 목표는 Docker lifecycle, native Windows host path → Linux container path mapping, candidate image Codex runtime, 두 ordinal의 boundary canary, dedicated ChatGPT subscription auth gate, structural preflight를 순서대로 확인하는 것이었다.

실제 모델 평가, Codex model request, candidate task 전송, auth-backed remote exec는 시작하지 않았다. current smoke plan의 model-default는 concrete model ID가 아니며, control CODEX_HOME의 environments.toml도 실제 실행을 위해 staging하지 않았다.

적용 저장소/브랜치:

- 저장소: Ronaldony/thinking-skills
- 경로: C:\DevWorks\thinking-skills
- 브랜치: feat/feynman-thinking-v0.5-draft
- 시작 HEAD: f2fcdee (docs: recheck Docker lifecycle endpoint)
- 시작 working tree: clean
- shell: Windows PowerShell

이번 turn에 skill-creator 지침 전체를 읽었다.

    Get-Content C:\Users\wotmd\.codex\skills\.system\skill-creator\SKILL.md -Encoding UTF8

적용되는 AGENTS.md는 발견되지 않았다. 기존 평가 전용 홈 C:\Users\wotmd\.codex-feynman-eval은 보존했다. 로그인 파일·토큰·원문 auth status·전체 환경변수·계정 식별 정보는 읽거나 출력하지 않았다. OpenAI Platform API/API key는 사용하지 않았다.

## 1. Docker Desktop과 lifecycle

사용한 Docker CLI:

    C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe

사용자 config/helper를 피하기 위해 빈 config를 지정했다.

    docker --config C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}|{{.Containers}}|{{.Images}}|{{.Driver}}|{{.OperatingSystem}}'

결과:

    29.7.2|linux|aarch64|3|4|overlayfs|Docker Desktop

추가 read-only 결과:

    docker ... version --format '{{.Client.Version}}|{{.Server.Version}}|{{.Server.Os}}|{{.Server.Arch}}'
    29.7.2|29.7.2|linux|arm64

    docker ... context ls --format '{{.Name}}|{{.Current}}|{{.DockerEndpoint}}'
    default|true|npipe:////./pipe/docker_engine

image inspect에서 존재하지 않는 optional Config.WorkingDir 필드를 참조한 첫 template 명령은 진단 command error였다. 수정한 read-only inspect 결과는 다음과 같다.

    sha256:dab903a5999b1d3165a70de99147029809fa26d3cb1881b7c7790aac185a4726|linux|arm64|["docker-entrypoint.sh"]|["node"]

최종 native artifact의 exact create/inspect/cleanup:

    CREATE_EXIT=0
    CREATE_ID=2f25d17b45fbb51214b2553719de73d26c0611c81ca2a20ef5d232ea02a145f6
    INSPECT_EXIT=0
    INSPECT_STDOUT=...|created|/run/codex;/run/temp;/run/candidate;/run/home;
    REMOVE_EXIT=0

version canary의 첫 create는 Docker backend 재시작 직후 45초 timeout이었고 container는 생성되지 않았다. 같은 native 경계를 docker run --rm으로 한 번 재검증했다.

    VERSION_CANARY_EXIT=0
    VERSION_CANARY_STDOUT=codex-cli 0.153.4
    VERSION_CANARY_STDERR=

Docker backend process는 Responding=True였다. 중간에 빈 Docker config directory가 이전 cleanup으로 없어져서 orchestrator가 중단된 경우에는 사용자 config를 사용하지 않고 빈 directory만 재생성했다. baseline canary의 첫 호출은 DockerDesktop.exe와 docker.exe를 혼동한 경로 오타로 preflight에서 중단됐고, Docker 작업은 시작되지 않았다.

## 2. Native path namespace 구현

기존 boundary probe는 observation의 path 하나를 evaluator-side host path와 동일시했다. Windows에서는 C:\ host source와 /run/... Linux container destination이 다른 namespace이므로 이 비교는 잘못된 성공을 만들 수 있다.

변경 파일과 이유:

- tooling/feynman_boundary_probe.py
  - shared 동작을 유지하고 native 실행 시 path_namespace=container 및 container observation path를 기록한다.
- tooling/feynman_boundary_probe_verify.py
  - host marker postcheck path와 container observed path를 별도 검증한다.
  - native path는 normalized absolute POSIX path여야 하며 모든 observation이 container namespace여야 한다.
  - legacy shared artifact는 계속 검증할 수 있다.
- evals/feynman-thinking/boundary-probe-artifact.schema.json
- evals/feynman-thinking/boundary-probe-report.schema.json
  - optional path namespace를 schema에 반영했다.
- tests/test_feynman_boundary_probe.py
  - host postcheck/container observation 분리 성공, host path masquerading 거부, namespace 기록을 검증하는 3개 테스트를 추가했다.

## 3. Candidate image용 probe와 실행기

candidate image에는 sh/node/codex가 있었고 Python은 없었다. Python probe 실행을 가정하지 않고 다음을 추가했다.

- tooling/feynman_boundary_probe_node.mjs
  - Python probe와 동일한 synthetic read/write/environment/network artifact contract를 Node 표준 library로 구현한다.
  - native eval 실행에서는 host가 계산한 program SHA를 artifact에 바인딩한다.
  - auth material과 protected file contents는 읽지 않는다.
- tooling/feynman_native_boundary_canary.py
  - validated runner job/profile의 canonical native mounts를 재사용한다.
  - loopback network reference를 준비하고 Docker create/inspect/start/cleanup를 수행한다.
  - host marker postcheck와 container /run/... observation을 native verifier로 연결한다.
  - 생성한 진단 container와 candidate-side temporary canary directory만 정리한다.
  - 모델 요청과 control login home staging은 수행하지 않는다.

문법 검증:

    node --check tooling\feynman_boundary_probe_node.mjs
    python -m py_compile tooling\feynman_native_boundary_canary.py tooling\feynman_boundary_probe.py tooling\feynman_boundary_probe_verify.py

두 명령 모두 exit 0이었다.

## 4. 두 ordinal native boundary canary

ordinal 1 Feynman과 ordinal 2 baseline에 각각 다음 orchestrator를 실행했다.

    python -X utf8 tooling\feynman_native_boundary_canary.py --runner-job <ordinal>\runner-job.json --boundary-profile <boundary-profile.json> --docker <DockerDesktop>\resources\bin\docker.exe --docker-config <empty-config> --output-dir <ordinal>\boundary-canary-20260910 --timeout-seconds 60

두 결과 모두:

    verdict=native-boundary-canary-passed
    container_inspect_verdict=docker-inspect-matches-profile
    path_namespace=container
    probe_report_verdict=passed
    failed_probes=[]
    not_required_probes=[]
    observed_env_keys=[CODEX_HOME, HOME, PATH, PYTHONDONTWRITEBYTECODE, TMPDIR]

검증한 경계:

- network none
- all Linux capabilities dropped
- no-new-privileges
- read-only root
- UID 1000:1000
- /tmp tmpfs
- host source → /run/candidate, /run/home, /run/codex, /run/temp
- protected reads/writes denied
- candidate write allowed
- secret-like environment key 없음

baseline에는 개발 대화나 handoff 문서를 전달하지 않았고, probe는 synthetic marker만 사용했다.

## 5. ChatGPT subscription auth gate

실행 명령:

    python -X utf8 tooling\feynman_subscription_auth_gate.py check --control-codex-home C:\Users\wotmd\.codex-feynman-eval --codex-bin C:\Users\wotmd\AppData\Local\OpenAI\Codex\bin\8618603f6caa97b3\codex.exe --timeout-seconds 30 --output <artifact-root>\auth-gate-20260910.json

결과:

    verdict=chatgpt-subscription-authenticated
    codex_cli=codex-cli 0.153.4
    authentication.mode=chatgpt-subscription
    authentication.source=codex-session
    api_key_auth_allowed=false
    raw_status_output_preserved=false
    credential_files_read_by_gate=false

gate는 version과 forced ChatGPT login status를 coarse classification에만 사용했다. raw status와 account/token 내용은 저장하지 않았다. 로그인 재실행은 하지 않았다.

## 6. Structural preflight 재검증

ordinal 1과 ordinal 2에 대해 feynman_subscription_run_preflight.py를 각각 실행했다. 두 결과 모두 다음과 같았다.

    verdict=ready-for-local-chatgpt-session-check
    runner_job_valid=true
    frozen_plan_job_match=true
    candidate_task_bytes_match=true
    boundary_profile_valid=true
    remote_environment_valid=true
    candidate_skill_preflight_valid=true
    control_codex_home_protected=true

ordinal artifact directory에 결과를 쓰려던 첫 시도는 [Errno 13] Permission denied였다. 기존 artifact를 덮어쓰지 않고 새 사용자 Temp output directory로 재실행했다.

## 7. 회귀 검증

실행 명령:

    python -X utf8 -m unittest discover -s tests
    python -X utf8 C:\Users\wotmd\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/feynman-thinking
    git diff --check

결과:

    Ran 278 tests in 11.729s
    OK (skipped=10)
    Skill is valid!

git diff --check는 CRLF 변환 warning만 출력하고 whitespace 오류 없이 통과했다.

## 8. 실제 모델 평가 경계

통과한 선행 조건:

- Docker lifecycle create/inspect/start/cleanup
- candidate image model-free codex --version
- native host/container path namespace 분리
- 두 ordinal Docker boundary canary
- dedicated ChatGPT subscription auth gate
- 두 ordinal structural preflight

아직 실행하지 않은 것:

1. feynman_subscription_smoke_exec.py
2. control CODEX_HOME의 job-specific environments.toml staging
3. concrete model ID를 지정한 Codex model request
4. smoke trace/final, attestation/link, review/gate/result lineage
5. Feynman skill 효과 평가

model-default를 실제 모델명으로 추측하지 않았다. 계정 entitlement나 configured default를 auth/session 내용에서 추출하지 않았다. concrete model ID가 정해지면 reversible job-specific environment staging을 먼저 수행하고, 실행 직전 auth gate와 native canary를 다시 확인한 뒤에만 smoke executor를 시작한다.

## 9. Commit/push 상태

이 log 작성 시점의 working tree에는 native namespace 구현, Node probe/orchestrator, schema 및 test 변경과 이 log가 아직 commit되지 않았다. 검증 후 feature branch에만 commit/push한다. main merge와 force push는 하지 않는다.
