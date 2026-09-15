# LOG-092 — Docker lifecycle list 재검증과 blocker 유지 (2026-09-14)

## 상태

- 작업 ID: LOG-092 / 상태: DONE (재검증), BLOCKED (Docker container lifecycle)
- 저장소: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `77b5200caa3a89c6a9b8739fb4b3506d597e2fad`
- 인증·모델·candidate payload·보호된 구독 로그인 홈은 사용하지 않았다.

## 목적

`LOG-091`의 최소 `docker create` 및 label 제한 목록 조회 timeout 뒤 Docker Desktop 상태가 회복됐는지 확인했다. 같은 `create`나 실제 subscription startup은 반복하지 않고, Engine metadata와 우리 control label의 lifecycle 목록 API를 분리해서 점검했다.

## 실제 명령과 관찰

Docker Engine metadata 조회:

```powershell
docker --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --host 'npipe:////./pipe/docker_engine' info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}|{{.ContainersRunning}}|{{.ContainersPaused}}|{{.Images}}'
```

결과:

```text
29.7.2|linux|aarch64|0|0|14
info_exit=0
```

우리 probe control label만 조회:

```powershell
docker --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --host 'npipe:////./pipe/docker_engine' ps -a --filter label=com.openai.feynman.control --format '{{.Names}}|{{.Status}}|{{.Image}}'
```

45초 이상 stdout/stderr 없이 반환되지 않아 PowerShell 세션에 Ctrl+C를 보내 중단했다. 따라서 `com.openai.feynman.control` 범위의 잔존 container 유무와 cleanup 가능 여부는 여전히 확인하지 못했다. 다른 container를 조회·삭제하지 않았고 broad prune/remove도 수행하지 않았다.

저장소 상태:

```powershell
git status --short --branch
git log -1 --oneline --decorate
```

관찰: tracked worktree는 clean이고 기존 untracked `.tmp/`와 사용자 PNG 2개만 보존돼 있다. HEAD는 `77b5200`이며 branch는 `origin/feat/feynman-thinking-v0.5-draft`를 추적한다.

추가 remote ref 확인:

```powershell
git ls-remote origin refs/heads/feat/feynman-thinking-v0.5-draft
```

결과: Windows Schannel credential helper 오류 `SEC_E_NO_CREDENTIALS (0x8009030e)`로 이번 확인은 실패했다. 이는 코드나 Docker 결과가 아니며, 직전 `77b5200` push 성공 기록을 소급 변경하지 않는다. 새 push가 필요한 경우에도 먼저 이 credential 상태를 해결해야 한다.

## 판단

- `docker info` 성공은 Engine metadata/control-plane 일부가 응답한다는 뜻이다.
- 같은 local named pipe에서 label-filtered `docker ps -a`가 45초 이상 정체된 것은 container lifecycle 목록 경로가 아직 회복되지 않았다는 새 증거다.
- 따라서 image entrypoint, path mapping, probe hardening 옵션, Codex exec-server, auth, 모델은 현재 blocker의 원인으로 확정할 수 없다.
- `docker create` 재실행 조건은 충족되지 않았다. 실제 runtime probe, path contract 비교, subscription startup, auth gate, Luna smoke, model evaluation은 실행하지 않았다.

## 검증 범위

- Docker Engine metadata: 통과 (`29.7.2`, Linux/aarch64, running/paused 0, images 14)
- container lifecycle list: 미통과/응답 없음 (45초 후 수동 중단)
- 코드 회귀: 새 코드 변경 없음. 직전 확정 결과는 집중 33 tests, 전체 441 tests, 11 skipped, schema 17 errors=0이다.
- 개인정보 보호: 로그인 파일·토큰·전체 환경변수·원문 payload를 읽거나 출력하지 않았다.

## 커밋·push

- 이번 로그 작성 전 HEAD: `77b5200`.
- 이 로그와 상태 포인터 변경 후에는 feature branch에 일반 commit/push하고 결과를 다시 확인한다.
- main merge와 force push는 하지 않는다.

## 미완료와 다음 한 행동

미완료는 Docker Desktop backend의 container lifecycle API 응답 정상화와, 정상화 이후 `com.openai.feynman.control` label 범위의 잔존 container 확인·정리다. 사람의 외부 환경 조작 없이 저장소에서 더 좁힐 수 있는 증거는 소진됐다.

다음 한 행동은 Docker가 lifecycle 목록에 응답한다는 새 증거가 생겼을 때, 수정된 schema v3 runtime probe를 새 artifact 경로로 정확히 1회 실행하는 것이다. 그 전에는 같은 create, path probe, 구독 startup, 모델 실행을 시작하지 않는다.
