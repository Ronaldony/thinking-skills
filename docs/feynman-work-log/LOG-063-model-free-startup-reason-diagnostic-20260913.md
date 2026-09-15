# LOG-063 — Model-free startup reason diagnostic

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 선행 checkpoint: [LOG-062](LOG-062-luna-config-metadata-rejections-20260913.md)
- 대상: payload-free request rejection reason과 model-free App Server startup
- 실제 model turn: 실행하지 않음
- OpenAI Platform API/API key: 사용하지 않음

## 목표와 공식 계약 확인

LOG-062는 실제 Luna 실행의 mapping rejection 9건을
`environmentConfig/read:1`, `fs/getMetadata:8`로 좁혔지만 거부 사유와 exit 1의
인과관계는 확정하지 못했다. 이번 작업은 실제 경로나 payload를 저장하지 않고
고정 사유를 계측하고, App Server startup을 model generation 없이 재현하는 것이다.

OpenAI 공식 App Server 문서에서 다음 계약을 확인했다.

- `thread/start`는 새 thread를 만들고 `thread/started`를 emit한다.
- 모델 생성을 시작하는 호출은 사용자 입력을 받는 `turn/start`다.
- remote thread가 반환하는 instruction source는 remote environment native path다.
- filesystem API는 absolute path를 사용한다.

로컬 Codex 0.154.0의 generated experimental JSON schema도 확인했다.

```powershell
& 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' app-server generate-json-schema --experimental --out 'C:\DevWorks\thinking-skills\.tmp-app-server-schema-20260913'
```

`ThreadStartParams`는 `ephemeral`을 지원하며, `TurnEnvironmentParams.cwd`와
`runtimeWorkspaceRoots`는 선택된 environment의 native path를 요구한다. 생성된
schema 디렉터리는 절대 경로가 정확히 workspace의 임시 디렉터리인지 확인한 뒤
PowerShell `Remove-Item -LiteralPath ... -Recurse -Force`로 삭제했고 `Test-Path`는
`False`였다.

## 구현

### 고정 rejection reason telemetry

`tooling/feynman_rpc_path_proxy.py`에 path/payload를 포함하지 않는 다음 bounded
reason code 집계를 추가했다.

- `outside-declared-mount`
- `invalid-host-path`, `invalid-container-path`
- `unsupported-file-uri`, `unsupported-file-uri-components`
- `invalid-container-file-uri`
- `invalid-path-array-shape`
- `malformed-request`, `invalid-request-structure`
- fixed probe policy reason 네 종류
- 알려지지 않은 값은 `unclassified`

기존 `_map_request_payload`의 2-value contract는 compatibility wrapper로 유지했고,
runtime proxy만 상세 helper에서 reason을 받아
`request_mapping_rejection_reasons` counter에 기록한다.

### model-free startup diagnostic

새 `tooling/feynman_subscription_startup_diagnostic.py`는 다음을 수행한다.

1. runner job/profile/remote environment/full-runner binding을 검증한다.
2. 실제 executor와 같은 full-runner 및 transient skill isolation override를 만든다.
3. canonical protected control home으로 `codex app-server --strict-config --stdio`를
   시작한다.
4. `initialize`와 `initialized` 뒤 `thread/start` 한 건만 보낸다.
5. thread는 `ephemeral=true`, approval `never`, sandbox `workspace-write`다.
6. `turn/start`, prompt, model generation 요청은 보내지 않는다.
7. thread ID, instruction source path, raw response/error/stderr는 보존하지 않는다.

artifact schema는
`evals/feynman-thinking/subscription-startup-diagnostic.schema.json`에 추가했다.

## 첫 model-free 실행과 관찰

