# LOG-008 — runner authentication contract v2 migration

- **시각(KST)**: 2026-09-08 21:28
- **시작 상태**: synthetic-auth reference까지 실제 성공했지만 runner-job이 `external-broker`라고 선언해 실제 검증 구조와 의미 불일치
- **최종 검증 head**: `730daf16e12d308b03535be55cfd54d280fd419d`

## 문제

실제 성공한 reference architecture는 다음이었다.

```text
host-side Codex model control plane
  └─ model-service credential 소유

selected remote stdio exec-server
  └─ candidate tools 실행
  └─ credential env/file/argv 없음
  └─ tool network는 profile에 따라 별도 통제
```

하지만 기존 runner-job은 authentication mode를 `external-broker`라고 기록했다. 별도 credential proxy/broker를 실제로 사용하지 않았으므로 이 명칭을 유지하면 pre-run contract와 실제 검증 구조가 다르다.

## migration 결정

runner-job/attestation/link를 모두 v2로 올리고 다음 구조를 정본으로 사용한다.

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

중요:

- credential **값은 job/attestation/link에 저장하지 않는다**.
- 현재 검증된 credential source는 `environment` 하나뿐이다.
- env key 이름만 기록한다.
- control-plane credential env key가 candidate env allowlist에 나타나면 실패한다.
- file/argv credential source로 확장하지 않는다.

## 변경된 계약

### runner-job schema v2

`evals/feynman-thinking/runner-job.schema.json`

- `schema_version = 2`
- `mode = control-plane-only`
- `control_plane_credential_source = environment`
- valid env-key name 필수
- candidate auth env/files/argv는 `maxItems=0`

### runner-job builder

`tooling/feynman_runner_job.py`

- 기본 control credential env key: `OPENAI_API_KEY`
- CLI: `--control-plane-credential-env-key`
- custom key 이름 지원, 값은 저장하지 않음
- profile candidate env key에 같은 이름이 있으면 생성 거부

### runner-job strict validator

`tooling/feynman_runner_job_validate.py`

- schema v1 거부
- legacy `external-broker` 거부
- `file` 등 미검증 source 거부
- invalid env-key 이름 거부
- credential key가 candidate env에 있으면 거부
- unexpected authentication field, candidate auth env/file/argv 모두 거부

### runner-attestation schema/validator v2

`evals/feynman-thinking/runner-attestation.schema.json`
`tooling/feynman_runner_attestation.py`

attestation environment에 다음 추가:

- `control_plane_auth_mode = control-plane-only`
- `control_plane_credential_source = environment`
- `control_plane_credential_env_key`
- 기존 `api_auth_exposed_to_candidate_tools = false` 유지

validator:

- schema v1 거부
- credential env key가 candidate env에 있으면 거부
- control-plane/tool-network separation을 명시적으로 요구

### runner-job ↔ attestation link v2

`evals/feynman-thinking/runner-job-link.schema.json`
`tooling/feynman_runner_job_link.py`

pre-run job과 post-run attestation에서 다음을 직접 비교:

- authentication mode
- credential source
- credential env-key 이름
- candidate auth exposure=false

link output에도 mode/source/env-key 이름을 보존한다.

## fixture migration

다음 테스트/fixture를 v2로 마이그레이션했다.

- `tests/test_feynman_runner_attestation.py`
- `tests/test_feynman_runner_job.py`
- `tests/test_feynman_runner_job_validate.py`
- `tests/test_feynman_runner_job_link.py`
- `tests/test_feynman_remote_exec_environment.py`
- `tests/test_feynman_remote_exec_reference_result.py`
- `tests/test_feynman_real_model_control_config.py`

## real-model control config drift 수정

전체 unittest 진단에서 마지막으로 남은 4개 오류는 `tests/test_feynman_real_model_control_config.py`의 hardcoded runner-job schema v1 fixture였다.

독립 diagnostic workflow를 추가해 전체 로그를 artifact로 보존했다.

- workflow: `validate-feynman-unit-diagnostic`
- 최초 diagnostic run: id `34226569790`
- artifact id: `10055946758`
- artifact ZIP SHA-256: `c5046516024f4f6ffb2c16c5bc1eeb07282fb10c294576fac2d31fd8c2aa99a1`
- 당시 결과: **280 tests / 4 errors**
- 4개 모두 `test_feynman_real_model_control_config.py`
- 공통 error: `unsupported runner job schema_version; expected 2`

수정:

`tooling/feynman_real_model_control_config.py`

- provider env key를 독립 hardcode하지 않고 runner-job v2의 `control_plane_credential_env_key`를 정본으로 사용.
- config에는 key **이름만** 기록, credential 값은 기록하지 않음.
- output validation에 `authentication_mode=control-plane-only`, `credential_source=environment` 기록.

`tests/test_feynman_real_model_control_config.py`

- v2 fixture로 전환.
- custom control-plane env key propagation 회귀 추가.
- credential key candidate env 노출 거부 회귀 추가.

## 최종 전체 unittest

최종 head `730daf16e12d308b03535be55cfd54d280fd419d`에서 diagnostic workflow 성공.

- diagnostic run id: `34226769546`
- artifact id: `10056027402`
- artifact ZIP SHA-256: `6f326082541b58928861678a15679d52292d8626897716d44d77ea2606356c4a`
- unittest exit code: `0`
- **Ran 282 tests**
- **OK**

## 최종 workflow 회귀

동일 head에서 다음 7개 workflow가 모두 **success**:

- `validate-feynman`
- `validate-feynman-docker-reference`
- `validate-feynman-codex-reference`
- `validate-feynman-remote-exec-reference`
- `validate-feynman-remote-patch-reference`
- `validate-feynman-synthetic-auth-reference`
- `validate-feynman-unit-diagnostic`

즉 auth v2 migration은 remote exec/patch/synthetic-auth reference를 깨뜨리지 않았다.

## 결론

이제 pre-run runner job, post-run attestation, job↔attestation linkage, real-model control config가 모두 같은 인증 architecture를 표현한다.

현재 사실로 주장 가능한 범위:

- control-plane credential의 **값**은 candidate tool contract에 포함되지 않는다.
- control-plane credential env-key 이름도 candidate tool env allowlist와 분리된다.
- synthetic bearer E2E에서는 실제 remote tool env/key/value 및 exact-byte artifact scan까지 통과했다.

아직 주장할 수 없는 것:

- 실제 OpenAI/model-service credential의 end-to-end 인증 성공
- refresh/account/project/organization 등 실제 provider auth semantics
- 실제 Feynman skill 성능 개선

## 다음 작업

analysis-ready result가 pre-run runner job을 우회하지 못하도록 `runner-job-link` artifact를 **필수 입력**으로 승격한다.

현재 result chain:

```text
plan → profile/probe → attestation → review → gate → result
```

다음 목표:

```text
plan → runner-job → profile/probe → attestation
            └──── runner-job-link ────┘
                         ↓
                    review/gate/result
```

이 단계는 사람 개입 없이 진행 가능하다.
