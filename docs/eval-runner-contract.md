# 행동 평가 외부 runner 계약

상태: **v0.4 research protocol — Docker reference boundary canary validated; model runner not yet validated**.

이 문서는 `feynman-thinking` 행동 비교에서 후보가 evaluator 자료·다른 조건의 스킬·실제 사용자 파일에 접근하지 못하도록 하는 외부 실행 경계와 그 검증 절차를 정의한다. 저장소의 Python 도구는 경계를 **기술하고, 실제 canary 동작을 검사하고, 결과를 해시로 연결**한다. OS/container/VM 경계 자체나 모델 API 인증 broker를 제공하지는 않는다.

## 1. 검증하려는 주장

단순히 `sandbox=true`, `workspace-write`, `read-only` 같은 설정 이름을 기록하는 것으로 격리를 입증하지 않는다. 다음 세 층을 구분한다.

1. **선언된 boundary profile**: 어떤 backend·image·mount·network·권한·환경변수 정책을 쓰기로 했는가.
2. **동작 기반 canary**: 그 경계 안에서 실제 read/write/network 시도가 허용·차단됐는가.
3. **평가 결과 결속**: 검증된 경계와 canary report가 정확히 어느 모델 run의 결과에 대응하는가.

세 층 중 하나라도 연결되지 않으면 해당 run을 primary 행동 비교에 사용하지 않는다.

## 2. 위협 모델

최소한 다음 오염을 막는다.

- 후보가 evaluator rubric, hidden/final-set 자료, 이전 결과를 읽음.
- 후보가 source repository 또는 실제 사용자 HOME을 읽음.
- baseline/generic이 전역 또는 상위 디렉터리의 사고 스킬을 발견함.
- 한 condition의 runtime/result가 다른 condition에 남음.
- candidate tool subprocess가 API key·credential을 환경변수나 파일로 읽음.
- tool network가 공개 정답이나 외부 자료를 임의로 조회함.
- runner가 `passed=true`라고 쓰지만 실제 파일/네트워크 동작은 그렇지 않음.
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

profile 원본 bytes의 SHA-256을 `boundary_profile_sha256`으로 사용한다. canary artifact와 report, runner attestation은 모두 이 값을 동일하게 가져야 한다.

중요: profile validator는 **선언의 내부 일관성**만 검사한다. 실제 Docker/VM이 그 선언대로 시작됐는지는 동작 canary와, 가능하면 backend inspect 자료로 별도 확인한다.

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
host/evaluator ── allowed control plane ── model service
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

API 인증정보는 candidate-readable file, candidate tool environment, command argument, trace tool output에 들어가면 안 된다. control-plane 인증은 별도 broker/process에서 처리하는 것이 바람직하다.

boundary probe는 환경변수 **값을 복사하지 않고 key 목록만** 기록한다. `TOKEN`, `KEY`, `SECRET`, `PASSWORD`, `CREDENTIAL`, `COOKIE`, `AUTH` 계열의 secret-like key가 candidate environment에 보이면 run을 실패시킨다.

## 8. 스킬·플러그인 오염

`tooling/feynman_eval_preflight.py`를 candidate와 동일한 boundary 안에서 수행한다.

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

## 11. artifact hash chain

primary 분석에 들어가는 한 run의 연결은 다음과 같다.

```text
boundary-profile.json
   │ raw SHA-256
   ▼
probe-artifact.json
   │ boundary_profile_sha256 + probe_program_sha256
   ▼
probe-report.json
   │ host postcheck + same boundary_profile_sha256
   ▼
runner-attestation.json
   │ probe_report_sha256 + boundary.profile_sha256
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
analysis result v2
   ▼
frozen-plan aggregator
```

`tooling/feynman_runner_attestation.py --probe-report ...`는 report run ID, profile digest, report bytes SHA, normalized probe records, env key, network-required 정책을 attestation과 대조한다.

