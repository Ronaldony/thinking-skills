# 로컬 Codex에 붙여넣을 작업 재개 프롬프트

> 현재는 `docs/feynman-work-log/LOG-063-model-free-startup-reason-diagnostic-20260913.md`를
> 먼저 읽어라. payload-free reason telemetry와 ephemeral `thread/start` 진단기는
> 구현됐다. 첫 model-free run은 host path를 remote-native cwd에 넣어 `-32603`으로
> 끝났고, `/run/candidate` 보정 후 재실행은 automatic approval review에서 시작 전
> 거부됐다. 전체 371 tests/11 skipped는 통과했다. 사용자가 보정된 model-free
> startup diagnostic 정확히 1회를 명시 승인하기 전에는 실행하지 마라.
> 아래 재개 안내는 역사 기록이다.

> 현재는 `docs/feynman-work-log/LOG-062-luna-config-metadata-rejections-20260913.md`를
> 먼저 읽어라. 승인된 Luna 1회는 exit 1/0-byte trace로 종료됐고 config 1건,
> metadata 8건의 mapping 거부를 확인했다. fs/walk mapping 거부는 없다.
> 모델 호출 부재를 단정하지 마라. CI는 전체 SHA로 조회하고 Linux 경로 fixture
> 보정 결과를 확인하라. 다음은 model-free 원인 분류이며 자동 모델 재호출은 없다.
> 아래 재개 안내는 역사 기록이다.

