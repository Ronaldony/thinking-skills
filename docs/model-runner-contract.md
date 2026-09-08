# 외부 model-runner 계약

상태: **v0.2 reference architecture proven with mock model — external model authentication and behavioral pilot pending**.

이 문서는 `feynman-thinking` 행동 비교의 실제 후보 모델 실행 경계를 정의한다. `docs/eval-runner-contract.md`가 filesystem/network canary와 boundary evidence를 다룬다면, 이 문서는 **모델 control plane과 candidate tool 실행을 어떻게 분리하고 frozen eval job을 어떤 순서로 실행할지**를 다룬다.

## 현재 채택한 구조

별도 TCP credential proxy를 새로 발명하는 대신 Codex의 remote environment / `exec-server` 경로를 사용한다.

```text
host/control plane
  ├── Codex frontend
  │    ├── model-service credential 또는 mock credential
  │    └── model network
  │
  └── stdio JSON-RPC
        ↓
Docker external tool boundary
  ├── codex exec-server --listen stdio
  ├── candidate workspace
  ├── ephemeral HOME / CODEX_HOME / temp
  ├── shell/file tool execution
  └── --network none
```

핵심은 **모델 API를 호출하는 frontend와 모델이 조작할 수 있는 shell/tool process의 네트워크 namespace를 분리**하는 것이다. control-plane credential을 candidate tool environment/file/argv에 전달하지 않는다.

2026-09-08 reference에서는 동일한 `codex-cli 0.153.4`를 control plane과 Docker tool image에 설치하고, 로컬 mock Responses server → Codex frontend → stdio remote `exec-server` → remote `exec_command` → tool output → mock final의 전체 왕복을 실제 GitHub Actions에서 통과시켰다. 이 reference는 **실제 외부 모델 인증 결과나 Feynman 스킬 성능 결과가 아니다.**

## 원칙

1. 모델 인증정보는 candidate tool environment, candidate-readable file, tool command argument에 넣지 않는다.
2. runner가 임의로 condition/prompt/runtime/profile을 재작성하지 않는다.
3. 실행 전 `runner-job.json`, 원본 `boundary-profile.json`, canonical `environments.toml`을 검증한다.
4. tool boundary는 evaluator/source/real-HOME을 mount하지 않는다.
5. closed-network case의 tool process는 `--network none` 또는 동등한 외부 enforcement를 사용한다.
6. boundary 성공, model transport 성공, 모델 답변 품질은 서로 다른 주장이다.
7. 실제 외부 model run이 없으면 행동 성능 데이터를 만들지 않는다.

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
  --output runner-job.json
```

`runner-job.json`에는 credential **값**을 넣지 않는다. authentication contract는 다음으로 고정한다.

```json
{
  "mode": "external-broker",
  "candidate_tool_auth_env_keys": [],
  "candidate_readable_credential_files": [],
  "credential_command_arguments": []
}
```

여기서 `external-broker`는 반드시 별도 custom proxy를 의미하지 않는다. **credential을 가진 model control-plane process가 tool boundary 밖에 있고 credential material을 tool process에 주지 않는 구조**를 의미한다.

## 2. 실행 전 strict validation

```bash
python tooling/feynman_runner_job_validate.py \
  --job runner-job.json \
  --boundary-profile boundary-profile.json
