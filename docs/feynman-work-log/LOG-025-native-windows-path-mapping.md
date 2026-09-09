# LOG-025 — Native Windows host-to-Linux path mapping

작성일: 2026-09-09 (Asia/Seoul)

## 범위

이 작업은 native Windows control plane + Docker Desktop Linux candidate boundary를 선택한 뒤, Windows 호스트 경로와 Linux container 경로가 같은 문자열로 재사용되던 실행 계약을 분리한 것이다. ChatGPT 구독 인증을 변경하거나 실제 모델 평가를 실행하는 작업은 아니었다.

적용 저장소/브랜치:

- C:\DevWorks\thinking-skills
- feat/feynman-thinking-v0.5-draft
- 시작 HEAD: 1eb15047594e5649c926787f62b76fdd3275415a
- 구현 커밋: e47420a (feat: map native Windows paths to Linux containers)
- 구현 커밋 push: 완료, origin/feat/feynman-thinking-v0.5-draft에 반영

AGENTS.md는 저장소에서 발견되지 않았다. 기존 평가 전용 control CODEX_HOME은 읽거나 변경하지 않았고, 로그인 파일/토큰/전체 환경변수는 출력·복사·해시·업로드하지 않았다. OpenAI Platform API와 API key는 사용하지 않았다. 개발 대화와 handoff 문서는 candidate 입력으로 전달하지 않았다.

## 시작 상태 확인

실행한 명령:

    git status --short --branch
    git log -3 --oneline --decorate
    rg --files -g 'AGENTS.md' -g '!**/.git/**'

관찰 결과:

- 작업 트리는 clean이었다.
- local/remote HEAD는 1eb1504에서 일치했다.
- 적용되는 AGENTS.md는 없었다.
- 관련 handoff와 LOG-019/020/021~024, boundary/runner/remote-exec 코드를 읽고 migration 지점을 확인했다.

기존 auth gate의 현장 재검증 결과는 이전 LOG-022에 기록된 최종 결과를 그대로 유지했다: dedicated control home에서 chatgpt-subscription-authenticated, Codex CLI 0.153.4. 이번 작업은 path/backend 경계 변경에 집중했으므로 재로그인이나 실제 model turn을 수행하지 않았다.

## 문제와 설계 결정

기존 계약은 runner-job.paths의 호스트 경로를 Docker -v source:source:rw, HOME, CODEX_HOME, TMPDIR, --workdir에 그대로 넣었다. Linux container에 Windows 경로를 같은 문자열로 전달하면 Docker source/destination namespace가 섞이고 container workdir가 유효하지 않다.

새 계약은 다음처럼 분리한다.

    runner-job.paths.candidate_dir  (Windows host) -> /run/candidate
    runner-job.paths.ephemeral_home (Windows host) -> /run/home
    runner-job.paths.codex_home     (Windows host) -> /run/codex
    runner-job.paths.temp_dir       (Windows host) -> /run/temp

- boundary-profile.read_write_mounts는 Linux container destination 집합이다.
- runner-job.boundary.mounts는 각 host source, POSIX destination, rw/ro access를 immutable job에 기록한다.
- 기존 POSIX synthetic fixture는 호환을 위해 source=destination identity mapping으로 읽지만, canonical /run/... profile은 explicit mapping을 요구한다. 이 fallback은 native Windows 계약으로 간주하지 않는다.
- runner-job schema v3와 attestation의 absolute_path가 POSIX /...뿐 아니라 Windows drive path C:\...도 표현하도록 수정했다.

## 구현 변경

1. tooling/feynman_path_mapping.py를 추가했다.
   - canonical destination 상수와 native mount 생성
   - host absolute path / POSIX container path 검증
   - explicit native mapping과 legacy identity mapping의 fail-closed 해석
2. feynman_runner_job.py가 canonical profile에서 boundary.mounts를 생성하고, feynman_runner_job_validate.py가 source root와 destination/profile의 정확한 대응 및 protected root 분리를 검증하게 했다.
3. feynman_remote_exec_environment.py가 mapping을 사용해 Docker -v 인자, container HOME, CODEX_HOME, TMPDIR, --workdir를 생성하게 했다.
4. feynman_docker_inspect.py/feynman_docker_reference_inspect.py가 선택된 runner job mapping을 받으면 Docker inspect의 mount Source도 비교하게 했다. feynman_remote_exec_reference_result.py는 native job일 때 이 검사를 연결한다.
5. native Windows smoke 실행기의 scrubbed PATH에 설치된 Docker Desktop CLI가 parent PATH에 없을 때의 per-user/Program Files 표준 위치를 제한적으로 추가했다. 환경변수 전체를 상속하지 않으며, 비밀 키 이름은 allowlist에 들어가지 않는다.
6. runner-job/attestation schema, local-smoke handoff, 평가 README에 namespace 계약을 문서화하고 native mapping/source tamper 테스트를 추가했다.

## 실제 검증 기록

### 1. 정적/Windows native fixture 검증

실행한 명령:

    python -m unittest tests.test_feynman_path_mapping
    python -m py_compile tooling\feynman_path_mapping.py tooling\feynman_runner_job.py tooling\feynman_runner_job_validate.py tooling\feynman_remote_exec_environment.py tooling\feynman_docker_inspect.py tooling\feynman_docker_reference_inspect.py tooling\feynman_remote_exec_reference_result.py tooling\feynman_subscription_smoke_exec.py
    python -c 'runner-job.schema.json/runner-attestation.schema.json JSON parse'
    git diff --check

