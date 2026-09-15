# 행동 평가 외부 runner 계약

상태: **v0.5 research protocol — Docker/Codex/remote-exec/remote-patch/synthetic-auth references validated; external model-service run pending**.

이 문서는 `feynman-thinking` 행동 비교에서 후보가 evaluator 자료·다른 조건의 스킬·실제 사용자 파일에 접근하지 못하도록 하는 외부 실행 경계와 그 검증 절차를 정의한다. 저장소의 Python 도구는 경계를 **기술하고, 실제 canary 동작을 검사하고, 실행 전/후 artifact를 해시로 연결**한다. OS/container/VM 자체를 제공하는 것이 아니라, 제공된 외부 경계의 선언과 동작을 fail-closed로 검증한다.

## 1. 검증하려는 주장

단순히 `sandbox=true`, `workspace-write`, `read-only` 같은 설정 이름을 기록하는 것으로 격리를 입증하지 않는다. 다음 네 층을 구분한다.

1. **선언된 boundary profile**: 어떤 backend·image·mount·network·권한·환경변수 정책을 쓰기로 했는가.
2. **동작 기반 canary**: 그 경계 안에서 실제 read/write/network 시도가 허용·차단됐는가.
3. **실행 전/후 lineage**: frozen plan에서 만든 pre-run runner job과 post-run attestation이 같은 실행을 기술하는가.
4. **평가 결과 결속**: 검증된 경계·runner linkage·trace/evidence/review/gate가 정확히 어느 모델 run 결과에 대응하는가.

네 층 중 하나라도 연결되지 않으면 해당 run을 primary 행동 비교에 사용하지 않는다.

## 2. 위협 모델

최소한 다음 오염을 막는다.

- 후보가 evaluator rubric, hidden/final-set 자료, 이전 결과를 읽음.
- 후보가 source repository 또는 실제 사용자 HOME을 읽음.
- baseline/generic이 전역 또는 상위 디렉터리의 사고 스킬을 발견함.
- 한 condition의 runtime/result가 다른 condition에 남음.
- candidate tool subprocess가 API key·credential을 환경변수나 파일로 읽음.
- tool network가 공개 정답이나 외부 자료를 임의로 조회함.
- runner가 `passed=true`라고 쓰지만 실제 파일/네트워크 동작은 그렇지 않음.
- pre-run runner job과 다른 model/path/profile/auth 정책으로 실행한 뒤 attestation만 맞춰 씀.
- multi-turn 사례를 서로 다른 대화 두 개로 실행한 뒤 하나의 수정/유지 episode처럼 합침.

이 계약은 악의적인 kernel/hypervisor/runner 운영자를 방어하는 암호학적 보안 설계가 아니다. 평가 harness와 runner의 우발적 또는 모델 주도 오염을 fail-closed로 발견하고 재현 가능하게 기록하는 것이 목표다.

## 3. boundary profile

각 외부 경계는 `boundary-profile.json`으로 기술한다. 구조는 `evals/feynman-thinking/boundary-profile.schema.json`, 의미 검사는 `tooling/feynman_boundary_profile.py`가 담당한다.

현재 v1 reference profile은 Docker만 지원하며 최소 불변조건은 다음과 같다.

- content-addressed Docker image ID 기록
- root filesystem read-only
- `no-new-privileges=true`
- Linux capability 0개
- protected root를 candidate boundary에 mount하지 않음
- candidate 전용 read-write mount만 허용
- probe program은 read-only mount
- ephemeral temp는 명시적 tmpfs 또는 candidate-owned temp
- candidate environment key는 allowlist이며 secret-like key가 없어야 함

profile 원본 bytes의 SHA-256을 `boundary_profile_sha256`으로 사용한다. canary artifact/report, runner job, runner attestation, runner-job-link, analysis result가 모두 같은 profile bytes를 가리켜야 한다.

중요: profile validator는 **선언의 내부 일관성**만 검사한다. 실제 Docker/VM이 그 선언대로 시작됐는지는 동작 canary와 backend inspect 자료로 별도 확인한다.

## 4. 파일 읽기 경계

candidate가 읽어야 하는 data root는 원칙적으로 다음뿐이다.

- candidate workspace
- 평가 전용 ephemeral HOME
- 평가 전용 CODEX_HOME
- 평가 전용 temp
- interpreter/OS 실행에 필요한 platform runtime root

반드시 candidate에서 보호할 root:

- evaluator directory
- source repository
- hidden/final-set storage
- 실제 사용자 HOME
- 다른 condition의 workspace/result

### read canary 규칙

외부 evaluator가 protected root마다 **실제로 존재하는 synthetic canary 파일**을 먼저 만든다. 실제 비밀 파일을 probe 대상으로 쓰지 않는다.

