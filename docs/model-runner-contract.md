# 외부 model-runner 계약

상태: **v0.4 — remote exec/patch + synthetic-auth reference proven; external model-service run and behavioral pilot pending**.

이 문서는 `feynman-thinking` 행동 비교의 실제 후보 모델 실행 경계를 정의한다. `docs/eval-runner-contract.md`가 filesystem/network canary와 boundary evidence를 다룬다면, 이 문서는 **모델 control plane과 candidate tool 실행을 어떻게 분리하고 frozen eval job을 어떤 순서로 실행해 analysis-result v3까지 연결할지**를 다룬다.

## 현재 채택한 구조

별도 arbitrary credential proxy를 새로 발명하지 않고 Codex의 remote environment / `exec-server` 경로를 사용한다.

```text
host/control plane
  ├── Codex frontend
  │    ├── model-service credential 또는 synthetic/mock credential
  │    └── model-service network
  │
  └── stdio JSON-RPC
        ↓
Docker external tool boundary
  ├── codex exec-server --listen stdio
  ├── candidate workspace
  ├── ephemeral HOME / CODEX_HOME / temp
  ├── shell/file/apply_patch tool execution
  └── closed case: --network none
```

핵심은 **모델 API를 호출하는 frontend와 모델이 조작할 수 있는 tool process의 filesystem/network boundary를 분리**하는 것이다. control-plane credential material을 candidate tool environment/file/argv에 전달하지 않는다.

### full-runner MCP 결속

tools-10의 native Windows artifact chain에 고정 MCP runner를 연결할 때는
`tooling/feynman_full_runner_binding.py`를 사용한다. 이 도구는 기존
`runner-job.json`과 `boundary-profile.json`을 수정하지 않고, 다음을 다시 검증한
payload-free binding manifest를 생성한다.

- job/profile의 schema·digest·ChatGPT subscription auth contract
- host path → `/run/candidate`, `/run/home`, `/run/codex`, `/run/temp` native mapping
- full-runner 3-tool catalog preflight와 실제 network-disabled Docker preflight
- model/auth 호출 0회 및 credential/task payload 비보존

full-runner adapter가 사용할 Docker image는 기존 remote-exec profile image와
다를 수 있다. 두 image digest는 manifest에 별도 기록하며, 불일치를 숨겨
기존 profile이 full-runner image를 실행했다고 주장하지 않는다. 이 binding은
실행 전 plumbing evidence일 뿐 actual model turn이나 skill performance evidence가
아니다.

2026-09-08 reference에서 다음을 실제 GitHub Actions로 분리 검증했다.

- control-plane Codex → network-none stdio remote `exec_command` → tool output → mock final 왕복
- patch-capable bundled model metadata를 명시한 remote `apply_patch → exec_command` 왕복
- synthetic bearer credential이 control-plane HTTP request에는 사용되지만 candidate remote tool env/file/argv 및 보존 artifact exact-byte scan에는 나타나지 않는 auth separation reference
- boundary profile ↔ Docker inspect consistency

이 reference들은 **실제 외부 model-service 인증 성공이나 Feynman 스킬 성능 결과가 아니다.**

## 원칙

1. 모델 인증정보는 candidate tool environment, candidate-readable file, tool command argument에 넣지 않는다.
2. credential **값**은 runner job, attestation, runner-job-link, analysis result에 저장하지 않는다.
3. runner가 임의로 condition/prompt/runtime/profile/model/auth architecture를 재작성하지 않는다.
4. 실행 전 `runner-job.json`, 원본 `boundary-profile.json`, canonical `environments.toml`을 검증한다.
5. tool boundary는 evaluator/source/real-HOME을 mount하지 않는다.
6. closed-network case의 tool process는 `--network none` 또는 동등한 외부 enforcement를 사용한다.
7. boundary 성공, model transport 성공, auth separation 성공, 모델 답변 품질은 서로 다른 주장이다.
8. 실제 외부 model run이 없으면 행동 성능 데이터를 만들지 않는다.
9. analysis-ready result는 pre-run runner job에서 post-run attestation까지의 lineage가 재계산 가능해야 한다.

## 1. runner job 생성

frozen plan에서 한 ordinal을 선택하고 condition workspace를 준비한 뒤 다음을 생성한다.

