# LOG-058 — Luna model-turn failed after preflight and auth

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 대상: `gpt-5.6-luna`, `ordinal=1`, `tools-10 / feynman-v05`
- 승인 범위: 단일 model-turn smoke 1회
- executor model-turn process: 1회 시작
- 자동 retry/fallback: 없음
- OpenAI Platform API/API key: 사용하지 않음

## 선행 조건

사용자가 실행한 auth gate 결과는 다음과 같았다.

```text
chatgpt-subscription-authenticated
exit code: 0
```

이전 LOG-057의 control environment lineage blocker는 사용자의 승인 후
기존 control home `environments.toml`을 TEMP 백업하고, evaluator에서
`remote-exec-environment-valid`로 검증된 Luna manifest로 교체해 해결했다.

기존 백업:

`%TEMP%\feynman-control-environments-backup-d824bd35025b42aa8e1c000165a7722f.toml`

## 실제 실행

canonical `tooling/feynman_subscription_smoke_exec.py`에 Luna의 frozen plan,
runner-job, boundary profile, full-runner binding, Node/Docker 입력과 control
environment를 전달해 정확히 1회 실행했다.

실행 결과:

```text
error: Codex exec failed with exit code 1; category=unclassified; raw stderr was not preserved
```

executor는 raw stderr를 저장하지 않도록 설계되어 있으며, 자동 재실행하지 않았다.
결과 디렉터리에는 `codex-trace.jsonl`만 생성됐고 크기는 0바이트였다. 따라서
모델 응답, candidate tool-call, final answer의 신뢰 가능한 증거는 없다.

## 추가 model-free 진단

실패한 model command를 재실행하지 않고, 동일한 full-runner/skill override를
구성한 `codex exec --help`만 disposable home과 현재 control home에서 각각
검사했다. 두 경우 모두 CLI argument/config parse는 exit 0이었다.

관찰:

- disposable home `--help`: exit 0, stdout 112 lines, stderr 0 lines
- control home `--help`: exit 0, stdout 112 lines, stderr 1 line
- 이 진단은 thread/turn/model request를 시작하지 않았다.
- Docker에 잔류한 `feynman-tool-*` container는 확인되지 않았다.

## 해석

현재 확인 가능한 경계는 다음과 같다.

1. runner-job/profile/binding 및 native path mapping: 통과
2. full-runner/skill wiring model-free preflight: 통과
3. control environment canonical validation: 통과
4. ChatGPT subscription auth gate: 통과
5. CLI flag/config parse: `--help` 기준 통과
6. 실제 Luna `exec` model-turn: exit 1, trace 0바이트, 실패 원문 미보존

따라서 이 결과를 auth 실패나 Docker boundary 실패로 단정하지 않는다. 남은
가능성은 실제 `exec` 시작 후 model availability/entitlement, remote environment
launch, 또는 full-runner runtime handoff 중 하나지만, 현재 보존된 안전한 metadata만으로
단일 원인을 확정할 수 없다. 실패한 model-turn을 반복하지 않는다.

## 현재 완료·미완료

완료:

- 승인된 단일 Luna model-turn 실행 시도
- pre-auth blocker 해소 및 control manifest backup
- auth gate 및 canonical environment 재검증
- 실패 결과와 payload 비보존 상태 기록

미완료:

- Luna의 실제 모델 응답 및 tool-use evidence
- Terra/Sol model-turn
- baseline job
- post-run canary, attestation, link, evidence, review, analysis-result
- Feynman 성능 판단

다음 행동은 실패 원문을 보존하지 않는 현재 정책 안에서 추가 model 실행을 승인할지,
또는 먼저 별도 non-model diagnostic/runner implementation 보정을 할지에 대한 사람의
결정이다. 자동 retry와 모델 fallback은 계속 금지한다.

## 저장 상태

- 이번 기록은 docs-only 변경이다.
- 구현 commit: `03457b1`
- 이전 blocker 기록 commit: `1668d73`
- 이 LOG-058 저장 후 docs-only commit/push와 CI 확인을 수행한다.
- 사용자 PNG 2개는 untracked로 보존한다.
- main merge와 force push는 하지 않는다.
