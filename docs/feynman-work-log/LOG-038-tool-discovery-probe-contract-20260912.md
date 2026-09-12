# LOG-038 — 비평가적 subscription tool-discovery probe 계약

- 시각(KST): 2026-09-12 21:00–21:10
- 시작 HEAD: `d69aa2e2754d8da2a216a5595f043aadcb04fb7d`
- branch: `feat/feynman-thinking-v0.5-draft`
- shell/OS: Windows PowerShell / Windows
- 상태: **구현·model-free 검증 완료, 실제 ChatGPT-subscription probe 미실행**

## 배경과 판단

LOG-037에서 actual ordinal 1 `feynman-v05` turn은 fixture/test failure를 서술했지만
completed candidate tool item이 0개였다. native Windows→Linux exec-server RPC
preflight는 이미 file read와 harmless `process/start`까지 통과했으므로, 다음
원인은 (a) control-plane의 모델 도구 발견/선택 또는 (b) 이 특정 evaluation task의
후보 행동 중 하나다. frozen task를 바꾸거나 같은 evaluation command를 반복하지
않고 이 둘을 분리할 필요가 있다.

OpenAI Docs 스킬을 사용해 공식 `Skills & Plugins` 문서를 조회했다. 이 문서는
skill이 name/description으로 자동 선택될 수 있고 Codex에서 `$skill`로 명시 선택할
수 있음을 설명한다. public documentation에서는 이번 `skills context budget` notice를
비활성화하는 설정을 찾지 못했다. 따라서 notice는 관찰 사실일 뿐 root cause로
확정하지 않는다. API/platform skills 경로는 조회·사용하지 않았다.

`codex debug prompt-input --help`와 `codex debug/app-server --help`는 모델 요청 없이
확인했다. temporary empty home을 만들고 common HOME/CODEX_HOME을 교체한 뒤 삭제하는
초기 진단 명령은 sandbox 정책상 거부됐으며 실행하지 않았다. 위험을 우회하지 않고
그 상태에서 멈췄다. 이 log의 새 probe는 그 회피책이 아니라 별도의,
preflight/auth-gated Codex invocation 계약이다.

## 추가 구현

`tooling/feynman_subscription_tool_use_probe.py`를 추가했다.

- repaired `tools-10 / feynman-v05 / single-turn` runner job만 수용한다.
- canonical structural preflight, dedicated ChatGPT-subscription auth gate,
  requested model/CLI version binding, scrubbed child environment 및 exact remote
  environment를 다시 확인한다.
- `task.txt`, evaluator rubric, review input, 개발 대화, handoff 문서는 모델 stdin에
  전달하지 않는다. 고정 prompt는 current workspace의 `candidate.py`에서 filesystem
  tool로 정확히 1 byte를 읽도록만 요구한다.
- JSON trace에서 completed tool item의 count/type만 result에 남긴다. raw final,
  tool call arguments/output, stderr, raw auth status, control home contents는
  보존하지 않는다.
- `tool-use-observed`는 Feynman evaluation·test 성공 증거가 아니다.
  `tool-use-not-observed`는 model tool discovery/selection 결함을 좁히는 진단
  결과일 뿐이다.

이 probe는 output-directory를 evaluator-owned new descendant로만 만들고,
`feynman_subscription_smoke_exec.py`의 fixed command controls를 재사용한다.

## 검증 명령과 결과

```powershell
python -m unittest tests.test_feynman_subscription_tool_use_probe tests.test_feynman_subscription_smoke_exec
python -m unittest discover -s tests -p 'test_*.py'
python -m py_compile tooling/feynman_subscription_tool_use_probe.py
git diff --check
```

- targeted: 18 tests, OK
- full: 299 tests, 10 skipped, OK
- Python compile: OK
- `git diff --check`: 오류 없음
- Git global ignore 접근 및 LF→CRLF warning만 발생했고 검증 결과에는 영향이 없었다.

## 미완료와 다음 행동

- 실제 probe는 아직 실행하지 않았다. dedicated eval home의 canonical
  `environments.toml`이 현재 의도적으로 부재하므로, 실행 전 canonical generator로
  해당 file만 생성하고 preflight가 bytes를 검증해야 한다. login/session file은
  열람·복사하지 않는다.
- core implementation의 commit/push는 이 log 작성 시점에 pending이다. 다음 행동은
  이 probe contract/test/log를 feature branch에 commit·push한 뒤, canonical remote
  environment를 복원하여 **한 번만** actual non-evaluative probe를 실행하는 것이다.
