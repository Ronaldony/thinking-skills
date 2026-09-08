# 행동 평가 외부 runner 계약

상태: **v0.3 proposal — external enforcement required**. 이 문서는 후보 모델의 행동 비교를 시작하기 전에 필요한 실행 격리 경계를 정의한다. 저장소의 Python 도구는 경계를 **검사하고 증거를 연결**하지만, OS/container/VM 격리 경계 자체를 만들지는 않는다.

## 왜 별도 경계가 필요한가

행동 평가에서 가장 위험한 실패는 후보가 evaluator rubric·source repository·다른 조건의 skill·사용자 비밀을 읽을 수 있는데도 “prompt에는 정답을 넣지 않았다”는 이유로 격리됐다고 착각하는 것이다.

2026-09-08 기준 OpenAI Codex 공개 이슈에는 `workspaceWrite`가 쓰기를 제한해도 같은 사용자 파일의 모델 주도 읽기를 충분히 제한하지 않는 배포 경로에 대한 요청(#40116), 중첩 외부 sandbox 아래 `codex exec -s read-only`가 쓰기를 허용한 재현(#15524), Windows restricted permission profile에서도 허용 root 밖 읽기가 성공한다는 보고(#42184)가 열려 있다. 반대로 일부 macOS 환경에서는 workspace 밖 읽기가 차단됐다는 보고도 있다. 플랫폼·버전·호스트에 따라 동작이 다를 수 있으므로 **sandbox 이름이나 설정 선언을 보안 성질의 증거로 쓰지 않고 실제 canary 동작을 검사한다.**

참고:
- https://github.com/openai/codex/issues/40116
- https://github.com/openai/codex/issues/15524
- https://github.com/openai/codex/issues/42184

## 위협 모델

runner는 최소한 다음 오염을 막아야 한다.

1. 후보가 evaluator directory, source repository, hidden/final rubric, 이전 결과를 읽음.
2. baseline/generic 조건이 전역·상위 경로의 사고 skill을 발견함.
3. 한 조건의 runtime이나 결과가 다음 조건에 남음.
4. 후보의 shell/tool subprocess가 실제 HOME, 프로젝트 형제 디렉터리, 자격증명 파일을 읽음.
5. 후보 tool network가 공개 평가 정답이나 외부 데이터를 조회함.
6. API 인증정보가 candidate-readable 파일·환경변수·명령행·로그로 노출됨.
7. 격리 설정은 있다고 보고되지만 실제 read/write/network enforcement가 실패함.
8. multi-turn 사례의 초기·후속 답변이 서로 다른 대화에서 생성됐는데도 하나의 수정/유지 episode로 합쳐짐.
9. runner가 `passed=true`를 임의로 기록했는데 실제 canary artifact·호스트 후검증과 연결되지 않음.

이 계약은 악의적인 커널·hypervisor·runner 운영자를 방어하는 설계가 아니다. 평가 harness가 같은 사용자·호스트의 우발적 또는 모델 주도 데이터 접근을 막고 재현 가능하게 기록하는 것을 목표로 한다.

## 필수 경계

### 1. 외부 enforcement

후보 runtime(Codex/agent)의 자체 sandbox 정책만 신뢰하지 않는다. candidate tool process와 host/evaluator 사이에 **후보 runtime 밖에서 설정된 OS sandbox, container, VM 또는 동등한 강제 경계**가 있어야 한다.

runner attestation의 `boundary.external_enforcement`는 `true`여야 한다. 이 선언 자체는 증거가 아니며 아래 canary artifact + evaluator-side 후검증이 필요하다.

### 2. 파일 읽기

후보가 읽어야 하는 data root는 원칙적으로 다음뿐이다.

- candidate workspace
- 평가 전용 ephemeral HOME
- 평가 전용 CODEX_HOME
- 평가 전용 temp
- interpreter/OS 실행에 필요한 platform runtime root

platform runtime root에는 evaluator 데이터, 실제 사용자 HOME, source checkout, 형제 프로젝트를 두지 않는다. validator는 protected root와 exposed/runtime root가 어느 방향으로든 겹치면 거부한다.

반드시 읽기 금지되는 root:

- evaluator directory
- source repository
- hidden/final-set storage
- 실제 사용자 HOME
- 다른 condition의 workspace/result

runner는 evaluator/source/real-HOME 쪽에 **실제 synthetic read canary 파일을 먼저 생성**하고, 경계 안에서 이를 읽게 한다. 파일 자체가 없어서 발생한 `ENOENT`는 격리 성공이 아니다. 현재 probe는 `EACCES`, `EPERM`, `EROFS` 계열의 실제 접근 거부만 `denied=true`로 기록한다.

### 3. 파일 쓰기

후보 쓰기 root는 candidate workspace와 명시적 ephemeral temp로 제한한다. 경계 안에서 candidate write canary는 성공해야 하고, evaluator/source/real HOME 쪽 synthetic write 경로는 실패해야 한다.

외부 verifier는 후보의 자기 보고만 보지 않는다.

- candidate write 파일이 실제로 생성됐고 marker bytes가 일치하는지 확인한다.
- forbidden write 경로가 실제로 생성되지 않았는지 확인한다.
- forbidden write가 성공했다면 해당 파일이 남으므로 run을 실패로 처리한다.

### 4. 네트워크

평가 case가 tool network를 필요로 하지 않으면 candidate tool subprocess의 네트워크는 차단한다. 모델 API control plane 연결이 필요하면 **tool network와 control-plane network를 분리**해야 한다.

권장 구조:

```text
host runner ── allowed control plane ── model service
     │
     └── external boundary ── candidate tool process
                              └── outbound tool network blocked
```

control plane과 candidate tool process가 같은 unrestricted network namespace를 공유한다면 `tool_network=blocked`라고 기록하지 않는다. `tool_network=blocked`일 때 `allowed_tool_destinations`는 비어 있어야 한다.

closed-network case의 network canary는 공개 인터넷 사이트 장애에 의존하지 않는다. runner가 통제하는 endpoint를 사용하고 다음 둘을 함께 남긴다.

1. evaluator/control-plane 쪽 `network-reference.json`: 같은 host/port가 control plane에서 reachable임을 확인.
2. boundary 내부 probe: 그 동일 host/port 연결 시도가 실패했음을 기록.

외부 verifier는 두 endpoint가 정확히 같은지 대조한다. `network-reference.json` 없이 단순 connection failure만으로는 network denial을 인정하지 않는다.

network가 필요한 case에서는 `tool_network_denied`를 성공으로 꾸미지 않는다. normalized report의 `not_required_probes`에 `tool_network_denied`를 명시하고, attestation의 network policy와 일치해야 한다.

### 5. 인증정보와 환경변수

모델/API 인증정보는 candidate-readable file, candidate tool environment, command argument, trace tool output에 들어가면 안 된다. control-plane 인증은 별도 broker/process에서 처리하는 것이 바람직하다.

candidate tool environment는 allowlist 방식으로 구성한다. probe artifact는 **값이 아니라 환경변수 key 목록만** 기록한다. `TOKEN`, `KEY`, `SECRET`, `PASSWORD`, `CREDENTIAL`, `COOKIE`, `AUTH` 계열의 secret-like key가 발견되면 verifier가 실패시킨다.

### 6. 스킬·플러그인 오염

`tooling/feynman_eval_preflight.py`의 예상 skill set 검사를 외부 boundary 안에서 수행한다. baseline/generic에서는 후보 skill 집합이 비어 있어야 한다. `legacy-clean`과 `feynman-v05`에서는 `feynman-thinking` 하나만 허용한다.

내장/system skill, plugin, connector를 끌 수 없다면 **모든 비교 조건에서 동일하게 노출되고 목록과 버전이 attestation에 기록**되어야 한다. 조건별로 달라지면 run은 비교에서 제외한다.

### 7. multi-turn 대화 연속성

`revise-08`, `retain-09`처럼 후속 증거에 대한 수정/유지를 평가하는 사례는 **초기 턴과 후속 턴이 동일한 Codex conversation/session을 공유해야 한다.** 독립 `codex exec` 두 개를 나중에 붙여서는 안 된다.

runner는 다음을 지킨다.

1. 사례마다 새 conversation/thread로 시작한다.
2. 초기 prompt를 실행하고 초기 JSONL trace와 final answer를 보존한다.
3. 후속 메시지는 기존 thread/session을 resume해 전달한다.
4. 후속 실행은 별도 JSONL trace로 보존한다.
5. 두 evidence index의 `thread_id`가 같은 nonempty 값이고 `source_trace_sha256`은 달라야 한다.
6. evaluator review bundle에는 초기 final answer와 후속 final answer를 모두 넣는다.

`tooling/feynman_review_bundle.py --include-followup --initial-evidence-bundle ...`가 이 연속성을 구조적으로 검사한다. 같은 `thread_id`는 유용한 연속성 증거지만 runner/session storage가 악의적으로 조작되지 않았다는 암호학적 증명은 아니다.

## 실행 가능한 boundary canary 프로토콜

경계가 준비된 뒤 한 run에서 다음 순서를 사용한다.

### A. evaluator가 synthetic canary 준비

외부/evaluator 쪽에서 임의 marker를 만든다.

- candidate readable canary 1개
- evaluator read canary 1개
- source read canary 1개
- real-HOME read canary 1개
- candidate write target 1개
- evaluator/source/real-HOME forbidden write target들
- closed-network case면 control-plane에서 reachable한 synthetic network endpoint + `network-reference.json`

실제 비밀 파일은 canary로 사용하지 않는다.

### B. 동일 external boundary 안에서 probe 실행

`tooling/feynman_boundary_probe.py`를 **candidate/model tool process와 동일한 외부 경계 안에서** 실행한다.

이 프로그램은 경계를 생성하지 않는다. 다음을 직접 시도해 `probe-artifact.json`에 기록한다.

- candidate canary read
- protected canary read 3종
- candidate write
- forbidden writes
- candidate environment key scan
- 필요 시 network TCP connect

보호 파일 내용을 artifact에 복사하지 않고 성공 여부·errno·bytes/hash만 기록한다. probe program 자체 SHA-256도 artifact에 포함한다.

### C. boundary 밖 evaluator verifier 실행

`tooling/feynman_boundary_probe_verify.py`를 경계 밖에서 실행한다.

외부 verifier는 다음을 재검증한다.

- probe program SHA가 기대한 repository bytes와 동일한가
- protected read canary가 실제로 존재하고 원래 marker를 유지하는가
- candidate read marker/hash가 실제 파일과 맞는가
- candidate write가 실제로 생성됐는가
- forbidden write가 실제로 미생성 상태인가
- env key에서 secret-like key가 없는가
- closed-network라면 control-plane network reference와 candidate 실패 endpoint가 같은가

출력 `probe-report.json`은 `evals/feynman-thinking/boundary-probe-report.schema.json`과 `validate_report()`의 구조를 따른다. `permission denied` 문자열 하나만으로 pass시키지 않는다.

### D. attestation과 analysis result에 결속

`runner-attestation.json`의 `digests.probe_report_sha256`는 **검증된 `probe-report.json` 원본 bytes SHA-256**과 같아야 한다.

`tooling/feynman_runner_attestation.py --probe-report ...`는 다음을 확인한다.

- report 자체 구조·verdict·failed/not-required probe self-consistency
- report run_id = attestation run_id
- report SHA = attestation의 `probe_report_sha256`
- report의 8개 boundary probe record = attestation의 대응 probe record
- report에서 관찰한 candidate env key = attestation env key
- closed/network-required 정책과 `not_required_probes`의 일치

`ambient_skill_preflight`는 boundary report의 8개 probe와 별도이며 attestation에서 계속 필수로 검증한다.

`tooling/feynman_eval_result.py`는 **review bundle뿐 아니라 verified probe report도 필수 입력**으로 요구한다. probe report가 없거나 SHA/내용이 attestation과 다르면 `valid_for_analysis` result를 만들지 않는다. `tooling/feynman_eval_aggregate.py`도 probe-report digest가 없는 수제 schema-v2 result를 거부한다.

## 동작 기반 probe 기대값

| Probe | 기대 결과 | 실패 시 |
|---|---|---|
| candidate 파일 읽기 | 성공 + marker 일치 | runner invalid |
| evaluator read canary | 접근 거부 + host canary 존재 | run invalid |
| source-repo read canary | 접근 거부 + host canary 존재 | run invalid |
| real-HOME read canary | 접근 거부 + host canary 존재 | run invalid |
| candidate write | 성공 + host marker 일치 | runner invalid |
| forbidden writes | 접근 거부 + 실제 미생성 | run invalid |
| tool network canary (closed-network) | control-plane reachable + boundary connect 거부 | run invalid |
| ambient skill preflight | 예상 집합과 정확히 일치 | run invalid |
| candidate env inspection | secret-like key 없음 | run invalid |

## runner attestation

각 run은 `runner-attestation.json`을 evaluator 쪽에 남긴다. `evals/feynman-thinking/runner-attestation.schema.json`이 구조를 정의하고 `tooling/feynman_runner_attestation.py`가 불변조건을 검사한다.

중요: attestation validator와 boundary report validator는 **runner가 거짓말하지 않는다는 증명**이 아니다. 실제 external boundary·probe artifact·evaluator-side postcheck와 runner 운영 환경의 신뢰가 전제된다. 따라서 결과는 `contract-valid`이지 `secure`가 아니다.

필수 기록:

- run/case/condition ID
- backend 종류·버전·platform/kernel
- `external_enforcement=true`
- candidate/evaluator/source/ephemeral HOME/CODEX_HOME/temp 경로
- candidate-readable/writable/platform runtime roots
- 실제 사용자 HOME이 readable root가 아님
- tool/control-plane network 분리 상태
- candidate env key 목록과 auth exposure 여부
- expected/observed skill set 및 plugin/system-skill 목록
- normalized read/write/network/env probe records
- `probe_report_sha256`
- model/Codex 버전, eval plan/runtime digest
- 알려진 제한사항

conversation continuity의 thread/trace 연결은 runner attestation 선언보다 evaluator-side evidence/review hash chain에서 별도로 확인한다.

## 조건별 유효성

`baseline` / `generic`:
- candidate skill set = empty
- condition-specific runtime 설치 없음

`legacy-clean` / `feynman-v05`:
- candidate skill set = `feynman-thinking` 하나
- runtime digest가 해당 job metadata와 일치

모든 조건:
- 같은 isolation backend/profile family
- 같은 platform/system/plugin 정책
- 같은 tool/network 정책(과제가 다르게 요구하지 않는 한)
- evaluator/source/real HOME read probe 차단
- 동일 condition의 반복 사이에 runtime digest가 바뀌지 않음
- analysis result가 verified boundary probe report에 결속됨

## 현재 구현 상태

현재 저장소는 다음을 구현했다.

- 런타임 allowlist
- candidate/evaluator directory 분리
- ambient skill-root preflight
- **boundary 내부 read/write/env/network probe recorder** (`feynman_boundary_probe.py`)
- **evaluator-side canary post-verifier + normalized report validator** (`feynman_boundary_probe_verify.py`)
- boundary probe report JSON schema와 attestation `probe_report_sha256` binding
- Codex JSONL의 reasoning-free evidence extraction과 final/evidence hash binding
- evaluator-only semantic review bundle
- multi-turn same-thread review linkage와 초기/후속 answer 보존
- trusted execution 구조 gate와 semantic review v2 primary outcome
- frozen eval plan → probe report/runner attestation → review bundle → semantic review → gate의 analysis-result hash linkage
- 누락·혼합 환경·runtime drift·probe-report 누락을 막는 descriptive aggregator
- deterministic condition plan
- sanitized pinned legacy runtime

**아직 구현되지 않은 것은 외부 OS/container/VM enforcement backend 자체와 그 backend에서 나온 실제 canary attestation이다.** 현재 도구는 외부 경계가 제대로 작동하는지 검사할 준비가 된 상태이지, 경계를 스스로 제공하지 않는다. 실제 external runner에서 위 probe가 통과하기 전에는 공개 개발 pilot도 행동 성능 근거로 사용하지 않는다.
