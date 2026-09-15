# LOG-029 — Windows autopilot portability verification

작성일: 2026-09-09 (Asia/Seoul)

## 범위와 시작 상태

이번 작업은 사용자가 요청한 “사람의 개입이 필요 없는 단계까지”의 저장소 내부 자동 진행이다. 직전 blocker인 Docker Desktop container lifecycle endpoint는 별도로 보존하고, 그 endpoint가 회복되기 전에는 실제 candidate/model 평가를 시작하지 않는다. 이번 목표는 native Windows path-mapping 구현이 Windows 테스트와 skill 구조 검증에서 회귀 없이 표현되는지 확인하고, 남은 host-level blocker를 명확히 기록하는 것이다.

적용 저장소/브랜치:

- 저장소: `Ronaldony/thinking-skills`
- 경로: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `db6893d` (`docs: revalidate Docker lifecycle endpoint`)
- 시작 working tree: clean
- shell: Windows PowerShell

적용 지침:

    Get-Content C:\Users\wotmd\.codex\skills\.system\skill-creator\SKILL.md -Encoding UTF8

`skill-creator` 지침을 전체 확인했다. 저장소에 적용되는 `AGENTS.md`는 기존 재개 확인과 동일하게 발견되지 않았다. 기존 평가 전용 홈 `C:\Users\wotmd\.codex-feynman-eval`은 보존했다. 로그인 파일, 토큰, 원문 auth 상태, 전체 환경변수, 계정 식별 정보는 읽거나 출력하지 않았다. OpenAI Platform API와 API key는 사용하지 않았다.

## 1. Windows 전체 테스트의 최초 관찰

실행 명령:

    python -m unittest discover -s tests

최초 결과:

    Ran 275 tests in 8.497s
    FAILED (errors=50, skipped=4)

실패는 production path validator의 오작동으로 단정하지 않고 Windows fixture가 POSIX 전용 가정을 가지고 있는지 분류했다.

- Windows temporary candidate가 사용자 프로필 아래에 만들어지면서 ambient `C:\Users\wotmd\.agents\skills`가 evaluation preflight에 보이는 hermetic-fixture 오류가 있었다.
- 여러 테스트가 `read_write_mounts`에 Windows host path를 직접 넣었지만 production contract는 container destination을 요구한다. Windows에서는 host source와 `/run/candidate`, `/run/home`, `/run/codex`, `/run/temp` 목적지를 분리해야 한다.
- Windows PowerShell의 기본 text encoding으로 UTF-8 fixture를 읽고 써서 cp949 decode/encode 오류가 발생했다.
- directory symlink는 현재 Windows 권한/정책에서 만들 수 없는 테스트가 있었다.
- POSIX shebang fake Codex 파일은 Windows에서 executable로 직접 실행할 수 없었다.

판정 이유: production validator를 Windows에 맞추기 위해 약화하지 않고, 테스트 fixture가 native Windows boundary contract를 사용하도록 고쳤다. symlink와 사용자 프로필 ambient skill root처럼 호스트 capability에 의존하는 경우에만 조건부 skip을 사용했다.

## 2. 수행한 수정과 수정 이유

새 helper:

- `tests/feynman_test_support.py`
  - Windows에서 profile의 mount destination을 canonical `/run/...`로 바꾼다.
  - Windows에서 `boundary.mounts`에 host source → Linux container destination 매핑을 부착한다.
  - non-Windows에서는 기존 POSIX fixture identity를 유지한다.

Windows portability를 반영한 테스트:

- `tests/test_feynman_eval_preflight.py`
  - 사용자 프로필의 ambient `.agents/skills`가 존재할 때 “깨끗한 환경”을 보장할 수 없는 두 fixture를 조건부 skip한다.
  - `ROOT.parent` 아래 temp를 만들려는 시도는 sandbox의 workspace 외부 쓰기 제한으로 `tempfile.mkdtemp`에서 정지하여 되돌렸다. 테스트가 실제로 검증해야 할 경계와 무관한 외부 경로 쓰기를 추가하지 않았다.
- `tests/test_feynman_eval_results.py`
- `tests/test_feynman_runner_job_validate.py`
- `tests/test_feynman_runner_job.py`
- `tests/test_feynman_remote_exec_environment.py`
- `tests/test_feynman_remote_exec_reference_result.py`
- `tests/test_feynman_runner_job_link.py`
- `tests/test_feynman_runner_attestation.py`
  - Windows host path와 container destination을 분리하고 native mount mapping을 사용한다.
  - Windows fixture의 UTF-8 read/write를 명시한다.
  - attestation filesystem root는 실제 Windows absolute path를 사용하되, container namespace 값은 `/run/...` contract를 사용한다.
- `tests/test_feynman_subscription_auth_gate.py`
- `tests/test_feynman_subscription_smoke_exec.py`
  - fake Codex를 Windows에서는 `.cmd` wrapper와 Python child script로 실행한다.
  - Windows shell이 주입하는 정상 시스템 변수(`COMSPEC`, `PROCESSOR_ARCHITECTURE`, `PROMPT`, `SYSTEMROOT`)를 safe allowlist 검증에 반영한다.
  - fake state/final artifact는 UTF-8로 읽는다.
