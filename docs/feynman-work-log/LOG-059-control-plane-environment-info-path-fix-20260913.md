# LOG-059 — Control-plane remote-environment handshake path fix

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 범위: 실패한 Luna model-turn의 **재실행이 아닌** model-free Codex control-plane 진단과 Windows path-mapping 보정
- OpenAI Platform API/API key: 사용하지 않음
- 모델 요청 / thread / turn / MCP tool: 모두 0회

## 출발점

LOG-058의 승인된 Luna `codex exec` 1회는 exit 1과 0-byte trace로 끝났다.
raw stderr를 보존하지 않는 정책 때문에 원인은 확정되지 않았고, 같은 model-turn의
자동 retry/fallback은 금지된 상태였다. Docker Desktop 정상화 뒤 기존 native RPC
preflight는 통과했지만, 그것은 Codex control-plane App Server가 실제 protected
`CODEX_HOME`의 remote environment를 연결하는지까지 증명하지 않았다.

공식 Codex App Server 문서의 experimental `environment/info`는 configured remote
environment에 연결하되 thread/turn을 시작하지 않는 API다. 이 경로를 별도 preflight로
구현했다.

## 구현

### 새 control-plane preflight

`tooling/feynman_subscription_control_plane_preflight.py`는 다음 순서로 실행한다.

1. canonical protected control home과 executor의 transient full-runner/skill
   override로 `codex app-server --stdio`를 시작한다.
2. `initialize(capabilities.experimentalApi=true)` 뒤 `environment/info(candidate)`만
   요청한다.
3. 응답의 shell/cwd **존재 여부**만 artifact에 기록한다. 경로, config, prompt,
   credential, raw stderr는 기록하지 않는다.
4. proxy telemetry를 evaluator의 canonical telemetry가 아닌 새 diagnostic 경로로
   우회한다.

Windows `.cmd` launcher가 remote teardown 동안 자식 App Server를 지연 종료하는
상황도 bounded process-tree cleanup으로 처리한다. 이는 이 probe가 직접 시작한 PID
tree만 대상으로 하며, unrelated Docker/Codex 작업을 대상으로 하지 않는다.

`tooling/feynman_subscription_smoke_exec.py`에도 full-runner 입력이 있는 실제
subscription executor에서 이 preflight를 auth gate와 model-facing `codex exec`보다
앞서 fail-closed로 호출하도록 연결했다.

### 발견한 원인과 보정

보정 전 control-plane telemetry는 `environment/info`, `initialize`, `initialized`
요청이 remote exec-server까지 전달됐지만 response mapping rejection 1회와 child exit
1을 기록했다. 즉 Docker/path mount 자체가 아니라 **응답 역매핑** 단계의 문제였다.

`environment/info`의 `cwd`는 공식 계약상 remote environment의 native path syntax다.
Linux remote `cwd`를 Windows host mount로 무조건 역매핑하던
`feynman_rpc_path_mapping.py`는 mount 밖의 remote service cwd를 거부했다.

보정은 요청 ID와 pending method를 이용해 `environment/info` 응답에 한정해 `cwd`를
그대로 전달하는 것이다. 다른 declared response path field와 모든 request mapping은
변경하지 않았다. 이는 Linux native cwd를 보존하며 host path를 노출하지 않는다.

추가로 `FEYNMAN_RPC_TELEMETRY_OVERRIDE`를 proxy에 도입했다. control-plane
diagnostic만 새 absolute, non-existing telemetry file을 지정할 수 있고, Docker
container는 `env -i`로 실행되므로 이 host-only value를 받지 않는다.

## 실제 검증

### 명령

1. model-free native RPC preflight:

```powershell
& $probePython -m tooling.feynman_rpc_preflight `
  --job "$evaluator\runner-job.json" `
  --boundary-profile "$compatRoot\boundary-profile.json" `
  --remote "$evaluator\environments.toml" `
  --docker-config $dockerConfig `
  --output "$evaluator\startup-preflight-20260913-01.json"
```

`native-rpc-preflight-passed`: initialize, candidate/task/skill read contract,
isolated process start 모두 통과했다. 모델 요청은 없었다.

2. protected control home의 `environment/info` 전용 preflight와 정확한 Luna
full-runner/skill override 결합 preflight를 각각 새 diagnostic telemetry로 실행했다.
최종 artifact는
`control-plane-preflight-20260913-06.json` 및
`control-plane-preflight-20260913-07.json`이다.

최종 `-07` 관찰:

- `subscription-control-plane-ready`
- App Server initialize / remote environment connect / shell 및 cwd metadata: true
- forwarded requests 3, responses 2, mapping rejection 0, remote child exit 0
- model requests, threads, turns, MCP tool calls: 0
- raw stderr, config payload, control-home contents, credential payload: 보존하지 않음
- 기존 canonical `rpc-proxy-telemetry.json`은 읽거나 덮어쓰지 않았고 수정 시각도
  바뀌지 않았다.

3. 회귀:

```powershell
& $probePython -m unittest discover -s tests -p 'test_*.py'
```

결과: `363 tests OK, 11 skipped`.

## 해석과 제한

이번 보정으로 LOG-058의 가능한 원인 중 **remote environment control-plane
handshake/path response mapping**은 실제 무모델 실행으로 해결·재검증됐다.
이는 `gpt-5.6-luna`에 실제 model request가 성공했다는 증거가 아니다. 모델
availability/entitlement 및 full tool-use/model response는 여전히 승인된 새 model-turn
없이는 확인할 수 없다.

## 저장 상태와 다음 행동

- 구현·문서·테스트 변경은 이 로그와 함께 commit/push할 예정이다.
- 사용자 PNG 2개는 untracked로 보존하며 stage하지 않는다.
- main merge와 force push는 하지 않는다.
- 다음 사람 개입 지점은 **새 Luna model-turn을 실행할지 여부의 명시적 승인**이다.
  이전에 승인된 단일 model-turn은 이미 소비됐으며 자동 retry/fallback/baseline은
  계속 금지된다.
