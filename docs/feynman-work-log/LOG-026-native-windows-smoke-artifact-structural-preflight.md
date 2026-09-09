# LOG-026 — Native Windows smoke artifact and model-free structural preflight

작성일: 2026-09-09 (Asia/Seoul)

## 범위와 시작 상태

이번 작업은 LOG-025의 다음 행동인 native Windows host-to-Linux path mapping을 사용하는 실제 smoke artifact 생성과 model-free structural preflight까지 수행한 것이다. ChatGPT 구독 model turn, candidate 실행, 의미 채점은 시작하지 않았다.

적용 저장소/브랜치:

- C:\DevWorks\thinking-skills
- feat/feynman-thinking-v0.5-draft
- 시작 HEAD: bc959f08027fbe41b5647cb583d0e8023b5b1c09
- 시작 working tree: clean
- shell: Windows PowerShell
- OS boundary: native Windows control plane + Docker Desktop Linux backend

저장소에서 적용되는 AGENTS.md는 이전 확인과 동일하게 발견되지 않았다. 기존 평가 전용 C:\Users\wotmd\.codex-feynman-eval은 메타데이터만 확인했으며 로그인 파일·토큰·auth status 원문·전체 환경변수는 읽거나 출력하지 않았다. environments.toml이 아직 없다는 것만 확인했고, 기존 config.toml과 로그인 상태는 변경하지 않았다. OpenAI Platform API/API key는 사용하지 않았다.

## 1. 관련 지침과 입력 계약 확인

실행한 명령:

    Get-Content C:\Users\wotmd\.codex\skills\.system\skill-creator\SKILL.md
    git status --short --branch
    git log -1 --oneline
    rg --files tooling evals/feynman-thinking docs
    python tooling/feynman_subscription_smoke_plan.py --help
    python tooling/feynman_condition_workspace.py --help
    python tooling/feynman_runner_job.py --help
    python tooling/feynman_subscription_run_preflight.py --help

관찰:

- skill-creator 지침에 따라 기존 tooling을 재사용하고, 반복 가능한 Windows byte invariant에만 최소 수정하기로 했다.
- frozen spec은 schema v2, tools-10, baseline/feynman-v05, repeat 1, seed 20260908, chatgpt-subscription/codex-session, API-key 금지, model-default reasoning policy였다.
- candidate에는 문제·fixture·허용 skill만 제공하고 개발 대화와 handoff 문서는 전달하지 않는 기존 계약을 유지했다.

## 2. Docker Desktop과 artifact root 확인

Docker CLI가 현재 PowerShell PATH에 없으므로 검증된 설치 경로를 사용했다. 사용자 Docker config/credential helper를 읽지 않도록 빈 임시 DOCKER_CONFIG만 지정했다.

실행한 명령:

    $docker = 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
    $env:DOCKER_CONFIG = Join-Path $env:TEMP 'feynman-empty-docker-config'
    & $docker version --format 'client={{.Client.Version}} server={{.Server.Version}} os={{.Server.Os}} arch={{.Server.Arch}}'
    & $docker image inspect feynman-codex-remote:local --format 'image={{.Id}} repo={{index .RepoTags 0}}'

결과:

    client=29.7.2 server=29.7.2 os=linux arch=arm64
    image=sha256:dab903a5999b1d3165a70de99147029809fa26d3cb1881b7c7790aac185a4726 repo=feynman-codex-remote:local

첫 artifact root는 %TEMP% 아래에 만들었다. runner job 생성 시 다음 보호 오류가 발생했다.

    error: protected/candidate-owned path overlap: real_home/candidate_dir

이는 %TEMP%가 real_home=C:\Users\wotmd 아래이기 때문에 candidate를 실제 사용자 HOME 내부에 두지 못하게 한 정상 fail-closed 결과다. 해당 임시 artifact는 덮어쓰지 않았고, 이후 C:\DevWorks의 저장소 형제 경로를 사용했다.

최종 transient artifact root:

    C:\DevWorks\feynman-smoke-preflight-native-6c6849e8feee4155a10e261ec175927b

## 3. Frozen plan과 조건별 workspace 생성

실행한 명령:

    python tooling/feynman_subscription_smoke_plan.py --root C:\DevWorks\thinking-skills --spec evals\feynman-thinking\subscription-smoke-spec.json --output <artifact-root>\frozen-subscription-smoke-plan.json
    python tooling/feynman_condition_workspace.py --case tools-10 --condition feynman-v05 --candidate-dir <ordinal-1>\candidate --evaluator-dir <ordinal-1>\evaluator
    python tooling/feynman_condition_workspace.py --case tools-10 --condition baseline --candidate-dir <ordinal-2>\candidate --evaluator-dir <ordinal-2>\evaluator