> 2026-09-13 최신 재개 지점: 먼저
> `docs/feynman-work-log/LOG-061-request-mapping-method-diagnostics-20260913.md`를 읽어라.
> model-free discovery diagnostic에서 ordinary `fs/walk` candidate path는
> Windows→Linux mapping 후 child까지 전달됐고 server의 synthetic `options`
> 누락 오류를 반환했다. guarded mode는 bounded allowlist로 거부됐다. method별
> payload-free rejection counter와 `fs/walk.path` mapping은 구현·회귀 검증됐다.
> 전체는 `364 tests OK, 11 skipped`다. 새 model-turn/retry/fallback/Terra/Sol/
> baseline은 실행하지 않는다.
>
> 직전 지점:
> `docs/feynman-work-log/LOG-060-luna-model-turn-request-mapping-blocker-20260913.md`.
> LOG-059 control-plane은 통과했지만 새로 승인된 Luna model-turn 1회는 모델 요청
> 전에 startup request mapping 9건 거부로 exit 1/0-byte trace가 됐다. Docker child
> exit 0, response mapping rejection 0이다. 같은 model command를 반복하지 말고,
> `environmentConfig/read`, `fs/canonicalize`, `fs/getMetadata`, `fs/walk`의
> per-method request rejection을 model-free로 먼저 계측하라.
>
> 직전 checkpoint:
> `docs/feynman-work-log/LOG-059-control-plane-environment-info-path-fix-20260913.md`.
> LOG-058의 Luna exit 1/0-byte trace 뒤, model-free App Server `environment/info`
> 경로에서 Linux remote cwd의 잘못된 Windows host reverse mapping을 발견·보정했다.
> exact full-runner/skill override control-plane preflight는 remote connection,
> response mapping rejection 0, remote child exit 0으로 통과했고 모델/thread/turn/tool
> 호출은 없다. canonical executor는 이 preflight를 auth/model 앞에 fail-closed로
> 실행한다. 새 model-turn은 별도 명시 승인 없이는 시작하지 마라.
>
> 직전 checkpoint:
> `docs/feynman-work-log/LOG-058-luna-model-turn-failed-20260913.md`.
> 승인된 Luna model-turn은 preflight/auth 후 `codex exec` exit 1로 종료됐고
> trace는 0바이트였다. 자동 retry/fallback하지 마라. model/tool-use 증거는
> 없다. 다음은 별도 non-model 진단/구현 보정 또는 추가 model 실행 여부를
> 사용자가 결정해야 하는 지점이다.
>
> 이전 checkpoint:
> `docs/feynman-work-log/LOG-056-subscription-executor-wiring-preflight-20260913.md`.
> canonical executor가 full-runner required inputs와 two-pass skill discovery를
> 검증하고 transient skill-disable override까지 실제 command builder에 자동
> 연결했다. Luna/Terra/Sol 모두 `subscription-executor-wiring-ready`, full-runner
> override 13개, transient override 1개, model/auth 0회를 기록했고 전체
> `358 tests OK, 11 skipped`다. 실제 model smoke, 자동 retry, baseline/frozen
> evaluation은 시작하지 마라. 다음은 별도 승인된 subscription auth gate와
> 그 후의 model-turn smoke다.
> `feynman_subscription_smoke_exec.py`의 공용 command builder에 LOG-053의
> full-runner 13개 override와 transient skill-disable override를 연결했고,
> Luna/Terra/Sol 모두 model-free preflight에서 `full-runner-skill-tool-wiring-ready`를
> 얻었다. Schema 상수 오류를 발견·보정했고 `354 tests OK, 11 skipped`, 세 artifact
> schema 검증을 통과했다. 모델·인증 호출은 0회다. 다음은 실제 subscription executor
> 호출부에서 binding/adapter/Docker 입력을 필수로 묶는 model-free fail-closed 검사다.
> 실제 model smoke, 자동 retry, baseline/frozen evaluation은 시작하지 마라.
> LOG-052 binding에 연결된 Luna/Terra/Sol candidate에서 exact skill exposure,
> full-runner 3-tool catalog, network-disabled fixed test 시작과 source 불변성을
> model-free로 확인했다. 빈 disposable Codex home에도 주변 skill 7개가 발견돼,
> 첫 discovery 결과를 두 번째 App Server의 transient disable override에만 쓰는
> two-pass 격리를 구현했다. 세 결과 모두
> `full-runner-skill-tool-wiring-ready`, model/auth 호출 0회다. 다음은 같은 격리와
> full-runner override를 실제 subscription smoke executor의 명령 생성 경로에
> model-free로 결속하는 것이다. 실제 model smoke, 자동 retry, baseline/frozen
> evaluation은 시작하지 마라.
>
> 이전 full-runner checkpoint는
> `docs/feynman-work-log/LOG-051-full-runner-mcp-contract-model-free-20260913.md`와
> LOG-052를 따른다. 승인된 Luna 비평가 probe 1회에서 실제 완료
> `mcp_tool_call` 1개를 확인한 뒤, 3-tool contract와 artifact binding을 모델 없이
> 검증했다.
>
> 이전 model-free checkpoint:
> `docs/feynman-work-log/LOG-049-transient-mcp-exec-preflight-20260913.md`를 읽어라.
> `codex exec --ignore-user-config`와 11개 CLI override로 protected login home의
> config를 수정하지 않는 bounded MCP diagnostic route를 구현했다. Luna 실제
> plan/job/version/Docker/security/catalog를 포함한 `--preflight-only` 결과는
> `ready-for-subscription-tool-use-probe`; model/auth 호출은 0회다. 다음은 새 명시적
> 승인 아래 Luna 비평가 model probe 딱 1회이며 실패 시 자동 재시도하지 않는다.
> 이 성공도 frozen evaluation/baseline 시작 허가는 아니다.
>
> 2026-09-13 재개 우선순위: 아래 최초 인계보다
> `docs/feynman-work-log/LOG-048-remote-container-mcp-catalog-20260913.md`도 함께
> 읽어라. 동일 Docker runtime의 격리 `/run/codex`에서 MCP catalog visibility가
> 확인됐지만 `codex exec` 구독 세션의 model tool-call 성공은 아니다. protected
> control home을 수정하거나 인증을 복사하지 마라.
> `docs/feynman-work-log/LOG-047-bounded-read-adapter-and-mcp-catalog-20260913.md`,
> `docs/feynman-remote-compatibility.md`를 먼저 읽어라. LOG-047의 one-byte
> diagnostic MCP adapter와 blank-home App Server catalog 노출은 model-free
> 확인됐지만 canonical remote exec/model tool-use의 성공은 아니다.
> 다음은 동일 격리 image와 `/run/codex`에서 remote catalog를 model-free로 확인하는
> 것이다. one-byte adapter를 tools-10 평가나 baseline에 사용하지 마라.
> 그 뒤에야 제한 model probe를 별도로 검토한다. 자동 retry는 금지한다.
>
> 2026-09-12 재개 우선순위: 아래 최초 인계보다
> `docs/feynman-work-log/LOG-046-three-model-runtime-and-read-boundary-20260912.md`와
> `docs/feynman-remote-compatibility.md`를 우선한다. Luna/Terra/Sol 추가 및 새 환경의
> control/server 0.154.0 정렬은 완료했다. 새로 발견한 blocker는 요청 len=1에도
> 117-byte 응답이 반환된다는 점과 code-mode 도구 계약 미검증이다. 초과 응답은
> proxy가 차단하고, probe의 live gate는 모델 호출 전 실패하도록 연결했다.
> 아래는 LOG-045까지의 역사이며 같은 model command를 반복하지 않는다.
> 인증·Docker canary·ordinal 1 모델 턴은 통과했으나 task는 실패했다.
> field-specific proxy가 Windows file URI를 Linux 경로로 변환하고 model-free task/skill
> read 및 harmless process까지 통과했다. repaired ordinal 1 transport는 완료됐지만
> model이 tool을 호출하지 않아 execution-required task 성공이 아니다. executor
> schema v2는 이를 `blocked-no-candidate-tool-call`로 기록한다. 동일 evaluation
> command를 반복하지 말고, 먼저 implementation+tests가 고정된 비평가적
> `feynman_subscription_tool_use_probe.py`를 canonical remote environment와
> ChatGPT auth gate 뒤 한 번 실행했다. 현재 Codex 0.154.0에서 auth/process는
> 성공했지만 tool item은 0개였고 `PROBE_TOOL_USED` 텍스트만 반환됐다. 이는
> execution evidence가 아니며 response-vs-trace verdict로 차단한다. 다른
> model/version 선택이나 remote-tool exposure 조사는 별도 결정 없이는 하지 않는다.
> 이후 raw trace 비보존과 payload-free RPC telemetry를 구현했고, 새 telemetry를
> 사용한 model-free native preflight도 통과했다. probe는 proxy에서
> `candidate.py`, `offset=0`, `len=1`, `fs/readFile`만 허용하도록 강제된다.
> Windows `.ps1` launcher와 auth gate의 `.cmd` companion 처리를 수정한 뒤
> actual probe의 인증·process는 성공했으나 tool-use는 실패했다. metadata allowlist
> 보정 후 추가 승인 1회(-07)도 tool item 0 / `fs/readFile` 0이었다. discovery 차단은
> 관찰됐지만 no-tool의 단일 원인으로 확정하지 않는다. model-free config RPC 거부와
> Windows CLI 0.154.0 / Docker 서버 0.153.4 불일치를 확인했다. 일반 RPC preflight
> 성공은 제한 모드 discovery 또는 model-facing tool 노출 성공이 아니다.
> 사용자 요청에 따라 이번 진단은 종료됐다. 자동 retry나 baseline은 시작하지 않는다.
> 향후 재개한다면 양쪽 버전·실제 RPC 스키마·제한 모드 discovery·모델 도구 계약을
> 모델 없는 검사부터 확인한다. 현재 결과로 모델 변경이나 allowlist 확대를 정당화하지 않는다.

