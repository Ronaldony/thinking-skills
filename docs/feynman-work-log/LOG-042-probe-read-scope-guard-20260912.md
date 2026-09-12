# LOG-042 — fixed one-byte probe read-scope guard

- 시각(KST): 2026-09-12
- 시작 HEAD: `9cff28d`
- branch: `feat/feynman-thinking-v0.5-draft`
- shell/OS: Windows PowerShell / Windows
- 목적: 승인된 추가 one-time probe의 후보 파일 데이터 범위를 proxy 경계에서
  강제하고, model-free 회귀 검증 후 실행한다.

## 변경 이유

기존 `PROBE_PROMPT`는 모델에게 `candidate.py` 한 byte를 읽으라고 요청했지만,
RPC proxy가 request의 `offset`, `len`, 대상 path를 강제하지 않았다. 따라서
prompt 계약만으로는 외부 model request에 전달되는 후보 데이터 범위를 보장할
수 없었다.

## 구현

`tooling/feynman_rpc_path_proxy.py`에 probe-only policy를 추가했다. 고정된
non-secret 환경값이 모두 있을 때만 활성화된다.

- 허용 RPC method: `initialize`, `initialized`, `fs/readFile`
- 허용 read path: `/run/candidate/candidate.py`
- `fs/readFile` request: `offset=0`, `len=1`로 proxy가 강제 재작성
- 그 밖의 method/path는 고정 JSON-RPC mapping error로 차단
- telemetry에 policy rejection/read-limit-applied count만 추가
- canonical 일반 evaluation environment에는 해당 probe 환경값을 넣지 않음

`tooling/feynman_subscription_tool_use_probe.py`는 probe subprocess에만 위
세 fixed control 값을 넣고, Docker의 `env -i` 뒤 candidate process에는
전달하지 않는다. raw model trace는 계속 `.control-tmp`에서만 처리 후 삭제한다.

## 검증

```powershell
python -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_subscription_tool_use_probe tests.test_feynman_subscription_smoke_exec
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q tooling tests
git diff --check
python tooling/feynman_rpc_preflight.py --job <runner-job-0.154.0> --boundary-profile <boundary-profile> --remote-environment <dedicated control home>/environments.toml --docker-config <empty docker config> --output <evaluator>/rpc-preflight-20260912-read-limit-regression.json
```

- targeted: 26 tests, exit 0, OK
- full: 303 tests, 10 skipped, exit 0, OK
- compile/diff check: exit 0
- actual general-mode Docker/RPC preflight: `native-rpc-preflight-passed`,
  exit 0; task/skill read, process start/exit, host path echo checks all passed
- model request: 이 checkpoint까지 0회

## 승인된 one-time probe

다음 명령으로 `gpt-5.6-luna / codex-cli 0.154.0` fixed probe를 추가 1회
실행한다. 이 실행은 기존 dedicated ChatGPT subscription control home을 사용하며,
`task.txt`, rubric, 개발 대화, handoff 문서를 model stdin에 넣지 않는다. proxy가
candidate.py 외 path와 `fs/readFile` 외 method를 차단하고 read length를 1로
강제한다. 실패하면 자동 반복하지 않는다.

성공 후에는 result의 completed tool item과 host proxy telemetry를 함께 비교한다.
그 결과는 tool exposure 원인 진단에만 쓰며 baseline 또는 Feynman 성능 근거로
승격하지 않는다.

## 저장 상태

- 이 log 작성 시점: code/log commit 및 push pending
- 인증 파일·token·전체 환경변수·raw model trace는 읽거나 기록하지 않음
- 다음 한 행동: 승인된 probe 1회 실행 후 safe result/telemetry만 집계하고,
  실행 종료 즉시 container/임시 control artifact 상태를 확인한다.

## 실행 시도 결과

승인된 명령을 실행했으나 `eval-plan.json` 경로를 잘못 입력해
`eval plan does not exist`로 exit 2가 발생했다. 이 오류는 probe의 구조 검증
단계에서 발생했으며 auth gate, model request, Docker start에는 도달하지 않았다.
실행 시도 후 probe output/result/.control-tmp가 모두 없고, Docker
`ps -a --filter name=feynman` 결과도 0행이었다.

사용자의 "실패 시 자동 반복하지 마" 지시에 따라 corrected path command는
자동 재실행하지 않았다. 다음 행동은 사용자가 corrected one-time command의
재실행을 별도로 지시할 때까지 대기하는 것이다.