boundary 안의 `tooling/feynman_boundary_probe.py`가 같은 host path를 읽어 본다. 다음 두 방식 모두 차단으로 인정할 수 있다.

- permission/filesystem policy로 `EACCES`, `EPERM`, `EROFS` 발생
- mount namespace에서 path가 보이지 않아 `ENOENT`, `ENOTDIR` 발생

단, `ENOENT`를 그대로 신뢰하지 않는다. boundary 밖 verifier가 **host 쪽 canary가 실제로 존재하고 marker가 그대로임을 확인한 경우에만** namespace invisibility로 인정한다. 따라서 canary fixture를 만들지 않아 발생한 `ENOENT`는 pass가 될 수 없다.

## 5. 파일 쓰기 경계

candidate write canary는 허용된 candidate-owned root에서 실제 성공해야 한다. boundary 밖 verifier가 생성된 파일의 marker bytes를 확인한다.

forbidden write target은 evaluator/source/real-HOME 아래에 둔다. 성공 조건은 다음을 모두 만족하는 것이다.

- boundary 내부 write 시도가 성공하지 않음
- 내부 관찰이 blocked errno로 기록됨
- **host 쪽 parent directory가 실제 존재함**
- target 파일이 host에 실제 생성되지 않음

mount namespace로 parent가 보이지 않아 `ENOENT`가 발생하는 것은 허용하지만, host parent 자체가 없는 경우에는 non-evidence로 거부한다.

## 6. 네트워크 경계

tool network가 필요 없는 case는 `tool_network=blocked`로 실행하고 control plane과 candidate tool network를 분리한다.

```text
host/control plane ── allowed model network ── model service
       │
       └── external boundary ── candidate tool process
                                └── outbound tool network blocked
```

closed-network canary는 공개 사이트 장애에 의존하지 않는다. runner가 통제하는 TCP endpoint를 사용한다.

1. control plane에서 `tooling/feynman_network_reference.py`가 실제 TCP connect에 성공해야만 `network-reference.json`을 생성한다.
2. reference에는 `probe_method=tcp-connect:v1`과 `sha256("tcp://host:port")` endpoint identity를 남긴다.
3. 같은 host/port를 boundary 내부 probe가 연결하려 시도한다.
4. 외부 verifier는 reference identity와 candidate 시도 endpoint를 다시 대조하고 candidate 연결 실패를 확인한다.

단순 connection failure나 임의로 작성한 `reachable_from_control_plane=true`만으로 network isolation을 인정하지 않는다.

network가 필요한 case에서는 `tool_network_denied`를 성공으로 꾸미지 않는다. normalized report의 `not_required_probes`에 명시하고 runner attestation의 network policy와 맞는지 검사한다.

## 7. 인증정보와 환경변수

현재 runner-job/attestation/link에서 검증된 인증 구조는 다음이다.

```json
{
  "mode": "control-plane-only",
  "control_plane_credential_source": "environment",
  "control_plane_credential_env_key": "OPENAI_API_KEY"
}
```

여기서 기록하는 것은 env-key **이름**뿐이다. 실제 credential 값은 pre-run/post-run artifact에 저장하지 않는다.

필수 규칙:

- API credential material은 candidate-readable file, candidate tool environment, command argument에 들어가면 안 된다.
- candidate env allowlist에 control-plane credential env-key 이름이 나타나면 run을 실패시킨다.
- control-plane process만 credential을 소유한다.
- closed-network tool process는 model endpoint에 직접 접근하지 못한다.
- 별도 arbitrary candidate-accessible credential proxy를 인증 분리의 근거로 만들지 않는다.

boundary probe는 환경변수 **값을 복사하지 않고 key 목록만** 기록한다. `TOKEN`, `KEY`, `SECRET`, `PASSWORD`, `CREDENTIAL`, `COOKIE`, `AUTH` 계열의 secret-like key가 candidate environment에 보이면 run을 실패시킨다.

synthetic-auth reference는 run-scoped synthetic bearer가 control-plane HTTP request에는 존재하지만 remote tool env/file/argv와 보존 artifact exact-byte scan에는 나타나지 않는 경로를 검증했다. 실제 model-service credential의 인증 성공 자체는 아직 미검증이다.

## 8. 스킬·플러그인 오염

`tooling/feynman_eval_preflight.py`를 candidate와 동일한 boundary 정책 아래에서 수행한다.

- `baseline`, `generic`: candidate skill set = empty
- `legacy-clean`, `feynman-v05`: candidate skill set = `feynman-thinking` 하나

`$HOME/.agents/skills`, `$CODEX_HOME/skills`, candidate 상위 `.agents/skills`에서 예상하지 않은 스킬이 발견되면 run을 무효 처리한다.

