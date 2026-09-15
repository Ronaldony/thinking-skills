# LOG-108 — NEXT-01~03 실행 spec 결속과 경계 회귀

Date: 2026-09-15 KST. Repository: `Ronaldony/thinking-skills`.
Branch: `feat/feynman-thinking-v0.5-draft`.

## 작업 범위와 보호 경계

이번 단계는 사용자 인계의 NEXT-01~03만 수행했다. 목표는 현재 코드와 문서의
기준을 분리하고, 한 번의 canonical smoke가 사용할 비밀 없는 실행 spec을
고정하며, `smoke → startup_diagnostic.run() → startup validator → model
boundary` 연결을 외부 프로세스 경계만 합성해 검증하는 것이다.

다음은 실행하지 않았다.

- 보호된 ChatGPT 구독 auth gate, 실제 subscription startup/thread 생성, model turn
- Luna/Terra/Sol fallback, retry, baseline 실행, 행동 평가 EVAL-01/02
- OpenAI Platform API, API key, credential/token 파일 열람 또는 전체 환경변수 출력
- main 병합, force push, broad Docker prune, Docker Desktop 전체 종료, mount 확대

`.tmp/`, 사용자 PNG 2개, `LOG-099`와 기존 evaluator 증거 및 로그인 홈은 보존했다.
LOG-107은 역사 기록이므로 수정하지 않았다.

## 시작 상태와 문서 정정

실행 명령:

```powershell
git status --short --branch
git rev-parse HEAD
git log -5 --oneline --decorate
rg --files -g AGENTS.md
```

관찰:

- 적용되는 `AGENTS.md`는 없었다.
- 시작 code/reference SHA는 `f7e9efdd61ee67f9df98cd509f54d925bcb0bd31`이었다.
- branch와 origin branch는 같은 SHA를 가리켰다.
- tracked/staged 변경은 없었고, untracked 보호 대상만 있었다: `.tmp/`, PNG 2개,
  `LOG-099`.
- 세 current pointer 문서의 상단이 과거 문서 commit `18026ce`를 “최종 HEAD”로
  표시하고 있었다. code SHA와 current documentation SHA를 혼동하는 문서 결함이다.
  과거 LOG-107의 문구는 보존하고 current pointer만 새 재개 지점으로 갱신한다.

## NEXT-01 — code SHA와 문서 상태 분리

과거 log를 계속 고치는 방식은 재개 비용을 늘리고 새 “final HEAD” 문서 commit을
무한히 만들 수 있다. LOG-108은 시작 시점의 code/reference SHA와 current branch
상태를 기록하고, current pointer는 최신 재개 지점과 code 기준을 분리한다. 이
문서 자체의 commit SHA는 self-reference하지 않는다.

완료 기준:

- historical receipt는 immutable하게 남는다.
- current pointer 하나가 LOG-108만 가리킨다.
- 실제 code 기준 SHA와 문서 갱신으로 생긴 후속 SHA를 최종 전달에서 별도로 보고한다.

## NEXT-02 — 비밀 없는 immutable execution spec

### 입력 고정

기존 checkpoint를 실행하지 않는 모드로 검증했다.

```powershell
python -B -m tooling.feynman_subscription_startup_diagnostic `
  --checkpoint .tmp/feynman-subscription-checkpoint-20260914-v4.json `
  --validate-only
```

관찰:

```text
verdict=subscription-checkpoint-valid
binding_valid=true
binding_config_override_count=13
model=gpt-5.6-luna
subprocesses_started=0
authentication_material_present=false
```

canonical runner job와 evaluator case를 현재 feature run root에서 읽어
`tooling.feynman_subscription_run_preflight.preflight_files()`로 비교했다.

관찰:

```text
verdict=ready-for-local-chatgpt-session-check
run_id=feynman-remote-compat-20260912-01-gpt-5.6-luna
condition_id=feynman-v05
model=gpt-5.6-luna
candidate_skill_preflight_valid=true
control_codex_home_protected=true
```

이 요약 단계에서 존재하지 않는 반환 키를 선택한 첫 one-liner는 `KeyError`로
끝났으며 preflight 자체의 실패가 아니었다. 실제 반환 schema의
`candidate_task_sha256`/ `runner_job_sha256`를 선택해 재실행했고 통과했다.

### model-free wiring preparation