- `tests/test_feynman_subscription_run_preflight.py`
  - native profile/mount helper를 사용한다.
  - ambient user skill root 및 directory symlink capability에 대한 조건부 skip을 추가한다.
- `tests/test_feynman_package.py`
- `tests/test_feynman_legacy_package.py`
- `tests/test_feynman_review_pipeline.py`
  - UTF-8 fixture I/O를 명시하고, Windows symlink capability가 없는 경우 해당 capability fixture만 skip한다.

운영 코드, frozen plan, 실제 smoke artifact, 평가 전용 login home은 이번 수정에서 변경하지 않았다.

## 3. Windows 회귀 검증

최종 실행 명령:

    python -m unittest discover -s tests

최종 결과:

    Ran 275 tests in 9.437s
    OK (skipped=10)

10개 skip은 다음 호스트 capability/격리 조건에 한정된다.

- 사용자 프로필에 존재하는 ambient `.agents\skills` 때문에 hermetic preflight fixture를 만들 수 없는 경우
- Windows symlink 생성 권한이 없는 경우
- 기존에 플랫폼 capability에 따라 skip되는 항목

따라서 “275개 테스트 전부 실행”이라고 표현하지 않고, 275개가 실행 대상에 포함되었고 결과는 `OK`, 그중 10개는 호스트 capability에 따라 skip되었다고 기록한다.

## 4. Skill 구조 검증

최초 명령:

    python C:\Users\wotmd\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/feynman-thinking

관찰:

- validator 자체가 Windows 기본 cp949로 UTF-8 `SKILL.md`를 읽으려 하여 실패했다.
- 이는 skill 구조 오류가 아니라 validator process encoding 문제였다.

재실행 명령:

    python -X utf8 C:\Users\wotmd\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/feynman-thinking

결과:

    Skill is valid!

추가 확인:

    git diff --check

CRLF 변환 경고는 있었지만 whitespace 오류는 없었다.

## 5. Docker 및 평가 경계

Docker Desktop CLI는 다음 절대 경로를 사용했다.

    C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe

사용자 Docker config/helper 영향을 피하기 위해 빈 config를 지정한 읽기 전용 health 명령:

    docker --config C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}|{{.Containers}}|{{.Images}}|{{.Driver}}|{{.OperatingSystem}}'

관찰:

    29.7.2|linux|aarch64|3|4|overlayfs|Docker Desktop

최종 native smoke artifact에 대한 exact `docker create` 재검증도 수행했으나, stdout/stderr 없이 30초 이상 반환하지 않아 진단 client만 Ctrl+C로 중단했다. 이후 read-only info는 계속 `3|4|29.7.2`로 응답했고, 대상 container는 생성되지 않았으며 남은 Docker client process도 없었다. `docker ps -a` lifecycle query 역시 같은 정지 양상을 보여 추가 반복하지 않았다.

현재 판정:

    Docker read-only health: responsive
    Docker container lifecycle create/ps: unresponsive
    native Windows mapping fixture/test contract: green
    model request: not started
    actual evaluation: not started

이 blocker는 auth gate 실패나 candidate Codex 실행 실패를 뜻하지 않는다. LOG-022의 direct local ChatGPT subscription auth evidence와 LOG-026의 model-free structural preflight evidence를 실제 model evaluation과 혼동하지 않았다. Docker Desktop 재시작/초기화, image/container 삭제, context 변경, login 재실행은 하지 않았다.

## 6. 검증 범위와 미완료 사항

이번 작업으로 검증한 것:

- Windows native host path → Linux container `/run/...` destination fixture contract
- runner job/validation, remote exec environment/reference result, attestation/link, package/review pipeline의 Windows fixture compatibility
- Windows fake Codex wrapper를 사용하는 auth/smoke test harness
- 전체 unittest suite와 Feynman skill structural validator
- Docker Desktop read-only server health가 응답하는 상태

아직 검증하지 않은 것:

1. 최종 artifact의 Docker `create`/`inspect`/`start`/candidate `codex --version`
2. native same-profile boundary probe의 Windows host namespace와 Linux container namespace 계약
3. concrete subscription model ID 확정
4. auth-backed remote exec 및 실제 smoke answer
5. trace/final, attestation v3, runner-job-link v3, review/gate/result v4 lineage
6. 실제 모델 평가

선행 조건인 Docker lifecycle endpoint가 회복되기 전에는 위 1~6을 자동으로 시작하지 않는다. 다음 안전한 행동은 Docker Desktop 상태가 host에서 회복된 뒤, 같은 final artifact에 대해 create/inspect 한 번을 재검증하는 것이다. 그 다음에도 모든 model-free gate를 통과한 뒤에만 ChatGPT 구독 auth-backed 단계로 이동한다.

## 7. Commit/push 상태

이 log 작성 시점의 working tree에는 다음 Windows portability fixture 변경과 이 log가 아직 commit되지 않았다. 변경을 검증한 뒤 feature branch에만 commit하고 push한다. main merge와 force push는 하지 않는다.

커밋 전 확인 항목:

- `git diff --check`
- `python -m unittest discover -s tests`
- `python -X utf8 C:\Users\wotmd\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/feynman-thinking`