`tooling/feynman_eval_result.py`는 verified probe report와 review bundle이 없으면 `valid_for_analysis` result를 만들지 않는다. `tooling/feynman_eval_aggregate.py`도 probe-report digest가 없는 수제 result를 거부한다.

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

## 13. Docker reference boundary

GitHub Actions `validate-feynman`은 실제 Docker boundary를 reference profile로 실행한다.

현재 reference 특성:

- Docker backend
- `python:3.12-slim` image와 실제 image ID 기록
- `--network none`
- `--read-only`
- `--cap-drop ALL`
- `--security-opt no-new-privileges`
- host UID:GID로 실행
- candidate/candidate-home/CODEX_HOME/temp만 rw mount
- probe program만 ro mount
- evaluator/source/real-HOME은 mount하지 않음
- environment는 `env -i`로 allowlist 구성
- control-plane에서 reachable한 synthetic TCP endpoint 사용

이 reference Docker run에서 candidate read/write 허용, evaluator/source/real-HOME read 차단, forbidden write 차단, tool network 차단을 evaluator-side verifier가 실제로 확인했고 CI가 성공했다.

이 결과가 증명하는 범위는 **reference Docker tool-process boundary canary가 현재 GitHub Actions 환경에서 의도한 filesystem/network 성질을 만족했다는 것**이다.

증명하지 않는 것:

- Codex/model process가 같은 boundary에서 실제 실행됐음
- model API control plane/auth broker가 안전하게 분리됐음
- 다른 host/OS/Docker 버전에서도 같은 성질을 보장함
- 악의적인 runner 운영자를 방어함

## 14. runner attestation

각 실제 model run은 `runner-attestation.json`을 evaluator 쪽에 남긴다. `evals/feynman-thinking/runner-attestation.schema.json`과 `tooling/feynman_runner_attestation.py`가 검사한다.

필수 기록에는 다음이 포함된다.

- run/case/condition ID
- backend/version/platform/kernel
- `external_enforcement=true`
- boundary profile SHA
- candidate/evaluator/source/HOME/CODEX_HOME/temp 경로
- readable/writable/platform runtime roots
- tool/control-plane network 정책
- candidate env key 목록
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
- 같은 external boundary profile family
- 같은 system/plugin 정책
- 같은 tool/network 정책(과제가 요구하지 않는 한)
- 동일 condition 반복에서 runtime digest 고정
- evaluator/source/real-HOME 보호 canary 통과
- verified probe report가 analysis result에 결속

한 조건이라도 다르면 aggregator가 `mixed-environment`, `incomplete`, `unverified-outcomes` 등으로 primary comparison을 차단해야 한다.

## 16. 현재 구현 상태

구현 완료:

- runtime allowlist와 candidate/evaluator 분리
- ambient skill-root preflight
- boundary profile schema/validator
- inside-boundary read/write/env/network probe recorder
- evaluator-side host post-verifier
- network control-plane reference generator
- boundary artifact/report/profile schemas
- profile → artifact → report → attestation hash linkage
- reasoning-free Codex evidence extraction
- final/evidence/review/gate hash linkage
- semantic review v2와 predefined hard failure
- multi-turn same-thread 검증
- analysis-result schema v2와 frozen-plan aggregator
- sanitized pinned legacy runtime
- 실제 Docker reference boundary canary CI

아직 미완료:

- Codex/model candidate process를 reference 외부 경계 안에서 실행하는 runner
- model control-plane 인증 broker와 candidate tool network 분리의 실제 end-to-end 검증
- 실제 `baseline / generic / legacy-clean / feynman-v05` 행동 pilot
- 독립 semantic judge / blinded human review
- 비공개 held-out 평가

따라서 **FYN-04의 boundary 검증 도구와 Docker reference profile은 구현·검증됐지만, model-runner 수준의 FYN-04 완료를 선언하지 않는다.** 실제 model process에서 같은 canary/attestation chain이 통과하기 전에는 행동 성능 근거로 사용하지 않는다.