현재 runner job, boundary profile, evaluator case, canonical remote environment,
full-runner binding, Node, adapter, Docker executable/config, image digest를
그대로 전달해 `prepare_full_runner_executor_wiring(..., timeout_seconds=30)`을
1회 수행했다. isolated Codex home만 사용했고 protected control home은 사용하지
않았다.

관찰:

```text
verdict=model-free-wiring-prepared
preparation_fingerprint=d726dd39e9bb23737b459d7ab8aa8f6424309df2be761664e93b33ef1bd76b2b
full_runner_override_count=13
skill_override_count=1
total_override_count=14
model_calls=0
authentication_used=false
```

과거 `.tmp` wiring artifact에는 이 fingerprint가 없었으므로 stale fingerprint를
재사용하지 않았다.

### execution spec 구현

추가한 `tooling/feynman_subscription_execution_spec.py`는 다음 정보를 SHA-256
또는 path identity hash로만 기록한다.

- eval plan, smoke spec, evaluator case, runner job, boundary profile,
  remote environment, candidate task, full-runner binding
- Codex/Node/adapter/Docker 실행 파일
- candidate/evaluator/control home/Docker config/output 디렉터리 identity
- candidate image와 full-runner image digest, model/CLI version
- baseline/feynman skill intent와 candidate `.codex` 부재
- evaluator-owned output, instruction-source allowlist required,
  stale report replay 금지, startup gate 선행 조건
- preparation fingerprint

Docker config 디렉터리 내용과 control home 내용은 읽거나 fingerprint하지 않는다.
실제 canonical 입력으로 read-only builder와 current revalidation을 실행했다.

관찰:

```text
verdict=subscription-execution-spec-frozen
schema_version=1
role_digest_count=12
path_identity_count=5
candidate_skills=['feynman-thinking']
candidate_project_codex_absent=True
instruction_source_allowlist_required=True
docker_config_contents_read=False
raw_contains_absolute_candidate_path=False
raw_contains_api_key_name=False
execution-spec-current=true
external_processes=0
auth=0
model=0
```

canonical smoke 실행 시 spec은 evaluator-owned output directory의
`execution-spec.json`으로 새로 저장되고 control-plane/auth/model 경계마다
동일 입력을 재계산한다. drift가 있으면 `frozen execution spec drift`로
fail-closed한다. 결과 schema v3에도 spec artifact와 SHA-256을 포함하도록
producer/reader/consumer를 함께 맞췄다.

## NEXT-03 — 실제 연결 경계와 실패 차단 회귀

`tests/test_feynman_subscription_smoke_exec.py`에 다음 회귀를 추가했다.

1. 실제 `execute_smoke_job()`이 실제 `startup_diagnostic.run()`을 호출하고,
   실제 `_validate_startup_gate()`가 startup report/telemetry를 검증하는 경로.
   App Server와 model-facing fake Codex는 외부 process boundary에서만 대체했다.
2. control-plane 반환 뒤 candidate task가 변조되면 execution spec drift로 auth 전에
   차단되는 경로.
3. `timeout_seconds=300`이 model-facing `subprocess.run(timeout=300)`에
   전달되고 startup budget은 별도 bounded budget으로 유지되는 경로.
4. evaluator-owned startup artifact와 execution spec artifact의 저장 및 schema 검증.
5. spec에 candidate raw path/API-key 이름이 들어가지 않는 개인정보 경계.

합성 시험 중 발견한 두 시험 설계 문제도 즉시 좁혔다.

- 빈 `instructionSources`와 `instruction_sources_allowed=true`를 함께 사용하던
  fake 응답을 실제 validator가 일관성 오류로 차단했다. 허용된 synthetic source를
  넣어 정상 경로를 검증했다.
- App Server용 `subprocess.Popen` fake가 전역 subprocess 객체를 통해 model fake
  실행까지 가로채던 문제가 있었다. `app-server` 명령만 fake로 분기하고 model
  subprocess는 실제 fake Codex child를 사용하도록 수정했다.

## 변경 파일

- `tooling/feynman_subscription_execution_spec.py` — 새 model-free immutable spec
  producer/reader/current validator
- `evals/feynman-thinking/subscription-execution-spec.schema.json` — spec schema v1
- `tooling/feynman_subscription_smoke_exec.py` — spec 저장, 경계별 drift 검사,
  결과 artifact 연결
- `evals/feynman-thinking/subscription-smoke-exec-result.schema.json` — execution
  spec result block을 required로 추가
