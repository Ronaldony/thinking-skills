# LOG-070 — Payload-free request field attribution

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `68b304f docs: record startup revalidation blocker`
- 적용 AGENTS.md: ancestor/repo 검색 결과 없음
- 외부 startup/model 실행: 없음
- OpenAI Platform API/API key: 사용하지 않음
- 기존 변경: 사용자 PNG 2개는 untracked로 보존하고 stage하지 않음

## LOG-069 기준 원인 분석

최근 승인된 startup diagnostic은 `initialize`를 완료했지만 `thread/start`에서
`-32603 / remote-environment-error`로 종료됐다. 이는 App Server 자체가 protocol
handshake 이전에 실패한 경우와 다르다. `turn/start`, prompt, model generation은
각각 0회이므로 candidate, Feynman skill, model-facing tool, baseline과는 아직
무관한 startup control-plane failure다.

관측을 층으로 나누면 다음과 같다.

| 층 | 확인된 사실 | 아직 결론낼 수 없는 사실 |
|---|---|---|
| 구독/login | 과거 standalone auth gate는 성공했고, 이번 probe는 credential을 직접 읽거나 보존하지 않았다 | 이번 `-32603`만으로 구독 auth 전체 성공을 재증명할 수는 없다 |
| App Server | `initialize_completed=true`; 이후 `thread/start`만 실패 | raw error text를 보존하지 않아 internal subcause를 단정할 수 없다 |
| RPC proxy | 12 request 중 5 forward, 7 mapping rejection; response mapping rejection 0 | 이전 telemetry는 method/reason의 개별 집계만 제공했다 |
| Docker exec-server | 4 response를 반환하고 child exit code 0, 잔여 Feynman container 0 | discovery에 필요한 path가 모두 도달했다는 뜻은 아니다 |
| model/evaluation | turn/model generation 0 | model tool exposure 또는 성능을 판단할 근거가 없다 |

따라서 현재 직접 원인은 remote environment discovery가 필요한 path request를
declared mount/namespace 경계에서 통과시키지 못하는 것이다. `fs/getMetadata`는
startup discovery의 filesystem RPC이며 모델 tool call 증거가 아니다.

## 기존 telemetry의 결정적 공백

LOG-069의 rejection은 method별 `environmentConfig/read:1`, `fs/getMetadata:6`과
reason별 container-outside:2, host-outside:4, invalid-host:1로 각각 집계됐다.
두 주변 집계는 동일 요청을 결합하지 않으므로 다음 질문에 답할 수 없었다.

- 유일한 `environmentConfig/read` 거부가 어느 reason이었는가?
- config request라면 `cwd`, `configPaths`, `requirementsPaths` 중 어느 field였는가?
- metadata의 여섯 거부가 host/container namespace 중 어디에 분포했는가?

raw POSIX fallback 수정과 scalar path fail-closed 보강 뒤에도 이전 분포가
그대로였다는 사실은 이 수정들이 충분하지 않았다는 뜻이다. 실제 거부 경로를
알거나 mount를 넓혀야 한다는 뜻은 아니다.

## 변경

`tooling/feynman_rpc_path_mapping.py`에서 mapping exception에 고정 protocol field
label만 부착한다. 가능 값은 `cwd`, `path`, `uri`, `configPaths`,
`requirementsPaths`와 `unknown`이며, path/URI/value는 부착하지 않는다.

`tooling/feynman_rpc_path_proxy.py` telemetry에는 다음 두 payload-free 구조를
추가했다.

```text
request_mapping_rejection_method_reasons
  method -> fixed reason -> count

request_mapping_rejection_method_reason_fields
  method -> fixed reason -> fixed field label -> count
```

method도 declared path-method contract에 있는 이름만 기록하고, 그 외 문자열은
`unknown`으로 정규화한다. 따라서 악의적이거나 우연한 method/path/URI/payload
문자열이 diagnostic artifact로 들어가지 않는다.

`subscription-startup-diagnostic`의 safe telemetry allowlist, standard-output
summary, JSON Schema를 함께 보강했다. 새 schema property는 optional이라 LOG-066의
`-03` 및 LOG-069의 `-04` artifact도 계속 schema validation error 0으로 통과한다.

## 실제 검증 명령과 결과

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_compatibility tests.test_feynman_subscription_startup_diagnostic
```

결과: `45 tests`, `OK`.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_*.py'
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m compileall -q tooling tests
git diff --check
```

결과: 전체 `378 tests`, `OK (skipped=11)`; compileall 및 whitespace check exit 0.
Git global-ignore 접근/CRLF warning은 있었지만 테스트나 formatting 실패는 아니었다.

기존 `startup-diagnostic-20260913-03.json` 및 `-04.json`을 갱신 schema로 검증해
각각 `schema_errors=0`을 확인했다. 이 작업은 Codex, Docker, auth, network,
model subprocess를 실행하지 않았다.

## 다음 행동과 제한

다음 외부 행동은 이 instrumentation을 포함한 **model-free startup diagnostic
정확히 1회**다. 이 실행은 새 output/telemetry 경로, `thread/start` only,
`turn/start=0` 제약을 유지해야 하며 별도 사용자 승인이 필요하다. 그 결과의
method→reason→field count를 바탕으로만 mapper/remote contract 수정 여부를
결정한다.

그 전에는 mount 범위 확대, config response 제조, 재로그인 요구, 동일 command의
자동 반복, Terra/Sol model run, baseline/evaluation을 하지 않는다. main merge와
force push도 하지 않는다.

## 저장 상태

이 로그와 구현 변경은 다음 checkpoint에서 함께 commit/push한다. 구현 commit,
remote SHA, CI 상태는 저장 직후 별도 receipt로 기록한다.