실제 plan 결과:

- ordinal 1: tools-10 / feynman-v05 / repeat 1 / no followup
- ordinal 2: tools-10 / baseline / repeat 1 / no followup
- plan status: execution-plan-no-model-results
- smoke spec SHA-256: 10392760be6e51d0efe463a6a59ff63d87284613e9f4a8900d61f9aa4668aa46

workspace 결과:

- feynman-v05 candidate 9 files, evaluator 3 files, current runtime feynman-thinking skill 설치
- baseline candidate 3 files, evaluator 3 files, candidate skill root 없음
- 두 baseline candidate의 파일 목록에는 docs, work-log, 개발 대화, handoff 파일이 없었다.
- feynman-v05 candidate의 references/handoff-contract.md는 개발 대화가 아니라 skill package의 고정 runtime resource이며 baseline에는 포함되지 않았다.

## 4. Windows newline digest blocker와 최소 수정

첫 plan/workspace/profile/job 생성 후 ordinal 1 preflight를 실행했을 때 다음 오류가 발생했다.

    error: candidate task bytes differ from frozen prompt

원인은 Windows Path.write_text()가 task.txt의 LF를 CRLF로 변환하는 반면, candidate_prompt_sha256 계약은 (prompt + LF).encode(utf-8)인 LF canonical bytes를 요구하기 때문이었다. 인증이나 Docker path mapping의 실패가 아니었다.

수정 파일:

- tooling/feynman_eval_workspace.py: _write_utf8_exact() 추가, base workspace task.txt를 newline=""으로 기록
- tooling/feynman_condition_workspace.py: condition prompt overwrite를 newline=""으로 기록
- tests/test_feynman_condition_workspace.py: 실제 task bytes와 candidate prompt SHA 일치 및 CRLF 부재 회귀 테스트 추가
- 같은 테스트의 evaluator JSON read를 UTF-8로 고쳐 Windows 기본 cp949 의존도 제거

수정 이유는 플랫폼별 newline 변환이 frozen prompt digest를 깨뜨리지 않도록 canonical bytes를 생성기에서 보장하기 위해서다. API/auth 경로, sandbox 정책, 평가 조건은 변경하지 않았다.

검증:

    python -m unittest tests.test_feynman_condition_workspace tests.test_feynman_path_mapping
    Ran 12 tests ... OK

    python -m py_compile tooling/feynman_eval_workspace.py tooling/feynman_condition_workspace.py tests/test_feynman_condition_workspace.py
    exit 0

    git diff --check
    exit 0

수정 커밋:

- 92fe5e1 fix: preserve canonical prompt bytes on Windows
- feature branch push 완료: bc959f0..92fe5e1

## 5. Native boundary profile, runner job, remote environment

실측 Docker 값을 profile에 기록하고 tooling/feynman_boundary_profile.py로 검증했다.

profile 계약:

    backend=docker
    backend_version=29.7.2
    image=feynman-codex-remote:local
    image_id=sha256:dab903a5999b1d3165a70de99147029809fa26d3cb1881b7c7790aac185a4726
    network_mode=none
    run_as=1000:1000
    read_only_root=true
    no_new_privileges=true
    read_write_mounts=/run/candidate,/run/home,/run/codex,/run/temp
    tmpfs_mounts=/tmp
    candidate_env_keys=HOME,CODEX_HOME,PATH,PYTHONDONTWRITEBYTECODE,TMPDIR

Windows host source와 Linux destination은 다음처럼 분리됐다.

    candidate_dir   -> /run/candidate
    ephemeral_home  -> /run/home
    codex_home      -> /run/codex
    temp_dir        -> /run/temp

각 ordinal에 대해 tooling/feynman_runner_job.py, tooling/feynman_runner_job_validate.py, tooling/feynman_remote_exec_environment.py를 순서대로 실행했다. 결과는 두 job 모두 mount 4개, canonical destination 4개, Linux /run/candidate workdir였다. remote environment는 최종 control login home을 수정하지 않고 각 transient job root에 저장했다.

runner metadata의 model field는 실제 모델 호출을 피하기 위해 model-default로 기록했다. 이는 이번 structural artifact의 nonempty metadata일 뿐, 실제 executor에 넘길 concrete model ID가 확정됐다는 뜻이 아니다. 설치된 CLI --help는 model option만 보여 주고 계정의 configured default model ID를 노출하지 않으므로 임의로 모델명을 추측하지 않았다.

## 6. Model-free structural preflight 결과

