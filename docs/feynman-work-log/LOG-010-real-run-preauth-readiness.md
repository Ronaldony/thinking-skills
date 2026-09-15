# LOG-010 — real-model pre-auth readiness 및 integration smoke 준비 완료

- **시각(KST)**: 2026-09-08 22:43
- **시작 기준**: LOG-009 완료 이후
- **최종 실행 검증 head**: `fed6ff976f827539a829c4087670da58d3439fe9`
- **목적**: 실제 외부 model-service credential을 사용하기 직전까지의 모든 구조·runtime·job·workspace 준비를 자동화하고, 사람이 개입해야 하는 첫 지점을 credential/account 권한으로 최소화한다.

## 1. analysis-result v3 형식 정본화

### 추가

- `evals/feynman-thinking/analysis-result.schema.json`
  - commit `cdc7f77ee8ce4e1c94a109fd98936669e435c8f2`
- `tests/test_feynman_analysis_result_schema.py`
  - commit `a2c6596a42af864cb716bad6c4b3d6d6d73b82f`

### 핵심 계약

canonical analysis result는 schema version 3이며 다음을 fail-closed로 요구한다.

- `valid_for_analysis=true`
- frozen job metadata
- exact model / Codex version
- runner profile
- `authentication.mode=control-plane-only`
- credential source=`environment`
- credential env-key **이름**
- `candidate_auth_exposed=false`
- `runner_job_attestation_bound=true`
- `runner_job_link_verdict=runner-job-attestation-bound`
- plan/prompt/profile/probe/review/gate/attestation/runner-job/runner-job-link SHA-256
- primary semantic metrics

credential 값 필드는 schema에 정의하지 않는다.

## 2. 문서 계약 v3/control-plane-only 동기화

다음 문서를 old result-v2 / `external-broker` 표현에서 현재 구조로 갱신했다.

- `evals/feynman-thinking/README.md`
  - commit `47b1d8a9fbf7577e80169752ed657bedaaaa074a`
- `evals/feynman-thinking/preregister.md`
  - commit `c6abcfd5295093dffe082543ecafe4865788215b`
- `docs/model-runner-contract.md`
  - commit `47e6bd26a160058db400ab0da461a8cf65ab5708`
- `docs/feynman-work-status.md`
  - commit `8793125189ce484959fdb5775f5bfcff5d59d3c0`
- `docs/eval-runner-contract.md`
  - commit `0369fc0c6438443ecd9004f0d3a4ac45ceff84b7`

현재 canonical chain:

```text
frozen plan
  → runner-job v2 (pre-run)
  → boundary profile/probe + execution
  → runner-attestation v2 (post-run)
  → runner-job-link v2

trace
  → evidence
  → review bundle
  → semantic review v2
  → gate

두 경로
  → analysis-result v3
  → canonical v3-only aggregator
```

semantic review v2와 analysis-result v3는 서로 다른 계층의 버전임을 명시했다.

## 3. credential-free real-run readiness preflight

### 추가

- `tooling/feynman_real_run_preflight.py`
  - 초기 commit `792fb83fdb5934d208ac5bf9f04bff83cc55f9ab`
- `evals/feynman-thinking/real-run-readiness.schema.json`
  - commit `2ce6e0a7c9ba16706f7a7e5819d817d512c9c115`
- `tests/test_feynman_real_run_preflight.py`
  - commit `2edc3c5a2bbad3e01c5d1dc847665e966809460c`

### readiness 검증 범위

입력:

- frozen eval plan
- ordinal
- evaluator case record
- runner-job v2
- boundary profile
- canonical remote `environments.toml`
- canonical real-model control config

검사:

- runner-job strict validation
- exact frozen ordinal/case/condition/repeat/followup
- raw eval-plan SHA
- prompt SHA
- evaluator condition metadata
- candidate `task.txt` raw bytes
- boundary profile digest
- canonical remote environment
- canonical real model control config
- filesystem skill preflight
- control-plane auth mode/source/env-key 이름
- credential env-key 이름이 candidate env allowlist에 없는지

성공 verdict:

```text
ready-for-control-plane-auth
```

이 verdict는 **credential 값을 읽지 않았고 외부 model request를 보내지 않았음**을 전제로 한다.

출력에는 다음이 명시된다.

- `credential_value_read_by_preflight=false`
- `candidate_auth_exposed=false`
- `required_external_input.kind=control-plane-environment-credential`
- 다음에 필요한 실제 model request / boundary attestation / runner link / result-v3 evidence 목록

## 4. symlink 검증 결함 발견 및 수정

정적 점검 중 초기 `_regular()` 구현에서:

```python
path = path.resolve()
if path.is_symlink():
    ...
```

처럼 resolve 후 symlink를 검사하여 symlink 정보가 사라질 수 있음을 발견했다.

이는 readiness가 "credential만 남았다"는 강한 verdict를 만들기 때문에 그대로 둘 수 없는 결함이었다.

### 수정

- `tooling/feynman_real_run_preflight.py`
  - commit `d57767a94e90c9871edf273918de7cce0d7e6f6f`

변경:

- resolve 전에 모든 path component를 순회
- file symlink 거부
- intermediate directory symlink 거부
- candidate directory 자체의 symlink component도 거부

### 회귀

- `tests/test_feynman_real_run_preflight_paths.py`
  - commit `e22730b3d53ca2131bd90d6d57a560a378873aca`

검사:

- direct file symlink reject
- intermediate directory symlink reject
- real file/directory accept

## 5. 실제 credential 첫 실행용 integration-only smoke spec

### 고정 spec

- `evals/feynman-thinking/real-model-smoke-spec.json`
  - commit `332ddc1b2d115ef8f1b55a2aa5770e07a933fb95`

정확한 scope:

- case: `tools-10`
- conditions: `baseline`, `feynman-v05`
- repeats: 1
- seed: `20260908`
- actual external model-service 필요
- control-plane-only auth 필요
- 기본 credential env-key 이름: `OPENAI_API_KEY`
- analysis use: `not-for-skill-performance-inference`

금지 주장:

- 2-job smoke로 Feynman skill effect를 추정하지 않음
- held-out 근거로 사용하지 않음
- smoke 성공만으로 behaviorally validated라고 표시하지 않음

### planner

- `tooling/feynman_real_smoke_plan.py`
  - commit `aff090cb8432f776642ecb3de2483f6e73916399`

planner는 spec drift를 거부한다.

- generic 조건 추가 거부
- 다른 case 거부
- repeats 증가 거부
- analysis use 변경 거부
- invalid auth env-key name 거부

그리고 raw `smoke_spec_sha256`을 frozen plan에 기록한다.

### tests

- `tests/test_feynman_real_smoke_plan.py`
  - 초기 commit `aa39f9662e05ae3856bc9ec24e1945710ce7ba5c`

## 6. pre-auth readiness GitHub Actions reference

### 추가

- `.github/workflows/validate-feynman-real-run-readiness.yml`
  - commit `444155c59ea842a9a3777440ddf1605fb2205c5e`

이 workflow는 credential을 사용하지 않는다.

실행 순서:

1. readiness/schema/smoke contract tests
2. current `@openai/codex` 설치
3. exact control-plane Codex version 기록
4. `codex debug models --bundled` catalog 기록
5. API-supported text model metadata 선택
6. 동일 Codex version의 Docker tool image build
7. integration-only 2-job smoke plan freeze
8. 각 ordinal에 대해 실제 condition workspace 생성
9. 실제 Docker version/image ID를 사용한 boundary profile 생성
10. runner-job v2 생성/strict validation
11. canonical remote environment 생성/재검증
12. canonical real-model control config 생성/재검증
13. `feynman_real_run_preflight.py` 실행
14. 두 job readiness summary 생성
15. artifact 업로드

workflow 자체는 실제 model-service request를 보내지 않는다.

## 7. 첫 CI 실패 — 테스트 문구 assertion 오류

검증 head: `e22730b3d53ca2131bd90d6d57a560a378873aca`

### unit diagnostic 실패

