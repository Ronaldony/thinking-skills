# LOG-096 — 최근 실행 증거 재검토와 후속 작업 계획 (2026-09-14)

## 범위와 현재 상태

- 요청: 최근 작업의 문제를 분석하고 다음 작업 계획을 세운다.
- 상태: 분석·계획 완료. 실제 startup 차단 해소는 미완료다.
- 시작 HEAD 및 원격 feature HEAD: `aa16305018e33d74777ab3be500ffbac600e77cc`.
- 브랜치: `feat/feynman-thinking-v0.5-draft`.
- 적용되는 `AGENTS.md`: 상위 경로와 저장소 검색에서 발견되지 않았다.
- 기존 `.tmp/`, 사용자 PNG 2개와 로그인 홈은 보존했다.
- 이번 변경은 분석 로그·재개 안내와 로컬 감사 스크립트다. production 코드 수정,
  새 구독 startup, 인증 검사, 모델 호출, commit/push는 하지 않았다.
- 직전 작업은 실행 증거를 남긴 진척이다. 다만 그 증거에 붙인 일부 결론은 틀렸고,
  이 로그가 LOG-095와 직전 응답의 원인 설명·다음 행동을 정정한다.

## 핵심 판단

`thread/start`가 `-32603`으로 실패한 사실은 유효하다. **최종 원인은 아직
확정되지 않았다.** 작업 지연에는 잘못된 집계 해석, 이미 준비된 입력의 수동 재조립,
검증 모드 간 차이, fixture 성공을 실제 실행 전체 성공으로 확대하는 문제가 기여했다.

따라서 다음 작업을 “누락된 응답 찾기”로 시작하면 안 된다. 입력과 판정 계약을
먼저 신뢰할 수 있게 만들고, 실제 시작 실패와 종료 증거 부족을 별도 재현해야 한다.

## 1. LOG-095에서 정정하는 내용

### 1.1 전송 6건·응답 5건은 응답 누락 증거가 아니다 — 확인

실제 telemetry에는 `initialize`, `initialized`, `environmentConfig/read`,
`fs/canonicalize`, `fs/getMetadata`, `fs/walk`가 각각 1건이다.

`request_seen()`은 ID 없는 `initialized` 알림도 `requests_seen`에 포함한다.
그러나 pending 등록은 문자열/정수 ID가 있는 메시지만 대상으로 한다. 따라서 이
6건은 응답이 필요한 요청 5건과 응답이 필요 없는 알림 1건으로 설명된다.
`responses_matched=5`, `pending_request_ids=0`, `responses_unmatched=0`도 이에
부합한다. 이 집계에서 누락된 method가 있다고 추정할 근거는 없다.