아래 구분선 뒤의 내용을 새 **개발 담당** Codex 세션에 붙여넣는다. 평가 candidate나 baseline 프롬프트로 사용하지 않는다.

---

너는 `Ronaldony/thinking-skills`에서 리처드 파인만 사고 스킬을 이어 개발하는 담당자다. 이 프로젝트는 유명 인물의 사고 방법을 실제 문제 해결 스킬로 구현한다. 기존 스킬은 `Ronaldony/feynman-thinking` v0.4.0이고, 현재 통합 스킬은 v0.5.0-draft research preview다.

## 시작 정보

- 사용자 로컬 저장소: `C:\DevWorks\thinking-skills`
- 사용자 shell: Windows PowerShell
- 작업 브랜치: `feat/feynman-thinking-v0.5-draft`
- PR #1: open / draft / not merged 유지
- 인계 문서 추가 전 원격 HEAD: `1613abd87b813be2aedfaee5ac360046397ad1ca`
- Windows auth gate 수정: `b412e9fa807458d428745c5e63a6fccd38885927`
- 평가 전용 Codex 홈의 예정 경로: `Join-Path $HOME '.codex-feynman-eval'`

먼저 현재 접근 가능한 OS·shell·저장소·branch·HEAD·dirty 상태를 직접 확인해라. 위 경로나 원격 HEAD가 지금 로컬과 같다고 가정하지 마라. 이 SHA로 reset하지 마라. 사용자 변경과 기존 로그인 홈을 보존해라. cloud 세션에서 사용자 PC를 조작할 수 있는 척하지 마라.

