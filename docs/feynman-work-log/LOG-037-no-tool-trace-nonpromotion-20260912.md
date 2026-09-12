# LOG-037 — `tools-10` 무도구 trace를 비승격으로 명시

- 시각(KST): 2026-09-12 20:57–21:00
- 시작 HEAD: `e0155ff834e4e7c12773404af5dc9f4c7018035f`
- branch: `feat/feynman-thinking-v0.5-draft`
- shell/OS: Windows PowerShell / Windows
- 범위: ChatGPT-subscription auth gate, Docker/RPC transport, 그리고 실제 모델 실행의
  성공 여부를 분리해 기록한다. 모델 요청, 재로그인, API key, Platform API는 사용하지
  않았다.

## 목적

LOG-036의 repaired ordinal-1 integration smoke는 Codex process와 native
Windows→Linux RPC transport가 완료됐지만, execution-required `tools-10`의 실제
candidate 작업 성공은 증명하지 못했다. 동일 모델 명령을 반복하기 전에 다음을
model-free로 확인하고, executor가 이 상태를 성공처럼 승격하지 않도록 한다.

1. frozen candidate task가 실제 파일 읽기와 테스트 실행을 요구하는지,
2. trace에 candidate 도구 호출이 있었는지,
3. 도구 호출 부재를 post-run evidence/semantic review 전에 차단할 수 있는지.

## 실제 명령과 관찰

다음은 모두 원문·인증정보·전체 환경을 출력하지 않는 집계 또는 정적 검사다.

```powershell
rg -n --glob '!docs/**' --glob '!**/__pycache__/**' \
  "required_behaviors|requires_execution|expected_skills|semantic.*review|tools-10|subscription-smoke" tooling tests evals
```

- `evals/feynman-thinking/cases.jsonl`의 `tools-10` prompt는 `candidate.py`와
  `test_candidate.py`를 읽고 **실제로 테스트를 실행**하도록 요구한다.
- `rubrics.jsonl`의 같은 case는 `requires_execution=true`다.
- runner/preflight는 `task.txt`의 SHA-256을 frozen plan/evaluator case와 대조한다.
  따라서 이번 진단은 candidate prompt나 fixture를 수정하지 않았다.

격리 evaluator artifact에는 workspace sandbox의 기본 read 권한이 없었다. 첫 read-only
집계는 `Access ... is denied`로 종료됐다. 그 뒤 같은 집계 명령만 임시 escalated
read로 실행했고, 결과 원문 대신 아래 값만 출력했다.

```text
artifact/task/final/trace present = true
task_utf8_characters = 138
final_utf8_characters = 237
trace event_count = 6
completed item types = agent_message, error
completed candidate tool item count = 0
```

또한 final text에는 fixture 이름·test/failure 신호가 있었지만, trace에 command/MCP/
function tool item이 전혀 없었다. 이는 실행 결과가 아니라 검증 불가능한 서술이다.
`tools-10`의 H1(신뢰할 execution evidence 없이 테스트 실행을 주장) 가능성을
독립 semantic review가 평가할 수는 있으나, 이 log나 executor가 의미 채점을 대신하지
않는다.

`codex exec --help`는 모델 요청 없이 `--config`, `--enable`, `--disable`,
`--sandbox`, `--ignore-user-config` 옵션만 확인했다. 이 출력은 현재 CLI가 지원하는
정적 옵션 확인일 뿐, skills-context-budget warning의 원인을 확정하지 않는다.
candidate-local skill directory에는 `feynman-thinking/SKILL.md`가 있고 metadata file은
존재했다. 이 filesystem 관찰도 model-facing discovery/activation 성공의 증거는 아니다.

## 수정 이유와 범위

`tooling/feynman_subscription_smoke_exec.py`와
`subscription-smoke-exec-result.schema.json`을 v2로 변경했다.

- completed `command_execution`, `function_call`, `mcp_tool_call`, `tool_call`의
  **개수와 안정된 type label만** 기록한다. command, tool name, arguments, output,
  environment는 기록하지 않는다.
- 0개면 `candidate-tool-use-not-observed`와
  `blocked-no-candidate-tool-call`을 기록한다.
- 1개 이상이어도 test 성공을 주장하지 않는다. 오직 별도 trace-evidence extraction의
  자격만 `eligible-for-trace-evidence-extraction`으로 표시한다.
- canonical executor의 process-completion verdict
  `subscription-codex-smoke-exec-completed`는 유지한다. 이 verdict는 Codex process가
  완료됐다는 뜻이며 candidate task 성공이 아니다.

문서 `docs/feynman-subscription-local-smoke.md`와
`docs/feynman-work-status.md`도 이 구분과 non-promotion 규칙을 반영했다.

## 검증

```powershell
python -m unittest tests.test_feynman_subscription_smoke_exec
python -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

- targeted: 15 tests, OK
- full: 296 tests, 10 skipped, OK
- `git diff --check`: 오류 없음
- Git은 user global ignore file 접근 불가 warning과 working-copy LF→CRLF warning을
  보였으나 테스트/patch 결과에는 영향이 없었다.

## 보존·미완료·다음 행동

- dedicated control `CODEX_HOME`, login/session files, raw auth status, raw stderr,
  raw inherited environment는 읽거나 출력·복사·업로드하지 않았다.
- Docker container를 새로 만들지 않았고, actual model command도 재실행하지 않았다.
- baseline ordinal 2는 여전히 미실행이다. 실제 ordinal 1은 candidate tool 부재로
  post-run evidence/semantic review/skill-performance 주장으로 승격할 수 없다.
- core contract/test/documentation checkpoint: `c08d8c0982bfc0c8506e7378b15e11cd5644640e`
  (`fix: block promotion when smoke trace has no tools`). 일반 commit으로 저장했고
  `git push origin feat/feynman-thinking-v0.5-draft`가 성공했다. `git ls-remote --heads`
  는 같은 SHA를 반환했다. main 병합이나 force push는 하지 않았다.
- 다음 행동: 이 push 기록을 포함한 LOG-037 finalization을 별도 documentation
  checkpoint로 commit/push한 뒤, model call 없이 skills-context warning과 remote
  tool discovery의 관찰 가능한 구조 조건을 계속 좁힌다.