```bash
python tooling/feynman_runner_job.py \
  --plan eval-plan.json \
  --ordinal <N> \
  --evaluator-case evaluator/case.json \
  --boundary-profile boundary-profile.json \
  --run-id <run-id> \
  --model <exact-model-id> \
  --codex-cli <exact-cli-version> \
  --candidate-dir <candidate> \
  --evaluator-dir <evaluator> \
  --source-repo <source> \
  --ephemeral-home <home> \
  --codex-home <tool-codex-home> \
  --temp-dir <tool-temp> \
  --real-home <real-home> \
  --control-plane-credential-env-key <ENV_KEY_NAME> \
  --output runner-job.json
```

`runner-job.json` schema v2에는 credential **값**을 넣지 않는다. 현재 검증된 authentication contract는 다음으로 고정한다.

```json
{
  "mode": "control-plane-only",
  "control_plane_credential_source": "environment",
  "control_plane_credential_env_key": "OPENAI_API_KEY",
  "candidate_tool_auth_env_keys": [],
  "candidate_readable_credential_files": [],
  "credential_command_arguments": []
}
```

`OPENAI_API_KEY`는 기본 env-key **이름**이다. 실제 운영 환경이 다른 key 이름을 사용하면 `--control-plane-credential-env-key`로 그 이름을 기록한다. 값은 artifact에 저장하지 않는다.

`control-plane-only`의 의미:

- credential을 가진 Codex/model provider process는 tool boundary 밖에 존재한다.
- candidate tool process는 그 credential key/value를 받지 않는다.
- 별도 custom TCP credential proxy가 존재한다고 주장하지 않는다.

## 2. 실행 전 strict validation

```bash
python tooling/feynman_runner_job_validate.py \
  --job runner-job.json \
  --boundary-profile boundary-profile.json
```

validator는 특히 다음을 검사한다.

- runner-job schema v2
- profile raw SHA가 job의 boundary/digest와 동일
- candidate workspace, ephemeral HOME, tool CODEX_HOME, temp가 profile의 **전체 rw mount 집합과 정확히 동일**
- evaluator/source/real-HOME은 candidate-owned root가 아님
- candidate credential env/file/argv 없음
- control-plane credential env-key 이름이 candidate env allowlist에 없음
- auth mode=`control-plane-only`, source=`environment`
- profile network mode와 job tool-network 정책 일치
- baseline/generic runtime 없음
- legacy-clean/v0.5 runtime SHA 존재
- condition별 expected skill set 정확

runner는 이 검사를 우회하는 별도 unsafe mode를 제공하지 않는다.

## 3. canonical remote environment 생성

`tooling/feynman_remote_exec_environment.py`가 validated runner job과 boundary profile에서 `environments.toml`을 생성한다.

```bash
python tooling/feynman_remote_exec_environment.py \
  --job runner-job.json \
  --boundary-profile boundary-profile.json \
  --output control-codex-home/environments.toml
```

closed-network Docker reference에서 생성기는 다음을 고정한다.

- `include_local = false`
- default environment 하나만 허용
- `program = "docker"`
- `docker run -i`
- `--network none`
- `--cap-drop ALL`
- `--security-opt no-new-privileges`
- read-only container root
- exact UID:GID
- candidate/HOME/CODEX_HOME/temp 네 개의 exact rw bind
- evaluator/source/real-HOME bind 없음
- `env -i` + 명시 환경변수
- `codex exec-server --listen stdio`

생성 후 동일 도구의 `--validate` 경로로 TOML을 다시 읽어 canonical document와 완전히 같은지 확인한다.

## 4. Docker 선언과 실제 launch config 검증

Docker reference backend에서는 profile 문자열만 믿지 않는다.

`tooling/feynman_docker_reference_inspect.py`가 실제 `docker inspect`의 다음 값을 profile과 대조한다.

- content-addressed image ID
- network mode
- read-only root
- privileged flag / capabilities
- no-new-privileges
- UID:GID
- bind/volume mount destination + RW
- tmpfs
- `env -i` 환경 key

이 검사는 **launch config consistency**의 증거다. 실제 접근 차단은 별도 canary가 담당한다.

## 5. boundary canary

실제 행동 pilot에서는 해당 run과 동일한 profile bytes에 대해 canary를 통과시킨다.

