# LOG-054 — subscription executor command wiring model-free preflight

- 시각: 2026-09-13 09:27 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 작업 상태: DONE (model-free checkpoint)
- 시작 HEAD: `0c6ad2e472ed56dce5b79f18c7ddd6ed292290b3`
- 모델 호출: 0회
- 인증 호출: 0회
- OpenAI Platform API/API key: 사용하지 않음

## 목적

LOG-053의 결과는 별도 skill/tool wiring preflight에서만 command override를
검증했다. 이번 작업은 실제 ChatGPT subscription smoke가 사용할
`feynman_subscription_smoke_exec.py`의 명령 조립 함수를 공용화하고, 같은 함수가
model-free wiring preflight에서도 사용되도록 연결하는 것이다.

검증 대상은 다음이다.

- 고정 full-runner MCP 설정이 executor command에 들어가는가
- 첫 skill discovery의 non-candidate를 transient `skills.config`로 차단하는가
- 고정 non-interactive Codex controls와 stdin task marker가 유지되는가
- API key literal, raw command payload, 인증 material을 artifact에 보존하지 않는가

이 작업은 auth gate, `codex exec` model turn, baseline/Feynman smoke를 실행하지
않는다.

## 시작 상태와 공식 문서 확인

실행한 명령:

```powershell
git status --short --branch
git log -3 --oneline
```

관찰:

- 시작 HEAD는 `0c6ad2e...`이며 원격 feature branch와 일치했다.
- 사용자 PNG 2개만 untracked였고 보존했다.
- `C:\Users\wotmd\.codex-feynman-eval`과 그 파일 내용은 읽지 않았다.

openai-docs skill 지침에 따라 공식 Codex 문서를 먼저 검색·확인했다. App Server의
`skills/list`는 `cwds`와 `forceReload`를 지원하고, skill은 사용자 입력의
`$skill-name` marker로 명시 호출할 수 있다. 또한 `skills.config`/CLI override로
skill을 삭제하지 않고 비활성화할 수 있다. 이 문서 확인은 구현 계약의 근거이며
이 저장소의 실행 성공이나 인증 성공을 대신하지 않는다.

## 구현 변경

1. `tooling/feynman_subscription_smoke_exec.py`

   기존 `execute_smoke_job` 내부의 Codex argv 조립을
   `build_codex_exec_command()`로 추출했다. 기존 기본 controls는 유지하고,
   이미 검증된 `-c` override tuple을 마지막 stdin marker `-` 앞에 추가한다.
   함수 자체는 설정 파일·인증·모델·응답을 읽지 않는다. 기존 executor도 이
   함수를 사용하므로 command construction의 단일 경로가 됐다.

2. `tooling/feynman_skill_tool_wiring_preflight.py`

   LOG-053의 두 번째 App Server pass가 실제로 사용한 full-runner override와
   transient skill-disable override를 위 command builder에 전달한다. command
   원문은 저장하지 않고 builder 사용 여부·override 개수·stdin 종료 marker·정책
   flag만 기록한다.

3. `evals/feynman-thinking/skill-tool-wiring-preflight.schema.json`

   command builder binding과 full-runner/skill override 개수, MCP/test wiring을
   닫힌 schema로 추가했다.

4. `tests/test_feynman_subscription_smoke_exec.py`

   builder가 validated override를 stdin marker 앞에 배치하고 빈 override를
   거부하는 회귀 테스트를 추가했다.

## 실제 실행과 관찰

새 disposable output root:

```text
C:\DevWorks\feynman-skill-tool-wiring-20260913-03
```

세 모델에 대해 실제 실행한 명령은 동일한 preflight module이며 model별 runner
job, binding, disposable `CODEX_HOME`, output 경로만 정확히 달리했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_skill_tool_wiring_preflight --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\<model>\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --binding 'C:\DevWorks\feynman-full-runner-binding-20260913-01\<model>-full-runner-binding.json' --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --codex-home 'C:\DevWorks\feynman-skill-tool-wiring-20260913-03\<model>-codex-home' --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --output 'C:\DevWorks\feynman-skill-tool-wiring-20260913-03\<model>-wiring-preflight.json' --timeout-seconds 30
```

실행 결과:

| model | verdict | command builder | full-runner overrides | skill-disable overrides | MCP tools | model/auth |
|---|---|---|---:|---:|---:|---|
| gpt-5.6-luna | `full-runner-skill-tool-wiring-ready` | true | 13 | 1 | 3 | 0 / false |
| gpt-5.6-terra | `full-runner-skill-tool-wiring-ready` | true | 13 | 1 | 3 | 0 / false |
| gpt-5.6-sol | `full-runner-skill-tool-wiring-ready` | true | 13 | 1 | 3 | 0 / false |

각 fixed test는 의도된 buggy fixture 때문에 `failed`였지만, command는 시작·종료됐고
candidate source는 변경되지 않았다. 이 실패는 wiring 실패나 model 평가 결과가
아니다.

## 발견한 오류와 수정

첫 산출물 검증 명령:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -c "import json, pathlib, jsonschema; s=json.loads(pathlib.Path(r'evals\feynman-thinking\skill-tool-wiring-preflight.schema.json').read_text(encoding='utf-8')); jsonschema.Draft202012Validator.check_schema(s); root=pathlib.Path(r'C:\DevWorks\feynman-skill-tool-wiring-20260913-03'); files=sorted(root.glob('*-wiring-preflight.json')); assert len(files)==3; [jsonschema.Draft202012Validator(s).validate(json.loads(p.read_text(encoding='utf-8'))) for p in files]; print('schema-valid=' + str(len(files)))"
```

관찰: command 실행은 성공했지만 schema가 `full_runner_override_count=12`를
기대했고 실제 contract의 override는 13개였다. `command`, `args`, `cwd`, enabled/
required/tool policy, timeout, env 설정을 포함한 값이다. 실제 명령의 오류가 아니라
schema 상수 오류이므로 13으로 보정했다.

보정 후 같은 세 산출물에 대해 위 검증을 다시 실행했고 `schema-valid=3`을 얻었다.

## 검증 범위

실행한 명령:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m py_compile tooling/feynman_subscription_smoke_exec.py tooling/feynman_skill_tool_wiring_preflight.py
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest -v tests.test_feynman_subscription_smoke_exec tests.test_feynman_skill_tool_wiring_preflight
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

결과:

- py_compile 성공
- 관련 테스트 `21 tests OK`
- 전체 회귀 `354 tests OK, 11 skipped`, exit 0
- 최종 schema 검증 `schema-valid=3`, exit 0
- `git diff --check` 통과

검증하지 않은 것:

- ChatGPT subscription auth gate 또는 protected login session
- 실제 `codex exec` model turn
- 모델의 skill load/tool selection trace
- baseline/Feynman smoke와 behavior/performance
- post-run canary, attestation, link, evidence, review, result-v4

## 저장 상태

- 구현 commit: pending
- push/remote HEAD/CI: pending
- 사용자 PNG 2개는 계속 untracked로 보존한다.
- main merge와 force push는 하지 않는다.

## 다음 정확한 행동

이 command builder와 full-runner binding이 실제 subscription executor의 입력으로
고정되도록, executor 호출부에 binding/adapter/Docker 입력을 요구하는 최종 fail-closed
검사를 추가한다. 그 model-free 검증이 통과한 뒤에만 별도 승인 아래 실제
subscription smoke 여부를 판단한다.