```

validator는 특히 다음을 검사한다.

- profile raw SHA가 job의 boundary/digest와 동일
- candidate workspace, ephemeral HOME, tool CODEX_HOME, temp가 profile의 **전체 rw mount 집합과 정확히 동일**
- evaluator/source/real-HOME은 candidate-owned root가 아님
- candidate credential env/file/argv 없음
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

생성기는 다음을 고정한다.

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

실제 행동 pilot에서는 동일 profile로 다음 canary를 먼저 통과시킨다.

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

## 6. credential-free mock model reference

`.github/workflows/validate-feynman-remote-exec-reference.yml`은 실제 API credential 없이 architecture 자체를 검증한다.

`tooling/feynman_mock_responses_server.py`의 첫 응답은 `exec_command`를 요청한다. remote command는 다음 세 marker를 모두 만들어야 한다.

- `REMOTE_EXEC_OK`: candidate workspace write가 실제 remote tool에서 실행됨
- `NETWORK_BLOCKED`: control plane에서 reachable한 동일 endpoint를 remote tool이 연결하지 못함
- `AUTH_ENV_CLEAN`: control plane에 둔 dummy `OPENAI_API_KEY` 등 secret-like env key가 remote tool env에 없음

두 번째 mock model request에 해당 tool output이 실제로 되돌아오지 않으면 mock server는 final을 반환하지 않는다. 정상 왕복일 때만 `REMOTE_EXEC_REFERENCE_OK`를 반환한다.

reference는 또한:

- control/tool Codex version 동일성
- frozen baseline job
- canonical `environments.toml`
- Docker inspect/profile 일치
- candidate marker file
- Codex JSONL의 completed `command_execution`
- exact final agent message

를 확인한다.

`tooling/feynman_remote_exec_reference_result.py`는 위 원본 증거를 다시 검증하고 다음 artifact들을 SHA-256으로 하나의 result에 결속한다.

- boundary profile
- runner job
- `environments.toml`
- control-plane network reference
- mock-state
- Codex trace
- Docker inspect
- candidate proof file
- mock server program

결과 구조는 `evals/feynman-thinking/remote-exec-reference-result.schema.json`을 따른다.

이 reference의 성공 범위는 **credential-free transport/tool-boundary architecture**까지다. 실제 OpenAI 또는 다른 외부 model service의 인증·정책·rate limit·응답 동작은 포함하지 않는다.

## 7. 실제 model-service 인증 경계

실제 pilot에서 사람이 개입해야 하는 첫 지점이다.

필요한 것은 credential 값을 코드나 채팅에 넣는 것이 아니라, runner 운영자가 승인된 secret store/credential mechanism에 **control-plane 전용 credential**을 설정하는 것이다.

필수 성질:

- credential은 control-plane Codex frontend/model provider만 소유
- candidate tool environment에 auth key/value 없음
- candidate-readable HOME/CODEX_HOME에 credential file 없음
- tool command line에 credential 없음
- tool boundary는 model endpoint에 직접 연결할 수 없음
- control-plane credential을 arbitrary tool TCP proxy로 바꾸는 우회 경로 없음

실제 credential은 이 저장소에 commit하지 않는다. 사용자에게 채팅으로 secret 값을 전달하도록 요구하지도 않는다.

## 8. candidate 실행

runner는 `runner-job.json`의 다음 값을 변경하지 않는다.

- model ID
- Codex/agent version
- condition
- candidate prompt digest
- runtime digest
- boundary profile digest
- candidate-owned path set
- network policy

실제 prompt는 candidate workspace의 `task.txt` bytes를 사용하고 frozen plan의 `candidate_prompt_sha256`과 재대조한다.

실행 trace는 `codex exec --json` JSONL로 저장한다. reasoning item은 evaluator evidence bundle에 복사하지 않는다.

## 9. multi-turn

`has_followup=true`이면 초기 실행 뒤 같은 conversation/thread를 resume한다.

- 초기 trace/final 보존
- 같은 thread에서 follow-up 전달
- follow-up trace 별도 보존
- 두 trace의 thread ID 동일
- trace SHA는 서로 달라야 함

독립 conversation 두 개를 하나의 update episode로 합치지 않는다.

## 10. runner attestation과 job linkage

candidate 실행 후 `runner-attestation.json`을 만든다. 이후:

```bash
python tooling/feynman_runner_job_link.py \
  --job runner-job.json \
  --boundary-profile boundary-profile.json \
  --attestation runner-attestation.json \
  --probe-report probe-report.json \
  --output runner-job-link.json
```

이 단계는 pre-run job과 post-run attestation의 다음 값을 대조한다.

- run/case/condition
- model/Codex version
- candidate/evaluator/source/HOME/CODEX_HOME/temp paths
- profile digest/backend/network policy
- runtime/prompt/plan digest

따라서 다른 job의 attestation을 재사용하는 경로를 구조적으로 차단한다.

## 11. evaluator 파이프라인

실제 model run 이후:

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

## 12. 현재 한계와 완료 정의

mock reference가 성공했어도 다음은 아직 별도 검증 대상이다.

- 실제 외부 model-service credential/authentication
- 외부 model의 실제 응답 생성
- 모든 candidate-accessible tool 종류가 remote boundary를 우회하지 않는지 추가 regression
- `baseline / generic / legacy-clean / feynman-v05` 반복 평가
- semantic judge/human review

특히 현재 mock reference는 `exec_command` round trip을 강하게 검증하지만, **Codex frontend의 모든 미래/내장 tool 경로가 자동으로 같은 remote boundary를 따른다는 보편적 증명은 아니다.** 새 tool 유형이 행동 평가에 사용되면 별도 boundary regression을 추가한다.

model-runner를 실제 평가용으로 완료했다고 부르려면 최소 다음이 필요하다.

- strict runner-job validation
- canonical remote environment validation
- Docker inspect/profile consistency
- boundary canary
- credential material candidate tool 미노출
- control plane / tool network 분리
- 실제 외부 model 응답
- trace/evidence/review/result hash chain
- multi-turn이면 same-thread continuity

현재 상태는 **credential-free mock control-plane → stdio remote tool boundary end-to-end reference 완료, 실제 external model authentication + behavioral pilot 미완료**다.