- inside-boundary: `tooling/feynman_boundary_probe.py`
- outside-boundary: `tooling/feynman_boundary_probe_verify.py`
- closed-network control reference: `tooling/feynman_network_reference.py`

검증 대상:

- candidate read/write 허용
- evaluator/source/real-HOME read 차단
- evaluator/source/real-HOME forbidden write 차단
- candidate tool env에서 secret-like key 부재
- control plane에서 reachable한 endpoint가 tool boundary에서는 unreachable

canary profile과 model-run profile digest가 다르면 canary를 재사용하지 않는다.

## 6. credential-free remote exec reference

`.github/workflows/validate-feynman-remote-exec-reference.yml`은 실제 API credential 없이 model/tool transport architecture를 검증한다.

mock Responses server가 `exec_command`를 요청하고 remote command는 다음 marker를 모두 만들어야 한다.

- `REMOTE_EXEC_OK`: candidate workspace write가 실제 remote tool에서 실행됨
- `NETWORK_BLOCKED`: control plane에서 reachable한 동일 endpoint를 remote tool이 연결하지 못함
- `AUTH_ENV_CLEAN`: control plane에 둔 dummy auth-like env key가 remote tool env에 없음

두 번째 mock model request에 해당 tool output이 실제로 되돌아오지 않으면 final을 반환하지 않는다. 정상 왕복일 때만 `REMOTE_EXEC_REFERENCE_OK`를 반환한다.

이 reference는 control/tool Codex version 동일성, frozen baseline job, canonical remote environment, Docker inspect/profile 일치, candidate marker, completed `command_execution`, exact final을 함께 확인한다.

## 7. remote apply-patch reference

`.github/workflows/validate-feynman-remote-patch-reference.yml`은 `apply_patch`를 exec-only transport 검증과 분리한다.

초기 실패에서 mock model은 fallback metadata를 사용해 `apply_patch` handler가 등록되지 않았는데도 custom tool call을 생성했다. 현재 reference는 설치된 Codex의 bundled model catalog에서 원래부터:

- unified exec shell
- text input
- `apply_patch_tool_type = "freeform"`

을 지원하는 model metadata만 선택하고 identity를 mock-model로 치환한다. `tooling/feynman_mock_model_catalog.py`는 unsupported model에 patch capability를 새로 만들어 넣지 않는다.

그 metadata가 명시적으로 적용된 상태에서:

```text
mock model → remote apply_patch → patch output round-trip
           → remote exec_command가 patch marker 읽음
           → network/auth-env marker 검증
           → mock final
```

을 검증한다.

이 reference의 성공은 **현재 Codex tool registration + selected remote environment에서 patch/exec round-trip이 가능함**을 보여준다. 실제 모델이 좋은 patch를 선택한다거나 Feynman skill이 좋아졌다는 뜻이 아니다.

## 8. synthetic-auth separation reference

`.github/workflows/validate-feynman-synthetic-auth-reference.yml`은 실제 secret 대신 run-scoped synthetic bearer 값을 사용한다.

검증 목표는 값의 인증 효력 자체가 아니라 **credential material의 위치**다.

- control-plane mock HTTP request의 Authorization bearer가 기대값 digest와 일치
- remote network-none tool env에는 credential key/value 없음
- candidate-readable file/argv에도 값 없음
- trace/evidence/result 등 보존 artifact를 exact bytes로 scan했을 때 synthetic secret이 없음
- scan result와 remote reference result를 content digest로 결속

synthetic-auth 성공은 실제 OpenAI OAuth/API key/account/project semantics를 검증하지 않는다.

## 9. 실제 model-service 인증 경계

실제 pilot에서 사람이/runner 운영자가 개입해야 하는 첫 외부 권한 지점이다.

필요한 것은 credential 값을 코드나 채팅에 넣는 것이 아니라 승인된 secret store/runner environment에서 **control-plane 전용 credential**을 사용할 수 있게 하는 것이다.

필수 성질:

- credential은 control-plane Codex frontend/model provider만 소유
- runner-job/attestation에는 env-key 이름만 기록
- candidate tool environment에 auth key/value 없음
- candidate-readable HOME/CODEX_HOME에 credential file 없음
- tool command line에 credential 없음
- closed-network tool boundary는 model endpoint에 직접 연결할 수 없음
- control-plane credential을 arbitrary candidate-accessible proxy로 바꾸지 않음