- workflow: `validate-feynman-unit-diagnostic`
- run #48
- run id `34233096999`
- result: failure
- **Ran 310 tests**
- failure: 1

실패 test:

```text
test_committed_spec_is_valid_and_explicitly_non_performance
```

실제 assertion:

```python
self.assertIn("performance", joined)
```

committed prohibited claims는 다음 의미를 이미 포함했지만 literal `performance` 단어는 없었다.

```text
do not estimate feynman skill effect from this two-job smoke
... do not use this smoke as held-out evidence
... do not mark the skill behaviorally validated from smoke success
```

따라서 이는 spec/runner 계약 결함이 아니라 **test wording bug**로 판정했다.

실패 diagnostic artifact:

- artifact id `10058635947`
- ZIP SHA-256 `6ee0b3d4ebfe2081e3ba61d06062ae4974dac15cfa8005a47747095346063f54`

### readiness workflow 실패

- workflow: `validate-feynman-real-run-readiness`
- run #5
- run id `34233096994`
- job id `102083872404`

동일 test assertion에서 첫 단계가 실패했다.

따라서:

- runtime build: skipped
- smoke plan: skipped
- two-job readiness: skipped

artifact 업로드도 선행 파일이 없어서 실패했으나 이는 2차 결과다.

중요: 이 실패에서 credential/tool/runtime E2E 실패를 추론하지 않았다. 해당 단계는 실행되지 않았기 때문이다.

## 8. test wording fix

수정 commit:

- `fed6ff976f827539a829c4087670da58d3439fe9`

literal `performance` 검색을 제거하고 실제 금지 의미를 확인하도록 변경했다.

```python
self.assertIn("skill effect", joined)
self.assertIn("held-out", joined)
self.assertIn("behaviorally validated", joined)
```

`analysis_use == not-for-skill-performance-inference` 검증은 그대로 유지했다.

따라서 spec 규칙은 완화되지 않았다.

## 9. 최종 full unittest 성공

검증 head:

- `fed6ff976f827539a829c4087670da58d3439fe9`

workflow:

- `validate-feynman-unit-diagnostic`
- run #50
- run id `34233537418`
- conclusion: **success**

결과:

- **Ran 310 tests**
- **1.021s**
- exit code `0`
- final `OK`

artifact:

- id `10058825451`
- ZIP SHA-256 `23f20772fd088af5e18d3961794d15642febd1ac9564d87db60088ce449dfd33`

## 10. 최종 pre-auth readiness E2E 성공

workflow:

- `validate-feynman-real-run-readiness`
- run #7
- run id `34233537420`
- conclusion: **success**

artifact:

- id `10058836269`
- size `108835` bytes
- ZIP SHA-256 `9f3cf4c5e430af52b594b16ee14d034b3a223b22b6c1ad3753987f150c0672d2`
- files: 21

### summary

`readiness-summary.json`:

```json
{
  "verdict": "integration-smoke-ready-for-external-auth",
  "analysis_use": "not-for-skill-performance-inference",
  "model_metadata_id": "gpt-6-astra",
  "codex_version": "codex-cli 0.153.4",
  "credential_value_used": false,
  "external_model_request_sent": false
}
```

`gpt-6-astra`는 해당 Codex version의 bundled catalog에서 readiness metadata용으로 선택한 model ID다. **실제 account entitlement/API 호출 성공은 아직 확인하지 않았다.**

smoke plan SHA-256:

- `d64dc0e685e40b824f5ad973f7d67f92230eeea02d772f9b81b14138844f4884`

### job 1

- ordinal: 1
- case: `tools-10`
- condition: `feynman-v05`
- verdict: `ready-for-control-plane-auth`
- expected skills: `["feynman-thinking"]`
- runtime SHA-256: `a3be8b7e0d52b332169133c5f77f6f77d898ebb6704c151a379a1f604cad140a`
- readiness SHA-256: `10b292898d76885c2d6c757a7bad5d77647f6048e16492a8ff160e5996744375`
- credential env-key name: `OPENAI_API_KEY`
- credential value read: false
- candidate auth exposed: false