각 ordinal에 대해 다음 canonical preflight를 실행했다.

    python tooling/feynman_subscription_run_preflight.py --plan <frozen-plan> --ordinal <1-or-2> --evaluator-case <ordinal>\evaluator\case.json --runner-job <ordinal>\runner-job.json --boundary-profile <boundary-profile.json> --remote-environment <ordinal>\remote-environment.toml --output <ordinal>\structural-preflight.json

두 결과 모두:

    verdict=ready-for-local-chatgpt-session-check
    runner_job_valid=true
    frozen_plan_match=true
    task_bytes_match=true
    boundary_profile_valid=true
    remote_environment_valid=true
    candidate_skill_preflight_valid=true
    control_home_protected=true
    model_request_started=false
    control_session_contents_read=false

이 결과가 증명하는 범위:

- frozen plan의 ordinal/case/condition/repeat/followup와 runner job이 일치한다.
- candidate task bytes와 frozen prompt digest가 일치한다.
- native Windows host path mapping과 Linux container destination이 canonical contract와 일치한다.
- candidate skill set이 조건 계약과 일치한다.
- evaluator/source/real HOME/control CODEX_HOME과 candidate-owned roots가 겹치지 않는다.
- ChatGPT subscription/codex-session 인증 구조이며 API-key 또는 candidate auth exposure가 없다.
- preflight가 control session contents를 읽지 않았고 model request를 시작하지 않았다.

이 결과가 증명하지 않는 범위:

- 실제 ChatGPT 구독 model turn 성공
- 실제 candidate container start 이후의 runtime/network boundary canary
- Codex remote exec server의 실제 실행 및 candidate tool 테스트 결과
- candidate 답변의 Feynman skill 성능
- post-run attestation/link/review/gate/result lineage

## 7. 회귀 범위

Windows focused tests:

    tests.test_feynman_condition_workspace
    tests.test_feynman_path_mapping
    Ran 12 tests ... OK

Docker Desktop Linux container에서 repository read-only mount, --network none, --user 0:0으로 전체 model-free suite를 재실행했다.

    Ran 275 tests in 15.288s
    OK (skipped=6)

앞서 별도로 실행한 Windows preflight fixture 묶음은 기존 POSIX-only profile fixture가 Windows host path를 read_write_mounts에 직접 넣어 profile validator에서 거부되는 한계를 보였다. canonical native artifact는 /run/... destination과 boundary.mounts를 사용해 통과했으며, POSIX fake executable/symlink fixture의 Windows 한계는 실제 smoke 성공으로 간주하지 않는다.

## 8. Commit/push와 보안 경계

실행한 명령:

    git add -- tooling/feynman_eval_workspace.py tooling/feynman_condition_workspace.py tests/test_feynman_condition_workspace.py
    git diff --cached --check
    git commit -m "fix: preserve canonical prompt bytes on Windows"
    git push origin feat/feynman-thinking-v0.5-draft

관찰:

- 코드 수정 commit 92fe5e1 push 완료
- 이 로그는 코드 push 이후 작성했다.
- LOG-026 최초 기록 commit 8b1141c push 완료
- main merge 없음
- force push 없음
- control login home에 environments.toml을 생성하지 않음
- API key/token 사용·주입·출력·해시·업로드 없음
- control CODEX_HOME을 candidate mount/env/argv에 노출하지 않음
- 개발 대화/handoff 문서를 baseline candidate에 전달하지 않음

## 미완료 사항과 다음 한 행동

미완료:

1. 실제 model ID가 아직 concrete하게 고정되지 않았다. model-default는 이번 preflight metadata placeholder다.
2. executor가 요구하는 canonical control CODEX_HOME/environments.toml은 아직 생성하지 않았다. 두 ordinal은 mount source가 다르므로 실제 실행 직전에 job별로 안전하게 준비해야 한다.
3. auth gate는 이전 LOG-022에서 chatgpt-subscription-authenticated로 통과했지만, 이번 turn에서는 다시 실행하지 않았다. preflight는 auth contents를 읽지 않는 구조 검사이고 auth gate와 동일한 증거가 아니다.
4. 실제 smoke, trace/final, boundary canary, attestation v3, runner-job-link v3, review/gate/result v4는 모두 pending이다.
5. Windows 전체 suite의 POSIX fake executable 및 symlink privilege fixture 한계는 별도 정리 대상이다.

다음 한 행동은 concrete subscription model ID를 정한 뒤, 각 job의 remote environment를 기존 control login home에 덮어쓰지 않는 안전한 staging/실행 계약으로 확정하고, 실행 직전 auth gate와 same-profile canary를 재검증하는 것이다. 그 전까지 canonical executor로 model request를 시작하지 않는다.
