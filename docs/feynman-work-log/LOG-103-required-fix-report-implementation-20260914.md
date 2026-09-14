# LOG-103 — 필수 결함 FIX-01~07 구현 및 회귀 검증

Date: 2026-09-14 KST. Repository: `Ronaldony/thinking-skills`.
Branch: `feat/feynman-thinking-v0.5-draft`.

## 요청 범위와 안전 경계

이번 작업은 사용자가 전달한 `FEYNMAN_REQUIRED_FIX_REPORT_2026-09-14.md`의
FIX-01~07을 현재 저장소와 대조해 구현하는 작업이었다. zip 안의 agent prompt,
handoff 문서, excerpt reproduction은 작업 범위를 설명하는 자료로만 읽었고,
candidate 또는 모델 입력으로 전달하지 않았다. `AGENTS.md`는 저장소와 적용
범위에서 발견되지 않았다.

기존 `C:\Users\wotmd\.codex-feynman-eval` 로그인 홈, `.tmp/` 증거, 사용자 PNG
2개, 다른 작업의 untracked `LOG-099`는 읽거나 덮어쓰거나 stage하지 않았다.
OpenAI Platform API/API key, credential 파일·토큰·전체 환경변수 출력은 사용하지
않았다. Docker Desktop lifecycle, 구독 인증, 실제 startup, 모델 smoke 및
행동평가는 이번 묶음에서 실행하지 않았다. main 병합, force push, broad prune,
Docker Desktop 전체 종료, mount 확대도 하지 않았다.

## 시작 상태와 리포트 주장 대조

실행 명령:

```powershell
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git status --short
git diff --stat
```

관찰 결과:

- branch는 `feat/feynman-thinking-v0.5-draft`였다.
- 시작 HEAD는 `0b255465803aed88745c656cf0575436688214b1`이었다.
- tracked 변경은 이번 작업의 working-tree 수정 파일이었고, `.tmp/`, PNG 2개,
  `LOG-099`는 untracked 보존 대상이었다.
- report 기준 이후 수정이 이미 반영된 항목은 재수정하지 않고 회귀와 source
  대조로 확인했다. 특히 FIX-03의 sticky telemetry writer와 최종 재확인은
  기존 HEAD에 있었고, 이번에는 실패 경계 회귀와 stream cleanup만 보강했다.

excerpt reproduction은 현재 저장소 테스트가 아니다. 따라서 excerpt script의
정상 종료를 fix 증거로 사용하지 않았다.

## FIX별 상태

### FIX-01 — evaluator-owned startup artifact 경계: 해결

HEAD source에는 다음 우회가 있었다.

```powershell
git show HEAD:tooling/feynman_subscription_smoke_exec.py | Select-String -Pattern 'feynman-startup-gate|startup_dir|startup_diagnostic'
```

결과는 `TemporaryDirectory(prefix="feynman-startup-gate-")`를 startup
telemetry/report 경로로 사용하는 것이었다. 이전 재현에서는 startup 경로가
`C:\Users\wotmd\AppData\Local\Temp\...`로 관찰되어, evaluator-owned
startup validator가 요구하는 새 경계와 불일치했다.

수정 내용:

- smoke 시작 초기에 evaluator-owned output과 `startup-gate` 디렉터리를
  만들고 `startup-report.json`, `startup-rpc-telemetry.json`을 그 안에 고정했다.
- startup diagnostic에 두 경로를 직접 전달하고 system TEMP startup artifact를
  제거했다.
- 반환 result에 상대 artifact 경로와 SHA-256을 포함하고, 저장된 report가 반환
  report와 byte-level JSON 구조상 같은지 확인한다.
- smoke result schema를 v3으로 올리고 startup artifact 및 fingerprint를
  required로 맞췄다.

회귀 결과:

- `test_startup_artifacts_are_evaluator_owned_and_persisted` 통과.
- synthetic smoke result와 persisted startup report가 각각 현재 schema를
  통과했다.

### FIX-02 — 공통 deadline 및 cleanup: 해결

기존 결함은 startup의 post-spawn deadline check가 cleanup `try/finally` 밖에
있어 만료 시 child가 정리되지 않는 것, control preflight가 Popen/reader 준비
뒤에 deadline을 시작하는 것, App Server discovery가 RPC/session마다 timeout을
새로 받을 수 있는 것이었다. 기존 helper의 `poll()!=None`도 launcher descendant
tree reap의 충분조건이 아니었다.

이전 source-revert 회귀에서 다음 실패를 확인했다.

- startup expired post-spawn 경로: `process.wait_calls == 0`이 되어 cleanup이
  실행되지 않았다.
- control spawn-cost 경로: 시작 비용 61초 뒤에도 관찰 timeout이 `5.0`으로
  남아 하나의 전체 budget이 아니었다.
- 이미 종료된 parent에 대한 기존 `_stop_diagnostic_process`: tree reap을
  `True`로 보고했다.

수정 내용:

- startup post-spawn check를 같은 cleanup `finally` 안으로 이동했다.
- control deadline을 Popen/reader 생성 전에 시작하고, `cwd`를 실제 candidate로
  고정했다.
