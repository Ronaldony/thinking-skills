# Remote compatibility checkpoint — Luna, Terra, Sol

이 문서는 개발 담당자용이다. candidate/baseline에 전달하지 않는다.

## 모델 선택

`tooling/feynman_subscription_models.py`의 선택 목록:

- `gpt-5.6-luna`
- `gpt-5.6-terra`
- `gpt-5.6-sol` (`gpt-5.6 sol` 사용자 표기를 정규 식별자로 반영)

각 runner job은 `--model` 하나를 명시한다. 자동 fallback/순회/실패 재시도는 없다.
기존 frozen plan/job/result의 모델명을 바꾸지 않는다. generic runner schema는
미래의 명시적 선택과 synthetic test model을 계속 지원하며 이 목록으로 과도하게
제한하지 않는다. 준비는 사용 승인·계정 접근·모델 실행 성공의 증명이 아니다.

공식 [Codex models](https://learn.chatgpt.com/docs/models)에서 세 ID를 확인했다.
`codex debug models --bundled`를 빈 별도 홈에서 실행한 CLI 0.154.0의 관찰:
세 모델 모두 `shell_type=unified_exec`, `tool_mode=code_mode_only`,
`node_repl_disabled=false`. bundled 정보는 실제 계정의 접근 권한이나 해당 세션에
전달된 tool catalog가 아니다. 모델을 바꾸면 remote 문제가 해결된다고 추론하지 않는다.

## 새 검사 자료

`C:\DevWorks\feynman-remote-compat-20260912-01` 아래 모델별 candidate/evaluator/
home/codex-home/temp와 runner-job/environments를 새로 만들었다. baseline fixture는
만들지 않았고 실제 모델 호출은 0회다. 기존 Luna 자료와 보호된 로그인 홈은 보존했다.

## LOG-047 후속 checkpoint — model-free bounded adapter

기존 `fs/readFile`은 요청에 `offset/len`을 넣어도 117-byte `dataBase64` 응답을
반환했다. 이 사실을 감추기 위해 자르지 않고 기존 proxy의 fail-closed 응답 검사를
유지한다. 별도로 Docker image에 `feynman_read_probe_byte` MCP STDIO adapter를
넣었다. adapter는 실행 환경이 고정한 candidate 파일만 열고 실제 1 byte를 최대
1회 읽으며, 모델이 path/offset/command를 넘길 수 없다. 로컬 protocol과
network-disabled Docker protocol이 통과했다.

blank `CODEX_HOME`의 Codex 0.154.0 App Server `mcpServerStatus/list`에서도 이
도구가 catalog에 보이는 것을 model-free로 확인했다. 이는 local App Server
catalog 계약의 증거이지 기존 exec-server remote 환경이나 실제 모델 tool-use의
증거가 아니다. 이 diagnostic adapter는 tools-10 전체 평가 실행기에 연결하지
않는다.

LOG-048에서 같은 adapter를 새 `arm64/linux` Docker image의 격리 `/run/codex`에
설정하고, container 내부 Codex App Server의 `mcpServerStatus/list`에서도
`feynman_read_probe_byte`가 보이는 것을 확인했다. `network=none`, 모델/turn 0회,
auth 0회다. 다만 이 검사는 canonical protected control home의 설정이나
`codex exec` 구독 세션의 실제 model tool-call을 변경·증명하지 않는다.

## LOG-049 후속 checkpoint — transient `codex exec` 결속

Codex 0.154.0의 `--ignore-user-config`는 user `config.toml`을 읽지 않으면서 auth는
기존 `CODEX_HOME`을 사용한다. 이 계약과 최상위 CLI `-c` precedence를 이용해
protected login home과 canonical `environments.toml`을 수정하지 않는 diagnostic
route를 구현했다. evaluator가 Node/adapter/candidate를 절대 경로와 digest로
고정하고, 모델에는 no-argument `feynman_read_probe_byte` 하나만 노출한다.

Luna 실제 plan/job에서 `--preflight-only` 전체 체인이 통과했다.

- structural/version/Docker security controls: pass
- transient App Server catalog와 empty input schema: pass
- exact adapter/candidate lineage: pass
- protected auth home과 evaluator runtime document 분리: pass
- model/auth 호출: 0회

기존 117-byte `fs/readFile` positive check는 새 adapter가 사용하지 않지만, 다른
파일/config/traversal/process/walk/canonicalize 거부 검사는 계속 필수다. frozen
smoke executor의 canonical config 계약은 변경하지 않았다. 다음은 새 승인을 받은
비평가 Luna model probe 1회다. 이는 full tools-10 runner 호환성이나 성능 증거가 아니다.

## LOG-050 결과 — Luna model-facing MCP tool-use 성공

새 승인 아래 비평가 probe를 정확히 1회 실행했다. ChatGPT subscription auth gate와
모든 LOG-049 preflight가 통과했고, Luna trace에 완료된 `mcp_tool_call` item 1개가
기록됐다. 응답 주장도 `trace-tool-use-observed`와 일치했다. raw trace, tool
arguments/output, model final은 보존하지 않았고 자동 retry나 모델 fallback은 없었다.

이로써 local transient STDIO MCP의 model-facing 노출 blocker는 해소됐다. 하지만
현재 도구는 no-argument 고정 1-byte read뿐이다. Docker 내부 remote MCP, candidate
write, test 실행, frozen job 성공은 아직 검증되지 않았다. 다음은 이 성공을 full
evaluation 권한으로 과장하지 않고 목적별 최소 도구 contract를 model-free로 만드는
것이다.

## LOG-051 결과 — full-runner MCP contract model-free 검증

full-runner에는 다음 세 도구만 고정했다.

- `feynman_read_candidate`: 인자 없이 `candidate.py`만 읽음
- `feynman_write_candidate`: `content`만 받아 `candidate.py`만 씀
- `feynman_run_tests`: 인자 없이 `test_candidate.py`를 `python3 -B -I`로 실행

모델은 path, shell, argv, Docker image, network mode를 선택하지 않는다. test
adapter의 Docker argv는 `--network none`, `--read-only`, `--cap-drop ALL`,
`no-new-privileges`, `env -i`, candidate read-only mount로 고정된다. pinned Codex
image에 Python runtime이 없었던 첫 disposable 실행을 확인한 뒤 Debian 12 image에
`python3`를 설치했고, 새 image ID
`sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a`로 실제
Docker protocol preflight가 `full-runner-mcp-docker-preflight-passed`가 됐다.

Codex App Server catalog도 모델 호출·인증 없이 정확한 3개 도구와 schema를
`full-runner-mcp-contract-ready`로 확인했다. 이 결과는 full-runner 구조와 Docker
호환성만 입증하며 실제 model trace, tools-10 실행, baseline/Feynman 비교는 아직
입증하지 않는다. 상세 명령·관찰·제한은
[LOG-051](feynman-work-log/LOG-051-full-runner-mcp-contract-model-free-20260913.md)에
기록했다.

새 Docker image:

- 태그: `feynman-codex-remote:0.154.0-20260912`
- ID: `sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6`
- 실행 profile의 `image`와 `image_id` 모두 위 immutable ID를 사용한다.
- Windows CLI, server, job 모두 `codex-cli 0.154.0` 일치 확인.
- recipe는 `tooling/docker/codex-remote/Dockerfile`; 이전 로컬 ARM64 image를
  기반으로 하는 **로컬 업그레이드 recipe**이며 다른 머신용 범용 build가 아니다.
  .dockerignore와 COPY 없는 최소 context로 repo/auth 자료가 image에 들어가지 않는다.

## 확인한 RPC 계약과 보정

`environmentConfig/read`의 검사에서 통과한 최소 형태:

```json
{
  "cwd": "file:///run/candidate",
  "configPaths": [["file:///run/candidate/.feynman-diagnostic-absent.toml"]],
  "requirementsPaths": []
}
```

두 경로 목록을 모두 비우면 서버는 거부한다. flat string list가 아니라 중첩
경로 그룹을 요구한다. `cwd`, 각 그룹의 Windows 경로를 declared Linux mount로
변환하며, 상대 경로/보호 영역/parent traversal은 거부한다.
`fs/canonicalize.path` 변환도 추가했다. 보정 후 일반 모드 canonicalize는 성공했다.

**config 조회는 파일 내용을 읽을 수 있으므로 metadata-only로 간주하면 안 된다.**
guard는 존재하지 않음을 확인한 고정 sentinel만 config 경로로 허용한다.
실제 config/candidate/skill 파일을 config RPC로 읽는 우회는 차단한다.
`fs/canonicalize`, `fs/walk`, `process/start`를 무조건 허용하도록 바꾸지는 않았다.

## 현재 실패하는 선행 조건

1. `offset=0,len=1` 요청을 보냈지만 서버의 decoded 응답은 117 bytes였다.
   fixture `candidate.py` 크기도 117 bytes다. 기존 요청 인자만으로는 1바이트
   계약이 성립하지 않는다. 새 proxy는 응답 ID와 요청 method를 연결해 실제
   base64 decoded 길이를 검사하고 초과/불명확 응답을 **client 전달 전에 거부**한다.
   잘라서 성공처럼 보이게 하지 않는다. 이 검사는 응답 전달 경계의 보호이며
   서버 내부에서 1바이트만 읽게 만든 구현은 아직 아니다.
2. filesystem-only probe와 code-mode 모델의 도구 연결이 검증되지 않았다.
   `process/start` 일반 허용은 읽기 범위 제한을 무력화할 수 있으므로 하지 않는다.
   `fs/*` 서버 기능과 모델 도구 이름은 별개다.

`feynman_guarded_rpc_preflight.py`는 실제 guard의 positive/negative 경로를 검사한다.
현재 결과는 `blocked-byte-read-contract`; 전체 discovery 및 model tool readiness는
false다. 정상 검사 결과와 실패 조건을 함께 남기고 모델 요청을 하지 않는다.

`feynman_subscription_tool_use_probe.py`에는 실행 전 version gate, legacy security
control gate, exact-lineage transient catalog gate를 연결했다. CLI는
`--docker-config`, `--node-bin`, `--bounded-adapter`가 필수이며 `--preflight-only`는
auth/model 이전에 종료한다. 실제 exec에는 `--ignore-user-config`가 강제된다. 기존
일반 smoke executor까지 이 새 readiness gate가 통합됐다는 뜻은 아니며,
baseline/smoke 직접 실행도 보류한다.

## 다음 실행 단위

제한 adapter와 실제 exec override의 model-free 검증은 완료됐다. 새 명시적 승인
아래 Luna 비평가 model probe를 1회 실행해 trace의 MCP tool item을 확인한다.
실패 시 자동 반복하거나 Terra/Sol로 자동 fallback하지 않는다. 성공해도 일반
shell 권한이나 full evaluation 권한은 아직 없으므로, 다음에는 별도 full-runner
tool contract를 설계한다. 현재 checkpoint로 Feynman 효과 또는 baseline 비교
결과를 주장하지 않는다.

## LOG-052 결과 — existing tools-10 artifact chain 결속

기존 `C:\DevWorks\feynman-remote-compat-20260912-01`의 Luna/Terra/Sol
`runner-job.json`을 읽기 전용 입력으로 사용해 `tooling/feynman_full_runner_binding.py`
를 추가했다. 각 job은 먼저 기존 strict validator를 통과했고, 실제 candidate의
`candidate.py`/`test_candidate.py`를 사용한 full-runner catalog preflight를 모델 없이
별도 1회씩 실행했다. 기존 synthetic Docker preflight도 고정 image에 대해 재사용했다.

세 모델 모두 다음 manifest를 생성했다.

- verdict: `full-runner-mcp-artifact-chain-bound`
- case: `tools-10`, condition: `feynman-v05`
- native mount: 4개, `/run/candidate`, `/run/home`, `/run/codex`, `/run/temp`
- catalog/Docker preflight: 모두 true
- `model_calls=0`, `authentication_used=false`

기존 runner profile의 remote-exec image와 새 full-runner image
`sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a`는
서로 다르다. 이를 별도 필드로 기록했으며 기존 profile을 덮어쓰지 않았다. 따라서
이번 결과는 artifact lineage와 Windows mapping의 model-free 결속이지 실제 모델
turn, subscription auth gate 성공, baseline/Feynman 비교가 아니다. 산출물은
`C:\DevWorks\feynman-full-runner-binding-20260913-01` 아래에 저장됐다.

자동 검증은 새 binding unit 2개와 전체 `349 tests OK, 11 skipped`로 통과했다.
다음 단계는 binding에 연결된 candidate skill 노출·고정 command wiring을 모델 없이
검증하는 것이며, 그 전에는 실제 smoke나 baseline을 시작하지 않는다.

## LOG-056 결과 — executor wiring command-plan preflight

`tooling/feynman_subscription_smoke_exec.py`에
`prepare_full_runner_executor_wiring()`을 추가해 canonical executor가 실제 auth
gate 전에 두 단계 App Server skill discovery를 수행하도록 연결했다. 첫 discovery의
활성 non-candidate skill 경로는 disposable process 사이에서만 사용하고, 하나의
통합 transient `skills.config` override로 전달한다. protected control home이나
전역 config는 읽거나 수정하지 않는다.

별도 `tooling/feynman_subscription_executor_wiring_preflight.py`는 같은 helper로
command를 만들되 auth, thread/turn, model call을 시작하지 않는다. 실제 command
payload와 경로·프롬프트 원문을 artifact에 저장하지 않고, builder 결속과 override
개수만 기록한다. candidate boundary image와 full-runner adapter image는 서로 다른
역할이므로 digest를 별도 lineage로 유지한다.

세 모델 결과는
`C:\DevWorks\feynman-subscription-executor-wiring-20260913-01`에 저장됐다.

| 모델 | verdict | full-runner override | transient override | model/auth |
|---|---|---:|---:|---|
| gpt-5.6-luna | `subscription-executor-wiring-ready` | 13 | 1 | 0 / false |
| gpt-5.6-terra | `subscription-executor-wiring-ready` | 13 | 1 | 0 / false |
| gpt-5.6-sol | `subscription-executor-wiring-ready` | 13 | 1 | 0 / false |

새 schema 검증은 `schema-valid=3`, exact command/argv/path payload key 검사는
0건이었다. 이는 실행기 배선이 준비됐다는 뜻이지 ChatGPT subscription auth 성공,
실제 model turn, candidate tool selection 또는 Feynman 성능 근거가 아니다.
다음 사람 개입 지점은 보호된 평가 전용 로그인으로 auth gate를 별도 실행할지에
대한 승인과, auth 성공 후 실제 smoke를 시작할지에 대한 승인이다.

## LOG-053 결과 — exact skill exposure와 fixed test wiring

`tooling/feynman_skill_tool_wiring_preflight.py`가 LOG-052 binding을 실제
Luna/Terra/Sol candidate에 연결했다. Codex App Server의
`skills/list(cwds=[candidate], forceReload=true)`를 사용했으며 thread/turn/auth/model
요청은 시작하지 않았다.

첫 Luna 실행에서 빈 disposable `CODEX_HOME`에도 candidate 외 활성 skill 7개가
발견됐다. 이는 filesystem preflight와 host App Server의 실제 discovery가 다를 수
있다는 격리 결함이다. preflight는 이를 허용하지 않고 다음 two-pass로 보정한다.

1. 첫 App Server에서 활성 non-candidate skill path를 메모리에서만 수집한다.
2. 해당 path만 `skills.config` CLI override로 일시 비활성화한다.
3. 새 App Server에서 candidate skill set과 MCP catalog를 다시 검증한다.
4. 결과 artifact에는 disable path나 skill description을 보존하지 않는다.

세 모델 모두 최종 활성 candidate skill은 `feynman-thinking` 하나, 주변 skill은 0,
MCP tool은 fixed read/write/test 3개였다. adapter에는 write가 아니라 인자 없는
`feynman_run_tests`만 직접 호출했다. test는 의도된 buggy candidate 때문에
실패했지만, 명령은 network none에서 시작·종료됐고 `candidate.py` digest는
전후 동일했다. 따라서 verdict는 wiring 준비 완료인
`full-runner-skill-tool-wiring-ready`이며 candidate correctness를 뜻하지 않는다.

실제 executor는 아직 이 two-pass disable override와 full-runner override를 자신의
최종 `codex exec` 명령에 결속하지 않았다. 다음 model-free 작업은 executor command
builder에 동일 계약을 fail-closed로 연결하는 것이다. 그 전에는 실제 subscription
smoke나 baseline을 시작하지 않는다.

## LOG-054 결과 — subscription executor command builder 결속

기존 `feynman_subscription_smoke_exec.py` 내부의 고정 Codex argv 조립을
`build_codex_exec_command()`로 추출했다. executor 자체와 wiring preflight가 같은
함수를 사용하므로, model-free 검사에서 통과한 설정과 실제 실행 경로의 command
construction이 달라지는 위험을 줄였다.

세 모델의 실제 model-free preflight에서 full-runner MCP override 13개와 transient
skill-disable override 1개가 builder에 전달됐다. 최종 명령은 fixed controls와
stdin marker를 유지했고 MCP tool 3개가 확인됐다. 명령·prompt 원문은 artifact에
저장하지 않았다.

첫 schema 검증은 실제 full-runner override 개수 13개를 12개로 잘못 기대해 실패했다.
실행 경로에는 오류가 없었으며 schema 상수를 13으로 보정한 뒤 세 산출물 모두
`schema-valid=3`이 됐다. 관련 테스트 21개와 전체 354개 테스트가 통과했다.

이번 결과는 executor가 실제 모델을 실행할 권한을 얻었다는 뜻이 아니다. auth gate,
model turn, candidate tool selection, baseline/Feynman 비교는 여전히 미실행이다.
다음은 executor 호출부가 binding/adapter/Docker 입력 없이는 실행되지 않도록 하는
최종 fail-closed 연결이다.

## LOG-055 결과 — executor required inputs와 pre-auth lineage gate

`feynman_subscription_smoke_exec.py`의 canonical CLI에 full-runner binding, Node
adapter, Docker executable/config, immutable image ID를 모두 required로 추가했다.
executor는 structural preflight 직후 auth gate 전에 runner job/profile과 binding의
identity·digest·재생성 override를 비교한다. 일부 입력만 주어져도 auth 전에 거부한다.

검증된 full-runner override 13개는 공용 `build_codex_exec_command()`에 전달된다.
관련 unit 및 전체 `355 tests / 11 skipped`가 통과했다. 이번 변경은 실제 auth/model
호출이나 smoke 결과를 만들지 않았다. 다음은 이 입력 계약과 transient skill-disable
override를 실제 smoke command plan artifact에 model-free로 연결하는 것이다.