실제 credential은 이 저장소에 commit하지 않는다. 사용자에게 채팅으로 secret 값을 전달하도록 요구하지도 않는다.

## 10. candidate 실행

runner는 `runner-job.json`의 다음 값을 변경하지 않는다.

- run/case/condition/repeat/followup
- model ID
- Codex version
- candidate prompt digest
- runtime digest
- boundary profile digest
- candidate-owned path set
- network policy
- authentication mode/source/env-key 이름

실제 prompt는 candidate workspace의 `task.txt` bytes를 사용하고 frozen plan의 `candidate_prompt_sha256`과 재대조한다.

실행 trace는 `codex exec --json` JSONL로 저장한다. reasoning item은 evaluator evidence bundle에 복사하지 않는다.

## 11. multi-turn

`has_followup=true`이면 초기 실행 뒤 같은 conversation/thread를 resume한다.

- 초기 trace/final 보존
- 같은 thread에서 follow-up 전달
- follow-up trace 별도 보존
- 두 trace의 thread ID 동일
- trace SHA는 서로 달라야 함

독립 conversation 두 개를 하나의 update episode로 합치지 않는다.

## 12. runner attestation과 mandatory job linkage

candidate 실행과 canary 검증 후 `runner-attestation.json` schema v2를 만든다. 그 다음:

```bash
python tooling/feynman_runner_job_link.py \
  --runner-job runner-job.json \
  --boundary-profile boundary-profile.json \
  --attestation runner-attestation.json \
  --probe-report probe-report.json \
  --output runner-job-link.json
```

link는 pre-run job과 post-run attestation의 다음 값을 대조한다.

- run/case/condition
- model/Codex version
- candidate/evaluator/source/HOME/CODEX_HOME/temp paths
- profile digest/backend/network policy
- authentication mode/source/env-key 이름
- expected skill set
- runtime/prompt/plan/probe digest

**link 생성만으로 충분하지 않다.** canonical analysis-result v3는 raw runner job과 raw saved link를 둘 다 다시 요구하고 동일 raw profile/probe/attestation에서 link를 재계산한다.

## 13. evaluator 파이프라인과 analysis-result v3

실제 model run 이후:

```text
frozen plan
  → runner-job.json (pre-run)
  → model/tool execution + boundary evidence
  → runner-attestation.json (post-run)
  → runner-job-link.json

Codex JSONL
  → codex_exec_evidence.py
  → feynman_review_bundle.py
  → semantic review v2
  → feynman_apply_review.py

두 경로
  → feynman_eval_result.py (analysis-result v3)
  → feynman_eval_aggregate.py (v3-only input)
```

canonical result 생성 예:

```bash
python tooling/feynman_eval_result.py \
  --plan eval-plan.json \
  --ordinal <N> \
  --evaluator-case evaluator/case.json \
  --runner-job runner-job.json \
  --runner-job-link runner-job-link.json \
  --attestation runner-attestation.json \
  --boundary-profile boundary-profile.json \
  --probe-report probe-report.json \
  --review-bundle review-bundle \
  --semantic-review semantic-review.json \
  --gate gate.json \
  --output analysis-result.json
```

`feynman_eval_result.py`는:

- raw runner job을 frozen plan과 직접 비교
- raw saved link를 같은 raw inputs로 재계산
- saved/recomputed link exact equality 확인
- 기존 boundary/evidence/review/gate hash linkage 재검증
- gate 재계산
- multi-turn same-thread continuity 확인

후에만 `schema_version=3`, `valid_for_analysis=true` 결과를 만든다. 형식 정본은 `evals/feynman-thinking/analysis-result.schema.json`이다.

historical schema-v2 assembler/aggregator는 `*_v2_legacy.py`에 보존되지만 canonical primary analysis에는 사용할 수 없다.

## 14. canonical aggregation

`feynman_eval_aggregate.py`는 analysis-result schema v3만 받는다.

다음이 섞이면 primary comparison을 차단한다.

- model
- Codex CLI version
- runner profile
- condition별 runtime digest
- control-plane authentication profile(mode/source/env-key 이름)

누락 job은 `incomplete`, 위 환경 혼합은 `mixed-environment`, primary semantic outcome 미검증은 `unverified-outcomes`다.

`analysis-ready`는 lineage가 검증된 분석 데이터라는 뜻이지 Feynman skill이 더 좋다는 뜻이 아니다.