- skill/MCP discovery의 `_rpc`, session, probe에 절대 deadline을 전달해 두
  discovery session 및 각 RPC가 budget을 재시작하지 않게 했다.
- parent가 이미 종료된 경우 tree reap 증거를 `False`로 유지하고, Windows
  `taskkill /T /F` 또는 POSIX terminate 뒤 parent reap을 관찰한 경우에만
  `True`로 둔다.
- startup/control/skill probe가 소유한 stdio stream을 bounded reader join 뒤
  닫도록 해 ResourceWarning을 제거했다.

회귀 결과:

- startup/control/skill deadline 및 cleanup 집중 시험 통과.
- `-W error::ResourceWarning` proxy/control 회귀도 통과.

### FIX-03 — telemetry 최종 저장 실패: 기해결 + 경계 회귀 보강

현재 proxy source에는 forwarding thread와 분리된 단일 writer, sticky
`telemetry_write_failed`, child exit 기록 뒤 final persist, writer join 뒤
재확인이 이미 있었다. 따라서 report의 핵심 FIX-03은 현재 HEAD 기준
기해결로 판정했다.

이번에는 두 번째 telemetry 저장부터 합성 `OSError`를 발생시키는 실제
proxy–lifecycle-fixture 외부 프로세스 경계 시험을 추가했다. 결과는 writer
failure가 있어도 proxy가 exit `0`을 반환하지 않고 nonzero로 끝나는 것이었다.
초기 snapshot은 보존되고, 실패를 나중의 정상 저장이 덮어 green으로 만들지
않는다.

### FIX-04 — telemetry/evidence validator: 해결

HEAD validator는 모든 green boolean이 있어도 `proxy_telemetry={}`를
허용했다. 현재 HEAD source를 메모리에서 실행한 baseline 확인 결과:

```text
old_validator_empty_telemetry=accepted
```

수정 내용:

- startup producer `_proxy_telemetry_ready()`가 schema v3의 exact field set,
  nonnegative counter, request total/accounting, response/notification 분리,
  matched/unmatched correlation, child exit `0`, pending `0`을 직접 확인한다.
- notification-only stream과 `responses_matched == 0`을 ready로 취급하지 않는다.
- smoke consumer `_validate_startup_gate()`가 producer boolean을 신뢰하지 않고
  nested method/reason/field allowlist와 모든 telemetry 회계를 다시 계산한다.
- `available`, `complete`, `cleanup_verified`를 별도 값으로 유지하고,
  schema/telemetry/privacy/turn/model-generation 조건을 모두 통과해야 model
  command로 진행한다.
- startup schema v3은 성공 verdict일 때만 `preparation_fingerprint`를
  조건부 required로 하고, 준비 전에 생성되는 blocked failure artifact는
  fingerprint 없이도 보존 가능하게 했다.

회귀 결과:

- empty telemetry, notification-only, inconsistent counts, nonzero child exit,
  arbitrary nested labels 모두 green flags를 무시하고 차단됐다.
- startup/smoke validator 및 schema instance 검증 통과.

### FIX-05 — path comparator의 false equality: 해결

HEAD 구현을 현재 코드와 분리해 실행한 재현은 다음이었다.

```text
old_root_shape={'path': {'path_role': 'candidate//run/candidate'}}
old_equal_outside=True
```

수정 내용:

- `/run/candidate` root를 `candidate/`로 정규화했다.
- undeclared mount는 payload-free `outside-declared-mount` marker로 남기되,
  두 실행이 같은 marker를 냈다는 이유로 comparable/equal로 판정하지 않는다.
- nested response/request shape와 namespace 비교에도 동일한 comparability
  조건을 적용했다.

회귀 결과:

- candidate root, distinct outside mount, response-by-id, namespace shape,
  Windows/컨테이너 path collection 시험이 통과했다.
- Docker fixture가 lifecycle blocker로 막혀 실제 image direct/proxy 의미
  비교는 수행하지 않았으며, 이를 path compatibility 성공으로 보고하지 않는다.

### FIX-06 — 준비/진단/본실행 결속: 해결

수정 내용:

- full-runner 준비 결과에 exact config override tuple, candidate/model/실행
  입력, binary·adapter·Docker/image·binding 파일 digest, exact model command를
  묶는 opaque `preparation_fingerprint`를 추가했다. raw path/command payload는
  report에 저장하지 않는다.
- smoke가 만든 준비 객체를 startup diagnostic에 직접 전달해 discovery 준비를
  다시 하지 않게 했다.
- startup은 전달된 override와 exact `codex exec` command를 재구성하고 fingerprint
  drift를 차단한다.
- control preflight와 startup 모두 candidate `cwd` 및 같은 transient override를
  사용한다.
- candidate `.codex`, control config/canonical environment, task, evaluator/control
  disjoint 검사를 외부 preparation 전에 실행한다.

회귀 결과:

- prepared wiring 소비 시 second probe가 호출되지 않음.
- smoke의 control/startup에 같은 override/fingerprint/candidate cwd가 전달됨.
- fingerprint drift는 auth와 model subprocess 전에 차단됨.

