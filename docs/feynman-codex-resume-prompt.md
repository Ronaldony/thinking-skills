# 로컬 Codex에 붙여넣을 작업 재개 프롬프트

> 2026-09-12 재개 우선순위: 아래 최초 인계보다
> `docs/feynman-work-log/LOG-035-native-rpc-proxy-preflight-20260912.md`를 우선한다.
> 인증·Docker canary·ordinal 1 모델 턴은 통과했으나 task는 실패했다.
> field-specific proxy가 Windows file URI를 Linux 경로로 변환하고 initialize까지 통과했다.
> 현재 blocker는 exact fs/readFile schema와 현 이미지 process/exec stub이다.
> 모델 없는 candidate read/spawn 및 스킬 탐색 검증부터 진행한다. baseline은 미실행이며,
> 이 결함이 해결되기 전에는 추가 모델 호출을 하지 않는다.

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