내장/system skill, plugin, connector를 완전히 끌 수 없다면 모든 비교 조건에 동일하게 노출하고 목록·버전을 기록한다. 조건별로 달라지면 같은 primary comparison에 합치지 않는다.

## 9. multi-turn 연속성

`revise-08`, `retain-09`처럼 후속 증거에 대한 수정/유지를 평가하는 사례는 초기와 후속 턴이 **동일 conversation/session**을 공유해야 한다.

- 사례마다 새 thread로 시작
- 초기 trace와 final answer 보존
- 후속 메시지는 그 thread를 resume해 전달
- 후속 trace는 별도 파일로 보존
- 두 evidence index의 `thread_id`는 같은 nonempty 값
- 초기/후속 `source_trace_sha256`은 서로 달라야 함
- evaluator input에는 초기 final과 후속 final을 모두 포함

`tooling/feynman_review_bundle.py --include-followup --initial-evidence-bundle ...`가 이 조건을 구조적으로 검사한다.

## 10. 실행 가능한 canary 절차

### A. evaluator가 synthetic canary 준비

준비 대상:

- candidate readable canary
- evaluator/source/real-HOME read canary
- candidate write target
- evaluator/source/real-HOME forbidden write target
- closed-network라면 control-plane TCP endpoint
- `boundary-profile.json`

### B. profile 검증

```bash
python tooling/feynman_boundary_profile.py \
  --profile boundary-profile.json
```

profile raw SHA-256을 이후 모든 artifact의 `boundary_profile_sha256`으로 사용한다.

### C. 동일 boundary 안에서 probe 실행

```bash
python feynman_boundary_probe.py \
  --run-id <run-id> \
  --boundary-profile-sha256 <profile-sha> \
  ...
```

probe는 protected contents를 복사하지 않고 성공 여부, errno, bytes/hash, env key, network connect 결과만 기록한다.

### D. boundary 밖에서 verifier 실행

```bash
python tooling/feynman_boundary_probe_verify.py \
  --artifact probe-artifact.json \
  --expected-run-id <run-id> \
  --boundary-profile-sha256 <profile-sha> \
  ...
```

verifier는 host canary와 candidate artifact를 교차검증하고 `probe-report.json`을 만든다.

report 구조는 `evals/feynman-thinking/boundary-probe-report.schema.json`과 `validate_report()`가 정의한다.

## 11. 실행 전/후 artifact hash chain

primary 분석에 들어가는 한 run의 canonical 연결은 다음과 같다.

```text
frozen eval plan
   │
   ▼
runner-job.json v2  ───────────────┐
   │ plan/prompt/runtime/profile    │
   ▼                                │
boundary-profile.json               │
   │ raw SHA-256                    │
   ▼                                │
probe-artifact.json                 │
   ▼                                │
probe-report.json                   │
   ▼                                │
runner-attestation.json v2          │
   │                                │
   └──────── runner-job-link.json v2◄┘
                    │
                    ▼
Codex JSONL trace / candidate final
   │ evidence/final hashes
   ▼
review bundle
   ▼
semantic review v2
   ▼
grade gate
   ▼
analysis-result.json v3
   ▼
v3-only frozen-plan aggregator
```

`tooling/feynman_runner_attestation.py --probe-report ...`는 report run ID, profile digest, report bytes SHA, normalized probe records, env key, network-required 정책을 attestation과 대조한다.

`tooling/feynman_runner_job_link.py`는 raw runner job과 raw attestation을 profile/probe report와 함께 검증해 run/case/condition/model/CLI/path/network/auth/prompt/runtime/plan digest를 결속한다.

`tooling/feynman_eval_result.py`는 raw runner job과 raw saved runner-job-link를 모두 다시 요구하며 saved link를 raw inputs에서 재계산한다. `analysis-result.schema.json` v3가 canonical 형식이다.

`tooling/feynman_eval_aggregate.py`는 schema-v3 result만 primary aggregation에 받는다. historical schema-v2 result는 canonical primary comparison에 사용할 수 없다.

## 12. probe 기대값

| Probe | 기대 결과 | 실패 시 |
|---|---|---|
| candidate read | 성공 + marker 일치 | runner invalid |
| evaluator read | boundary에서 차단 + host canary 존재 | run invalid |
| source read | boundary에서 차단 + host canary 존재 | run invalid |
| real-HOME read | boundary에서 차단 + host canary 존재 | run invalid |
| candidate write | 성공 + host marker 일치 | runner invalid |
| forbidden writes | boundary에서 차단 + host parent 존재 + target 미생성 | run invalid |
| tool network, closed case | control-plane reachable + boundary connect 실패 | run invalid |
| ambient skill preflight | 예상 skill set과 정확히 일치 | run invalid |
| candidate env | secret-like key 없음 | run invalid |

