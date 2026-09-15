# LOG-097 — checkpoint 입력 검증 보강 및 회귀 고정 (2026-09-14)

## 상태

- 단계: 구현·회귀 검증 완료
- 범위: Windows/Docker startup 이전의 비밀정보 없는 checkpoint 입력 검증
- 실제 subscription auth: 0회
- 실제 startup diagnostic: 0회
- 실제 Codex model turn: 0회
- Docker 실행: 0회
- 대상 브랜치: `feat/feynman-thinking-v0.5-draft`
- main 병합·force push: 없음

이번 묶음은 LOG-096의 1단계 구현이다. 새로운 구독 startup을 반복하지 않고, 먼저 잘못된 입력이 Codex·Docker 실행 계층에 도달하지 않도록 차단 규칙을 공통 checkpoint validator에 넣었다.

## 확인한 문제와 수정 이유

기존 `tooling/feynman_subscription_checkpoint.py:validate()`는 다음을 확인하지 않았다.

1. `remote_environment`가 runner job의 보호된 control `CODEX_HOME/environments.toml`인지
2. `telemetry`와 `output`이 evaluator 소유의 새 경로인지
3. 두 출력 경로가 서로 다른지
4. 직접 호출된 `validate()` 입력이 절대 경로인지
5. direct validation에서도 Docker image digest 형식이 유지되는지

그 결과 validate-only가 실제 실행 규약보다 느슨해질 수 있었다. 특히 candidate 내부 output, 상대 output, telemetry/output 동일 경로, 비정규 remote environment를 외부 프로세스 시작 전에 정확히 거부할 수 없었다.

수정 내용:

- 모든 path field를 `validate()`에서도 절대 경로로 확인한다.
- Docker image ID가 `sha256:` 64자리 digest인지 확인한다.
- runner job의 `evaluator_dir`와 `control_codex_home`을 읽어 evaluator 경계와 canonical remote environment를 확인한다.
- `remote_environment`는 반드시 control home의 `environments.toml`이고 실제 regular file이어야 한다.
- `telemetry`와 `output`은 존재하지 않는 evaluator 하위 경로여야 하며, 서로 같으면 거부한다.
- 기존 binding validator는 그대로 재사용하며, 이 계층은 subprocess를 시작하지 않는다.

## 실제 명령과 관찰 결과

### 현재 상태 확인

실행 명령:

```powershell
git status --short --branch
rg -n "def (validate|run|main)|validate-only|evaluator|telemetry|output|binding|lineage|checkpoint" tooling/feynman_subscription_checkpoint.py tests/test_feynman_subscription_checkpoint.py
```

관찰:

- 브랜치는 `feat/feynman-thinking-v0.5-draft`이며 origin을 추적한다.
- LOG-095/LOG-096 및 인계 문서 변경, `.tmp/`, 사용자 PNG 2개가 작업 트리에 있었다.
- 기존 production 수정은 `tooling/feynman_subscription_checkpoint.py`에 없었고, validator가 위 경계를 충분히 검사하지 않았다.

### 변경 영역 빠른 회귀

실행 명령:

```powershell
python -B -W error::ResourceWarning -m unittest tests.test_feynman_subscription_checkpoint -v
```

관찰:

```text
Ran 8 tests in 0.114s
OK
```

추가된 fixture/test는 다음을 확인한다.

- canonical control environment와 evaluator-owned 새 출력은 통과
- noncanonical remote environment 거부
- relative output 거부
- telemetry/output 동일 경로 거부
- candidate-owned output 거부
- 모든 거부 경로에서 subprocess를 시작하지 않음

### 관련 진단·proxy 회귀

실행 명령:

```powershell
python -B -W error::ResourceWarning -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_subscription_checkpoint tests.test_feynman_subscription_startup_diagnostic -q
```

관찰:

```text
Ran 59 tests in 0.965s
OK
```

### 전체 Python suite

실행 명령:

```powershell
python -B -W error::ResourceWarning -m unittest discover -s tests -q
```

관찰:

```text
Ran 451 tests in 18.265s
OK (skipped=11)
```

`ResourceWarning`은 발생하지 않았다. 기존 skip 11개는 이번 묶음에서 임의로 성공 처리하거나 범위를 넓히지 않았다.

### diff 안전성

실행 명령:

```powershell
git diff --check
```

관찰:

- 오류 없음
- Git의 LF/CRLF 경고와 사용자 환경의 global ignore 접근 경고만 출력됨

## 검증 범위와 미검증 범위

통과한 범위:

- checkpoint 입력·경계·출력 경로의 model-free validation
- 잘못된 입력의 사전 차단
- 기존 RPC path proxy, checkpoint, startup diagnostic 회귀
- 전체 Python 테스트 suite
- `ResourceWarning` 차단

이번 묶음에서 하지 않은 것:

- 실제 ChatGPT 구독 auth gate
- Codex app-server `thread/start`
- Docker container lifecycle 또는 path meaning 비교
- 실제 model turn 및 Luna smoke
- telemetry writer/lifecycle deadline 수정

따라서 이번 결과는 startup 성공 증거가 아니며, 실제 `thread/start -32603` 원인을 확정하지 않는다.

## 커밋·push와 다음 행동

- 이 로그 작성 시점의 commit/push: 아직 수행 전
- 다음은 이번 코드·테스트·작업 로그 및 이미 준비된 최신 인계 문서만 feature branch에 일반 commit/push한다.
- `.tmp/`와 사용자 PNG 2개는 staging하지 않는다.
- 다음 구현 우선순위는 synthetic App Server fixture를 통한 진단기 전체 `run()` lifecycle 재현이다. 여기서 60초 startup deadline과 15초 cleanup deadline, 비정상 child exit, EOF를 실제 진입점 기준으로 회귀 고정한다.
- 새 증거 없이 subscription startup을 재실행하지 않는다.
