# LOG-023 — Windows backend preflight remains blocked

- **시각(KST)**: 2026-09-09 18:28 이후
- **저장소**: `Ronaldony/thinking-skills`
- **브랜치**: `feat/feynman-thinking-v0.5-draft`
- **시작 HEAD**: `fb02f36acd363865e686aa2b2cbb9531c52dfa04`
- **목적**: LOG-022 이후 실제 smoke를 시작할 수 있는 Docker/WSL2/Linux 실행 경로가 이 로컬 Windows 환경에 있는지 재확인한다.
- **상태**: BLOCKED — 인증은 통과했지만 candidate Docker boundary 실행 backend가 없다.

## 1. 시작 상태 / DONE

- `git status --short --branch`: clean, feature branch가 origin과 일치.
- 기존 전용 Codex login home과 기존 증거는 건드리지 않았다.
- auth token, auth.json, credential contents, 전체 환경변수는 읽지 않았다.
- OpenAI Platform API, API key, 모델 요청은 사용하지 않았다.

## 2. 실제 실행 명령과 관찰

```powershell
Get-Command docker,podman,nerdctl,wsl,bash,ubuntu,codex -All
python -c "import shutil; ..."
docker --version
wsl.exe --status
wsl.exe --list --quiet
Get-Service -Name 'com.docker.service'
Get-Process -Name 'Docker Desktop','com.docker.backend','dockerd'
```

민감정보를 출력하지 않는 요약:

- `docker`, `podman`, `nerdctl`은 PATH에서 찾지 못했다.
- `wsl.exe`와 WindowsApps `bash.exe` shim은 존재하지만, distro/backend는 확인되지 않았다.
- `wsl.exe --status`는 이전 점검과 같이 access-denied 계열로 종료했고, `wsl.exe --list --quiet`도 exit `-1`로 끝났다.
- 흔한 Docker Desktop CLI 경로 4곳을 `Test-Path`로 확인했으나 모두 존재하지 않았다.
- `com.docker.service`, Docker Desktop/backend/dockerd 프로세스는 관찰되지 않았다.
- `codex exec --help`는 executor가 쓰는 `--json`, `--ephemeral`, `--strict-config`, `--skip-git-repo-check`, `--sandbox`, `--cd`를 계속 지원한다.

## 3. 경로 계약 재판정 / DONE

모델 호출 없이 현재 코드를 재검토했다.

- `tooling/feynman_boundary_profile.py`의 boundary profile v1은 mount와 tmpfs를 absolute POSIX path로 요구한다.
- `tooling/feynman_remote_exec_environment.py`의 reference generator는 runner-job의 path 문자열을 `-v host:container:rw`와 `--workdir`에 그대로 사용한다.
- 따라서 `C:\...` job path를 native Windows에서 생성해 Linux container destination으로 그대로 사용할 수 없다. 경로 변환 또는 POSIX workspace를 제공하는 별도 실행 계약이 필요하다.
- LOG-022의 executor Windows launch/UTF-8 수정은 control-plane subprocess에 대한 것이며 Docker container path mapping을 해결하지 않는다.

이 판정은 인증 성공과 독립적이다.

```text
auth gate: PASS
Codex local version/help: PASS
Docker backend availability: NOT AVAILABLE
Windows-to-Linux container path contract: NOT PROVEN / currently incompatible
actual model smoke: NOT STARTED
```

## 4. 안전하게 중단한 범위 / DONE

다음 단계로 넘어갈 수 있는 조건이 없으므로 실행하지 않았다.

- `feynman_subscription_run_preflight.py` 실제 artifact run
- `feynman_subscription_smoke_exec.py` 실제 실행
- Codex model turn
- Docker container/canary
- runner attestation/link/evidence/review/gate/result

로그인 재실행이나 credential 복사/WSL 이동도 요구하거나 수행하지 않았다. 개발 대화와 인계 문서를 candidate에 전달하지 않았다.

## 5. 저장 / DONE

- 코드 변경 없음.
- 이 backend preflight log만 추가한다.
- 다음 커밋은 feature branch에 non-force로 push한다.
- main merge와 force push는 하지 않는다.

## 6. 미완료 사항과 다음 한 행동

미완료:

1. Docker Desktop 또는 승인된 Linux/WSL2 backend가 이 PC에서 사용 가능하지 않다.
2. Windows host path를 POSIX container path로 매핑하는 실행 계약은 아직 구현/검증하지 않았다.
3. 실제 smoke 및 모든 후속 evidence lineage는 pending이다.

**다음 한 행동**: 사용자가 Docker Desktop/WSL2를 활성화해 실행 backend를 제공하거나, POSIX 경로를 가진 승인된 Linux/self-hosted control plane을 지정해야 한다. 그 전에는 auth gate를 반복하거나 모델 평가를 시작하지 않는다.
