# LOG-028 — Docker lifecycle endpoint revalidation

작성일: 2026-09-09 (Asia/Seoul)

## 범위와 시작 상태

이번 작업은 LOG-027에서 미완료로 남은 Docker Desktop lifecycle endpoint를 재확인한 것이다. 목적은 native Windows path-mapping 구현이나 ChatGPT 구독 auth gate의 실패 여부가 아니라, 최종 smoke artifact에 대해 Docker `create`가 실제로 응답하는지 분리하는 것이다.

실제 model request, candidate container start, Codex remote exec, 의미 평가, auth file/token inspection은 시작하지 않았다.

적용 저장소/브랜치:

- C:\DevWorks\thinking-skills
- feat/feynman-thinking-v0.5-draft
- 시작 HEAD: 2760d60 (docs: log native Windows final canary blocker)
- 시작 working tree: clean
- shell: Windows PowerShell

기존 평가 전용 C:\Users\wotmd\.codex-feynman-eval은 보존했다. 로그인 파일·토큰·auth status 원문·전체 환경변수·계정 식별 정보는 읽거나 출력하지 않았다. OpenAI Platform API/API key는 사용하지 않았다.

## 1. Skill 지침과 저장소 상태

스킬 개발 작업이므로 다음 지침을 다시 읽었다.

    Get-Content C:\Users\wotmd\.codex\skills\.system\skill-creator\SKILL.md -Encoding UTF8

관찰:

- 기존 native path-mapping 코드와 LOG-027의 보수적 canary 중단 결정을 유지했다.
- `AGENTS.md`는 이전 확인과 동일하게 저장소에 없다.
- branch는 원격과 동일했고, 시작 시 미추적·수정 파일이 없었다.

## 2. Docker Desktop read-only health 재확인

사용자 Docker config/helper를 피하기 위해 빈 설정 경로를 명시했다.

    C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config

실행한 읽기 전용 명령:

    docker --config C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}|{{.Containers}}|{{.Images}}|{{.Driver}}|{{.OperatingSystem}}'

결과:

    29.7.2|linux|aarch64|3|4|overlayfs|Docker Desktop

해석:

- Docker Desktop server endpoint와 image/container metadata summary는 응답한다.
- `Containers=3`, `Images=4`는 LOG-026/027의 진단 container가 남아 있지 않음을 간접적으로 확인하는 값이다.
- 이 명령은 container lifecycle 동작이나 candidate 코드를 실행하지 않는다.

## 3. 최종 native artifact create 재검증

대상:

    C:\DevWorks\feynman-smoke-preflight-native-6c6849e8feee4155a10e261ec175927b\ordinal-1-feynman-v05\remote-environment.toml

TOML에서 `run`을 `create`로 바꾼 exact argv를 사용했다. 유지한 경계:

- `--network none`
- `--cap-drop ALL`
- `--security-opt no-new-privileges`
- `--read-only`
- `--user 1000:1000`
- `/tmp` tmpfs
- host source 4개를 `/run/candidate`, `/run/home`, `/run/codex`, `/run/temp`로 매핑
- `/run/candidate` workdir
- `env -i`와 candidate-safe `HOME`, `CODEX_HOME`, `PATH`, `TMPDIR`
- image `feynman-codex-remote:local`
- image command `codex exec-server --listen stdio`는 create 시 실행되지 않음

권한 승인된 Docker create를 한 번 실행했다.

관찰:

- 30초 이상 stdout/stderr 없이 Docker client가 정지했다.
- Ctrl+C로 이 진단 client만 중단했다.
- 이어서 동일한 Docker info summary를 읽었고 결과는 다시 `3|4|29.7.2`였다.
- 대상 container name으로 생성된 container가 없음을 확인했다. 별도 `docker ps -a` client는 같은 lifecycle API 정지 양상을 보였으므로 더 반복하지 않았다.
- 남은 docker client process는 없었다.

판정:

    Docker read-only health = responsive
    Docker container lifecycle create/ps = unresponsive
    final artifact same-profile canary = incomplete

이 결과는 다음을 의미하지 않는다.

- auth gate가 실패했다는 의미가 아니다.
- native Windows path mapping이 validator에서 거부됐다는 의미가 아니다.
- image digest가 다르거나 model request가 실패했다는 의미가 아니다.
- candidate의 Codex 실행 실패가 아니다.

현재 가장 좁은 재현은 “Docker Desktop이 version/info/image metadata에는 응답하지만 container lifecycle API 호출은 반환하지 않는다”이다. Docker Desktop service 재시작, image 삭제, container 삭제, context 변경은 하지 않았다.

## 4. 코드 및 증거 범위

변경하지 않은 통과 증거:

- LOG-022: 이전 direct local ChatGPT subscription auth gate 통과
- LOG-025: 별도 native host-to-Linux mapping canary 통과
- LOG-026: 두 ordinal의 model-free structural preflight 통과
- LOG-027: boundary probe가 Windows host namespace와 Linux container namespace를 직접 동일시하면 안 된다는 audit

이번 작업에서 새로 확인한 범위:

- Docker Desktop 읽기 전용 server health 및 image/container summary
- 최종 artifact exact create argv의 lifecycle 정지 재현
- create 이후 container 미생성 및 diagnostic process 정리

여전히 실행하지 않은 범위:

- final artifact inspect/start/version
- native same-profile boundary probe report
- concrete subscription model request
- smoke answer, trace/final, attestation v3, runner-job-link v3, review/gate/result v4

## 5. 회귀 검증

실행한 명령:

    python -m unittest tests.test_feynman_path_mapping tests.test_feynman_boundary_probe
    git diff --check

결과:

    Ran 18 tests in 0.230s
    OK

`git diff --check`도 오류 없이 통과했다. 테스트는 native mount destination/source 분리, runner validation, Docker argv, probe denial/postcheck 및 namespace-hidden ENOENT 동작을 다루며 실제 model 평가를 시작하지 않는다.

## 6. Commit/push 상태

이번 작업의 저장소 변경은 이 진단 log 하나뿐이다. code, frozen plan, artifact, control login home은 변경하지 않았다.

다음 검증 후 `docs/feynman-work-log/LOG-028-docker-lifecycle-endpoint-revalidation.md`만 commit하고 feature branch에 push한다. main merge와 force push는 하지 않는다.

## 미완료 사항과 다음 행동

미완료:

1. Docker Desktop lifecycle API 정지 원인은 host Docker Desktop 상태에서 추가 진단이 필요하다.
2. native path mapping을 boundary probe/attestation까지 확장할 path namespace contract가 아직 pending이다.
3. concrete model ID와 job별 remote environment staging은 실제 실행 직전에 확정해야 한다.
4. auth gate는 이번 작업에서도 재실행하지 않았으며, LOG-022 evidence와 structural preflight를 혼동하지 않는다.

다음 한 행동은 Docker Desktop을 재설정하거나 데이터를 삭제하지 않고, lifecycle endpoint가 회복된 뒤 최종 artifact create/inspect를 재검증하는 것이다. create/inspect가 통과하기 전에는 candidate start, auth-backed model request, 실제 평가를 시작하지 않는다.