## 15. 현재 한계와 완료 정의

reference가 성공했어도 다음은 아직 별도 검증 대상이다.

- 실제 외부 model-service credential/authentication
- 외부 model의 실제 응답 생성
- 행동 평가에 사용되는 모든 candidate-accessible tool 유형의 boundary regression
- `baseline / generic / legacy-clean / feynman-v05` 반복 평가
- semantic judge/human review 실제 결과
- private held-out

특히 exec/patch/synthetic-auth reference는 **검증한 tool/auth 경로에 대해서만** 증거다. 미래/내장 tool 경로가 자동으로 같은 boundary를 따른다는 보편적 증명으로 취급하지 않는다. 새 tool 유형이 행동 평가에 사용되면 별도 boundary regression을 추가한다.

model-runner를 실제 평가용으로 완료했다고 부르려면 최소 다음이 필요하다.

- strict runner-job v2 validation
- canonical remote environment validation
- Docker inspect/profile consistency
- boundary canary
- control-plane credential material candidate tool 미노출
- control plane / tool network 분리
- 실제 외부 model 응답
- runner-job ↔ attestation link
- analysis-result v3 lineage
- trace/evidence/review/gate hash chain
- multi-turn이면 same-thread continuity

현재 상태는 **mock/synthetic control-plane → stdio remote tool boundary reference와 analysis-result v3 구조 완료, 실제 external model authentication + behavioral pilot 미완료**다.

## 16. candidate skill/tool wiring preflight

실제 model turn 전에는 `feynman_skill_tool_wiring_preflight.py`로 LOG-052
full-runner binding의 실행 배선을 검증한다. 이 검사는 runner-job/profile/binding
lineage, candidate filesystem skill set, task의 명시적 skill marker, App Server의
최종 활성 skill set, exact fixed MCP catalog와 network-disabled fixed test를 묶는다.

빈 `CODEX_HOME`은 host의 built-in/user skill을 반드시 제거하지 않는다. 따라서 첫
`skills/list(forceReload=true)`에서 non-candidate skill을 식별하고, 그 정확한
경로만 transient `skills.config` override로 비활성화한 새 App Server 프로세스에서
두 번째 검증을 수행한다. 전역 config와 protected auth home은 수정하지 않는다.

성공 verdict `full-runner-skill-tool-wiring-ready`는 모델 호출 0회인 구조 증거다.
고정 test가 시작·종료되고 candidate source가 불변이면 buggy fixture의 test failure와
wiring failure를 구분한다. 실제 executor 명령에 같은 override를 결속하고 별도
preflight하기 전에는 model smoke를 시작하지 않는다.

## 17. subscription executor command binding

`feynman_subscription_smoke_exec.py`의 `build_codex_exec_command()`가 canonical
Codex argv를 만드는 단일 함수다. 기존 fixed controls를 보존하면서, preflight가
검증한 full-runner MCP와 transient `skills.config` override를 stdin marker 앞에
추가할 수 있다. 함수는 실행·인증·설정 파일 읽기를 수행하지 않는다.

model-free wiring preflight는 이 builder에 full-runner override 13개와 첫 discovery
결과의 transient skill-disable override를 전달하고, command payload 자체는 저장하지
않는다. 실제 subscription executor 호출부에서도 binding/adapter/Docker 입력을
동일한 lineage로 검증한 뒤 이 builder를 사용해야 한다. 그 fail-closed 호출부
검증이 끝나기 전에는 실제 model turn을 시작하지 않는다.

## 18. canonical executor required inputs

운영용 `feynman_subscription_smoke_exec.py` CLI는 full-runner binding manifest,
Node adapter, Docker executable/config directory, immutable Docker image ID를
모두 요구한다. structural preflight 뒤 auth gate 전에 binding의 runner identity,
profile/job digest, adapter/candidate/Docker 재생성 override를 대조한다. 일부 입력
또는 lineage drift는 모델 호출 전에 거부된다.

이 검사는 executor가 올바른 full-runner를 사용하도록 보장하지만, App Server에서
발견한 non-candidate skill을 실제 smoke command plan에 자동 전달하는 단계까지
완료했다는 뜻은 아니다. transient skill-disable override의 command-plan 결속은
별도 model-free 단계로 남아 있다.
