# LOG-053 — skill exposure and fixed tool wiring model-free preflight

- 시각: 2026-09-13 04:13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 작업 상태: DONE (model-free checkpoint)
- 시작 HEAD: `b8a1e5b600a5f5fa823995f94c2551e9f85d50a2`
- 모델 호출: 0회
- 인증 호출: 0회
- OpenAI Platform API/API key: 사용하지 않음

## 목적

LOG-052에서 만든 Luna/Terra/Sol tools-10 full-runner binding을 실제 candidate
디렉터리에 연결해 다음 실행 전 조건을 모델 없이 검증한다.

1. candidate의 `.agents/skills/feynman-thinking`만 최종 활성 상태인지 확인
2. task의 명시적 `$feynman-thinking` 호출과 runner-job condition을 결속
3. Codex App Server에서 고정 full-runner MCP 3개만 노출되는지 확인
4. write tool이나 모델을 호출하지 않고 고정 `feynman_run_tests`만 실제 실행
5. Docker test 전후 `candidate.py`가 바뀌지 않았고 network가 차단됐는지 확인

이는 실제 모델 실행, 인증 성공, candidate의 문제 해결 성공 또는 Feynman skill의
성능 근거가 아니다.

## 시작 상태와 보호 조건

실행한 확인 명령:

```powershell
git status --short --branch
git log -5 --oneline
rg --files -g 'AGENTS.md' -g '!node_modules'
```

관찰:

- 적용되는 저장소 `AGENTS.md`는 없었다.
- branch와 원격 추적 branch는 모두 `feat/feynman-thinking-v0.5-draft`였다.
- 시작 HEAD는 `b8a1e5b...`였다.
- 저장소 루트의 사용자 PNG 2개만 untracked였고 읽거나 stage하지 않았다.
- protected `C:\Users\wotmd\.codex-feynman-eval`은 읽기·복사·수정·해시하지 않았다.
- 개발 대화나 인계 문서를 candidate 입력으로 전달하지 않았다.

OpenAI 공식 문서에서 확인한 계약:

- skills는 progressive disclosure를 사용하고 저장소의 `.agents/skills`를 현재
  작업 디렉터리부터 저장소 루트까지 탐색한다.
- App Server는 `skills/list`에 `cwds`와 `forceReload`를 제공한다.
- 이 checkpoint는 위 discovery API만 사용했고 thread/turn을 시작하지 않았다.

## 구현

추가 파일:

- `tooling/feynman_skill_tool_wiring_preflight.py`
- `evals/feynman-thinking/skill-tool-wiring-preflight.schema.json`
- `tests/test_feynman_skill_tool_wiring_preflight.py`

preflight는 다음을 fail-closed로 수행한다.

- runner-job/profile와 LOG-052 binding의 identity 및 digest lineage 재검증
- 기존 filesystem skill preflight로 candidate skill set과 경계 재검증
- `task.txt` digest와 `$feynman-thinking` marker만 검사하고 prompt 본문은 미보존
- 비어 있는 disposable `CODEX_HOME`과 최소 allowlist 환경으로 App Server 실행
- 첫 `skills/list(forceReload=true)`에서 주변 skill을 메모리에서 식별
- 식별한 경로만 `skills.config=[{path=...,enabled=false}]` CLI override로 일시 차단
- 새 App Server 프로세스의 두 번째 `skills/list`에서 candidate skill만 남는지 확인
- 같은 두 번째 프로세스에서 exact MCP server 1개와 고정 tool 3개 확인
- adapter에 빈 arguments로 `feynman_run_tests`만 직접 호출
- test output/source payload는 저장하지 않고 시작·종료·exit/result·불변성만 기록

전역 설정이나 protected login home은 바꾸지 않는다. 주변 skill 경로도 결과 JSON에
저장하지 않고 이름과 개수만 남긴다.

## 첫 실행 실패와 원인

Luna에 대해 다음 형태의 실제 명령을 먼저 실행했다. 각 인자는 아래 고정 경로로
완전히 해석됐으며 output root는 `C:\DevWorks\feynman-skill-tool-wiring-20260913-01`이었다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_skill_tool_wiring_preflight `
  --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' `
  --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' `
  --binding 'C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json' `
  --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' `
  --codex-home 'C:\DevWorks\feynman-skill-tool-wiring-20260913-01\gpt-5.6-luna-codex-home' `
  --node-bin 'C:\Program Files\nodejs\node.exe' `
  --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' `
  --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' `
  --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' `
  --output 'C:\DevWorks\feynman-skill-tool-wiring-20260913-01\gpt-5.6-luna-wiring-preflight.json'
