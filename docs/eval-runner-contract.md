# 행동 평가 외부 runner 계약

상태: **v0.1 proposal — external enforcement required**. 이 문서는 후보 모델의 행동 비교를 시작하기 전에 필요한 실행 격리 경계를 정의한다. 현재 저장소의 Python workspace/preflight 도구나 Codex 내부 sandbox 설정 하나만으로 이 계약이 충족됐다고 간주하지 않는다.

## 왜 별도 경계가 필요한가

행동 평가에서 가장 위험한 실패는 후보가 evaluator rubric·source repository·다른 조건의 skill·사용자 비밀을 읽을 수 있는데도 “prompt에는 정답을 넣지 않았다”는 이유로 격리됐다고 착각하는 것이다.

2026-09-08 기준 OpenAI Codex 공개 이슈에는 `workspaceWrite`가 쓰기를 제한해도 같은 사용자 파일의 모델 주도 읽기를 충분히 제한하지 않는 배포 경로에 대한 요청(#40116), 중첩 외부 sandbox 아래 `codex exec -s read-only`가 쓰기를 허용한 재현(#15524), Windows의 restricted permission profile에서도 허용 root 밖 읽기가 성공한다는 보고(#42184)가 열려 있다. 반대로 일부 macOS 환경에서는 workspace 밖 읽기가 차단된다는 보고도 있다. 즉 플랫폼·버전·호스트 경로에 따라 동작이 달라질 수 있으므로 **sandbox 이름을 보안 성질의 증거로 쓰지 않고 실제 canary 동작을 검사한다.**

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

이 계약은 악의적인 커널·hypervisor·runner 운영자를 방어하는 설계가 아니다. 평가 harness가 같은 사용자·호스트의 우발적 또는 모델 주도 데이터 접근을 막고 재현 가능하게 기록하는 것을 목표로 한다.

## 필수 경계

### 1. 외부 enforcement

후보 runtime(Codex/agent)의 자체 sandbox 정책만 신뢰하지 않는다. candidate tool process와 host/evaluator 사이에 **후보 runtime 밖에서 설정된 OS sandbox, container, VM 또는 동등한 강제 경계**가 있어야 한다.

runner attestation의 `boundary.external_enforcement`는 `true`여야 한다. 이 값 자체는 증거가 아니므로 아래 canary probe도 모두 통과해야 한다.

### 2. 파일 읽기

후보가 읽어야 하는 데이터 root는 원칙적으로 다음뿐이다.

- candidate workspace
- 평가 전용 ephemeral HOME
- 평가 전용 CODEX_HOME
- 평가 전용 temp
- interpreter/OS 실행에 필요한 platform runtime root

platform runtime root에는 evaluator 데이터, 사용자 HOME, source checkout, 형제 프로젝트를 두지 않는다.

반드시 읽기 금지되는 root:

- evaluator directory
- source repository
- hidden/final-set storage
- 실제 사용자 HOME
- 다른 condition의 workspace/result

runner는 evaluator와 source 쪽에 임의 canary 파일을 만들고 **동일한 boundary에서 candidate tool command로 직접 읽기를 시도하여 실패**해야 한다. 실제 비밀 파일을 probe 대상으로 쓰지 않는다.

### 3. 파일 쓰기

후보의 쓰기 root는 candidate workspace와 명시적 ephemeral temp로 제한한다. evaluator/source/real HOME 쪽에 synthetic write-canary 경로를 만들고 동일 boundary에서 쓰기 시도가 실패하는지 확인한다.

테스트 후 write canary는 evaluator가 존재 여부를 확인한다. 단순히 command의 자체 보고만 신뢰하지 않는다.

### 4. 네트워크

평가 case가 tool network를 필요로 하지 않으면 candidate tool subprocess의 네트워크는 차단한다. 모델 API control plane 연결이 필요한 경우 **tool network와 control-plane network를 구분**해야 한다.

권장 구조:

```text
host runner ── allowed control plane ── model service
     │
     └── external boundary ── candidate tool process
                              └── outbound tool network blocked
```

control plane과 tool process가 같은 unrestricted network namespace를 공유한다면 `tool_network_blocked=true`라고 기록하지 않는다.

네트워크 차단은 동일 boundary에서 synthetic probe로 확인한다. 공개 인터넷의 특정 사이트 가용성에 의존하기보다 runner가 통제하는 canary endpoint/DNS 또는 명시적 firewall counter를 사용한다.

### 5. 인증정보와 환경변수

모델/API 인증정보는 candidate-readable file, candidate tool environment, command argument, trace의 tool output에 들어가면 안 된다. runner가 control plane 인증을 별도 broker/process에서 처리하는 것이 바람직하다.

candidate tool environment는 allowlist 방식으로 구성한다. `TOKEN`, `KEY`, `SECRET`, `PASSWORD`, `CREDENTIAL`, `COOKIE`, `AUTH` 같은 비밀 가능성이 높은 이름은 별도 검토 없이 통과시키지 않는다.

### 6. 스킬·플러그인 오염

`tooling/feynman_eval_preflight.py`의 예상 skill set 검사를 외부 boundary 안에서 수행한다. baseline/generic에서는 후보 skill 집합이 비어 있어야 한다. `legacy-clean`과 `feynman-v05`에서는 `feynman-thinking` 하나만 허용한다.

내장/system skill, plugin, connector가 끌 수 없다면 **모든 비교 조건에서 동일하게 노출되고 목록과 버전이 attestation에 기록**되어야 한다. 조건별로 달라지면 run은 비교에서 제외한다.

## 동작 기반 canary probe

각 run 또는 동일하고 불변인 sandbox image/profile 단위에서 다음 probe가 필요하다. profile 단위 재사용 시 image/profile digest와 probe 결과를 모든 run에 연결한다.

| Probe | 기대 결과 | 실패 시 |
|---|---|---|
| candidate 파일 읽기 | 성공 | runner invalid |
| evaluator read canary | 거부 | run invalid |
| source-repo read canary | 거부 | run invalid |
| real-HOME read canary | 거부 | run invalid |
| candidate write | 성공 | runner invalid |
| evaluator/source write canary | 거부 + 실제 미생성 | run invalid |
| tool network canary (closed-network case) | 거부 | run invalid |
| ambient skill preflight | 예상 집합과 정확히 일치 | run invalid |
| candidate env inspection | 비밀성 key 없음 | run invalid |

`permission denied` 문자열만 찾지 않는다. exit code, 실제 파일 존재 여부, canary token 유출 여부를 evaluator 쪽에서 함께 확인한다.

## runner attestation

각 run은 `runner-attestation.json`을 evaluator 쪽에 남긴다. `evals/feynman-thinking/runner-attestation.schema.json`이 구조를 정의하고 `tooling/feynman_runner_attestation.py`가 최소 불변조건을 검사한다.

중요: attestation validator는 **runner가 거짓말하지 않는다는 증명**이 아니다. 실제 external boundary가 생성한 probe artifact와 runner 운영 환경의 신뢰가 전제된다. 따라서 validator 결과는 `contract-valid`이지 `secure`가 아니다.

필수 기록:

- run/case/condition ID
- backend 종류·버전·platform/kernel
- `external_enforcement=true`
- candidate/evaluator/source/ephemeral HOME/CODEX_HOME/temp 경로
- candidate-readable data roots / writable roots / platform runtime roots
- 실제 사용자 HOME이 readable root가 아님
- tool network와 control-plane network의 분리 상태
- candidate tool env key 목록과 auth exposure 여부
- expected/observed skill set 및 plugin/system-skill 목록
- read/write/network canary 결과와 artifact SHA-256
- model/Codex 버전, eval plan/runtime digest
- 알려진 제한사항

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

## 현재 구현 상태

현재 저장소는 다음을 구현했다.

- 런타임 allowlist
- candidate/evaluator directory 분리
- ambient skill-root preflight
- Codex JSONL의 reasoning-free evidence extraction
- evaluator-only semantic review bundle
- trusted execution 구조 gate
- deterministic condition plan
- sanitized pinned legacy runtime

**아직 실제 external read/network isolation runner는 구현하지 않았다.** 따라서 위 계약을 검증하는 실제 attestation이 나오기 전에는 공개 개발 pilot조차 행동 성능 근거로 사용하지 않는다.