관찰 결과:

- native mapping 테스트 6개 통과
- Python compile 통과
- 두 schema JSON parse 통과
- diff check 오류 없음
- 별도 path regex 확인에서 POSIX /run/candidate와 Windows C:\run\candidate 모두 허용됨

Windows에서 기존 auth-gate fixture까지 포함한 명령은 41 tests 중 5 errors였다. 오류는 제품 auth gate 판정이 아니라 기존 테스트 fake가 POSIX #!/usr/bin/env python3라 Windows WinError 193을 내는 문제 4건과, symlink 생성 권한이 없어 WinError 1314를 내는 fixture 1건이었다. 실제 설치된 codex.cmd/codex.exe의 auth gate 성공 결과와 혼동하지 않는다.

### 2. 실제 Docker Desktop backend 경계 확인

Docker CLI가 현재 Codex PowerShell PATH에 없어서 검증된 절대 경로 C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe를 사용했다. 임시 빈 DOCKER_CONFIG만 사용해 user credential helper/config를 읽지 않게 했다.

중간 진단과 수정:

- 첫 temporary PowerShell script는 $home가 예약된 $HOME 변수와 충돌해 시작 전에 중단됐다. 변수명을 $ephemeralHome으로 바꿨다.
- 다음 시도에서 Docker create exit는 0이었으나 PowerShell stdout capture가 container ID를 주지 않았다. name-based inspect로 바꿨다.
- 기존 작업에서 남은 exact project-generated exited container name과 충돌했으나 이를 삭제하지 않고 unique run/container name을 사용했다.
- Docker 29.7.2의 docker create가 --cidfile을 지원하지 않아 사용하지 않았다.
- PowerShell Set-Content -Encoding utf8의 BOM을 Python verifier가 거부해 inspect JSON을 BOM 없는 UTF-8로 기록하게 했다.

최종 실행은 모델을 호출하지 않고 다음 경로만 수행했다.

    generated runner job/profile
      -> canonical remote environment
      -> docker create (container not started)
      -> docker inspect
      -> feynman_docker_reference_inspect.py --runner-job
      -> cleanup of this unique stopped container and temporary directories

최종 관찰 결과:

    native_mapping_verdict=docker-inspect-matches-profile
    docker_server_version=29.7.2
    container_started=False
    host_sources_mapped_to_linux_destinations=4

### 3. Linux control/container compatibility suite

실행한 명령:

    docker run --rm --network none --user 0:0
      -v C:\DevWorks\thinking-skills:/repo:ro
      --workdir /repo python:3.12-slim
      python -m unittest discover -s /repo/tests

PowerShell에서는 Docker Desktop 절대 CLI와 빈 임시 DOCKER_CONFIG를 사용했다. 중간 첫 suite는 legacy container_path_for_key lookup 17 errors를 보여 주었고, legacy identity mapping fallback을 보완한 뒤 재실행했다. 최종 구현 commit 상태에서 다시 실행한 최종 결과:

    Ran 274 tests in 15.546s
    OK (skipped=6)

모든 테스트는 model-free였고, control login home나 credential material을 container에 mount하지 않았다.

## Commit/push

실행한 명령:

    git add -- <reviewed implementation/doc/test files>
    git diff --cached --check
    git commit -m "feat: map native Windows paths to Linux containers"
    git push origin feat/feynman-thinking-v0.5-draft

관찰 결과:

- commit e47420a 생성 완료
- 1eb1504..e47420a로 feature branch push 완료
- main 병합 없음
- force push 없음

LOG-025 문서 commit은 bd52681로 생성했고 origin/feat/feynman-thinking-v0.5-draft에 push 완료했다.

## 미완료 사항과 다음 행동

- 실제 ChatGPT 구독 model turn: 아직 수행하지 않았다. auth gate와 Docker mapping/backend 검증을 구분하며, 사용자가 명시한 frozen tools-10 × {baseline, feynman-v05} × repeat 1의 모든 structural preflight와 실제 실행 전 조건이 다시 확인되기 전에는 실행하지 않는다.
- Windows 전체 unit suite: POSIX fake executable과 symlink privilege fixture의 Windows 대응은 별도 작업이다. native mapping 구현과 Linux full suite에는 영향을 주지 않지만, 실제 Windows smoke executor를 평가하려면 Windows-native fake launcher/권한 독립 fixture가 필요하다.
- Docker CLI PATH: 현재 사용자 shell PATH에는 Docker Desktop CLI가 없어 canonical smoke 실행 시 scrubbed PATH 보강은 추가했지만, 최종 실행 전 generated remote environment가 같은 프로세스 PATH에서 docker를 찾는지 structural preflight에서 확인해야 한다.
- 기존 exited container: 이름 충돌을 일으킨 별도 exited project-generated container는 보존했다. 사용자 데이터/credential로 단정하지 않고 삭제하지 않았으므로, 필요하면 명시적 정리 작업으로 분리한다.
- 다음 행동은 native profile/job/remote environment를 실제 smoke artifact에 생성하는 model-free structural preflight까지 수행하는 것이다. 그 결과가 pass일 때만 사용자에게 실제 smoke 실행 여부를 묻거나 허용된 범위에서 다음 단계로 진행한다.