기존 `test_proxy_drains_healthy_child_after_parent_stdin_closes`도 정상 경로에서
전송 3건·응답 2건을 기대한다. 이번에 해당 시험을 포함한 회귀를 다시 통과했다.
공식 문서도 `initialized`를 notification으로 명시한다.
[공식 App Server 메시지 계약](https://learn.chatgpt.com/docs/app-server#message-schema).
이 공개 계약을 executor 내부 protocol 전체의 증명으로 확대하지는 않는다.

실제 telemetry를 수정하지 않고 메모리 복사본의 `child_exit_code`만 0으로 놓으면
현재 `_proxy_telemetry_ready()`가 true가 된다. 이는 응답 수 차이가 현재 readiness
실패 원인이 아님을 확인하는 반사실 계산이며, 실제 child가 exit 0이었다는 증거가 아니다.

근거: `tooling/feynman_rpc_path_proxy.py:139,625,660`,
`tooling/feynman_subscription_startup_diagnostic.py:418`.

### 1.2 오래된 binding 때문이라는 설명은 틀렸다 — 재현 확인

기존 binding과 새 binding을 비교한 결과 `full_runner`와 `lineage` 블록이 각각
완전히 동일하다. adapter, candidate, test, runner job, profile digest가 모두 같다.
기존 binding을 올바른 tool image와 넣으면 현재 validator에서 그대로 통과한다.
remote boundary image를 tool image 인자로 넣으면 실패가 재현된다.

- remote boundary image: `sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6`
- full-runner tool image: `sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a`

즉 첫 오류는 binding이 낡아서가 아니라 **호출자가 다른 역할의 image digest를
전달했기 때문**이다. 뒤의 preflight 재생성은 최신 관측을 추가했지만 구현 drift를
수정한 작업은 아니다. 일반 synthetic catalog와 실제 Luna catalog를 혼용한 시도도
있었으므로, 그 차이를 candidate 변경으로 해석하면 안 된다.

이미 `.tmp/feynman-subscription-checkpoint-20260913-v3.json`에는 올바른 이미지,
binding, canonical environment 경로가 들어 있었다. 새 실행에는 이 검증된 입력을
기반으로 출력 경로만 새로 정해야 했다. 과거 report 자체를 startup 성공으로 재사용하는
것과, 정확한 입력 설정을 재사용하는 것은 별개다.

### 1.3 Docker 잔존 container 없음의 확인 방식이 부정확했다 — 보완 확인

실제 `expected_docker_args()`는 고정 `--name`을 사용하고 control/runtime-probe
label을 붙이지 않는다. 이전 label 조회 0건은 이 startup container의 부재를 증명하지
못한다. 이번에는 job에서 생성되는 **정확한 이름**으로 `container inspect`를 1회
실행했다. Docker가 `No such object/container`를 반환해 현재 부재를 확인했다.

이는 현재 container 부재 증거다. 당시 정상 종료, proxy 프로세스 종료 코드,
최종 telemetry 저장 여부를 소급하여 증명하지는 않는다.

### 1.4 로그인 파일 미접근과 설정 검증을 구분한다

credential 파일을 읽거나 복사하지 않은 정책은 유지됐다. 다만 실행기는 non-secret
`config.toml`과 `environments.toml`을 읽어 검증한다. “control home의 파일 내용을
전혀 읽지 않았다”는 LOG-095 표현은 부정확하다. 정상 Codex가 로그인 상태를 사용하는
것과 진단기가 credential을 직접 덤프하는 것도 구별해야 한다.

## 2. 현재 코드에서 확인한 결함·검증 공백

| 우선도 | 항목 | 현재 증거와 영향 |
|---|---|---|
| P1 | `validate-only`와 실제 실행의 검증 불일치 | evaluator의 비정규 environment 경로, 상대 출력 경로, report/telemetry 동일 경로, candidate 내부 출력 경로를 모두 통과시킴. 실제 subprocess를 막은 상태에서 재현했다. |
| P1 | 입력 오류의 일반화 | 개별 인자 CLI가 `CheckpointError` 등을 `startup-diagnostic-input-invalid-value-error`로 축약한다. 입력명·실패 이유가 사라져 잘못된 재시도와 수동 진단을 유발한다. |
| P1 | 종료 판정과 시작 원인의 혼합 | `process_tree_reaped=True`가 초기값이고 종료 helper는 부모 종료만으로 true를 반환할 수 있다. 실제 report는 child exit null이다. `thread/start` 응답은 `finally` 전에 받으므로 나중의 정리 실패를 시작 오류 원인으로 단정할 수 없다. |
| P1 | 전체 시작 deadline 누락 | startup의 60초 시계가 wiring 준비와 프로세스 생성 후 시작한다. 실제 smoke가 먼저 호출하는 control-plane preflight에는 15초 cleanup deadline을 startup 전에 설정하는 결함도 남아 있다. |
| P1 | 계측이 전달에 개입 | proxy 전달 스레드가 각 메시지 전후에 lock, 임시 파일, `fsync`, rename을 동기 실행한다. 느린 저장이나 저장 실패가 protocol에 영향을 줄 수 있다. 실제 오류의 직접 원인인지는 미확정이다. |
| P1 | 경로 비교 범위와 판정 손실 | Docker fixture는 절대 URI와 명시적인 sub cwd만 사용한다. root/sub 설정 선택, 상대 config 그룹, cwd 생략/기본값 차이를 시험하지 않는다. 서로 다른 외부 cwd 또는 `/run/codex` 하위 경로가 같은 shape로 축약되는 것도 재현됐다. |
| P1 | 실제 smoke gate·설정 통합 미완료 | full-runner 인자가 모두 없으면 startup gate 없이 모델 실행 경로로 간다. gate 소비부는 verdict 문자열만 확인한다. wiring 준비를 중복 수행하고, startup evidence를 임시 디렉터리 종료 시 삭제한다. |
| P2 | 시험 범위와 CI 설명 불일치 | startup fixture 시험이 실제 `run()`/CLI 전체 흐름을 호출하지 않는다. 전체 suite에는 Windows 로컬 Codex/Docker가 있으면 자동 실행되는 integration 시험도 있고 Docker inspect에 timeout이 없다. 따라서 순수 unit suite라는 설명과 다르다. |

실행기가 과거 보고서 파일을 직접 읽어 재사용하는 경로는 현재 없다. 위의
verdict-only 문제는 새 결과를 받는 소비부 자체에서 schema·필수 checks를 다시
검증하지 않는다는 뜻이다. 또한 모델 요청 수는 보고서에서 상수 0으로 채워지므로,
모델 없는 진단의 전송 허용 목록과 실제 write/flush 관찰 횟수를 함께 검증해야 한다.

주요 위치:

- `tooling/feynman_subscription_checkpoint.py:72` — 공유되지 않은 입력 검증.
- `tooling/feynman_subscription_startup_diagnostic.py:473,520,522,556,636,741` —
  wiring/deadline/종료/오류 축약; correlation을 cleanup과 같은 bool로 저장.
- `tooling/feynman_subscription_control_plane_preflight.py:126,197` — 부모 종료 판정,
  너무 일찍 설정되는 cleanup deadline.
- `tooling/feynman_rpc_path_proxy.py:322,576,605,668` — 전달 스레드에서 동기 저장.
- `tooling/feynman_rpc_path_contract_probe.py:59,106,486` — 시험 입력과 정보 손실.
- `tooling/feynman_subscription_smoke_exec.py:602,606,635,652,669` — 선택적인 gate,
  중복 준비·별도 preflight·evidence 삭제·verdict-only 검증.
- `tests/test_feynman_full_runner_preflight.py:15` — 명시적 opt-in 없는 integration.

추가로 startup에만 있는 `project_doc_max_bytes=0` 등과 실제 smoke의 instruction
발견 설정이 다르다. 스킬은 별도 discovery로 검사하지만, 그 결과가 동일한 원격
실행 조건을 증명하는지는 아직 확인되지 않았다. 이 차이를 다음 공유 준비 객체의
명시적인 비교 대상으로 포함한다.

## 3. 실제 실패에 대한 남은 가설

현재 확정된 관찰은 App Server initialize 성공, `thread/start -32603`, 모델 turn 0,
mapping rejection 0, 최종 child exit 미확정이다. `remote-environment-error`는
오류 문구를 단어 검색해 만든 로컬 추정 label이며 Codex의 공식 원인 분류가 아니다.

다음 가설을 구분해야 한다.

1. executor는 정상 응답했으나 App Server가 기대한 config/cwd/response 의미와 달랐다.
   기존 절대 URI fixture만으로는 이 가능성을 배제하지 못한다.
2. 동기 telemetry 저장이나 App Server/proxy/Docker의 종료·pipe 소유 관계가
   초기화 중 protocol 동작에 영향을 줬다. 로그에는 이를 판별할 timing 증거가 없다.
3. 시작 실패 뒤 App Server가 하위 프로세스를 닫거나 중단해 final telemetry가
   기록되지 않았다. 이 경우 child exit null은 원인보다 실패 후의 증거 손실이다.

“응답 1건 누락”과 “stale binding”은 후속 작업의 전제가 될 수 없다. 모델·Codex
버전 변경, mount 확대, 재로그인 역시 현재 증거가 가리키는 우선 해결책이 아니다.

## 4. 다음 작업 계획과 합격 기준

| 순서 | 작업·산출물 | 검증과 완료 기준 | 외부 실행 범위 |
|---|---|---|---|
| 0 | LOG-095 원인 정정, 현재 입력을 새 checkpoint로 고정. remote/tool image 역할을 별도 필드로 표현하거나 profile/binding에서 각각 도출·검증한다. | 기존 binding은 올바른 이미지에서 통과, 잘못된 이미지에서 정확한 input/reason을 반환. 과거 출력은 덮어쓰지 않는다. | 로컬 읽기·문서·fixture |
| 1 | checkpoint·진단 CLI·실제 실행기에 공통 입력 검증을 적용. `stage/input/reason`의 고정 분류를 추가한다. | 잘못된 binding, 비정규 environment, 상대·중복·candidate 내부·기존 출력, symlink 경계, profile 불일치가 모두 subprocess 0회로 차단. 오류 원문에 합성 민감값을 넣어도 콘솔/보고서에 남지 않는다. | 인증·Docker 없는 단위 검사 |
| 2 | 진단 `run()`/CLI 전체를 호출하는 가짜 App Server fixture를 추가. 준비 시작부터 단일 60초 deadline, `finally`부터 cleanup 15초를 공통 적용. 요청/알림·응답 일치·저장 완료·부모/하위 종료를 각각 기록한다. | 지연 준비, notification 폭주, EOF, stderr 폭주, 부모 선종료, 비정상 child, 늦은 final snapshot, 저장 실패에서 시간 상한과 실패 판정 검증. 정상 6 messages/5 responses는 누락으로 분류하지 않음. | 합성 프로세스만 |
| 3 | telemetry 저장을 전달 스레드에서 분리하고 제한된 writer로 병합 저장. 새 증거 계약에는 구버전과 구별되는 schema를 사용한다. | 저장 off/on·느린 저장에서 전달 바이트와 protocol 결과가 같음. 저장 실패가 protocol thread를 죽이지 않고 evidence incomplete로 기록. ID/원문 없이 method별 결과·duration·전송 성공 횟수 보존. | 합성 프로세스만 |
| 4 | pinned remote image의 Docker 경로 비교를 필요한 사례로 확장. root/sub 표식 설정, config/requirements 그룹 순서, 상대/절대/URI, 요청 cwd 생략/지정, 프로세스 cwd 기본/지정을 비교한다. | 잘못된 설정 선택·다른 canonical 경로를 일부러 주입하면 반드시 실패. Linux 직접 요청과 Windows 변환 요청이 기대한 표식·파일·namespace를 선택. 불명확한 필드는 확인 전 임의 역변환하지 않는다. | 네트워크 없는 Docker·빈 시험 홈 |
| 5 | 동일 준비 객체를 실제 smoke에 연결. 필요한 full-runner 인자 누락·오래된 schema·설정 불일치·불완전 cleanup이면 모델 실행 차단. 중복 discovery/preflight를 정리하고 실행별 evidence를 evaluator 소유 보존 위치에 남긴다. | 가짜 실행기로 startup 실패/구버전 보고서/거짓 ready verdict를 주입해 실제 모델 명령 0회 확인. candidate cwd·두 이미지·버전·스킬·instruction 허용 경계가 일치한다. | 모델 없는 통합 시험 |
| 6 | 새 결함의 수정 전후 증거와 최종 checkpoint를 검토한 뒤 실제 구독 startup 재검증. 성공할 때만 승인 범위의 Luna smoke로 진행한다. | 시작·인증·모델 완료·실제 fixed tool/test·보호 파일·사후 경계 증거를 별도 통과. 같은 실패에 새 정보가 없으면 반복하지 않는다. | 아래 실행 예산 적용 |

5단계의 evidence 보존 위치는 candidate/control home과 겹치지 않는 evaluator-owned
실행별 디렉터리다. 현재 source repo의 `.tmp`는 개발 진단 증거로 계속 보존한다.
진단용 instruction 차이를 없애는 과정에서 필요한 Feynman skill을 끄지 않도록
candidate skill discovery와 실제 실행 설정을 함께 비교한다.

개발 중에는 해당 변경 영역의 빠른 회귀만 수행한다. 안정된 묶음에서 전체 suite,
schema, ResourceWarning 검사를 하고 Windows/Linux CI를 확인한다. 실제 Docker
integration은 명시적 opt-in으로 분리하고 timeout을 적용한다. skip은 시험 ID와
사유를 기록하며, 필요한 Windows/Docker 검사의 skip을 성공으로 집계하지 않는다.
현재 `446 tests/11 skipped`는 이전 실행 기록이지 이번의 재검증 수치가 아니다.

### 자율 진행과 실행 예산

0~5단계의 코드·합성 fixture·네트워크 없는 Docker 검증과 정확한 실행 준비는 기존
작업 범위 안에서 진행 가능하다. 이 요청은 분석·계획이므로 이번 턴에서는 구현하지
않았다. 추가 구현 지시 시 이 순서를 따른다.

실제 구독 startup은 LOG-095의 승인 1회가 이미 소진됐다. 다음 실행은 새로 입증한
결함과 회귀 결과, 실행할 최종 checkpoint가 준비된 시점에만 추가 1회 예산을 판단한다.
이는 이 스킬이 추가 승인을 요구해서가 아니라 사용자가 정한 실행 횟수 제한 때문이다.

기존 조건부 Luna smoke 승인 범위는 유지한다. startup과 공식 구독 auth gate가
통과한 뒤 `tools-10 / feynman-v05 / gpt-5.6-luna` 1회, 최대 300초이며 자동
retry·후속 prompt·Terra/Sol fallback은 없다. 검증 실패 시 모델을 시작하지 않는다.
API key나 Platform API, credential 복사, candidate 읽기 범위 확대를 대안으로 삼지 않는다.

## 5. 이번 감사의 실제 명령·결과

읽기 검사는 다음 경로와 패턴으로 수행했다. 보호된 credential 파일은 열지 않았다.

```powershell
git status --short --branch
git log -5 --oneline
git diff aa16305~1 aa16305 --stat
rg --files --hidden -g AGENTS.md -g '!\.git' -g '!\.tmp' -g '!node_modules'
Get-Content -LiteralPath 'docs/feynman-work-log/LOG-095-subscription-startup-gate-revalidation-20260914.md'
Get-Content -LiteralPath 'tooling/feynman_subscription_checkpoint.py'
Get-Content -LiteralPath '.tmp/startup-diagnostic-20260914-v4.json'
Get-Content -LiteralPath '.tmp/startup-diagnostic-20260914-v4-telemetry.json'
Get-Content -LiteralPath '.tmp/feynman-subscription-checkpoint-20260913-v3.json'
rg -n 'requests_seen|pending|child_exit|persist|initialized|join\(' tooling/feynman_rpc_path_proxy.py
rg -n 'skipTest|@unittest.skip|skipUnless|skipIf' tests -g '*.py'
```

추가로 위 근거 파일들의 명시된 코드 구간, 테스트, LOG-083/094, 현재 schema bundle,
CI workflow를 읽었다. Git 샌드박스에서는 전역 ignore 권한 경고가 있었지만 읽기
결과는 얻었다. 출력이 긴 검색은 필요한 코드 구간으로 좁혀 확인했다.

실행 가능한 감사 스크립트:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B '.tmp/log096-review-audit.py'
```

이 스크립트는 subprocess 진입을 mock으로 차단하고, JSON 입력은 메모리에서만
변형한다. 기존 artifact·candidate·로그인 홈을 수정하지 않는다. exit 0, 결과:

```json
{
  "binding_implementation_block_unchanged": true,
  "binding_job_lineage_unchanged": true,
  "initialized_notifications_in_method_count": 1,
  "matched_responses": 5,
  "old_binding_rejected_with_remote_image_as_tool_image": true,
  "old_binding_valid_with_original_tool_image": true,
  "path_comparator_collapses_distinct_codex_subpaths": true,
  "path_comparator_collapses_distinct_external_cwds": true,
  "pending_ids": 0,
  "remote_generator_declares_label": false,
  "remote_generator_declares_workdir": false,
  "remote_generator_uses_profile_digest": true,
  "same_counters_with_zero_exit_pass_readiness": true,
  "startup_rpc_error": -32603,
  "startup_telemetry_ready_as_recorded": false,
  "startup_thread_failed": true,
  "subprocess_calls": 0,
  "validate_only_accepts_candidate_owned_output": true,
  "validate_only_accepts_noncanonical_environment": true,
  "validate_only_accepts_relative_output": true,
  "validate_only_accepts_same_report_and_telemetry": true,
  "wire_messages": 6
}
```

기존 변경 영역 회귀:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -W error::ResourceWarning -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_subscription_checkpoint tests.test_feynman_subscription_startup_diagnostic -q
```

결과: `54 tests`, `OK`, 1.204초, skip 0, ResourceWarning 없음. 실제 Codex,
구독 로그인, Docker integration은 이 묶음에 없다. 이 성공과 입력 검증 공백의
재현이 함께 존재한다는 사실 자체가 현재 시험의 커버리지 한계를 보여준다.

정확한 container의 현재 상태 조회:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B '.tmp/log096-review-audit.py' --docker-state
```

script가 만든 Docker 명령은 `docker --config <empty-config> --host
npipe:////./pipe/docker_engine container inspect
feynman-tool-feynman-remote-compat-20260912-01-gpt-5.6-luna --format
'{{.State.Status}}|{{.State.Running}}|{{.State.ExitCode}}'`이며 timeout 15초다.
wrapper exit 0, Docker CLI exit 1, `exact_container_absent_now=true`, inspect 1회.
삭제·생성은 없었다. 이 결과를 당시의 정상 cleanup 증거로 승격하지 않았다.

```powershell
git ls-remote origin refs/heads/feat/feynman-thinking-v0.5-draft
```

권한 승격한 읽기 전용 조회가 exit 0으로 원격 `aa16305018e33d74777ab3be500ffbac600e77cc`
를 반환했다. 직전 push는 확인됐으며 이번 분석은 새 commit/push를 하지 않았다.

## 완료와 다음 한 행동

이번 분석·계획은 완료다. 미완료 항목은 production 검증/계측/실행기 수정과 실제
시작 실패 원인 규명이다. **다음 구현의 첫 행동은 기존 checkpoint를 기반으로 입력
검증을 공유하고, 이번 감사에서 통과해 버린 잘못된 입력 네 가지를 회귀 시험으로
고정하는 것**이다. 추가 구독 startup을 먼저 수행하지 않는다.
