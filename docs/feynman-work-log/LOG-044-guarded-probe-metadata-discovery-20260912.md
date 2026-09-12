# LOG-044 — guarded probe 결과와 metadata discovery 보정

- 시각(KST): 2026-09-12
- 시작 HEAD: `4358372`
- branch: `feat/feynman-thinking-v0.5-draft`
- shell/OS: Windows PowerShell / Windows
- 목적: 승인된 read-scope-guarded probe의 실제 결과를 안전하게 해석하고,
  파일 본문 노출 없이 필요한 Codex metadata discovery를 허용한다.

## 실제 one-time probe 결과

정확한 frozen plan, dedicated ChatGPT subscription control home,
`gpt-5.6-luna`, `codex-cli 0.154.0`으로 새 evaluator output directory에서
probe를 1회 실행했다.

- process verdict: `subscription-tool-use-probe-completed`
- auth gate: `chatgpt-subscription-authenticated`
- probe verdict: `tool-use-not-observed`
- completed candidate tool item: 0
- response claim: `explicit-no-tool-claim`
- output에는 safe `subscription-tool-use-probe.json`만 존재하고 raw trace,
  candidate final, control temp는 존재하지 않음
- Docker `ps -a --filter name=feynman`: 0행

safe RPC telemetry는 `initialize:1`, `initialized:1`,
`environmentConfig/read:2`, `fs/getMetadata:24`를 보였다. requests seen 28 중
2개만 forwarded 되었고, 26개는 probe policy rejection이었다. `fs/readFile`은
0회이며 `probe_read_limit_applied`도 0이었다. 따라서 candidate.py 본문은
이 probe에서 읽히거나 모델로 전달되지 않았다.

이는 model capability 자체의 부재로 확정할 수 없다. 기존 guard가 Codex의
filesystem metadata discovery를 과도하게 차단해 tool invocation 전에 진행을
막은 결과다. baseline과 Feynman evaluation은 실행하지 않았다.

## 보정

probe-only allowlist에 `environmentConfig/read`, `fs/getMetadata`를 추가했다.
`feynman_rpc_path_mapping.py`는 `fs/getMetadata.path`도 Windows host path에서
Linux mount path로 매핑한다.

- `fs/readFile`: `/run/candidate/candidate.py`만 허용하고 proxy가
  `offset=0`, `len=1`로 강제
- `fs/getMetadata`: `/run/candidate` 하위 metadata만 허용
- `environmentConfig/read`: Codex control discovery만 허용
- 그 외 method/path: 고정 mapping error

`feynman_rpc_preflight.py`에 metadata-only RPC 확인을 추가했다. response의
summary key에 `dataBase64`, `content`, `text`가 있으면 실패한다. response
payload 자체는 보존하지 않는다.

## 검증

```powershell
python -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_preflight tests.test_feynman_subscription_tool_use_probe
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q tooling tests
git diff --check
python tooling/feynman_rpc_preflight.py --job <runner-job-0.154.0> --boundary-profile <boundary-profile> --remote-environment <dedicated control home>/environments.toml --docker-config <empty docker config> --output <evaluator>/rpc-preflight-20260912-metadata.json
```

- targeted: 24 tests, exit 0, OK
- full: 306 tests, 10 skipped, exit 0, OK
- compile/diff check: exit 0
- actual model-free Docker/RPC preflight: `native-rpc-preflight-passed`,
  candidate metadata read true, candidate task/skill read true, process exit 0,
  host path echo false

## 저장 상태와 다음 행동

- 이 log 작성 시점: code/log commit 및 push pending
- 다음 실제 model probe는 updated metadata allowlist와 one-byte read guard를
  사용해야 한다. 이번 model probe는 이미 종료됐으므로 추가 실행은 새 사용자
  지시가 필요하다.