## 13. reference boundary / tool E2E

GitHub Actions의 reference workflows는 서로 다른 주장을 분리한다.

### Docker boundary reference

- content-addressed Docker image ID
- `--network none`
- read-only root
- `--cap-drop ALL`
- no-new-privileges
- exact rw mounts
- `env -i`
- filesystem/network canary
- Docker inspect/profile consistency

### Codex reference

동일한 inspected boundary profile에서 Codex CLI 자체가 실행 가능함을 확인한다. 이 reference만으로 model request를 증명하지 않는다.

### remote-exec reference

host/control-plane Codex가 mock Responses endpoint와 통신하고, candidate command는 network-none Docker `codex exec-server --listen stdio`에서 실행되며 tool output이 model loop에 되돌아오는 것을 확인한다.

### remote-patch reference

installed Codex bundled metadata 중 실제 `apply_patch_tool_type=freeform` 지원 model만 이용해 selected remote environment에서 `apply_patch → exec_command` round trip을 확인한다.

### synthetic-auth reference

run-scoped synthetic bearer가 control-plane request에만 존재하고 candidate remote tool env/file/argv 및 보존 artifact exact-byte scan에는 나타나지 않음을 확인한다.

각 reference 성공은 **그 reference가 직접 검사한 architecture property**만 증명한다. 실제 외부 model-service credential/authentication 또는 Feynman 행동 품질을 증명하지 않는다.

## 14. runner attestation v2

각 실제 model run은 `runner-attestation.json`을 evaluator 쪽에 남긴다. `evals/feynman-thinking/runner-attestation.schema.json`과 `tooling/feynman_runner_attestation.py`가 검사한다.

필수 기록에는 다음이 포함된다.

- schema version 2
- run/case/condition ID
- backend/version/platform/kernel
- `external_enforcement=true`
- boundary profile SHA
- candidate/evaluator/source/HOME/CODEX_HOME/temp 경로
- readable/writable/platform runtime roots
- tool/control-plane network 정책
- candidate env key 목록
- control-plane auth mode/source/env-key 이름
- expected/observed candidate skill 및 system/plugin 정책
- normalized boundary probe records
- `probe_report_sha256`
- model/Codex 버전
- eval-plan/prompt/runtime digest
- 알려진 한계

validator 결과는 `contract-valid`이지 `secure`가 아니다.

## 15. 비교 조건의 유효성

모든 primary 조건은 다음을 만족해야 한다.

- 같은 model snapshot
- 같은 Codex/agent 버전
- 같은 external boundary profile
- 같은 system/plugin 정책
- 같은 tool/network 정책(과제가 요구하지 않는 한)
- 같은 control-plane authentication profile(mode/source/env-key 이름)
- 동일 condition 반복에서 runtime digest 고정
- evaluator/source/real-HOME 보호 canary 통과
- pre-run runner-job 존재
- post-run attestation 존재
- recomputable runner-job-link 존재
- analysis-result schema v3

하나라도 다르면 aggregator가 `mixed-environment`, `incomplete`, `unverified-outcomes` 등으로 primary comparison을 차단해야 한다.

## 16. 현재 구현 상태

구현·reference 검증 완료:

- runtime allowlist와 candidate/evaluator 분리
- ambient skill-root preflight
- boundary profile schema/validator
- inside-boundary read/write/env/network probe recorder
- evaluator-side host post-verifier
- network control-plane reference generator
- profile → artifact → report → attestation hash linkage
- runner-job schema v2 / strict validator
- runner-attestation schema v2
- runner-job-link schema v2 / recomputation
- control-plane-only/environment auth architecture contract
- reasoning-free Codex evidence extraction
- final/evidence/review/gate hash linkage
- semantic review v2와 predefined hard failure
- multi-turn same-thread 구조 검증
- analysis-result schema v3 / v3-only canonical aggregator
- sanitized pinned legacy runtime
- Docker/Codex/remote-exec/remote-patch/synthetic-auth reference workflows

아직 미완료:

- 승인된 실제 외부 model-service credential을 사용한 end-to-end run
- 실제 외부 model 응답으로 만든 `baseline / generic / legacy-clean / feynman-v05` 행동 pilot
- 실제 multi-turn model run의 same-thread evidence
- 독립 semantic judge / blinded human review
- 비공개 held-out 평가

따라서 **FYN-04/FYN-05의 구조와 reference 검증은 크게 진척됐지만 실제 model-service 행동 평가 완료를 선언하지 않는다.** 실제 model process와 credential로 같은 runner-job/profile/probe/attestation/link/result-v3 chain이 통과하기 전에는 행동 성능 근거로 사용하지 않는다.