### job 2

- ordinal: 2
- case: `tools-10`
- condition: `baseline`
- verdict: `ready-for-control-plane-auth`
- expected skills: `[]`
- runtime SHA-256: `null`
- readiness SHA-256: `78d345b24b9f50fc24ed1003f6b870ff3d0243ec0c361de2ed769427db031e41`
- credential env-key name: `OPENAI_API_KEY`
- credential value read: false
- candidate auth exposed: false

두 job은 같은:

- smoke-plan bytes
- Codex version
- model metadata ID
- auth architecture

를 사용하되 condition별 runtime 존재 여부는 frozen condition 계약에 따라 다르다.

## 11. 동일 head 전체 workflow 상태

검증 head `fed6ff976f827539a829c4087670da58d3439fe9`에서 다음 **8개 workflow가 모두 completed / success**:

1. `validate-feynman`
   - run #407
   - id `34233537435`
2. `validate-feynman-docker-reference`
   - run #105
   - id `34233537474`
3. `validate-feynman-codex-reference`
   - run #95
   - id `34233537379`
4. `validate-feynman-remote-exec-reference`
   - run #112
   - id `34233537478`
5. `validate-feynman-remote-patch-reference`
   - run #74
   - id `34233537462`
6. `validate-feynman-synthetic-auth-reference`
   - run #53
   - id `34233537400`
7. `validate-feynman-unit-diagnostic`
   - run #50
   - id `34233537418`
8. `validate-feynman-real-run-readiness`
   - run #7
   - id `34233537420`

## 12. 현재 사실로 주장 가능한 것

- frozen two-job integration smoke의 pre-auth 구조가 실제 GitHub runner에서 만들어진다.
- baseline과 feynman-v05 condition workspace/runtime 차이가 frozen job과 일치한다.
- runner-job, boundary profile, remote environment, real-model control config가 credential 없이 검증된다.
- readiness preflight는 실제 credential 값을 읽거나 serialize하지 않는다.
- readiness artifact는 exact file digests와 다음 필수 evidence를 기록한다.
- 현재 code head에서 기존 7 reference + 새 readiness reference가 모두 녹색이다.

## 13. 아직 주장할 수 없는 것

- `gpt-6-astra`가 실제 운영 credential/account에서 사용 가능함
- 실제 OpenAI/model-service 인증 성공
- 실제 external model request/response 성공
- 실제 `tools-10` model 답변 품질
- baseline vs feynman-v05 효과
- four-condition behavioral pilot 결과
- held-out 일반화

특히 readiness smoke는 `analysis_use=not-for-skill-performance-inference`다.

## 14. 다음 작업 / 사람 개입 지점

이제 다음 단계에서 처음으로 외부 권한이 필요하다.

운영자가 해야 할 일:

- 승인된 model-service credential/account access를 **control-plane environment**에 제공
- 기본 key name은 `OPENAI_API_KEY`
- secret 값을 repository, candidate workspace, 채팅에 쓰지 않음

이 시스템에서 GitHub/runner secret store의 secret 값을 생성·조회할 수 있는 API는 사용하지 않는다. 따라서 실제 credential 값의 설정은 사람이/승인된 운영 환경이 해야 한다.

credential이 준비되면 다음 순서로 진행한다.

1. 먼저 `tools-10 × {baseline, feynman-v05} × 1` integration smoke만 실제 model service로 실행한다.
2. account/model entitlement를 실제 응답으로 확인한다.
3. 동일 run의 boundary canary/report를 새로 만든다.
4. post-run runner-attestation v2를 만든다.
5. raw pre-run job과 runner-job-link v2를 재계산한다.
6. trace → evidence → semantic review → gate를 진행한다.
7. analysis-result v3를 만든다.
8. smoke 결과는 성능 추정에 쓰지 않고 plumbing 검증에만 사용한다.
9. smoke가 완전히 녹색일 때만 별도 four-condition public-development pilot로 넘어간다.

**현재 시점부터는 실제 model-service credential/account 권한 없이는 의미 있는 다음 실행 단계로 진행할 수 없다.**