첫 실행은 새 artifact 두 개에 수행했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_subscription_startup_diagnostic --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote-environment 'C:\Users\wotmd\.codex-feynman-eval\environments.toml' --binding 'C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json' --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --telemetry 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-01-rpc.json' --output 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-01.json' --timeout-seconds 45
```

결과:

```json
{
  "verdict": "subscription-startup-thread-blocked",
  "thread_started": false,
  "error_code": -32603,
  "turn_requests_sent": 0,
  "model_generation_requests_sent": 0,
  "request_mapping_rejection_methods": {},
  "request_mapping_rejection_reasons": {}
}
```

safe artifact의 추가 관찰:

- notification: `remoteControl/status/changed:1`
- proxy request: `initialize:1`, forwarded 1, rejected 0
- proxy response: seen/forwarded 1/1, mapping rejection 0
- remote child exit: 0
- process tree reaped: true
- 남은 `feynman-*` Docker container: 없음

따라서 첫 `thread/start`는 remote child에 filesystem/config request를 보내기 전에
App Server 내부 `-32603`으로 끝났다. 첫 버전은 오류 원문을 저장하지 않았으므로
정확한 category를 소급 생성하지 않는다.

첫 버전의 `environments.cwd`와 `runtimeWorkspaceRoots`에는 Windows host candidate
path가 들어갔다. generated schema가 environment-native path를 요구하므로 이를
canonical destination `/run/candidate`로 보정했다. 동시에 `-32603` 메시지를
원문 없이 `remote-path-error`, `remote-environment-error`, `mcp-startup-error`,
`model-configuration-error`, `authentication-error`, `configuration-error`,
`internal-error` 중 하나로 분류하도록 했다.

`-01` artifact는 이 보정과 `error_category` 필드 추가 전에 생성됐으므로 새
`subscription-startup-diagnostic.schema.json`을 만족하는 최종 산출물로 취급하지
않는다. 이는 첫 prototype 실행의 제한된 관찰 증거일 뿐이며, schema-valid 결과는
보정된 새 경로에 대한 별도 승인 실행에서만 생성할 수 있다.

## 두 번째 실행 시도와 승인 경계

보정 후 새 `startup-diagnostic-20260913-02*.json`에 같은 model-free 진단을
실행하려 했으나, 실행 시작 전에 automatic approval review가 거부했다.

거부 이유는 첫 외부 startup diagnostic 뒤 같은 목적의 재실행은 이전의 단일 실행
승인 범위를 넘으며, 보정된 path만으로 추가 networked run 승인이 성립하지 않는다는
것이다. 우회하거나 다른 명령으로 같은 실행을 시도하지 않았다. 따라서 `-02`
진단 결과를 주장하지 않으며, 보정된 environment-native path의 실제 결과는 별도
사용자 승인 전까지 미확인이다.

## 검증

관련 테스트:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_rpc_path_proxy tests.test_feynman_rpc_compatibility
```

결과: `25 tests`, `OK`.

전체 회귀:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

결과: `371 tests`, `OK (skipped=11)`; whitespace error 없음.

## 판정과 미완료

- LOG-062의 9개 mapping rejection은 method-level까지만 확정됐다.
- 새 reason telemetry는 향후 실행에서 path를 공개하지 않고 원인을 구분한다.
- 첫 startup diagnostic의 `-32603`은 host path를 environment-native field에 넣은
  진단기 결함과 일치하지만, 보정 실행이 차단됐으므로 인과관계를 확정하지 않는다.
- 실제 model response/tool-use/Feynman 효과성은 여전히 미검증이다.
- 재로그인이나 Terra/Sol 전환을 요구할 근거는 없다.

다음 한 행동은 보정된 `/run/candidate`, `ephemeral=true`, `turn/start=0` startup
diagnostic 정확히 1회를 명시 승인받아 새 `-02` artifact로 실행하는 것이다. 성공하면
그 telemetry에 따라 executor 선행 gate 편입 여부를 결정한다. 실패하면 자동 반복하지
않고 고정 category/reason으로 작업 원인을 기록한다.

## 저장 상태

- 구현·테스트·schema·이 로그의 최초 상태는 commit
  `f7ae713e01e79d9f5894ded70cf604920bb6a5a7`
  (`feat: add model-free remote startup diagnostics`)로 저장하고
  `origin/feat/feynman-thinking-v0.5-draft`에 일반 push했다.
- 위 정확한 SHA로 조회한 GitHub Actions는 push/PR 중복을 포함한 12개 run이
  모두 `success`였다. distinct workflow 7종은 `validate-feynman`,
  `validate-feynman-unit-diagnostic`, `validate-feynman-subscription-readiness`,
  `validate-feynman-codex-reference`, `validate-feynman-docker-reference`,
  `validate-feynman-remote-exec-reference`,
  `validate-feynman-remote-patch-reference`다.
- 본 저장 상태 갱신은 별도 docs-only follow-up commit으로 남긴다.
- 사용자 PNG 2개는 untracked로 보존하고 stage하지 않는다.
- main merge와 force push는 하지 않는다.
