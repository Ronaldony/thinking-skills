# LOG-064 — Corrected startup request-mapping diagnostic

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 선행 checkpoint: [LOG-063](LOG-063-model-free-startup-reason-diagnostic-20260913.md)
- 대상: environment-native `/run/candidate` 기반 subscription startup 재검증
- 승인: 보정된 model-free ephemeral `thread/start` 정확히 1회
- 실제 model turn: 실행하지 않음
- OpenAI Platform API/API key: 사용하지 않음

## 실행 명령

기존 protected ChatGPT subscription login home, canonical runner job,
full-runner binding, Docker image를 그대로 사용했다. 새 artifact 경로를 지정했고
로그인 파일·토큰·전체 환경변수·raw RPC payload는 출력하거나 보존하지 않았다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_subscription_startup_diagnostic --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote-environment 'C:\Users\wotmd\.codex-feynman-eval\environments.toml' --binding 'C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json' --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --telemetry 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-02-rpc.json' --output 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-02.json' --timeout-seconds 45
```

## 관찰 결과

표준 출력의 safe summary:

```json
{
  "verdict": "subscription-startup-thread-blocked",
  "thread_started": false,
  "error_code": -32603,
  "error_category": "remote-environment-error",
  "turn_requests_sent": 0,
  "model_generation_requests_sent": 0,
  "request_mapping_rejection_methods": {
    "environmentConfig/read": 1,
    "fs/getMetadata": 6
  },
  "request_mapping_rejection_reasons": {
    "invalid-host-path": 1,
    "outside-declared-mount": 6
  }
}
```

artifact와 별도 proxy telemetry를 읽을 때도 고정 필드만 확인했다.

- schema version: `1`
- `initialize_completed`: `true`
- proxy request methods: `initialize:1`, `initialized:1`,
  `environmentConfig/read:1`, `fs/getMetadata:9`
- request mapping rejection: `environmentConfig/read:1`, `fs/getMetadata:6`
- rejection reason: `invalid-host-path:1`, `outside-declared-mount:6`
- child exit code: `0`
- response mapping rejection: `0`
- process tree reaped: `true`
- payload/instruction path/raw stderr 보존: 모두 `false`
- 진단 후 남은 `feynman-*` Docker container: 없음

## 판정

`/run/candidate`를 사용한 보정은 적용됐지만 startup은 여전히
request-side path mapping에서 막힌다. `environmentConfig/read` 1건은 host path
형태가 현재 mapper의 절대경로 규칙에 맞지 않고, `fs/getMetadata` 6건은 선언된
mount 밖으로 판정된다. `fs/getMetadata` 전체 9건 중 3건은 전달됐으나 thread
startup이 완료되지는 않았다.

이번 실행은 thread를 만들지 못했고 `turn/start` 및 모델 생성은 각각 0회이므로
모델 평가 결과나 Feynman 효과성에 대한 증거가 아니다. authentication 성공과
executor의 Windows/Docker 호환성도 아직 분리된 상태이며, executor gate에
편입하지 않는다.

## 다음 작업

추가 외부 실행 없이 로컬 mapper/config builder를 분석하고, 다음을 model-free
unit fixture로 재현한다.

1. `environmentConfig/read`의 선언 경로 배열·cwd 변환 계약을 native path로
   정규화한다.
2. `fs/getMetadata` 요청에서 canonical candidate mount 및 full-runner에 필요한
   허용 metadata 경로를 최소 범위로 확인한다.
3. path/payload를 저장하지 않는 reason telemetry와 회귀 테스트를 유지한다.
4. 이 로컬 수정과 테스트가 끝난 뒤에만 추가 외부 진단 필요 여부를 다시 판단한다.

자동 retry, 모델 fallback, Terra/Sol 전환, baseline 전달, main 병합, force push는
하지 않는다.

## 저장 상태

- 진단 결과 기록은 docs checkpoint commit으로 저장한다.
- 사용자 PNG 2개는 untracked로 보존하고 stage하지 않는다.
- main merge와 force push는 하지 않는다.
