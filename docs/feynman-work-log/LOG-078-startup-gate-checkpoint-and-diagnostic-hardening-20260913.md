# LOG-078 — Startup gate checkpoint 및 진단기 hardening

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 작업 성격: Windows/Docker subscription startup gate 구현 및 검증
- OpenAI Platform API/API key: 사용하지 않음
- 보호된 ChatGPT control home: 보존, credential/token 원문을 읽거나 저장하지 않음
- 실제 model turn/baseline/evaluation: 0회
- 사용자 PNG 2개: 기존 untracked 상태로 보존하고 stage하지 않음

## 이번 작업의 목적

작업 정체 원인을 입력 검증, RPC 경로 의미, process lifecycle, startup 판정,
실제 executor 연결로 분리했다. 이전 `-15`~`-23` 입력 실패를 remote 실행
실패로 해석하지 않도록 checkpoint 기반 사전 검증을 추가하고, `thread/start`
실패나 telemetry 누락을 성공으로 승격하지 않도록 gate를 강화했다.

## 구현 변경

1. `tooling/feynman_subscription_checkpoint.py`와
   `evals/feynman-thinking/subscription-checkpoint.schema.json`을 추가했다.
   checkpoint에는 절대경로와 고정 Docker `sha256` digest만 들어가며, 입력 파일,
   binding lineage, candidate, 신규 telemetry/output 경로를 subprocess 없이
   검사한다. `--validate-only` 결과에서 `subprocesses_started=0`을 보고한다.

2. `tooling/feynman_rpc_path_mapping.py`를 보강했다. `C:relative` drive-relative
   경로와 traversal을 거부하고, `/run/candidate` mount가 실제 선언된 경우에만
   상대 environment-config path를 허용한다. `cwd`가 있으면 매핑된 environment
   cwd를 기준으로 하며, `file:` URI인 cwd도 올바르게 해석한다.

3. `tooling/feynman_rpc_path_proxy.py` telemetry를 v2로 올렸다. 임의 method명은
   `unknown`으로 제한하고, 실제 write 이후 forwarded를 증가시키며, duplicate ID,
   write failure, notification, matched/unmatched response, pending request를
   payload-free counter로 기록한다. proxy join/wait와 child 정리를 bounded하게
   했다.

4. `tooling/feynman_subscription_startup_diagnostic.py`를 v2로 올렸다. 전체
   timeout deadline, stderr drain, strict telemetry shape/counter 검사,
   response instructionSources shape 검사를 추가했다. thread 성공만으로 green으로
   판정하지 않고 telemetry correlation, mapping rejection 0, pending 0, process
   reap까지 통과해야 `subscription-startup-thread-ready`가 된다. 진단기 실패도
   payload-free blocked artifact를 만들며, artifact 위치가 ACL/sandbox에 막혀도
   traceback을 출력하지 않는다.

5. 실제 `tooling/feynman_subscription_smoke_exec.py`에 fresh model-free startup
   gate를 auth 및 model command보다 앞에 연결했다. startup gate가 통과하지 않으면
   인증 후속 또는 model exec로 진행하지 않는다. smoke result schema에는 startup
   gate와 full-runner binding 상태를 추가했다.

6. `tooling/feynman_skill_tool_wiring_preflight.py`와 control-plane preflight의
   RPC deadline/stderr drain/Windows child cleanup을 보강했다. 문서에는 checkpoint
   사용 순서와 startup gate의 위치를 추가했다.

## 실행 명령과 관찰 결과

### 사전 확인

실행:

```powershell
Get-ChildItem -Recurse -Filter AGENTS.md
git status --short --branch
git log -5 --oneline
```

관찰:

- 적용되는 `AGENTS.md`는 없었다.
- branch는 `feat/feynman-thinking-v0.5-draft`이며 시작 HEAD는 `5f25260`이었다.
- 기존 사용자 PNG 2개만 untracked였고 보존했다.

### 오프라인 검증

실행:

```powershell
python -B -m unittest discover -s tests -q
python -B -c "jsonschema로 subscription schema 검사"
python -B -m compileall -q tooling tests
python -B -m tooling.feynman_subscription_startup_diagnostic --checkpoint <local-checkpoint> --validate-only
```

관찰:

- 최종 전체 suite: `399 tests OK, 11 skipped`.
- subscription schema 5개: `errors=0`.
- `compileall`: exit code `0`.
- checkpoint: `subscription-checkpoint-valid`, `binding_valid=true`,
  `subprocesses_started=0`, `authentication_material_present=false`.
- 영향을 받은 경로/proxy/startup/checkpoint/smoke 묶음은 최종 `72 tests OK`였다.

### Windows/Docker model-free startup 확인

새 checkpoint와 새 계측으로 startup 확인을 수행했다. 첫 확인은
`initialize` 응답 대기에서 `thread-start-timeout`, exit code `1`로 종료됐다.
그 뒤 실패 artifact 저장을 보강한 확인에서는 같은 초기화 timeout이 재현됐고,
원래 evaluator 출력 경로가 현재 sandbox의 쓰기 범위 밖이라 blocked artifact
저장 시 ACL 오류가 추가로 관찰됐다. 이 두 실행 이후에는 동일 startup을 반복하지
않았다. 현재 확인은 `thread/start` 성공이나 remote lifecycle green을 증명하지
않으며, 실제 model/turn은 0회다.

검증 중 남은 process는 확인되지 않았다. raw stderr, JSON-RPC payload, credential
파일, token, 전체 환경변수는 읽어 저장하지 않았다.

## 판정

- 입력 checkpoint, binding, 경로 contract, telemetry shape, process cleanup,
  executor fail-closed 연결은 코드 및 오프라인 테스트로 보강됐다.
- 실제 startup gate는 현재 `initialize` 단계 timeout으로 blocked다. `thread/start`
  원격 lifecycle의 최종 원인은 아직 확정하지 않는다.
- startup 선행 조건이 통과하지 않았으므로 ChatGPT auth 재검증과 Luna model-turn,
  baseline/Feynman evaluation은 수행하지 않았다.
- Terra/Sol fallback, Linux control-plane 전환, mount 확대, force push, main merge는
  하지 않았다.

## 커밋·push·미완료

- 이 로그 작성 시점의 code/docs commit 및 push는 아직 수행하지 않았다.
- 다음 작업은 새 startup을 반복하는 것이 아니라, timeout 단계의 원인을 구분할 수
  있는 오프라인 fake App Server/child lifecycle fixture와 실제 실행기의 동일-context
  검증을 추가하는 것이다. 그 fixture가 통과하고 필요 시 새 가설이 생겼을 때만
  별도 승인된 model-free 확인을 1회 계획한다.
