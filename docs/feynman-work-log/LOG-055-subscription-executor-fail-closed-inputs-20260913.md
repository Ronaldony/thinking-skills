# LOG-055 — subscription executor fail-closed full-runner inputs

- 시각: 2026-09-13 09:45 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 작업 상태: DONE (model-free checkpoint)
- 시작 HEAD: `452c2fcd887c62758f95ec87850b0913817bd723`
- 모델 호출: 0회
- 인증 호출: 0회
- OpenAI Platform API/API key: 사용하지 않음

## 목적

LOG-054에서 공용 Codex command builder를 만들었지만, 실제 subscription smoke
executor CLI가 full-runner binding 없이도 시작될 여지가 있었다. 이번 작업은
canonical CLI가 다음 입력을 모두 요구하고, structural preflight 직후 인증·모델
호출 전에 binding lineage를 검증하도록 연결한다.

- full-runner binding manifest
- Node executable
- full-runner adapter
- Docker executable
- isolated Docker config directory
- content-addressed Docker image ID

인증 파일이나 protected `CODEX_HOME`의 내용을 읽지 않고, 실제 `codex exec` model
turn도 시작하지 않는다.

## 시작 확인

실행한 명령:

```powershell
git status --short --branch
git log -3 --oneline
rg -n "execute_smoke_job|build_codex_exec_command|codex exec" tooling/feynman_subscription_smoke_exec.py tests/test_feynman_subscription_smoke_exec.py
```

관찰:

- 시작 HEAD는 `452c2fc...`이며 feature branch와 원격이 일치했다.
- 사용자 PNG 2개만 untracked였고 stage하지 않았다.
- `C:\Users\wotmd\.codex-feynman-eval`은 읽거나 수정하지 않았다.
- 이전 단계에서 인증·모델 호출은 0회였다.

## 구현

`tooling/feynman_subscription_smoke_exec.py`에
`_validate_full_runner_binding()`을 추가했다. 이 함수는 다음을 검사한다.

- binding schema/verdict와 runner job의 run/case/condition/model/Codex identity
- runner job 및 boundary profile digest lineage
- 실제 adapter·candidate·Docker 입력으로 재생성한 full-runner override와 binding
  implementation의 exact equality
- immutable Docker image ID 형식

`execute_smoke_job()`은 이 입력 묶음이 일부만 주어지면 fail-closed하고, 전부 주어질
때는 structural preflight 직후, control auth gate 이전에 binding을 검증한다. 검증된
override만 `build_codex_exec_command()`에 전달한다.

canonical `main()` CLI에는 아래 6개를 모두 required로 추가했다.

```text
--full-runner-binding
--full-runner-node-bin
--full-runner-adapter
--full-runner-docker-bin
--full-runner-docker-config
--full-runner-image-id
```

기존 직접 호출 unit fixture는 하위 호환을 위해 override 없이 builder를 검사하지만,
운영용 canonical CLI에는 argparse 단계에서 누락 입력 우회가 없다.

## 실제 실행과 관찰

CLI 인터페이스 확인:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_subscription_smoke_exec --help
```

관찰: 위 6개 인자가 모두 `required` usage에 나타났고, auth/model subprocess는
시작되지 않았다.

부분 입력 fail-closed unit:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest -v tests.test_feynman_subscription_smoke_exec
```

새 `test_partial_full_runner_inputs_fail_before_auth`가 통과했다. 한 개의 binding
경로만 전달한 경우 ValueError가 auth gate보다 먼저 발생하고 auth call count는 0이다.

실제 모델 없이 이전 단계의 세 model wiring preflight artifact를 대상으로 command
builder 경로도 유지 확인했다.

- Luna/Terra/Sol: `full-runner-skill-tool-wiring-ready`
- full-runner override: 각 13개
- transient skill-disable override: 각 1개
- MCP tool: 각 3개
- model calls: 0
- authentication used: false

## 검증

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m py_compile tooling/feynman_subscription_smoke_exec.py
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

결과:

- py_compile 성공
- 전체 회귀 `355 tests OK, 11 skipped`, exit 0
- `git diff --check` 통과

검증하지 않은 것:

- ChatGPT subscription auth gate 재실행
- 실제 `codex exec` model turn
- 모델의 skill load/tool selection trace
- baseline/Feynman smoke 및 behavioral performance
- post-run canary, attestation, link, evidence, review, result-v4

## 저장 상태

- 구현 commit: pending
- push/remote HEAD/CI: pending
- 사용자 PNG 2개는 계속 untracked로 보존한다.
- main merge와 force push는 하지 않는다.

## 다음 정확한 행동

다음은 새 required CLI 입력을 실제 Luna/Terra/Sol smoke 명령 계획 artifact에
model-free로 연결하고, transient skill-disable override를 executor 입력 계약에
명시적으로 포함하는 작업이다. 그 preflight와 별도 승인 전에는 실제 모델 실행을
시작하지 않는다.