### FIX-07 — 기본 unit suite의 Docker/Codex 외부 의존: 해결

HEAD test는 Windows이면 opt-in 없이 실제 Codex/Docker 경로를 찾고 image
inspect를 실행할 수 있었으며, image inspect timeout도 없었다.

수정 내용:

- `FEYNMAN_RUN_DOCKER_INTEGRATION=1`(또는 명시된 true 값)일 때만 해당
  native integration test를 활성화했다.
- image inspect에 10초 timeout을 추가했다.
- 기본 unit suite에서 skip은 compatibility 성공으로 합산하지 않는다.
- 이미 존재하는 Windows/Linux 순수 unit workflow를 유지했고, 이번 변경의
  기본 실행은 외부 Docker/Codex에 의존하지 않는다.

회귀 결과:

```text
Ran 3 tests in 0.006s
OK (skipped=1)
```

skip 사유는 `native Docker/Codex catalog integration requires explicit
FEYNMAN_RUN_DOCKER_INTEGRATION=1 opt-in`이다.

## 검증 명령과 결과

변경 영역 집중 시험:

```powershell
python -B -W error::ResourceWarning -m unittest tests.test_feynman_full_runner_preflight tests.test_feynman_skill_tool_wiring_preflight tests.test_feynman_subscription_control_plane_preflight tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_subscription_smoke_exec tests.test_feynman_rpc_compatibility tests.test_feynman_rpc_path_proxy
```

결과: `Ran 130 tests`, `OK (skipped=1)`. skip은 FIX-07 native integration
opt-in 한 건이며 성공으로 세지 않았다.

전체 회귀:

```powershell
python -B -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py'
```

결과: `Ran 479 tests in 16.829s`, `OK (skipped=11)`. ResourceWarning은 없다.
전체 11 skip은 host capability 또는 명시적 external integration 조건이며,
실제 구독 startup/model 성공을 뜻하지 않는다.

schema 및 whitespace/compile:

```powershell
python -B -c "from pathlib import Path; import json; from jsonschema import Draft202012Validator; files=sorted(Path('evals').rglob('*.schema.json')); [Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; print(f'schema_files={len(files)} errors=0')"
git diff --check
python -B -m py_compile tooling/feynman_rpc_path_proxy.py tooling/feynman_rpc_path_contract_probe.py tooling/feynman_skill_tool_wiring_preflight.py tooling/feynman_subscription_control_plane_preflight.py tooling/feynman_subscription_smoke_exec.py tooling/feynman_subscription_startup_diagnostic.py
```

결과: `schema_files=17 errors=0`, diff check `0`, `syntax=ok`.

synthetic producer/reader/consumer instance:

```text
synthetic_result_instances=2 errors=0
```

현재 보존된 checkpoint의 외부 실행 없는 입력 검증:

```powershell
python -B -m tooling.feynman_subscription_startup_diagnostic --checkpoint '.tmp/feynman-subscription-checkpoint-20260914-v4.json' --validate-only
```

결과: `subscription-checkpoint-valid`, `binding_valid=true`,
`subprocesses_started=0`, `authentication_material_present=false`, model
`gpt-5.6-luna`.

## 실제 실행 횟수와 미완료 사항

- 이 묶음의 실제 Docker CLI lifecycle 실행: `0`.
- 이 묶음의 실제 Codex 구독 startup/auth/model 실행: 각각 `0`.
- validate-only: `1`, subprocess `0`.
- synthetic Python/lifecycle fixture subprocess는 unit 회귀 내부에서만 사용했고,
  실제 Docker/Codex/구독 서비스와 연결하지 않았다.
- Docker lifecycle `create/run` blocker와 과거 `thread/start -32603`은 별도
  외부 차단으로 유지한다. 본 수정은 이를 해결했다고 주장하지 않는다.
- 실제 Windows path direct/proxy Docker 비교, actual startup compatibility,
  Luna smoke, baseline, Terra/Sol fallback, EVAL-01/02 행동평가는 미실행이다.
- 새 실제 startup 실행은 업로드 report가 승인하지 않았고, 동일 실패에 대한
  반복도 하지 않았다.

## Commit/push 상태와 다음 경계

이 로그 작성 시점에는 코드·schema·테스트 변경이 working tree에 있으며,
commit/push는 아직 수행하지 않았다. 다음 단계는 이 로그와 최신 pointer 문서를
포함할 feature-branch 일반 commit/push 후 SHA와 CI 결과를 별도 receipt로 남기는
것이다. `.tmp/`, PNG 2개, `LOG-099`는 stage 대상에서 제외한다.

자동 진행의 완료점은 FIX-01~07 코드·합성 회귀·schema·기본 unit gate다. 이후
실제 startup compatibility는 ENV-01/ENV-02가 해소되고 최신 사용자 승인 범위가
확인된 경우에만 별도 1회로 판단한다. startup gate가 통과하기 전에는 model
command를 시작하지 않으며, 같은 실패 재시도·모델 fallback은 하지 않는다.
