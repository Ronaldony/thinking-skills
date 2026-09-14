# LOG-101 — gate 보강 commit/push와 CI 영수증 (2026-09-14)

## 완료한 변경 묶음

LOG-100의 A~D 구현을 다시 확인한 뒤 지정된 15개 파일만 stage했다. `.tmp/`,
사용자 PNG 2개, 이전 untracked `LOG-099`는 stage하지 않고 보존했다. 변경 내용은
startup 직접 API·개별 CLI의 공통 checkpoint 검증, tools-10 full-runner 필수 gate,
startup evidence 필수 검사, checkpoint/output 경계와 digest 검증, shared deadline,
단일 telemetry writer, 빈 telemetry 차단, non-candidate mount suffix 비교다.

## 실제 명령과 관찰

### Stage 확인

실행 명령:

```powershell
git add -- evals/feynman-thinking/subscription-smoke-exec-result.schema.json tests/test_feynman_rpc_compatibility.py tests/test_feynman_subscription_checkpoint.py tests/test_feynman_subscription_smoke_exec.py tests/test_feynman_subscription_startup_diagnostic.py tooling/feynman_rpc_path_contract_probe.py tooling/feynman_rpc_path_proxy.py tooling/feynman_subscription_checkpoint.py tooling/feynman_subscription_control_plane_preflight.py tooling/feynman_subscription_smoke_exec.py tooling/feynman_subscription_startup_diagnostic.py docs/feynman-work-log/LOG-100-autonomous-gate-and-telemetry-hardening-20260914.md docs/feynman-work-status.md docs/feynman-codex-handoff.md docs/feynman-codex-resume-prompt.md
git diff --cached --check
git diff --cached --stat
git status --short --branch
```

관찰 결과:

- 15개 파일, `693 insertions(+), 114 deletions(-)`가 stage됐다.
- staged diff check는 통과했다. CRLF 변환 및 Git global ignore 접근 권한 경고는
  patch 실패가 아닌 로컬 환경 경고였다.
- `.tmp/`, PNG 2개, `LOG-099`는 staged 목록에 없었다.

### Commit과 일반 push

실행 명령:

```powershell
git commit -m "fix: close subscription startup gate bypasses"
git push origin feat/feynman-thinking-v0.5-draft
git status --short --branch
git ls-remote --heads origin feat/feynman-thinking-v0.5-draft
```

관찰 결과:

- commit: `8ddde91 fix: close subscription startup gate bypasses`.
- force push와 main 병합은 하지 않았다.
- push 결과: `86177c8..8ddde91 feat/feynman-thinking-v0.5-draft -> feat/feynman-thinking-v0.5-draft`.
- 원격 SHA: `8ddde9128ab1be6de62a67bc744589be931da08c`.
- commit 후 tracked 변경은 없었다. 보존 대상 untracked만 남아 있다.

### GitHub Actions

실행 명령:

```powershell
gh run list --commit 8ddde9128ab1be6de62a67bc744589be931da08c --limit 20 --json name,status,conclusion,databaseId,url
```

push 직후 일부 workflow가 `in_progress`였고 20초 뒤 같은 명령을 한 번만 재확인했다.
현재 commit에 대한 결과는 다음과 같다.

- `validate-feynman-docker-reference`: completed / success
- `validate-feynman-subscription-readiness`: completed / success
- `validate-feynman`: completed / success
- `validate-feynman-unit-diagnostic`: completed / success
- `validate-feynman-codex-reference`: completed / success
- `validate-feynman-remote-patch-reference`: completed / success
- `validate-feynman-remote-exec-reference`: completed / success

목록에 함께 표시된 이전 run도 모두 success였으며, 위 목록에서 SHA가 현재 commit과
일치하는 run을 현재 push의 CI 증거로 사용한다.

## 검증 범위와 미완료

- 로컬 최종 회귀는 `461 tests OK, 11 skipped`, schema `17 errors=0`,
  `ResourceWarning` 없음이다.
- CI는 코드·schema·reference workflow까지 모두 green이지만, CI green이 실제
  Windows의 구독 remote `thread/start` 성공을 의미하지는 않는다.
- 실제 ChatGPT 구독 auth/startup diagnostic, Luna model smoke, baseline 비교는
  실행하지 않았다. API key/Platform API와 credential 파일·토큰·전체 환경변수도
  사용하지 않았다.
- 이전 유효한 구독 startup에서 발생한 `thread/start -32603`의 최종 원인은 여전히
  미확정이다. 이번 commit은 원인을 확정한 것이 아니라 입력·증거·실행기 우회를
  제거하고 재현 가능한 실패만 남기는 보강이다.

## 다음 작업과 사람 개입 경계

자동으로 완료된 범위는 코드 수정, 순수 회귀, schema, commit, 일반 push, 원격 CI
확인이다. 다음은 실제 보호된 구독 로그인 홈을 사용한 **새 startup diagnostic 1회**
검토 지점이다. 그 실행은 최신 feature SHA와 검증된 full-runner/boundary 입력을
사용하고, startup gate가 통과하기 전 모델 명령을 실행하지 않는다.

그 1회가 통과할 때만 기존 승인 범위의 `tools-10 / feynman-v05 /
gpt-5.6-luna` smoke 1회(최대 300초)를 별도로 진행한다. 실패 시 자동 재시도,
Terra/Sol fallback, baseline 비교는 하지 않는다. 같은 실패에 새 증거가 없으면
반복하지 않고 payload-free 최소 재현 자료만 정리한다.
