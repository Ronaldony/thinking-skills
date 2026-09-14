# LOG-098 — startup lifecycle reap 판정 회귀 고정 (2026-09-14)

## 상태

- 단계: 구현·회귀 검증 완료
- 범위: synthetic App Server fixture를 이용한 startup/control-plane lifecycle 관찰
- 실제 subscription auth: 0회
- 실제 Codex startup: 0회
- 실제 model turn: 0회
- Docker 실행: 0회
- 대상 브랜치: `feat/feynman-thinking-v0.5-draft`
- main 병합·force push: 없음

LOG-096의 다음 우선순위인 진단기 전체 `run()` lifecycle 검증을 수행했다. 실제 Codex나 Docker를 실행하지 않고, 메모리 fixture를 주입해 initialize와 `thread/start`를 처리한 뒤 graceful `wait()` 및 payload-free telemetry snapshot을 확인했다.

## 발견한 결함과 수정

`tooling/feynman_subscription_startup_diagnostic.py`와
`tooling/feynman_subscription_control_plane_preflight.py`는 child process 종료
관찰 플래그를 `True`로 초기화하고 있었다. 따라서 실제 `process.wait()`가 성공했는지
관찰하기 전에도 `process_tree_reaped`를 성공처럼 기록할 수 있었다.

수정:

- 두 경로의 초기값을 `False`로 변경했다.
- graceful `process.wait()`가 정상 반환할 때만 `True`로 전환한다.
- graceful wait가 timeout이면 기존 bounded `_stop_diagnostic_process()` 결과만 사용한다.
- startup의 `cleanup_verified`는 이 실제 reap 관찰과 telemetry의 child exit 0을 모두 요구한다.

이 수정은 인증 상태나 원격 환경을 우회하지 않으며, 모델 없는 startup 증거의 성공 판정을 더 엄격하게 한다.

## 실제 명령과 관찰 결과

### startup diagnostic 대상 회귀

실행 명령:

```powershell
python -B -W error::ResourceWarning -m unittest tests.test_feynman_subscription_startup_diagnostic -v
```

관찰:

```text
Ran 30 tests in 0.322s
OK
```

추가된 `test_synthetic_run_records_graceful_process_reap`은 실제 `run()` 진입점에
다음 fixture를 연결했다.

- initialize response와 ephemeral `thread/start` response를 메모리 stdout으로 공급
- private thread ID와 instruction source를 결과에 보존하지 않는 기존 summary 경로 사용
- fake process의 `wait()` 호출과 return code 0을 관찰
- telemetry snapshot의 child exit code 0을 공급
- 최종 `process_tree_reaped=true`, `cleanup_verified=true`,
  `subscription-startup-thread-ready`를 확인

fixture는 `turn/start`, prompt, model-generation request를 보내지 않는다.

### 관련 회귀 및 정적 컴파일

실행 명령:

```powershell
python -B -W error::ResourceWarning -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_subscription_checkpoint tests.test_feynman_subscription_startup_diagnostic -q
python -m compileall -q tooling tests
```

관찰:

```text
Ran 60 tests in 0.838s
OK
```

`compileall`도 exit code 0이었다.

### 전체 Python suite

실행 명령:

```powershell
python -B -W error::ResourceWarning -m unittest discover -s tests -q
```

관찰:

```text
Ran 452 tests in 16.568s
OK (skipped=11)
```

`ResourceWarning`은 발생하지 않았다. 기존 skip 11개는 이번 변경으로 통과 처리하지 않았다.

## 검증 범위와 미완료 사항

통과한 범위:

- startup diagnostic 실제 `run()`의 synthetic initialize/thread-start/cleanup 경로
- graceful child reap 성공 판정
- control-plane preflight의 동일한 reap 상태 전이 코드
- checkpoint·RPC proxy·startup 관련 60개 회귀
- 전체 452개 Python 테스트와 정적 compile

미완료:

- sync telemetry persistence 비간섭 검증 및 writer 분리
- Docker fixture의 default cwd/상대 config path 의미 비교
- 실제 실행기와 startup gate의 공통 prep 완전 결속
- 새로운 subscription startup 1회
- 조건부 Luna smoke

따라서 `thread/start -32603`의 실제 원인은 아직 확정되지 않았다. 이번 수정은 그 실패를 새로 실행해 확인하지 않았고, `process_tree_reaped` 오판 가능성만 제거했다.

## 커밋·push와 다음 행동

- 이 로그 작성 시점의 commit/push: 아직 수행 전
- 다음은 lifecycle 코드·회귀 테스트·LOG-098 및 최신 pointer 문서만 feature branch에 일반 commit/push한다.
- `.tmp/`와 사용자 PNG 2개는 staging하지 않는다.
- 다음 자동 단계는 telemetry writer가 forward path를 block하지 않는지 synthetic response-order/slow-write fixture로 검증하는 것이다.
- 새 증거 없이 subscription startup 또는 model fallback을 반복하지 않는다.