적용되는 AGENTS.md가 있으면 먼저 확인하고, 다음 파일을 읽어라.

1. `docs/feynman-codex-handoff.md`
2. `docs/feynman-work-log/LOG-020-windows-auth-gate-fix-and-green-ci.md`
3. `docs/feynman-work-log/LOG-019-windows-auth-gate-version-command-failure.md`
4. `tooling/feynman_subscription_auth_gate.py`
5. `tests/test_feynman_subscription_auth_gate.py`

이후 실제 smoke를 준비할 때 `docs/feynman-subscription-local-smoke.md`, `tooling/feynman_subscription_smoke_exec.py`, 관련 preflight/remote environment/boundary/job 코드와 smoke spec을 읽어라. LOG-013 이전 API-era 실행 안내는 폐기된 역사 기록이다.

## 정확한 중단 지점

사용자는 ChatGPT Codex 로그인 완료를 보고했지만 **실제 auth gate 성공은 아직 확인되지 않았다.** 마지막 사용자 오류는 `error: Codex version command failed`였다. 이는 gate 내부 `codex --version` 실패이며 login-status 검사 이전이다.

그 뒤 Windows 최소 subprocess 환경과 경로 처리를 수정해 원격에 저장했고 수정 head의 CI 7개가 success였다. 그러나 사용자 PC에서 수정 후 재실행 결과는 없다. 따라서 다음 첫 작업은 **최신 로컬 코드 확인 → Codex 버전 호출과 실행 경로 진단 → 기존 전용 홈으로 auth gate 재검증**이다. 재로그인을 먼저 요구하지 마라.

특히 확인할 사항:
- PowerShell의 codex.ps1/codex.cmd/codex.exe 선택과 Python shutil.which('codex') 결과를 비교하되, 런처 문제를 미리 원인으로 확정하지 마라.
- auth gate의 Windows _safe_env 수정과 달리 smoke executor의 _safe_exec_env는 아직 네 개의 POSIX식 환경값만 설정한다. gate 성공과 executor 호환성을 별도로 확인해라.
- Windows safe-env 단위 테스트는 실제 Windows Codex 실행 증거가 아니다. POSIX shell fake 테스트의 플랫폼 한계를 기록해라.
- POSIX 경로를 전제하는 Docker boundary에 Windows C:\ 경로를 그대로 넣지 마라. native Windows/WSL2/Linux 중 최소 변경 경로를 검토하되 설치나 새 인증이 필요하면 그 지점에서만 사용자에게 요청해라.

## 절대 조건