```

결과는 sanitized `ValueError`, exit 2였다. 같은 model-free discovery 결과를
payload 없이 분류해 보니 candidate 외에 다음 7개 활성 skill이 노출됐다.

```text
find-skills, imagegen, openai-docs, plugin-creator,
review-agent, skill-creator, skill-installer
```

빈 `CODEX_HOME`만으로 built-in/user discovery source가 사라진다고 가정한 것이
원인이었다. 이를 허용하거나 전역 설정을 수정하지 않고, 위의 two-pass transient
disable 방식으로 보정했다. 이 실패 중 모델·인증·Docker test는 시작되지 않았다.

## 보정 후 실제 실행과 관찰

수정된 preflight를 Luna/Terra/Sol에 각각 한 번 실행했다. 명령은 위와 같고 model,
runner-job, binding, disposable Codex home, output 파일만 각각 바꿨다. output root:

```text
C:\DevWorks\feynman-skill-tool-wiring-20260913-02
```

세 결과가 모두 다음 조건을 만족했다.

| model | verdict | 최종 candidate skill | 초기 주변 skill | 최종 주변 skill | MCP tools | fixed test | source |
|---|---|---|---:|---:|---:|---|---|
| gpt-5.6-luna | `full-runner-skill-tool-wiring-ready` | feynman-thinking | 7 | 0 | 3 | started, failed | unchanged |
| gpt-5.6-terra | `full-runner-skill-tool-wiring-ready` | feynman-thinking | 7 | 0 | 3 | started, failed | unchanged |
| gpt-5.6-sol | `full-runner-skill-tool-wiring-ready` | feynman-thinking | 7 | 0 | 3 | started, failed | unchanged |

fixed test의 `failed`는 현재 fixture의 `candidate.py`가 의도적으로 결함이 있기
때문이다. 이 checkpoint의 성공 조건은 모델이 답을 고쳤다는 것이 아니라 고정
명령이 network-disabled Docker에서 실제 시작·종료되고 source를 바꾸지 않았다는
것이다. 세 결과 모두 `model_calls=0`, `authentication_used=false`였다.

## 검증

단위·전체 회귀:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_*.py'
```

결과: `353 tests OK, 11 skipped`, exit 0. 일부 Git global ignore 접근 경고는
기존 샌드박스 권한 경고이며 test failure는 아니었다.

세 실제 산출물 schema 검증:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -c "import json, pathlib, jsonschema; s=json.loads(pathlib.Path(r'C:\DevWorks\thinking-skills\evals\feynman-thinking\skill-tool-wiring-preflight.schema.json').read_text(encoding='utf-8')); jsonschema.Draft202012Validator.check_schema(s); root=pathlib.Path(r'C:\DevWorks\feynman-skill-tool-wiring-20260913-02'); files=sorted(root.glob('*-wiring-preflight.json')); [jsonschema.Draft202012Validator(s).validate(json.loads(p.read_text(encoding='utf-8'))) for p in files]; print('schema-valid=' + str(len(files)))"
```

결과: `schema-valid=3`, exit 0.

Docker 잔여 컨테이너 확인:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' ps -a --filter 'ancestor=sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --format '{{.ID}}|{{.Status}}|{{.Names}}'
```

첫 sandbox 호출은 Docker named pipe 권한 거부로 exit 1이었다. 승인된 읽기 전용
재조회는 exit 0, 빈 출력이므로 해당 image의 잔여 컨테이너는 없다.

`git diff --check`는 문서 작성 전과 전체 문서 반영 후 모두 exit 0이었다. 후자의
LF→CRLF 안내는 Windows working-tree 변환 경고이며 whitespace error는 아니었다.

## 검증하지 않은 것

- protected subscription auth gate 재실행 또는 실제 model turn
- 모델이 `$feynman-thinking`을 실제 로드·사용했다는 trace
- 모델이 read/write/test 도구를 선택·호출하는 실행
- baseline/Feynman two-job smoke
- post-run attestation/link/evidence/review/result-v4
- behavioral quality 또는 Feynman skill의 인과적 효과

## 저장 상태

- 구현·스키마·테스트·문서 9개 파일만 명시적으로 stage했다.
- 사용자 PNG 2개는 계속 untracked로 보존했다.
- 구현 commit: `9365063a299d1b92b5c74134c27397848efd0945`
  (`feat: preflight candidate skill and tool wiring`)
- push: `origin/feat/feynman-thinking-v0.5-draft`에 완료했다.
- `git ls-remote`로 원격 feature branch가 같은 `9365063a...`임을 확인했다.
- 해당 구현 commit의 최신 PR-triggered workflow 7개가 모두 success였다.

| workflow | run ID |
|---|---:|
| validate-feynman | 34713772662 |
| validate-feynman-subscription-readiness | 34713772692 |
| validate-feynman-unit-diagnostic | 34713772678 |
| validate-feynman-docker-reference | 34713772655 |
| validate-feynman-codex-reference | 34713772672 |
| validate-feynman-remote-exec-reference | 34713772724 |
| validate-feynman-remote-patch-reference | 34713772685 |

- 이 저장 상태를 반영하는 docs-only 마감 커밋은 이 로그 변경으로 남기며, 그
  commit SHA와 최종 push 상태는 Git history와 최종 작업 보고에서 확인한다.
- main merge와 force push는 하지 않는다.

## 다음 정확한 행동

two-pass transient skill isolation과 LOG-052 full-runner CLI override를 실제
subscription smoke executor의 **명령 생성 경로**에 model-free로 결속한다. 새
preflight에서 executor가 최종적으로 만들 명령과 환경을 검증한 뒤에만, 별도
명시적 승인 아래 실제 모델 smoke 여부를 판단한다. 현재 checkpoint에서는 모델
실행이나 baseline을 시작하지 않는다.