- `tests/test_feynman_subscription_smoke_exec.py` — 실제 startup/validator 연결,
  drift, 300초 model timeout, schema/privacy 회귀
- current pointer 문서 3개 — LOG-108을 최신 재개 지점으로 지정

## 검증 결과

### 변경 영역

```powershell
python -B -W error::ResourceWarning -m unittest -v `
  tests.test_feynman_subscription_smoke_exec `
  tests.test_feynman_subscription_startup_diagnostic `
  tests.test_feynman_subscription_run_preflight `
  tests.test_feynman_subscription_checkpoint `
  tests.test_feynman_subscription_executor_wiring_preflight `
  tests.test_feynman_docker_runtime_probe `
  tests.test_feynman_rpc_compatibility
```

결과: `133 tests OK, 2 skipped`.

첫 목록에 존재하지 않는 `tests.test_feynman_rpc_path_contract`를 넣은 실행은
loader `ModuleNotFoundError`로 끝났다. 모듈을 제외한 동일 범위를 재실행해
`133 tests OK, 2 skipped`를 확인했다.

### 전체 suite

```powershell
python -B -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -q
```

결과: `Ran 489 tests`, `OK (skipped=11)`, ResourceWarning 없음.

11 skip 사유:

- Windows에서 FIFO 불가 1
- Windows symlink/special-file privilege 또는 host별 symlink 동작 차이 5
- Windows ambient skill-root가 temp fixture에 상속되는 조건 3
- native Docker/Codex catalog integration은 명시적
  `FEYNMAN_RUN_DOCKER_INTEGRATION=1` opt-in 필요 1
- 나머지 symlink privilege 조건 1

위 skip은 호환성 성공으로 세지 않았다. Docker/path 실제 gate의 과거 통과 증거도
이번 unit 결과로 재승격하지 않았다.

### schema/정적 검증

```powershell
python -B -c "... Draft202012Validator.check_schema(...) ..."
python -B -m py_compile tooling/feynman_subscription_execution_spec.py tooling/feynman_subscription_smoke_exec.py tests/test_feynman_subscription_smoke_exec.py
git diff --check
```

결과: `schema_files=18 errors=0`, compile 통과, diff check 오류 없음.
PowerShell 환경의 기존 CRLF 변환 warning만 관찰했다.

## 실행 횟수와 현재 경계

| 항목 | 이번 단계 |
|---|---:|
| checkpoint validate-only | 1 |
| canonical structural preflight | 2회 시도(첫 출력 키 선택 오류 1, 통과 1) |
| isolated model-free wiring preparation | 1 |
| 실제 protected subscription auth | 0 |
| 실제 protected startup/thread 생성 | 0 |
| 실제 model command / model turn | 0 |
| retry / fallback / Terra / Sol | 0 |
| baseline smoke / behavioral evaluation | 0 |

이번 합성 시험의 fake App Server와 fake Codex는 실제 구독 실행 증거가 아니다.
Docker runtime/path contract의 기존 `docker-runtime-ready`와
`rpc-path-contract-equivalent`도 실제 ChatGPT startup 호환성 증거가 아니다.

## commit/push와 미완료 사항

이 log 작성 후 보호 대상이 아닌 9개 변경 파일만 feature branch에 commit했다.
commit은 268f716 (feat: freeze subscription smoke execution spec)이며,
f7e9efd..268f716 범위가 feature branch로 normal push 성공했다. main 병합과
force push는 하지 않았다. 이 후속 문서 정정은 이미 push된 code commit의 현재
상태를 정확히 남기기 위한 것이며, 새 실행이나 code behavior 변경을 포함하지 않는다.

commit/push 후에도 사람 개입 경계는 그대로다. 최신 code/docs pointer, current
execution spec, full-runner input, intended evaluator-owned output path,
preparation fingerprint를 검토한 뒤에만 다음을 승인할 수 있다.

```text
startup diagnostic: 최대 1회
조건부 성공 시 Luna tools-10 smoke: 최대 1회
model-facing timeout: 명시적 --timeout-seconds 300
retry/fallback/baseline/evaluation: 0회
```

startup gate가 실패하면 같은 입력 반복이나 다른 모델 fallback 없이 중단한다.
startup 성공은 model smoke 성공과 분리하고, smoke 성공도 Feynman 행동 성능
비교와 분리한다.
