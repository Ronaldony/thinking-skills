# LOG-100 — 자동 gate·telemetry·경로 비교 보강 (2026-09-14)

## 요청과 안전 범위

이번 묶음은 사용자가 승인한 자동 진행 계획의 A~D 구현을 진행한 것이다. 기존
ChatGPT 구독 로그인 홈 `C:\Users\wotmd\.codex-feynman-eval`, 사용자 PNG 2개,
`.tmp/` 증거를 보존했다. OpenAI Platform API/API key, 인증 파일·토큰·전체 환경변수
출력, 실제 구독 startup, 모델 smoke/evaluation은 사용하지 않았다. 개발 대화와
인계 문서는 candidate 입력으로 전달하지 않았다.

## 시작 상태 확인

실행 명령:

```powershell
git status --short --branch
git log -3 --oneline
rg -n "def execute_smoke_job|full_runner|subprocess\.run|startup_gate|def _run|def test_" tooling/feynman_subscription_smoke_exec.py tests/test_feynman_subscription_smoke_exec.py tooling/feynman_subscription_startup_diagnostic.py tests/test_feynman_subscription_startup_diagnostic.py
```

관찰 결과:

- 브랜치 `feat/feynman-thinking-v0.5-draft`, 시작 HEAD `86177c8`.
- tracked 변경은 없고 `.tmp/`, PNG 2개, 이전 미커밋 로그 `LOG-099`만 untracked였다.
- 적용되는 `AGENTS.md`는 이전 확인과 이번 상태에서 발견되지 않았다.
- smoke API에는 full-runner 입력이 선택적이고, 모두 없을 때
  `not-run-no-full-runner-binding` sentinel 뒤 auth와 일반 `codex exec`로 진행하는
  우회가 있었다.
- startup 직접 API는 CLI checkpoint 검증을 호출하지 않았고, 개별 인자 CLI도
  실행 모드에서 공통 validator를 거치지 않았다.

## 구현 내용과 이유

### A. 입력·gate 연결

- `feynman_subscription_checkpoint.from_run_inputs()`를 추가해 직접 API가 CLI와
  같은 1개 비밀정보 없는 checkpoint shape를 만들게 했다.
- startup `run()`은 `validate_checkpoint()`를 `Popen` 이전에 호출한다. evaluator
  경계, canonical control home/environment, binding identity, 새 출력 경로,
  정규 파일·디렉터리를 같은 contract로 검사한다.
- 개별 인자 CLI도 checkpoint form과 같은 공통 검증 결과를 사용한다.
- `tools-10` smoke의 full-runner binding·Node·adapter·Docker·config·image digest
  입력은 전부 필수다. 하나라도 없으면 auth와 모델 subprocess 전에 고정 오류로
  중단한다.
- 더 이상 성공 결과에 `not-run-no-full-runner-binding`을 허용하지 않도록 smoke
  result schema를 `subscription-startup-thread-ready` const로 좁혔다.
- checkpoint Docker digest는 단순 길이가 아니라 `sha256:` 뒤 정확히 64자리
  lowercase hex인지 검사한다. evaluator 밖의 새 출력, 파일인 조상 디렉터리,
  symlink/junction 조상, telemetry/output 경로 중첩도 거부한다.

### B. 종료·계측 증거

- startup diagnostic의 준비부터 handshake까지 최대 60초의 단일 deadline을
  사용하고, 준비 후 deadline이 만료되면 `Popen` 전에 차단한다. cleanup 15초는
  `finally`에 진입한 뒤 별도로 시작한다.
- control-plane preflight의 initialize와 environment/info도 각 요청마다 timeout을
  재시작하지 않고 공유 deadline을 사용한다. cleanup deadline은 `finally`에서
  시작한다.
- startup telemetry reader는 `response_error_codes`의 key를 숫자 RPC code 형식으로
  제한한다. 요청·응답이 0건인 snapshot은 child exit 0이어도 ready가 아니다.
- RPC proxy는 forwarding worker가 직접 `fsync/replace`하지 않고 단일 telemetry
  writer thread에 최신 snapshot 저장을 알린다. writer 실패는 sticky 상태가 되고
  최종 proxy exit를 비정상으로 만든다. 초기 snapshot은 child launch 전에 한 번
  동기 저장해 partial evidence 경로를 남긴다.

### C. 경로 의미 비교

- path contract probe에서 `/run/home`, `/run/codex`, `/run/temp` 하위 경로를
  모두 `/...`로 축약하던 문제를 수정했다. 이제 mount identity와 suffix SHA-256을
  비교하므로 서로 다른 설정·파일을 같은 결과로 오인하지 않는다. 원래 suffix는
  report에 저장하지 않는다.

### D. 실제 실행기 결속

- smoke executor는 항상 full-runner wiring → control-plane preflight → fresh
  startup diagnostic → auth → model exec 순서로 간다.
