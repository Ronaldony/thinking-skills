# LOG-057 — Luna model-turn preflight blocked by control environment lineage

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 대상: `gpt-5.6-luna`, `ordinal=1`, `tools-10 / feynman-v05`
- 사용자 승인: 단일 model-turn smoke 1회
- 모델 요청 시작: 0회
- auth gate 호출 도달: 0회
- protected credential/token 내용: 읽거나 출력하지 않음
- OpenAI Platform API/API key: 사용하지 않음

## 목적

auth gate가 사용자의 기존 평가 전용 홈에서
`chatgpt-subscription-authenticated`, exit code 0으로 통과한 뒤 승인된 첫
Luna model-turn smoke를 canonical executor로 시작하려 했다. 자동 retry와 모델
fallback은 적용하지 않았다.

## 실행 명령과 관찰

첫 실행은 Luna evaluator 폴더의 `environments.toml`을 remote environment로
전달했다. executor는 모델 호출 전 다음 오류로 중단했다.

```text
error: remote environment must be the canonical control CODEX_HOME/environments.toml
```

이는 명령 입력 위치 오류였고 auth/model subprocess는 시작되지 않았다.

canonical 위치인
`C:\Users\wotmd\.codex-feynman-eval\environments.toml`이 존재하는지만 확인한 뒤,
같은 명령을 반복하지 않고 해당 정확한 경로로 한 번 보정 실행했다. executor는
다시 auth 이전에 다음 오류로 fail-closed 중단했다.

```text
error: environments.toml differs from canonical runner-job/profile remote exec document
```

즉, auth gate 성공과 별개로 현재 control home의 remote environment manifest가
현재 Luna runner-job/profile lineage와 다르다. 모델 request는 시작되지 않았고,
승인된 model-turn은 아직 소비되지 않았다.

## 읽기 전용 원인 확인

보호된 홈의 파일 본문은 읽거나 출력하지 않았다. 비보호 evaluator manifest만
validator로 확인했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_remote_exec_environment --job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --validate 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\environments.toml'
```

결과는 `remote-exec-environment-valid`였다. 따라서 현재 blocker는 Docker
backend나 ChatGPT auth가 아니라, canonical control-home manifest와 현재
runner-job/profile의 lineage 불일치다. boundary image와 full-runner image가
서로 다른 구조는 정상이며 이번 오류 원인이 아니다.

## 사람 개입 지점

현재 control home의 기존 `environments.toml`을 보존할지, 현재 Luna job용
canonical manifest로 교체할지 사용자가 결정해야 한다. 이 파일은 credential/token
파일은 아니지만 protected home의 실행 설정이므로 자동 덮어쓰기를 하지 않았다.

교체를 승인하는 경우에는 기존 파일을 별도 백업한 뒤, 비보호 evaluator의
검증된 Luna manifest를 정확한 control-home 경로에 배치해야 한다. 그 후에만
동일한 승인 범위의 Luna model-turn을 1회 재개할 수 있다. 이때도 자동 retry,
Terra/Sol fallback, baseline 실행은 하지 않는다.

## 저장 상태

- 이번 LOG-057은 model-free diagnosis 기록이며 source 변경은 없다.
- 이전 구현 commit `03457b1`, docs close commit `3680456`은 원격과 일치한다.
- 이번 blocker 기록 후 docs-only commit/push를 수행한다.
- 사용자 PNG 2개는 계속 untracked로 보존한다.
- main merge와 force push는 하지 않는다.
