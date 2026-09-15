# LOG-060 — Luna model-turn stopped at remote request mapping

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 대상: `gpt-5.6-luna`, `ordinal=1`, `tools-10 / feynman-v05`
- 승인 범위: 새 Luna model-turn 1회
- 자동 retry/fallback: 없음
- OpenAI Platform API/API key: 사용하지 않음

## 선행 조건

직전 LOG-059의 control-plane 보정 후 다음을 먼저 확인했다.

- runner job/profile와 canonical protected `environments.toml`: valid
- Docker Desktop: `29.7.2`, Linux `aarch64`, active
- exact full-runner/skill override control-plane preflight:
  `subscription-control-plane-ready`
- App Server initialize, remote environment connect, shell/cwd metadata: 통과
- control-plane preflight의 model/thread/turn/MCP tool: 모두 0회

## 실제 명령과 결과

새 output 디렉터리에 canonical executor를 정확히 한 번 실행했다.

```powershell
& $python -m tooling.feynman_subscription_smoke_exec `
  --plan "$compatRoot\frozen-subscription-smoke-plan.json" `
  --smoke-spec "C:\DevWorks\thinking-skills\evals\feynman-thinking\subscription-smoke-spec.json" `
  --ordinal 1 `
  --evaluator-case "$evaluator\case.json" `
  --runner-job "$evaluator\runner-job.json" `
  --boundary-profile "$compatRoot\boundary-profile.json" `
  --remote-environment "C:\Users\wotmd\.codex-feynman-eval\environments.toml" `
  --output-dir "$evaluator\subscription-exec-20260913-luna-03" `
  --codex-bin "C:\Users\wotmd\AppData\Roaming\npm\codex.cmd" `
  --full-runner-binding "C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json" `
  --full-runner-node-bin "C:\Program Files\nodejs\node.exe" `
  --full-runner-adapter "C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs" `
  --full-runner-docker-bin "$docker" `
  --full-runner-docker-config "$dockerConfig" `
  --full-runner-image-id "sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a" `
  --timeout-seconds 600
```

executor 출력은 다음과 같았다.

```text
error: Codex exec failed with exit code 1; category=unclassified; raw stderr was not preserved
```

안전한 산출물 관찰:

- `subscription-exec-20260913-luna-03/codex-trace.jsonl`: 0 bytes
- `subscription-exec-result.json`: 생성되지 않음
- 남은 `feynman-*` Docker container: 없음
- 모델 응답, thread/turn event, candidate tool-call: 관찰되지 않음

## proxy telemetry 해석

실제 실행의 payload-free telemetry는 다음을 기록했다.

- requests seen/forwarded: `18 / 9`
- request mapping rejections: `9`
- responses seen/forwarded: `8 / 8`
- response mapping rejections: `0`
- child exit code: `0`
- request method counts: `initialize:1`, `initialized:1`,
  `environmentConfig/read:1`, `fs/canonicalize:1`, `fs/getMetadata:13`,
  `fs/walk:1`
- remote child response error codes: `-32004:4`, `-32600:1`

따라서 LOG-059에서 고친 `environment/info` response 역매핑 문제는 이번 실행에서
재발하지 않았다. 이번에는 Codex가 remote exec-server startup/discovery 중 보낸
filesystem/config request 일부가 선언된 Windows→Linux mount 범위 밖으로 해석되어
proxy에서 거부된 것이 현재 가장 강한 설명이다. Docker child 자체는 정상 종료했고,
response path mapping 거부는 0건이었다.

telemetry는 경로 payload를 보존하지 않으므로 9건의 개별 path와 단일 원인은 확정할
수 없다. `environmentConfig/read` 1건, `fs/canonicalize` 1건, `fs/getMetadata`
13건, `fs/walk` 1건은 전체 method count이며, 어느 요청이 거부됐는지와 각 경로의
내용을 뜻하지 않는다. 로그·토큰·전체 환경변수·candidate payload는 읽거나 저장하지
않았다.

## 판정

이번 승인으로 허용된 Luna model-turn 1회는 소비됐으며, 모델 요청 전에 차단됐다.
이는 Luna entitlement/auth 실패나 Feynman skill 성능 실패로 판정하지 않는다. 또한
이 결과는 실제 모델 응답이나 tool-use evidence가 아니므로 baseline, evidence,
attestation, behavioral analysis를 시작하지 않는다.

## 미완료와 다음 사람 개입

미완료:

- 실제 Luna model response 및 candidate tool-use
- Terra/Sol model-turn
- baseline과 Feynman 성능 비교
- startup request 9건의 per-method rejection 원인 확정

다음 개발 작업은 모델 없이 proxy telemetry에 method별 rejection counter를 추가하고,
`environmentConfig/read`, `fs/canonicalize`, `fs/getMetadata`, `fs/walk`의 정확한
path-bearing contract를 검증하는 것이다. 이 gate가 통과하기 전에는 새 model-turn을
실행하지 않는다. 추가 model-turn 승인은 이 진단 보정 후 별도로 필요하다.

## 저장 상태

- 이 로그 저장 전 최신 push: `f989a3c` (`docs: finalize control-plane handoff log`)
- 이번 실행 자체는 저장소 파일을 변경하지 않았다.
- 사용자 PNG 2개는 untracked로 보존하고 stage하지 않는다.
- main merge와 force push는 하지 않는다.
