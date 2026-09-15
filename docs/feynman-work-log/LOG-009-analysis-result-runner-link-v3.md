# LOG-009 — analysis-result runner-job linkage v3 migration

- **시각(KST)**: 2026-09-08 22:14
- **시작 head**: `bc0f0b8f74cb9deef4d116eba43c7a1567ece116`
- **검증 head**: `cb85c21266608a0f3011af07e432ea4d31e27898`
- **목적**: pre-run `runner-job.json`이 analysis-ready result 생성 경로에서 우회될 수 있던 마지막 구조 공백을 닫는다.

## 시작 상태와 공백

LOG-008 시점의 검증 체인은 다음과 같았다.

```text
plan → profile/probe → attestation → review → gate → result
```

`runner-job.json`은 실행 전에 생성되고 `runner-job-link.json`으로 attestation과 별도 결속할 수 있었지만, canonical `feynman_eval_result.py`는 이 두 파일을 필수 입력으로 요구하지 않았다.

따라서 공격적/실수성 경로를 가정하면 다음 문제가 남았다.

1. 실제 실행 전에 동결된 runner job을 거치지 않고도 attestation + review/gate만으로 analysis-ready result를 만들 수 있다.
2. valid한 `runner-job-link` 도구가 존재해도 result 생성기가 이를 소비하지 않으면 provenance chain의 필수 edge가 아니다.
3. aggregator가 schema-v2 result를 계속 받아들이면 과거 link 없는 result가 새 primary comparison에 섞일 수 있다.

## migration 결정

새 canonical 체인은 다음으로 승격한다.

```text
plan → runner-job → profile/probe → attestation
            └──── runner-job-link ────┘
                         ↓
                  review → gate → result-v3
                                   ↓
                            aggregate-v3
```

핵심 원칙:

- raw `runner-job.json`과 raw `runner-job-link.json`을 **둘 다** result assembler의 필수 입력으로 요구한다.
- 저장된 link JSON을 그대로 신뢰하지 않고, result assembler 안에서 `feynman_runner_job_link.bind()`를 다시 실행한다.
- 저장된 link와 재계산 link가 JSON object 기준으로 정확히 같아야 한다.
- raw runner-job 자체도 frozen plan의 ordinal/case/condition/repeat/followup/prompt/plan digest와 직접 비교한다.
- 기존 schema-v2 result는 historical reproduction용으로만 보존하고 canonical aggregation 입력에서는 거부한다.
- 실제 credential 값은 어느 새 artifact에도 저장하지 않는다.

## 변경 1 — 기존 v2 구현 보존

커밋:

- `6d942a11215caba35b02865698685e05ceebdbd5`

추가:

- `tooling/feynman_eval_result_v2_legacy.py`
- `tooling/feynman_eval_aggregate_v2_legacy.py`

두 파일은 마이그레이션 직전 canonical v2 blob을 그대로 재사용했다.

목적:

- 과거 결과 재현성 유지
- 새 v3의 규칙을 완화하지 않고도 기존 계산/검증 로직을 재사용
- 과거 schema와 새 primary-analysis schema를 명시적으로 분리

## 변경 2 — analysis-result schema v3 assembler

커밋:

- `72e5f0b4478d8bec8fb1dd14d25ada838b2c9a02`

추가:

- `tooling/feynman_eval_result_v3.py`

새 필수 입력:

- `runner_job_path`
- `runner_job_link_path`
- 기존 review bundle / probe report / boundary profile도 계속 필수

### runner job ↔ frozen plan 직접 검증

v3 assembler는 runner job에 대해 다음을 frozen plan과 직접 비교한다.

- ordinal
- case_id
- condition_id
- repeat
- has_followup
- eval-plan raw SHA-256
- candidate prompt SHA-256
- runtime digest의 내부 일관성

따라서 잘 만들어진 새 link가 있더라도 frozen plan과 다른 runner job은 거부된다.

### saved link 재계산

v3 assembler는 다음 raw input을 사용해 link를 다시 계산한다.

- runner job
- boundary profile
- verified probe report
- runner attestation

그리고 저장된 `runner-job-link.json`과 재계산 결과가 정확히 동일해야 한다.

추가 byte binding:

- runner-job SHA-256
- attestation SHA-256
- eval-plan SHA-256

### 기존 evidence/review/gate 검증 유지

runner-link 검증 이후에만 보존된 v2 assembler를 호출한다.

즉 기존의 다음 검증은 삭제하거나 약화하지 않았다.

- boundary profile / probe report / attestation binding
- evaluator condition record / runtime manifest binding
- review-input / review-manifest binding
- semantic review SHA binding
- gate recomputation
- trusted execution IDs
- candidate final / trace hashes
- multi-turn same-thread continuity
- update_behavior 규칙

### v3 result 추가 필드

`schema_version = 3`

`authentication`:

```json
{
  "mode": "control-plane-only",
  "control_plane_credential_source": "environment",
  "control_plane_credential_env_key": "<runner-job/link에 기록된 env key 이름>",
  "candidate_auth_exposed": false
}
```

`lineage`:

```json
{
  "runner_job_attestation_bound": true,
  "runner_job_link_verdict": "runner-job-attestation-bound"
}
```

새 digest:

- `runner_job_sha256`
- `runner_job_link_sha256`

그리고 link가 중복 보존하는 다음 digest를 result와 다시 대조한다.

- eval plan
- candidate prompt
- runtime
- boundary profile
- probe report
- attestation
- runner job

## 변경 3 — canonical result entrypoint 교체

커밋:

- `e9a39ef7a4d3ea3cffa591263b81701957efdcb4`

`tooling/feynman_eval_result.py`는 이제 v3 entrypoint만 노출한다.

v2는 `feynman_eval_result_v2_legacy.py`에서만 명시적으로 접근 가능하다.

## 변경 4 — canonical aggregator v3

커밋:

- `55f4570d8aac42302ee1520c6016b39eceb615d0`
- `da8d9c726873c39defda40a496a1d776080a0735`

추가/변경:

- `tooling/feynman_eval_aggregate_v3.py`
- canonical `tooling/feynman_eval_aggregate.py`를 v3 shim으로 교체

canonical aggregator는 이제 다음을 요구한다.

- result schema version 3
- `valid_for_analysis=true`
- SHA-256 digests:
  - eval plan
  - candidate prompt
  - boundary profile
  - probe report
  - attestation
  - runner job
  - runner-job-link
- lineage binding=true
- link verdict exact match
- auth mode=`control-plane-only`
- credential source=`environment`
- valid env-key 이름
- candidate_auth_exposed=false

schema-v2 result는 canonical aggregator에서 거부된다.

기존 descriptive/frozen-plan 계산은 legacy aggregator에 위임하되, v3 validation이 먼저 성공해야 한다.

추가 environment consistency:

- authentication profile 집합
- `single_authentication_profile`

서로 다른 control-plane auth profile이 섞이면 `mixed-environment`로 차단한다.

## 변경 5 — regression suite migration

커밋:

- `cb85c21266608a0f3011af07e432ea4d31e27898`

`tests/test_feynman_eval_results.py`를 v3 계약으로 마이그레이션했다.

### v3 result 회귀

다음을 직접 검증한다.

- valid linkage-complete result는 schema v3 analysis-ready
- runner job 누락 거부
- runner-job-link 누락 거부
- saved link 변조 거부
- fresh valid link를 재생성해도 ordinal drift 거부
- repeat drift 거부
- link 생성 후 attestation 변경 거부
- plan digest drift 거부
- 기존 review bundle 필수 규칙 유지

### v3 aggregate 회귀

다음을 검증한다.

- complete v3 pair descriptive comparison 유지
- schema-v2 result 거부
- runner-job-link digest 누락 거부
- 거짓 lineage 거부
- auth profile 혼합 시 mixed-environment
- candidate auth exposure 거부
- missing result → incomplete
- mixed model / mixed runner profile 차단
- unverified primary outcome 차단
- duplicate result 거부
- wrong ordinal 거부
- prompt digest drift 거부
- skill condition runtime digest 필수
- invalid auth env-key 거부

## 전체 unittest 검증

workflow:

- `validate-feynman-unit-diagnostic`
- run #19
- run id: `34230512976`
- conclusion: **success**

결과:

- **Ran 285 tests**
- **OK**
- 실행 시간: 1.120s

artifact:

- artifact id: `10057556912`
- artifact ZIP SHA-256: `21ff9e2000b096b55ef9b13db1980a16ba7094e2a9758993764951f6c07e9357`

## 동일 head 전체 workflow 회귀

검증 head: `cb85c21266608a0f3011af07e432ea4d31e27898`

다음 7개 workflow가 모두 **completed / success**:

1. `validate-feynman`
   - run #376
   - id `34230512944`
2. `validate-feynman-docker-reference`
   - run #87
   - id `34230512959`
3. `validate-feynman-codex-reference`
   - run #77
   - id `34230513015`
4. `validate-feynman-remote-exec-reference`
   - run #89
   - id `34230512957`
5. `validate-feynman-remote-patch-reference`
   - run #51
   - id `34230512963`
6. `validate-feynman-synthetic-auth-reference`
   - run #35
   - id `34230512955`
7. `validate-feynman-unit-diagnostic`
   - run #19
   - id `34230512976`

따라서 analysis-result/aggregate v3 migration은 기존 Docker/Codex/remote exec/remote patch/synthetic auth reference를 깨뜨리지 않았다.

## 현재 사실로 주장 가능한 것

- 새 canonical analysis-ready result는 raw pre-run runner job 없이 생성할 수 없다.
- 새 canonical analysis-ready result는 recomputable runner-job-link 없이 생성할 수 없다.
- saved runner-job-link만 위조해도 재계산 결과와 달라지면 거부된다.
- frozen plan과 다른 ordinal/repeat를 가진 runner job은 valid link가 있더라도 거부된다.
- schema-v2 result는 새 canonical primary aggregator에 들어갈 수 없다.
- control-plane authentication architecture가 서로 다른 결과를 primary comparison으로 혼합할 수 없다.

## 아직 주장할 수 없는 것

- 실제 OpenAI/model-service credential의 end-to-end 인증 성공
- 실제 model service를 사용한 baseline/generic/legacy-clean/feynman-v05 행동 결과
- Feynman skill의 품질 개선량
- held-out 일반화 성능

## 다음 작업

1. canonical analysis-result v3 JSON Schema를 추가해 Python semantic validator뿐 아니라 artifact format 자체도 정본화한다.
2. `evals/feynman-thinking/README.md`, `preregister.md`, `docs/model-runner-contract.md`, `docs/feynman-work-status.md`의 schema-v2/old chain/external-broker 표현을 v3/control-plane-only 기준으로 정리한다.
3. PR 본문을 실제 현재 구조와 일치시킨다.
4. 그 다음 사람 개입 없이 가능한 실제-run orchestration을 준비하되, external model-service credential 주입 직전에서만 멈춘다.

현재 단계에는 사람 개입이 필요하지 않다.
