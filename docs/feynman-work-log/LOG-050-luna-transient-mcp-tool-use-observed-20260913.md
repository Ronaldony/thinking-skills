# LOG-050 — Luna transient MCP 실제 tool-use 관찰

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `73ab41fead9a208bab63c6e95ef3beda966b9088`
- 시작 상태: clean, local/remote feature SHA 일치, 직전 PR workflow 7개 success
- 사용자 승인: Luna 비평가 bounded-MCP probe 정확히 1회
- 모델: `gpt-5.6-luna`
- 인증: 공식 Codex ChatGPT 구독 로그인
- OpenAI Platform API/API key: 미사용

## 목적과 실행 제한

LOG-049에서 실제 plan/job/version/Docker/security/transient catalog를 포함한
model-free preflight가 `ready-for-subscription-tool-use-probe`로 통과했다. 이번
작업은 승인된 1회만 실제 모델에 연결해 model-facing MCP tool call이 trace에
나타나는지 확인했다.

평가 실행이 아니다. prompt는 고정 no-argument tool 이름과 고정 응답 token만
포함한다. `task.txt`, test, rubric, skill, evaluator 자료, 개발 대화 및 인계 문서를
모델에 전달하지 않는다. 실패해도 자동 재시도하거나 Terra/Sol로 fallback하지
않도록 했다.

공식 OpenAI 문서에서 실행 직전 다시 확인한 계약:

- `codex exec --ignore-user-config`는 `$CODEX_HOME/config.toml`을 로드하지 않는다.
- enabled MCP가 `required=true`이고 초기화에 실패하면 exec가 오류로 종료한다.
- `--json` event에는 MCP tool call item이 포함된다.
- `gpt-5.6-luna`는 Codex의 공식 선택 가능 model ID다.

자료:

- https://learn.chatgpt.com/docs/non-interactive-mode
- https://learn.chatgpt.com/docs/models?surface=app

## 실제 단일 실행

```powershell
$probeOutput = 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\transient-model-probe-01'
if (Test-Path -LiteralPath $probeOutput) { throw 'probe output already exists; refusing to reuse it' }
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_subscription_tool_use_probe --plan 'C:\DevWorks\feynman-remote-compat-20260912-01\frozen-subscription-smoke-plan.json' --ordinal 1 --evaluator-case 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\case.json' --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote-environment 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\environments.toml' --output-dir $probeOutput --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --node-bin 'C:\Program Files\nodejs\node.exe' --bounded-adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_bounded_read_adapter.mjs' --timeout-seconds 240
```

명령은 1회만 시작했고 같은 process의 완료만 기다렸다. 종료 코드 0, stdout의
고정 결과는 다음과 같았다.

```json
{"verdict":"subscription-tool-use-probe-completed","probe_verdict":"tool-use-observed"}
```

## sanitized 결과

artifact:

`C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\transient-model-probe-01\subscription-tool-use-probe.json`

관찰:

- auth gate: `chatgpt-subscription-authenticated`
- completed tool item count: `1`
- completed tool item type: `mcp_tool_call`
- probe verdict: `tool-use-observed`
- response/trace verdict: `trace-tool-use-observed`
- transient catalog: `bounded-mcp-catalog-visible`
- server/tool: `feynman_bounded_read / feynman_read_probe_byte`
- model-selectable arguments: false
- fixed read limit: 1 byte
- adapter/candidate digest: LOG-049 preflight lineage와 일치
- raw auth status, raw stderr, raw model final, raw trace, tool arguments/output: 미보존
- candidate task/rubric: 미전달
- process environment: 미상속

결과 디렉터리에는 sanitized JSON 4개만 남았다.

- `guarded-readiness.json`
- `guarded-readiness-rpc.json`
- `transient-mcp-catalog.json`
- `subscription-tool-use-probe.json`

임시 `.control-tmp`와 model-authored raw JSONL trace는 `finally` cleanup으로
삭제된 것을 directory inventory로 확인했다. 실행 후
`docker ps -a --filter name=feynman-` 결과는 0개였다.

## 해석

이 결과는 이전 `PROBE_TOOL_USED` 텍스트-only 결과와 다르다. 이번에는 Codex
0.154.0의 실제 subscription model trace에 완료된 `mcp_tool_call` item이 1개 있다.
따라서 다음 결론까지는 입증됐다.

1. protected ChatGPT subscription auth와 `--ignore-user-config`를 함께 사용할 수 있다.
2. CLI override로 등록한 local bounded STDIO MCP가 model-facing catalog에 노출된다.
3. Luna는 no-argument 고정 도구를 실제 호출했다.
4. 기존 remote exec-server `fs/readFile`의 117-byte 계약 결함을 사용하거나 완화하지
   않고 one-byte diagnostic read를 실행할 수 있다.

입증되지 않은 사항:

- Docker 내부 remote MCP tool call
- candidate 전체 파일 읽기/쓰기 및 test 실행
- frozen tools-10 job 성공
- baseline/feynman 비교 또는 Feynman skill 성능 효과
- Terra/Sol의 같은 동작

## 저장 상태와 다음 행동

- 실행 직후 source code 변경은 없다.
- 이 로그와 인계 문서 변경은 작성 시점 commit/push pending이다.
- main 병합과 force push는 하지 않는다.

다음 안전한 작업은 모델 호출 없이 **full evaluation runner용 최소 MCP tool
contract**를 설계하는 것이다. 고정 candidate 파일 읽기, `candidate.py`에 한정된
쓰기, network-disabled Docker에서 고정 test command 실행을 서로 분리해야 한다.
임의 path/argv/shell은 노출하지 않는다. 이 계약을 model-free로 검증하기 전에는
baseline이나 실제 평가를 시작하지 않는다.