1. **OpenAI Platform API 및 API-key 평가 경로는 절대 사용하지 않는다. 폐기 상태를 유지한다.** 공식 Codex의 ChatGPT 구독 로그인만 사용한다. 다른 유료 모델 API로 대체하지 말고 추가 크레딧 구매나 자동충전도 하지 마라.
2. OPENAI_API_KEY/CODEX_API_KEY/CODEX_ACCESS_TOKEN 주입, 로그인 토큰·auth.json·쿠키의 내용 열람/출력/복사/해시/커밋/업로드를 금지한다. 정상 Codex가 자신의 인증을 사용하는 것은 허용한다. 전체 환경변수와 control home을 덤프하지 마라.
3. candidate는 control 인증정보와 evaluator 정답·루브릭·개발 대화를 볼 수 없어야 한다. 개발 담당인 너를 baseline candidate나 독립 심사자로 간주하지 마라.
4. 전체 environment 상속, 무검토 shell=True, sandbox/검증 조건 완화, GITHUB_ACTIONS guard 우회로 문제를 숨기지 마라.
5. 사용자 변경, 기존 로그인 홈, 기존 증거를 보존한다. reset --hard/clean -fd/force push/무단 main 병합을 하지 않는다. root AGENTS.md와 전역 Codex 설정을 인계 편의 때문에 덮어쓰지 않는다.
6. 실행하지 않은 명령·테스트·모델 요청을 했다고 말하지 않는다. mock 성공, 구독 인증 성공, 실제 tool 경계 성공, 스킬 성능 향상을 각각 분리한다.

## 진행 순서

A. 현재 상태를 확인하고 기존 수정이 반영돼 있는지 검증한다. 필요한 update는 사용자 변경을 보호하는 fast-forward 방식만 쓴다.
B. Codex 자체의 버전 호출과 gate의 subprocess 차이를 검사한다. auth gate 출력은 새 파일명으로 저장한다. 실패하면 가설 하나씩 최소 재현 후 패치/회귀 테스트를 한다.
C. gate 성공 뒤에도 실제 executor 환경·CLI 플래그·Docker와 경로 계약을 모델 호출 없이 먼저 점검한다. 필요 없는 전면 재설계나 테스트 수 늘리기를 하지 않는다.
D. 인증·환경·boundary·preflight가 준비됐을 때만 `tools-10 × {baseline, feynman-v05} × 각 1회`의 기존 frozen integration smoke를 canonical executor로 진행한다. 실패 시 자동으로 모델 요청을 반복하지 말고 기록한다. 두 답변 차이로 성능 향상을 주장하지 않는다.
E. 각 job의 실제 trace/final → boundary evidence → attestation v3/link v3 → evidence/review v2/gate → result v4 연결을 검증한다. 빠진 단계나 독립 의미 채점이 없으면 pending으로 남긴다.
F. 4조건 behavioral pilot은 explicit reasoning effort를 versioned 실행 계약에 결속한 뒤 별도 단계로 진행한다. API 경로는 다시 열지 않는다.

## 세부 로그와 저장

`docs/feynman-work-log/`의 최신 번호를 먼저 조회하고 다음 로그를 만든다. LOG-021은 이 인계 준비 기록이다. 각 작업 직후 시각(KST), 목적, 시작 HEAD/dirty 상태, OS·shell·버전, 실제 명령(민감정보 제거), 종료 코드, 관찰, 확인/미확인 원인, 수정 파일, 테스트와 환경, artifact 위치, local commit/push 여부, 남은 문제와 **다음 한 행동**을 기록한다.

단계가 길어지면 짧은 진행 보고와 checkpoint를 남겨라. 기록에는 공개 가능한 실행 사실과 결정 이유만 남기고 비밀정보나 불필요한 원문 덤프를 넣지 마라. CI를 무한 polling하지 마라. 완료된 작은 변경 단위마다 검토·테스트·commit하고 권한 범위 내에서 작업 브랜치에 push한 뒤 remote SHA를 확인해라. push 불가면 로컬 저장 상태와 이유를 명시해라. main은 병합하지 않는다.

지금은 **Windows auth gate 재검증부터 실제로 수행**해라. 설명만 반복하거나 사용자에게 같은 명령을 무작정 다시 시키지 마라. 네가 접근 가능한 로컬 명령은 직접 실행하고, 로그인 UI·운영체제 설치·새 권한 등 실제 사람만 필요한 지점에서만 정확한 요청을 해라. 첫 checkpoint의 종료 보고는 완료/미완료/검증 범위/commit·push 상태/다음 행동을 포함해라.