- startup gate 소비부는 verdict와 model-generation 0뿐 아니라 initialize 완료,
  ephemeral thread, 허용 instruction source, process reap, cleanup verified,
  telemetry complete/correlated, mapping clean, turn 0, RPC error 없음,
  telemetry available를 모두 확인한다.
- 테스트 fixture는 선택적 full-runner 누락을 묵인하지 않고, 합성 wiring·control
  preflight·startup gate를 명시적으로 공급하도록 바꿨다. 이는 실제 인증·모델 실행이
  아니라 실행 순서와 차단 조건만 검증한다.

## 검증 명령과 관찰 결과

1. 첫 변경 뒤 집중 시험:

```powershell
python -B -W error::ResourceWarning -m unittest tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_subscription_smoke_exec
```

처음에는 기존 synthetic telemetry가 요청·응답 0건이라 새 readiness 조건과 충돌했고,
그 fixture를 실제 initialize/thread-start 교환을 나타내는 2 request/2 response로
보정했다. 이후 `52 tests OK`.

2. checkpoint·startup·proxy·smoke 집중 시험:

```powershell
python -B -W error::ResourceWarning -m unittest tests.test_feynman_subscription_checkpoint tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_subscription_control_plane_preflight tests.test_feynman_subscription_smoke_exec
```

한 번은 readiness 조건을 추가하는 중 `and` 누락으로 `py_compile` SyntaxError가
발생했으나 즉시 수정했다. 수정 후 `68 tests OK`.

3. proxy·path comparator까지 포함한 변경 영역 시험:

```powershell
python -B -W error::ResourceWarning -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_rpc_compatibility tests.test_feynman_subscription_checkpoint tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_subscription_control_plane_preflight tests.test_feynman_subscription_smoke_exec
```

결과: `116 tests OK`.

4. 전체 회귀:

```powershell
python -B -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py'
```

최종 결과: `Ran 461 tests in 17.990s`, `OK (skipped=11)`. `ResourceWarning`은
발생하지 않았다. 전체 suite의 skip 11개는 성공으로 합산하지 않았다. 이 suite는
환경에 따라 실행되는 Windows catalog preflight를 포함하지만, 이번 결과에서 실제
구독 auth/startup/model smoke를 실행했다는 의미는 아니다.

5. schema 자체 검사 및 diff:

```powershell
python -B -c "from pathlib import Path; import json; from jsonschema import Draft202012Validator; files=sorted(Path('evals').rglob('*.schema.json')); [Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; print(f'schema_files={len(files)} errors=0')"
git diff --check
```

결과: `schema_files=17 errors=0`, diff check exit 0. Git이 CRLF 변환 가능성을
알린 것은 경고이며 patch 오류는 아니었다. Git global ignore 접근 권한 경고도
작업 파일·인증 상태와 무관한 로컬 환경 경고로 기록한다.

## 검증 범위의 한계

- Docker direct/proxy path contract의 실제 이미지 비교와 설치된 Codex의 실제
  `thread/start`는 이번 묶음에서 실행하지 않았다. path comparator는 순수 fixture로
  서로 다른 non-candidate mount suffix가 충돌하지 않는지만 검증했다.
- proxy writer의 실제 Windows 실패 ACL을 재현하지 않았고, sticky failure와
  forwarding 비간섭은 코드·기존 subprocess fixture 회귀로만 확인했다.
- 실제 `thread/start -32603`의 최종 원인은 여전히 확정되지 않았다. 이번 변경은
  입력·증거·실행기 우회를 제거했을 뿐, 성공으로 가장하던 진단 경로를 닫은 것이다.
- 새 startup diagnostic은 `run()` 직접 호출에서도 checkpoint validation을 수행하므로
  기존보다 엄격하다. 실제 구독 실행을 다시 시작할 근거로는 아직 충분하지 않다.

## Git·push 상태

이 로그 작성 시점에는 코드·schema·테스트 변경이 아직 working tree에 있고,
commit/push는 수행하지 않았다. `.tmp/`, 사용자 PNG, 기존 로그인 홈은 stage 대상에서
제외한다. 다음 단계는 `git diff --check`와 변경 영역/전체 회귀 결과를 재확인한 뒤
현재 feature branch에 일반 commit 및 push하는 것이다. main 병합과 force push는 하지
않는다.

## 다음 행동과 사람 개입 경계

commit/push 후에는 최신 원격 SHA와 CI 상태를 기록하고, 실행 설정에 full-runner
binding·두 image digest·Codex version·candidate/evaluator/control 경계를 한 번만
고정한다. 그 다음에만 이전에 승인된 범위의 **새 구독 startup diagnostic 1회**를
사람 경계로 검토한다. 같은 입력·같은 실패·새 증거 없음이면 반복하지 않는다.

startup이 통과할 때만 `tools-10 / feynman-v05 / gpt-5.6-luna` smoke 1회, 최대
300초를 별도 승인 범위로 이어가며 Terra/Sol fallback·자동 재시도·baseline 비교는
하지 않는다. startup이 실패하면 모델을 실행하지 않고 새 payload-free 증거와 남은
가설만 기록한다.
