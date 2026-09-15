# LOG-039 — 0.154.0 tool-discovery probe의 무도구 결과

- 시각(KST): 2026-09-12 21:10–21:35
- 시작 HEAD: `467fac07434e43e36583acbc2a62d692b261ee11`
- branch: `feat/feynman-thinking-v0.5-draft`
- shell/OS: Windows PowerShell / Windows
- 승인: 사용자가 fixed one-byte tool-discovery probe 실행을 명시 승인함
- 상태: **probe process/auth 성공, tool-use 미관측; baseline 및 평가 실행 차단**

## 버전 mismatch 차단과 복구

첫 승인 실행은 model request 전에 stale runner-job guard에서 종료됐다.

```text
runner job: codex-cli 0.153.4
resolved launcher: C:\Users\wotmd\AppData\Roaming\npm\codex.ps1
direct codex --version: codex-cli 0.154.0 / exit 0
auth gate: chatgpt-subscription-authenticated / codex-cli 0.154.0
```

raw login status는 저장·출력하지 않았다. 기존 `runner-job.json`과 기존 smoke
artifacts는 보존하고, 현재 CLI에 맞춘 새 probe 전용 job
`runner-job-20260912-codex-0.154.0.json`을 generator로 만들었다.
`feynman_runner_job_validate.py` exit code는 0이었다. model request는 첫 시도에서
시작되지 않았다.

새 job으로 다시 실행한 subscription structural preflight도 exit code 0이었다.
candidate task byte match, candidate skill preflight, remote environment valid가
모두 true였다. 이 preflight는 model request를 시작하지 않는다.

## 실제 one-time probe

generator/validator는 모두 성공했고, subscription probe는 exit code 0으로 끝났다.

safe result summary:

```text
verdict: subscription-tool-use-probe-completed
probe verdict: tool-use-not-observed
auth gate: chatgpt-subscription-authenticated
trace events: 5
completed item types: agent_message, error
completed candidate tool items: 0
raw model final preserved: false
candidate-final.txt: absent by design
```

raw trace를 출력하지 않는 정규식 집계에서는 `PROBE_TOOL_USED` 문자열이 있었지만
filesystem/fs-read/command/MCP tool item은 없었다. 또한 fixed
`skills context budget` notice가 trace에 있었다. 따라서 이는 “도구를 사용했다”는
모델 텍스트 주장과 실제 trace의 불일치이며, candidate 파일이 실제로 읽혔다는
증거가 아니다. notice와 무도구의 인과관계는 확정하지 않는다.

## 수정과 검증

`feynman_subscription_tool_use_probe.py`에 `_response_claim_verdict`를 추가해
향후 result가 trace 우선의 `trace-tool-use-observed`,
`text-claim-without-tool-trace`, `explicit-no-tool-claim`,
`no-tool-trace-unclassified-response`를 구분한다. 텍스트 응답은 trace 증거를
덮어쓸 수 없다.

targeted 19 tests와 full 300 tests(10 skipped)가 모두 통과했고, Python compile 및
`git diff --check`도 통과했다. 실제 artifact는 이 보강 전 실행본이므로 새 field는
offline 판정으로만 기록하며 model command를 재실행하지 않았다.

## Docker 및 보안 정리

probe 후 Docker `ps -a --filter name=feynman`에서 단일 `Exited (0)` probe container를
확인했다. exact short ID `001731437a1a`만 `docker rm`으로 제거했고 재확인 결과
matching row는 0개였다. container logs/inspect와 auth files는 읽지 않았다.

제가 생성한 dedicated control home의 canonical `environments.toml`은 probe finally
cleanup으로 제거됐고 file 부재를 확인했다. API key, Platform API, raw auth status,
full environment, credential/session contents는 사용·출력·복사·업로드하지 않았다.

## commit/push 및 남은 문제

- stale-job correction artifact는 외부 evaluator directory에만 생성됐고 기존 job을
  덮어쓰지 않았다.
- 이 log 작성 시점의 response-claim code/doc 변경 commit/push는 pending이다.
- baseline ordinal 2와 Feynman smoke의 post-run evidence/semantic review는 시작하지
  않았다. 현재 환경은 Windows/Docker/RPC/auth가 아니라 **Codex model turn에서
  candidate tool invocation이 0회인 상태**에서 막혀 있다.
- 다음 행동: response-vs-trace 보강을 commit/push한 뒤, 추가 모델 호출 없이 이
  blocker를 보고한다. 다른 model/version 선택 또는 Codex 0.154.0의 remote-tool
  exposure investigation은 별도 방향 결정이 필요하다.
