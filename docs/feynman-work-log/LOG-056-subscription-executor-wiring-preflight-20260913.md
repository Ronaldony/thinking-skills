# LOG-056 — subscription executor wiring model-free preflight

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `8b88b4f5f4f9f1a73e8629d0404cb87c48310365`
- 작업 범위: native Windows executor wiring과 model-free command-plan preflight
- 모델 호출: 0회
- 인증 호출: 0회
- OpenAI Platform API/API key: 사용하지 않음
- protected evaluation home: `C:\Users\wotmd\.codex-feynman-eval`을 읽거나 수정하지 않음

## 목적

LOG-055에서 canonical smoke CLI의 full-runner binding, Node adapter, Docker
executable/config, immutable image ID를 required로 만들었다. 이번 단계는 그
입력 계약을 실제 executor command construction에 연결하고, LOG-053의 two-pass
skill discovery 결과를 같은 실행 명령에 자동으로 결속하는 것이다. 목표는 사람이
skill 경로를 수동으로 전달하지 않아도 실행 전에 candidate skill/tool wiring을
검증할 수 있게 만드는 것이며, 실제 auth/model turn은 시작하지 않는다.

## 시작 확인

실행 명령:

```powershell
git status --short
git diff -- tooling/feynman_subscription_smoke_exec.py
rg -n "prepare_full_runner|build_codex_exec_command|transient_config_overrides" tooling tests
```

관찰:

- 시작 HEAD는 `8b88b4f`였고 branch는 feature branch였다.
- 기존 사용자 PNG 2개만 untracked였으며 이번 변경에서 stage하지 않았다.
- Codex `0.154.0`, Windows `codex.cmd`, Node, Docker Desktop executable과
  full-runner image digest 입력이 준비돼 있었다.
- 세 runner job은 `tools-10 / feynman-v05`이며 모델은 Luna, Terra, Sol이었다.

## 구현과 수정 이유

### 1. 실제 executor에 자동 wiring 연결

`tooling/feynman_subscription_smoke_exec.py`에
`prepare_full_runner_executor_wiring()`을 추가했다. 함수는 다음 순서를 고정한다.

1. runner job/profile/binding lineage와 native Windows full-runner 입력을 검증한다.
2. disposable empty `CODEX_HOME`, candidate HOME, temp를 만든다.
3. App Server `skills/list(cwds=[candidate], forceReload=true)`를 첫 번째로 호출한다.
4. 활성 non-candidate skill 경로를 메모리에서만 받아 통합 transient
   `skills.config` disable override를 만든다.
5. 새 disposable App Server에서 candidate skill set과 fixed MCP catalog를 다시
   확인한다.
6. full-runner override와 skill override를 `build_codex_exec_command()`에 전달한다.

이 helper는 실제 executor에서 structural preflight 뒤, protected subscription auth
gate 전에 호출되도록 연결했다. helper가 실패하면 auth/model 호출로 진행하지 않는다.
결과에는 full-runner binding 및 skill isolation 여부를 boolean으로만 남기고 raw
config/path/prompt payload는 보존하지 않는다.

### 2. 별도 command-plan preflight CLI와 schema

다음을 추가했다.

- `tooling/feynman_subscription_executor_wiring_preflight.py`
- `evals/feynman-thinking/subscription-executor-wiring-preflight.schema.json`
- `tests/test_feynman_subscription_executor_wiring_preflight.py`

새 CLI는 같은 helper와 command builder를 사용하지만 auth, thread/turn, model call,
fixed evaluation test를 시작하지 않는다. candidate boundary image와 full-runner
adapter image는 역할이 다르므로 image ID equality를 강제하지 않도록 보정했다.
또한 6개 non-candidate skill을 1개의 통합 override로 비활성화하는 실제 결과를
발견해, skill 개수와 override 개수를 혼동하지 않도록 검증을 수정했다.

## 실제 명령과 관찰

관련 테스트:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_*.py'
```

결과: `358 tests / 11 skipped`, exit 0.

세 모델 command-plan 실행은 다음 공통 입력을 사용했다.

- Codex: `C:\Users\wotmd\AppData\Roaming\npm\codex.cmd`
- Node: `C:\Program Files\nodejs\node.exe`
- Docker: `C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`
- Docker config: `C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config`
- full-runner image: `sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a`
- adapter: repository의 `feynman_full_runner_adapter.mjs`

Luna, Terra, Sol 각각 다음 결과를 출력했다.

```text
verdict: subscription-executor-wiring-ready
condition_id: feynman-v05
full_runner_override_count: 13
transient_skill_disable_override_count: 1
model_calls: 0
authentication_used: false
```

산출물 위치:

`C:\DevWorks\feynman-subscription-executor-wiring-20260913-01\<model>\executor-wiring-preflight.json`

저장 위치가 workspace 밖이라 sandbox 쓰기에서 한 번 `PermissionError`가 났고,
사용자 지정 artifact root에 한정한 외부 쓰기 승인을 받은 뒤 같은 명령을 재실행해
세 결과를 저장했다. auth home에는 접근하지 않았다.

Schema/민감 payload 검사:

```powershell
... jsonschema.Draft202012Validator.check_schema(...)
... 세 artifact validate
```

결과: `schema-valid=3`; JSON 안에 exact `command`, `argv`, `path` payload key는
0건이었다. command plan은 builder 이름, override 개수, stdin marker 결속,
model/candidate cwd 결속 boolean만 기록한다.

## 검증 범위와 해석

확인한 것:

- 세 모델 job/profile/binding의 lineage 일치
- candidate의 `feynman-thinking` skill set과 명시적 invocation marker
- App Server two-pass skill isolation
- fixed MCP 3-tool catalog
- full-runner override 13개 + transient skill-disable override 1개
- canonical command builder와 stdin marker 결속
- model/auth 0회 및 payload 비보존
- 전체 unit 회귀와 artifact schema

확인하지 않은 것:

- ChatGPT subscription auth gate 재실행
- 실제 Codex `exec` model turn
- 모델의 skill load/tool selection과 candidate 응답
- baseline/Feynman behavioral comparison
- post-run canary, attestation, evidence, review, analysis-result

따라서 현재 상태는 `subscription-executor-wiring-ready`이지 auth/evaluation-ready가
아니다. 사람 개입이 필요한 다음 지점은 보호된 ChatGPT subscription login을
사용하는 auth gate 실행 승인과, auth 성공 후 실제 model-turn smoke 실행 승인이다.

## 저장 상태

- 구현 commit: `03457b135da1a79de7a3ef61f5ab508261eb1b89`
  (`feat: bind subscription executor skill isolation preflight`)
- `origin/feat/feynman-thinking-v0.5-draft`에 push했고 local/remote HEAD가
  `03457b1`로 일치한다.
- `git diff --check` 통과, 전체 `358 tests / 11 skipped` 통과.
- PR-triggered workflow 7개가 모두 `completed / success`다.
- 이 문구 보정은 docs-only 후속 commit으로 저장한다.
- main merge와 force push는 하지 않는다.
- 사용자 PNG 2개는 계속 untracked로 보존한다.
