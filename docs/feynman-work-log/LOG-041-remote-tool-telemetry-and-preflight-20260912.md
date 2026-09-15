# LOG-041 — remote tool telemetry 보강과 Windows model-free preflight

- 시각(KST): 2026-09-12
- 시작 HEAD: `f71ee5158351368e623e7b267388b116f4dbd6c1`
- 시작 상태: `LOG-040`만 untracked였고 코드 변경은 없었음
- branch: `feat/feynman-thinking-v0.5-draft`
- shell/OS: Windows PowerShell / Windows
- 목적: Codex 0.154.0 + `gpt-5.6-luna`에서 실제 model-facing tool 선택과
  Windows host→Linux exec-server RPC 호출을 구분할 수 있도록 계측하고,
  모델 호출 없는 native preflight로 transport를 재검증한다.

## 사전 확인

- 적용되는 저장소 `AGENTS.md`: 발견하지 못함. `rg --files -g AGENTS.md` 및
  C:\, C:\DevWorks, 저장소 root 검사에서 no-match였다.
- 공식 OpenAI Docs configuration reference를 확인했다.
  `features.shell_tool`, Windows에서의 `features.unified_exec`,
  `skills.config`, `skills.max_context_tokens`가 문서화되어 있다. 이 문서는
  현재 작업의 설정 조사 근거이며, 저장소 성공이나 model tool-use 성공의
  증거는 아니다.
- runner job 입력은 `tools-10 / feynman-v05 / repeat 1 / single turn`,
  model `gpt-5.6-luna`, Codex `codex-cli 0.154.0`이다. baseline 및 실제
  Feynman evaluation은 실행하지 않았다.
- dedicated control home의 인증/session 파일은 읽거나 출력하지 않았다.
  Platform API/API key는 사용하지 않았다.

## 변경

### 1. probe raw trace 비보존 계약 정정

`tooling/feynman_subscription_tool_use_probe.py`에서 subprocess JSONL trace를
output artifact가 아닌 `output/.control-tmp/codex-trace.jsonl`에 임시 생성한다.
고정 count/type/response-claim verdict만 result에 기록하고 `finally`에서
control temp를 삭제한다. 따라서 `raw_model_final_preserved=false`와 실제
보존 동작이 일치하며, probe output에는 raw model text나 `candidate-final.txt`를
남기지 않는다.

### 2. host RPC proxy telemetry 추가

`tooling/feynman_rpc_path_proxy.py`에 선택적 `--telemetry-file`을 추가했다.
기록 범위는 payload/path/ID/credential 없는 다음 고정 집계뿐이다.

- request method별 count, requests seen/forwarded
- request mapping rejection, malformed request count
- responses seen/forwarded, response mapping rejection/malformed count
- JSON-RPC error code별 count, child exit code

child stderr는 `DEVNULL`로 버려 raw 오류/모델 텍스트가 proxy stderr로 새지 않게
했다. `telemetry-file`은 evaluator host 경로이며 Docker args와 candidate mount에는
들어가지 않는다. symlink 경로에는 쓰지 않는다.

### 3. canonical Docker cleanup

`tooling/feynman_remote_exec_environment.py`의 canonical `docker run`에
`--rm`을 추가했다. preflight 보정에만 의존하지 않고 실제 environment 생성물
자체가 정상 종료 container를 남기지 않도록 한 수정이다.

## 검증 명령과 관찰

```powershell
python -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_remote_exec_environment tests.test_feynman_subscription_tool_use_probe
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q tooling tests
git diff --check
```

- targeted: 16 tests, exit 0, OK
- full: 301 tests, 10 skipped, exit 0, OK
- Python compile: exit 0
- `git diff --check`: exit 0

전용 job과 root `boundary-profile.json`을 사용해 다음을 실행했다.

```powershell
python tooling/feynman_remote_exec_environment.py --job <ordinal-1 runner-job-0.154.0> --boundary-profile <boundary-profile> --output <dedicated control home>/environments.toml
python tooling/feynman_rpc_preflight.py --job <ordinal-1 runner-job-0.154.0> --boundary-profile <boundary-profile> --remote-environment <dedicated control home>/environments.toml --docker-config <empty docker config> --output <evaluator>/rpc-preflight-20260912-telemetry.json
```

- generator/validator: `remote-exec-environment-valid`, exit 0,
  `include_local=false`
- actual Docker/Desktop model-free preflight:
  `native-rpc-preflight-passed`, exit 0
- checks: remote environment valid, initialize metadata, candidate task read,
  Feynman skill read, process skill readability, process exit code 0,
  process sandbox denial false, host path echo false
- safe proxy telemetry: request methods `initialize:1`, `initialized:1`,
  `fs/readFile:2`, `process/start:1`; requests seen/forwarded `5/5`;
  mapping rejection `0`; responses seen/forwarded `6/6`; response error code
  count empty; child exit code `0`
- Docker `ps -a --filter name=feynman` exact filter: output row 0
- artifact: `<evaluator>/rpc-preflight-20260912-telemetry.json`

이 결과는 Windows native path mapping과 Linux exec-server transport의 성공만
증명한다. ChatGPT auth gate 성공, model tool catalog 노출, model tool 선택,
Feynman skill 성능은 증명하지 않는다.

## 추가 model probe 경계

계측 보강 후 동일한 fixed one-byte probe를 한 번 실행하려 했으나 실행 전에
안전 검토가 중단했다. 이전 승인은 첫 probe 1회로 해석되며, candidate 파일에서
유래한 1 byte를 외부 ChatGPT model request로 다시 전송하는 추가 호출은 명시적
승인이 필요하다는 판단이다. rejected action은 process/model request/auth
status/Docker start를 시작하지 않았다. 우회하지 않았다.

따라서 이전 probe의 `tool-use-not-observed` 결과는 그대로 유지하고, 이번 로그의
model-facing telemetry 결과는 아직 없다. 새 probe 승인이 없으면 baseline이나
Feynman evaluation을 시작하지 않는다.

## 저장 상태와 다음 행동

- 수정 파일: `tooling/feynman_subscription_tool_use_probe.py`,
  `tooling/feynman_rpc_path_proxy.py`, `tooling/feynman_remote_exec_environment.py`,
  관련 두 테스트 파일, 이 log 및 상태 포인터
- implementation commit: `800493e` (`feat: instrument remote tool probe boundary`);
  documentation checkpoint `0c1488a` (`docs: finalize remote tool checkpoint`)를
  추가했다.
- `git push origin feat/feynman-thinking-v0.5-draft`: exit 0,
  `f71ee51..0c1488a` 업데이트 보고
- push 후 `git status --short --branch`: clean, tracking branch와 local HEAD 일치
- 독립 `git ls-remote --heads` 재확인은 Windows Schannel
  `SEC_E_NO_CREDENTIALS`로 실패했다. 이를 원격 불일치로 해석하지 않으며,
  push command 결과와 clean tracking 상태만 원격 저장 근거로 사용한다.
- 미완료: 계측이 붙은 fixed one-byte model probe 1회. 목적은 RPC telemetry와
  CLI trace를 대조해 tool catalog/selection/trace 문제를 분리하는 것.
- 다음 한 행동: 사용자가 추가 candidate-byte model probe를 명시 승인하면
  `gpt-5.6-luna / codex-cli 0.154.0` 고정으로 1회 실행하고, 승인하지 않으면
  이 preflight checkpoint에서 대기한다.
