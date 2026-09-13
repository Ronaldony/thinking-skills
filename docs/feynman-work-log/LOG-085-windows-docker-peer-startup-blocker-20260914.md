# LOG-085 — Windows/Docker peer startup blocker 분리와 진단 보강 (2026-09-14)

## 작업 상태

- 작업 ID: LOG-085 / 상태: DONE (오프라인 진단 보강), BLOCKED (Docker peer 실행 및 실제 startup)
- 저장소: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 기준 상태: 직전 feature branch push 이후 tracked worktree는 clean이었고, `.tmp/`와 사용자 PNG 2개는 기존 untracked 상태로 보존했다.
- 보안 범위: 임시 fixture와 pinned Docker image만 사용했다. ChatGPT 구독 로그인 홈, 인증 파일·토큰, 전체 환경변수, API key, candidate payload는 읽거나 출력·업로드하지 않았다.

## 목적과 실행 범위

앞선 계획의 A~C 중 새 결함을 겨냥할 수 있는 오프라인 부분을 수행했다. startup diagnostic의 cleanup 예산을 보강하고, path contract probe를 `environmentConfig/read`, `fs/canonicalize`, `fs/getMetadata`, `fs/walk`, `fs/readFile`, `process/start`까지 확장했다. 실제 구독 startup, 인증 검사, `codex exec`, model turn, baseline 평가는 실행하지 않았다.

## 현재 코드·브랜치 확인

실행 명령:

```powershell
git status --short --branch
git rev-parse HEAD
git diff --stat
```

관찰:

- branch는 `feat/feynman-thinking-v0.5-draft`이며 origin tracking branch를 사용한다.
- 기존 `.tmp/`와 사용자 PNG 2개는 untracked로 남아 있었다.
- 이번 변경은 startup diagnostic, path contract probe, 해당 회귀 테스트에만 한정했다.

## 코드 수정과 이유

### 1. startup cleanup deadline 보강

`tooling/feynman_subscription_startup_diagnostic.py`에서 cleanup 진입 시점부터 15초 전체 deadline을 유지하고, 정상 종료 대기는 최대 10초로 제한했다. proxy telemetry의 `child_exit_code`를 먼저 기다린 뒤 필요한 경우 App Server process tree를 정리하고, stderr/stdout reader join도 남은 cleanup 예산 안에서만 수행한다.

이유: 이전 진단은 `thread/start` 실패 뒤 proxy의 최종 child exit가 기록되기 전에 부모 process tree를 정리할 수 있어 `child_exit_code=null`이라는 불완전한 증거를 남겼다. 이 보강은 `null`을 성공으로 승격하지 않으며, cleanup 시간이 startup deadline을 소급해 늘리지 않도록 한다.

### 2. Docker path contract probe의 실패 단계 보존

`tooling/feynman_rpc_path_contract_probe.py`에서 다음을 추가했다.

- peer별 timeout·peer close·비정상 종료를 `failure_stage`로 보존한다.
- 첫 initialize 응답 전에 양쪽 peer가 끝나면 `docker-peer-startup-timeout`, `docker-peer-closed-before-initialize`, 또는 `docker-peer-no-initialize-response`로 분류한다.
- `initialize_response_observed`와 direct/proxy response namespace digest를 기록한다.
- 요청 응답을 기다리는 중 실패하면 뒤 요청을 보내지 않고, Windows에서는 알려진 peer process tree를 `taskkill`로 정리한다.
- 요청 집합을 실제 path 의미 후보인 config/requirements 배열, canonicalize, metadata, walk options, readFile, process cwd까지 확장했다.

이유: 이전 probe의 `rpc-path-contract-blocked`만으로는 Docker 실행 실패와 path semantic 불일치를 구분할 수 없었다. initialize 응답이 없으면 path response를 해석하지 않는 것이 안전하다.

## 실제 명령과 관찰

### 회귀 테스트

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m py_compile tooling/feynman_rpc_path_contract_probe.py tooling/feynman_subscription_startup_diagnostic.py tests/test_feynman_rpc_compatibility.py
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -W error::ResourceWarning -m unittest tests.test_feynman_rpc_compatibility tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_path_proxy tests.test_feynman_subscription_startup_diagnostic -q
git diff --check
```

결과: `86 tests`, `OK`; `ResourceWarning` 없음; compile 및 diff check 통과.

### Docker engine/image read-only 확인

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}|{{.Containers}}|{{.Images}}'
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' image inspect 'sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6'
```

