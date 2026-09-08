# 외부 model-runner 계약

상태: **v0.1 interface contract — runner implementation and model execution pending**.

이 문서는 `feynman-thinking` 행동 비교의 실제 후보 모델 프로세스를 외부 경계 안에서 실행할 때 필요한 인터페이스를 정의한다. `docs/eval-runner-contract.md`가 boundary 자체와 canary 검증을 다룬다면, 이 문서는 **frozen eval job을 어떤 실행 단위로 넘기고 어떤 순서로 증거를 회수할지**를 다룬다.

## 원칙

1. 모델 인증정보는 candidate tool environment, candidate-readable file, command argument에 넣지 않는다.
2. runner가 임의로 condition/prompt/runtime/profile을 재작성하지 않는다.
3. 실행 전 `runner-job.json`과 원본 `boundary-profile.json`을 함께 검증한다.
4. canary와 실제 candidate는 같은 boundary profile과 candidate-owned roots를 사용해야 한다.
5. boundary canary 성공과 모델 정답은 서로 다른 주장이다. 둘을 한 verdict로 합치지 않는다.
6. 실제 model run이 없으면 행동 성능 데이터를 만들지 않는다.

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
  --codex-home <codex-home> \
  --temp-dir <temp> \
  --real-home <real-home> \
  --output runner-job.json
```

`runner-job.json` 구조는 `evals/feynman-thinking/runner-job.schema.json`을 따른다.

job에는 credential **값**이 들어가지 않는다. authentication은 다음으로 고정한다.

```json
{
  "mode": "external-broker",
  "candidate_tool_auth_env_keys": [],
  "candidate_readable_credential_files": [],
  "credential_command_arguments": []
}
```

## 2. 실행 전 strict validation

runner는 job을 그대로 신뢰하지 않고 다음을 반드시 실행한다.

```bash
python tooling/feynman_runner_job_validate.py \
  --job runner-job.json \
  --boundary-profile boundary-profile.json
```

validator는 특히 다음을 검사한다.

- profile raw SHA가 job의 boundary/digest와 동일
- candidate/workspace, ephemeral HOME, CODEX_HOME, temp가 profile의 **전체 rw mount 집합과 정확히 동일**
- evaluator/source/real-HOME은 candidate-owned root가 아님
- external-broker 이외 인증 방식 또는 candidate credential 노출 없음
- profile network mode와 job tool-network 정책 일치
- baseline/generic runtime 없음
- legacy-clean/v0.5 runtime SHA 존재
- condition별 expected skill set 정확

runner는 이 검사를 우회할 수 있는 별도 “unsafe mode”를 제공하지 않는다.

## 3. boundary 실제 설정 검증

Docker reference backend에서는 container를 바로 시작하지 않는다.

```text
docker create
   ↓
docker inspect
   ↓
profile/inspect validator
   ↓
docker start
```

`tooling/feynman_docker_reference_inspect.py`는 Docker inspect의 실제 image ID, network mode, read-only root, privilege/capability, no-new-privileges, UID:GID, bind/volume mount RW, tmpfs, `env -i` key를 profile과 대조한다.

inspect 검사는 동작 canary를 대체하지 않는다. 선언과 실제 launch config가 같은지를 확인하는 단계다.

## 4. canary 단계

실제 candidate 실행 전에 같은 profile로 boundary canary를 실행한다.

- inside-boundary: `tooling/feynman_boundary_probe.py`
- outside-boundary: `tooling/feynman_boundary_probe_verify.py`
- closed network reference: `tooling/feynman_network_reference.py`

성공한 `probe-report.json` raw SHA를 이후 runner attestation에 고정한다.

canary profile과 model-run profile이 다르면 canary를 재사용하지 않는다.

## 5. 인증 broker 경계

`external-broker`는 다음 의미를 가진다.

```text
host/evaluator
   │
   ├── credential-owning control-plane broker ── model service
   │
   └── external candidate boundary
          ├── candidate workspace
          ├── agent/model frontend without credential material
          └── candidate tool subprocesses
```

필수 성질:

- API key/token은 broker 프로세스만 소유
- candidate tool environment에 auth key 이름조차 노출하지 않음
- candidate-readable HOME/CODEX_HOME에 credential file 없음
- credential이 command line에 없음
- candidate tool network와 model control-plane network 분리
- broker가 candidate의 arbitrary TCP proxy로 동작하지 않음

이 저장소는 현재 broker 구현을 제공하지 않는다. 따라서 실제 모델 pilot은 아직 차단된다.

## 6. candidate 실행

runner는 `runner-job.json`의 다음 값을 변경하지 않는다.

- model ID
- Codex/agent version
- condition
- candidate prompt digest
- runtime digest
- boundary profile digest
- candidate-owned path set
- network policy

실제 prompt는 candidate workspace의 `task.txt` bytes를 사용하며 frozen plan의 `candidate_prompt_sha256`과 다시 대조한다.

실행 trace는 가능한 경우 `codex exec --json` JSONL로 저장한다. reasoning은 후속 evaluator bundle에 복사하지 않는다.

## 7. multi-turn

`has_followup=true`이면 초기 실행 뒤 같은 conversation/thread를 resume한다.

- 초기 trace/final 보존
- 같은 thread에서 follow-up 전달
- follow-up trace 별도 보존
- 두 trace의 thread ID 동일
- trace SHA는 서로 달라야 함

새 독립 conversation을 후속 턴으로 대체하지 않는다.

## 8. runner attestation

candidate 실행이 끝나면 `runner-attestation.json`을 만든다.

attestation은 최소한 다음 원본 artifact와 연결된다.

- `runner-job.json`
- `boundary-profile.json`
- `probe-report.json`
- eval-plan/prompt/runtime digest
- exact model/CLI version
- observed candidate/system/plugin skill set
- candidate env key 목록
- boundary backend/profile 정보

현재 runner-attestation schema에는 job SHA 전용 필드가 아직 없으므로, model-runner 구현 시 이를 추가하는 것이 다음 migration 대상이다. 그 전에는 runner job을 별도 immutable artifact로 보존한다.

## 9. evaluator 파이프라인

model run 이후 순서:

```text
Codex JSONL
  → codex_exec_evidence.py
  → feynman_review_bundle.py
  → semantic review v2
  → feynman_apply_review.py
  → feynman_eval_result.py
  → feynman_eval_aggregate.py
```

`feynman_eval_result.py`는 원본 boundary profile, verified probe report, review bundle을 다시 요구한다. 결과 생성 단계에서 경계 증거를 생략할 수 없다.

## 10. 완료 정의

model-runner 구현이 완료됐다고 부르려면 최소 다음이 실제 run에서 확인되어야 한다.

- strict runner-job validation 통과
- actual backend inspect/profile consistency 통과
- boundary canary 통과
- credential material candidate 미노출
- model control plane과 tool network 분리
- 실제 candidate model 응답 생성
- trace/evidence/review/result hash chain 완성
- multi-turn이면 same-thread continuity 완성

현재 상태는 **runner job contract + boundary/profile/canary reference까지 준비됨, credential broker + 실제 candidate model process 미구현**이다.