안전하게 선택한 필드의 관찰:

- Docker `29.7.2`, server `linux/arm64`.
- pinned image `linux/arm64`, `User=1000:1000`, entrypoint `docker-entrypoint.sh`, 기본 `WorkingDir` 필드 없음.
- `docker ps -a`에서 잔여 container 없음.

이는 Docker daemon과 image metadata가 보인다는 뜻이지, image process가 실행 완료된다는 뜻은 아니다.

### 확장 offline path probe

사용 명령:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_rpc_path_contract_probe --docker 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --image 'sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6' --proxy 'C:\DevWorks\thinking-skills\tooling\feynman_rpc_path_proxy.py' --output 'C:\DevWorks\thinking-skills\.tmp\rpc-path-contract-20260914-expanded-v2.json' --timeout 15
```

artifact: [`rpc-path-contract-20260914-expanded-v2.json`](../../.tmp/rpc-path-contract-20260914-expanded-v2.json)

관찰:

- verdict: `rpc-path-contract-blocked`
- failure stage: `docker-peer-startup-timeout`
- direct/proxy 모두 `response_ids=[]`, `initialize_response_observed=false`, `notifications=0`, `malformed_lines=0`, `timed_out=true`, exit `1`
- direct/proxy request shape digest는 같았지만 response shape는 빈 결과 digest이며, path response가 하나도 없어 path 의미 동등성을 판정할 수 없다.

따라서 이번 결과는 Windows path mapping의 통과·실패 증거가 아니다. pinned image process가 첫 JSON-RPC initialize 응답을 내기 전에 Docker peer 실행/stdio 단계에서 정체된 것으로만 분류한다.

동일 output 경로로 재실행한 후속 명령은 probe의 안전한 “새 절대 output만 허용” 검증에 걸려 exit `2`와 `output must be a new absolute path`를 반환했다. 이는 코드 결함이 아니라 기존 artifact 덮어쓰기를 막은 입력 보호이며, 기존 artifact는 삭제하지 않았다.

## 전체 검증·커밋 범위

이번 변경 묶음 뒤에 다음을 실행한다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -W error::ResourceWarning -m unittest discover -s tests
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m py_compile tooling/feynman_rpc_path_contract_probe.py tooling/feynman_rpc_path_proxy.py tooling/feynman_subscription_startup_diagnostic.py
git diff --check
```

스키마 검증은 기존 subscription startup report schema v3와 실제 보존 report instance에 대해 수행한다. Docker peer가 initialize 전에 막힌 상태이므로 path contract equivalent나 startup ready로 기록하지 않는다.

## 미완료 사항과 다음 행동

- 미완료: Docker image process가 왜 `/bin/echo`, `node --version`, `codex exec-server --listen stdio` 모두 실행 완료하지 못하는지. 현재 증거는 daemon/image metadata 접근 성공과 process completion 실패를 분리할 뿐 내부 원인을 확정하지 않는다.
- 미완료: Codex 0.154.0의 `thread/start -32603` 내부 원인. 실제 subscription startup 재실행은 하지 않았다.
- 미완료: direct Linux와 Windows proxy의 실제 response semantics. initialize 응답이 없으므로 아직 비교 불가하다.
- 다음 안전한 단계: Docker Desktop에서 고정 image의 단순 process 실행/종료를 별도 model-free fixture로 좁힌 뒤, peer가 initialize 응답을 내는 경우에만 확장 path contract probe를 새 output 경로로 1회 수행한다. 그 결과가 특정 코드 결함을 가리키고 회귀 테스트가 있으면 그때 startup 재검증 1회 여부를 판단한다.
- 실제 startup gate와 Luna smoke는 이 blocker가 해소되고 별도 실행 경계에 도달하기 전에는 시작하지 않는다.

## 커밋·push

- 명시적으로 선택한 7개 tracked 파일만 stage했다. `.tmp/`와 사용자 PNG 2개는 stage하지 않고 보존했다.
- 커밋: `583c8119f4554797674d53f9ed07307c303c9519` (`fix: classify Docker peer startup blockers`)
- `git push origin feat/feynman-thinking-v0.5-draft` 성공.
- push 후 local HEAD와 `refs/remotes/origin/feat/feynman-thinking-v0.5-draft`가 모두 `583c8119f4554797674d53f9ed07307c303c9519`로 일치한다.
- main merge와 force push는 하지 않았다.
