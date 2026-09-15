# LOG-046 — 세 모델 추가, runtime 정렬, byte 응답 경계 결함

- 날짜: 2026-09-12 KST, 마지막 상태 확인 23:35:13 이후.
- repo: `C:\DevWorks\thinking-skills`, branch `feat/feynman-thinking-v0.5-draft`.
- 시작 HEAD `af798a3`; 시작 tree clean. ancestor와 repo에서 AGENTS.md 미발견.
- 사용자 요청: Luna에 Terra/Sol도 작업 모델로 추가하고 LOG-045의 해결 우선순위로
  후속 구현을 진행한다. `gpt-5.6 sol`은 `gpt-5.6-sol`로 정규화한다고 먼저 알렸다.
- 이번 실제 모델 호출 **0회**, 로그인 검사 0회. baseline/새 성능 평가 미실행.
- 기존 frozen Luna 자료, Docker image, 전용 로그인 홈을 보존했다.

## 1. 자료 확인과 모델 추가

OpenAI Docs 스킬과 model-migration reference를 읽었다. 공식 자료:

- [Codex models](https://learn.chatgpt.com/docs/models): 세 ID와 CLI 선택 방법 확인.
- [요청한 GPT-5.6 migration 안내](https://developers.openai.com/api/docs/guides/upgrading-to-gpt-5p6-sol):
  공식 안내로 redirect. API 사용 방식으로 전환하지 않았고 가격/계정 접근을 추론하지 않았다.

실제 read-only command: `git status --short`, ancestor `Get-Item ...AGENTS.md`,
`rg --files -g AGENTS.md`, `Get-Content`으로 skill/reference, smoke-plan, runner-job,
condition-workspace, profile, remote generator, RPC 검사/관련 tests 읽기.
`rg -n 'Dockerfile|docker build|npm install|0.153.4|0.154.0' docs/feynman-work-log --glob 'LOG-03*.md'`
등으로 기존 build/version 기록을 확인했다. 첫 PowerShell brace-glob 검색은
`rg: unrecognized file type: Format`으로 실패해 명시적 glob으로 보정했다.
존재하지 않는 `feynman_subscription_smoke_prepare.py` 조회도 실패했으며 실제
smoke-plan/condition-workspace/runner-job generator를 찾아 사용했다.

`feynman_subscription_models.py`에 세 정확한 ID를 등록하고 runner-job CLI help에
표시했다. 기존 generator는 원래 explicit model string을 지원하므로 호환 schema를
불필요하게 제한하지 않았다. model selection report는 자동 fallback/자동 실행,
계정 접근 검증, 전체 모델 도구 사용 검증을 모두 false로 명시한다.
기존 frozen 모델명을 바꾸지 않고 모델마다 별도 새 job을 준비했다.

## 2. 실제 경로와 runtime build

아래 변수는 실행 때 literal로 전달한 실제 절대 경로의 축약이다.

```powershell
$compatPython = 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe'
$compatDocker = 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
$compatDockerConfig = 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config'
$compatCodex = 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd'
$compatRoot = 'C:\DevWorks\feynman-remote-compat-20260912-01'
$compatEvaluator = "$compatRoot\gpt-5.6-luna\evaluator"
$compatOldImage = 'sha256:dab903a5999b1d3165a70de99147029809fa26d3cb1881b7c7790aac185a4726'
$compatImage = 'sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6'

& $compatCodex --version
& $compatDocker --config $compatDockerConfig image inspect $compatOldImage --format '{{.Id}} {{.Architecture}}'
& $compatDocker --config $compatDockerConfig run --rm --network none --read-only --user 1000:1000 --entrypoint sh $compatOldImage -c 'command -v codex; command -v npm; command -v node; uname -m'
& $compatDocker --config $compatDockerConfig build --pull=false -t feynman-codex-remote:0.154.0-20260912 tooling/docker/codex-remote
& $compatDocker --config $compatDockerConfig image inspect feynman-codex-remote:0.154.0-20260912 --format '{{.Id}}'
& $compatDocker --config $compatDockerConfig run --rm --network none --read-only --user 1000:1000 --entrypoint codex feynman-codex-remote:0.154.0-20260912 --version
```

Windows CLI 0.154.0; 이전 image ARM64, `aarch64`, npm/node/codex 존재.
새 recipe는 기존 immutable image에서 공식 `@openai/codex@0.154.0`만 설치한다.
COPY 없는 3.072kB context이며 `.dockerignore`는 recipe 외 항목을 제외한다.
build exit 0, 새 image 위 ID, server version 0.154.0 확인. 기존 태그는 보존했다.
legacy builder deprecation / readonly PATH-alias warning은 있었지만 실패는 아니었다.
image는 로컬 ARM64 기반 recipe다. 다른 머신에서 같은 base가 없으면 별도 준비가
필요하며 범용 재현 image라고 주장하지 않는다. image를 registry에 push하지 않았다.

```powershell
& $compatPython -m tooling.feynman_rpc_compat_prepare --root C:\DevWorks\thinking-skills --profile C:\DevWorks\feynman-smoke-gpt-5.6-luna-20260910-01\boundary-profile.json --output $compatRoot --control-home C:\Users\wotmd\.codex-feynman-eval --real-home C:\Users\wotmd --image-id $compatImage --codex-cli 'codex-cli 0.154.0'
```

새 factory는 겹침/기존 output을 거부하고 세 모델의 독립 fixture/job/environment를
생성했다. source runtime allowlist 및 public fixture만 candidate에 제공한다.
plan에는 원래 frozen 2-condition 계약이 남지만 baseline fixture/모델은 실행하지
않았다. 새 profile의 `image`와 `image_id`는 둘 다 위 immutable ID다.
로그인 홈의 내용은 읽거나 복사하지 않았고 새 environments.toml은 evaluator에만 저장했다.

## 3. RPC 요청 형식 진단과 수정

기본 실제 command(-01 및 -03):

```powershell
& $compatPython -m tooling.feynman_rpc_discovery_diagnostic --job "$compatEvaluator\runner-job.json" --profile "$compatRoot\boundary-profile.json" --remote "$compatEvaluator\environments.toml" --docker-config $compatDockerConfig --output "$compatEvaluator\discovery-01.json"
& $compatPython -m tooling.feynman_rpc_discovery_diagnostic --job "$compatEvaluator\runner-job.json" --profile "$compatRoot\boundary-profile.json" --remote "$compatEvaluator\environments.toml" --docker-config $compatDockerConfig --output "$compatEvaluator\discovery-03.json"
```

-02, -04, -05, -06, -07, -08은 PowerShell here-string을 Python stdin에 전달해
동일 `diagnostic.run(...)`을 호출했다. 각 suffix는 별도 파일이며 덮어쓰지 않았다.
다음이 공통 실제 호출이다(출력 파일 suffix와 선택 label만 각 표 항목처럼 변경).

```python
from pathlib import Path
import tooling.feynman_rpc_discovery_diagnostic as diagnostic
base = Path(r'C:\DevWorks\feynman-remote-compat-20260912-01')
evaluator = base / 'gpt-5.6-luna/evaluator'
result = diagnostic.run(
    evaluator / 'runner-job.json', base / 'boundary-profile.json',
    evaluator / 'environments.toml',
    Path(r'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config'),
    evaluator / 'discovery-08.json',
)
for mode, records in result['modes'].items():
    for label in ('config-path-group', 'requirements-path-group'):
        print(mode, label, records[label])
```

| artifact | 당시 고정 입력과 관찰 |
|---|---|
| -01 | 같은 최소 입력을 새 0.154.0 server에 전달. 오류 재현, version 정렬만으로 해결되지 않음 |
| -02 | fixed synthetic 오류 문구만 표시. 빈 config lists 거부, Windows URI의 Linux 경로 거부 확인 |
| -03 | cwd/canonicalize mapping 추가. 일반 canonicalize 성공, flat config list는 invalid type |
| -04 | fixed invalid-type 문구에서 string이 아니라 sequence가 필요함을 확인 |
| -05 | 두 요소 sequence의 null/false 항목은 string 요구 오류 |
| -06 | 안전한 candidate URI 두 개를 포함한 group으로 config 성공 |
| -07 | label/path 위치만으로 의미를 특정할 수 없었음. requirements flat list도 거부 |
| -08 | URI 하나를 포함한 nested group으로 config/requirements 모두 일반·guarded 성공 |

위 table은 intermediate 입력의 의미를 명시한다. 최종 코드에서는 불필요한
tuple/label 추측 입력을 제거하고 유효한 경로 그룹과 최소 negative case만 남겼다.
-02/-04/-05/-06의 wrapper는 `diagnostic.summarize`를 임시로 감싸서 **고정 synthetic
오류**의 message만 최대 500자로 표시했다. auth/config 결과/파일 본문/모델 trace는
표시하지 않았다. 표시한 문구: 빈 목록 거부, invalid type, Windows URI의 Linux
거부, 존재하지 않는 고정 fixture의 not-found. 원본 오류 본문은 artifact로 저장하지 않았다.

보정:

- `environmentConfig/read.cwd`, 중첩 `configPaths`/`requirementsPaths`의 각 path,
  `fs/canonicalize.path`를 명시적으로 매핑한다. arbitrary command 문자열은 변경하지 않는다.
- host-side `..`/encoded traversal도 거부한다. 이전 host mapping의 검증 공백을 닫았다.
- config 조회는 전체 파일을 읽을 수 있으므로 **metadata-only라는 이전 표현을 정정**한다.
  guarded config 조회는 사전에 부재를 확인한 고정 candidate sentinel에만 허용한다.
  임의 candidate/skill/home config 읽기를 통한 one-byte 우회는 거부한다.
- canonicalize/walk/process를 blanket allowlist로 확장하지 않았다.

## 4. 모델 없는 도구 metadata 확인

```powershell
& $compatCodex debug --help
& $compatCodex exec --help
& $compatCodex debug prompt-input --help
& $compatCodex debug models --help
```

실제 prompt-input 렌더링은 실행하지 않았다. bundled 모델 목록만 다음 절차로 조회했다.
별도 빈 `$compatRoot\catalog-home`을 만들고 `_safe_probe_env`로 환경을 축소,
그 경로를 `CODEX_HOME`으로 지정한 subprocess에서 다음 명령을 실행했다.

```text
C:\Users\wotmd\AppData\Roaming\npm\codex.cmd debug models --bundled
```

전체 stdout은 메모리 JSON으로만 처리했다. 첫 조회는 대상 세 ID의 shell/visibility
및 field 이름만, 두 번째는 `slug`, `shell_type`, `tool_mode`, `node_repl_disabled`,
`node_repl_auto_review_required`, `experimental_supported_tools`만 출력했다.
base instructions/model messages를 출력·보존하지 않았다. 계정 login home을 사용하지
않았으며 --bundled는 refresh를 건너뛰는 옵션임을 help에서 먼저 확인했다.

세 모델 공통: `shell_type=unified_exec`, `tool_mode=code_mode_only`,
`node_repl_disabled=false`, `node_repl_auto_review_required=false`, experimental tools `[]`.
이 metadata는 실제 session tool catalog나 계정 접근 증거가 아니다. 다만 기존
filesystem-only prompt/guard와 code-mode 모델의 실행 연결을 별도로 검증해야 하는
구체적 근거이며 다른 모델 이름으로만 재시도할 근거는 아니다.

## 5. 실제 바이트 경계 결함과 fail-closed 보강

`feynman_rpc_version_gate.py`는 profile image ID, actual control/server CLI,
job version 일치를 검사한다. `feynman_guarded_rpc_preflight.py`는 실제 guard로
metadata/absent config/one-byte read와 범위 밖 file/config/traversal/process 차단을 검사한다.

```powershell
& $compatPython -m tooling.feynman_rpc_version_gate --job "$compatEvaluator\runner-job.json" --profile "$compatRoot\boundary-profile.json" --codex-bin $compatCodex --docker-config $compatDockerConfig --docker $compatDocker --output "$compatEvaluator\runtime-versions.json"
& $compatPython -m tooling.feynman_guarded_rpc_preflight --job "$compatEvaluator\runner-job.json" --profile "$compatRoot\boundary-profile.json" --remote "$compatEvaluator\environments.toml" --docker-config $compatDockerConfig --output "$compatEvaluator\guard-controls-01.json"
```

version gate는 `rpc-runtime-versions-matched`. guard -01은 실제 응답이 1바이트가
아니어서 실패했다. -02는 같은 `verify(...)` 함수를 stdin wrapper에서 호출해
`ValueError`의 고정 검사명만 표시: `guard response did not contain exactly one byte`.

기존 len=1 request 삽입만으로 server가 범위를 지킨다고 가정한 결함을 확인했다.
proxy에 request ID→method 결속과 실제 base64 응답 길이 검사를 추가했다.
초과/형식불명 result는 raw payload를 client에 보내지 않고 고정 오류로 반환한다.
잘라서 성공처럼 보이게 하지 않는다. ordinary mode의 파일 읽기 계약은 바꾸지 않는다.

```powershell
& $compatPython -m tooling.feynman_guarded_rpc_preflight --job "$compatEvaluator\runner-job.json" --profile "$compatRoot\boundary-profile.json" --remote "$compatEvaluator\environments.toml" --docker-config $compatDockerConfig --output "$compatEvaluator\guard-controls-03.json"
& $compatPython tooling/feynman_subscription_tool_use_probe.py --plan "$compatRoot\frozen-subscription-smoke-plan.json" --ordinal 1 --evaluator-case "$compatEvaluator\case.json" --runner-job "$compatEvaluator\runner-job.json" --boundary-profile "$compatRoot\boundary-profile.json" --remote-environment "$compatEvaluator\environments.toml" --output-dir "$compatEvaluator\blocked-entrypoint-01" --codex-bin $compatCodex --docker-config $compatDockerConfig --timeout-seconds 240
Get-Content -LiteralPath "$compatEvaluator\blocked-entrypoint-01\guarded-readiness-rpc.json"
Get-Item -LiteralPath "$compatRoot\gpt-5.6-luna\candidate\candidate.py" | Select-Object Name,Length
```

- guard -03: `blocked-byte-read-contract`. positive initialize/metadata/config와
  negative 다른 파일/config/traversal/process/walk/canonicalize 차단은 성공.
- 실제 probe entrypoint에도 live version/guard gate를 연결했다. 호출 결과:
  `guarded model-facing tool contract is not ready; no model call started`.
  이는 **모델 probe 실행이 아니라 model-free 선행 조건에서 차단된 진입점 검사**다.
- 실제 auth check 및 model subprocess 이전에 실패하도록 regression test로 확인했다.
- 최종 telemetry: request 11/forwarded 5, request rejections 6, response rejections 1,
  **rejected decoded read size 117 bytes**. fixture file size도 117 bytes.
  응답 전달 전에 차단됐으며 bytes 자체는 출력/보존하지 않았다.
- 이전 실제 모델 probe에는 fs/readFile이 0회였다. 이전 모델에게 이 경로로
  본문이 전달됐다고 주장할 증거는 없다. 이번 diagnostic은 model-free다.
- server 내부의 실제 읽기를 1바이트로 제한한 구현은 아직 아니다. 읽기 범위가
  보장됐다는 주장과 응답을 fail-closed로 차단했다는 사실을 구분한다.

## 6. 검증 범위

실제 명령:

```powershell
& $compatPython -m unittest tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_path_proxy tests.test_feynman_rpc_discovery_diagnostic tests.test_feynman_subscription_tool_use_probe
& $compatPython -m unittest tests.test_feynman_rpc_compatibility tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_path_proxy tests.test_feynman_rpc_discovery_diagnostic tests.test_feynman_subscription_tool_use_probe
& $compatPython -m unittest tests.test_feynman_rpc_compatibility tests.test_feynman_subscription_tool_use_probe
& $compatPython -m unittest discover -s tests -p 'test_*.py'
& $compatPython -m compileall -q tooling tests
& $compatPython tooling/feynman_subscription_tool_use_probe.py --help
git diff --check
& $compatDocker --config $compatDockerConfig ps -a --filter name=feynman --format '{{.Names}} {{.Status}}'
```

- intermediate targeted: 28, 39 tests OK; final focused: 17 tests OK.
- full suite: **325 tests, 10 skipped, OK**, 14.487초 (315 passed).
- compileall/help/diff check exit 0. Git global-ignore/CRLF warning은 비치명적.
- 세 모델의 각 새 plan/case/job/profile/environments를 `preflight_files(...)`에
  명시적으로 전달한 구조 검사: 모두 `ready-for-local-chatgpt-session-check`.
  auth/tool/runtime 전체 성공으로 승격하지 않는다.
- Feynman container 목록 0행. --rm 진단/build intermediate 컨테이너는 정리됐고
  기존 image/volume/로그인 홈/과거 artifact는 삭제하지 않았다.

## 7. 남은 작업과 저장 상태

완료: 세 모델 선택 및 독립 artifact, 동일 버전 환경, config/canonicalize mapping,
traversal 및 config 내용 우회 차단, 실제 response-size 검사, live gate의 probe 결속.
미완료: 실제 server-side bounded read와 code-mode 모델 도구를 연결하는 제한 adapter,
완전한 discovery, 실제 세션 tool catalog/계정 접근/모델 tool use, baseline/성능 평가.

다음 단위는 고정 경로·symlink/traversal·읽기 범위·응답 크기·임의 argv 차단이
검증되는 제한 read adapter다. 일반 process/shell을 열거나 다른 모델로 자동
재시도하지 않는다. 기존 generic smoke executor로 우회 실행도 하지 않는다.

이번 작업은 OpenAI Platform API/API key, auth/token 파일 읽기·복사·해시·업로드,
전체 환경 덤프를 사용하지 않았다. Docker image는 공식 npm package 설치만 했다.
개발 문서는 baseline/candidate 입력에 포함하지 않았다. main merge/force push 없음.
구현/log commit과 일반 push 결과는 아래 저장 checkpoint에서 기록한다.

## 8. 저장 checkpoint

구현 commit **`85a2815`** (`fix: gate subscription probes on runtime and actual read bounds`),
18 files changed. 아래 명령으로 stage/diff/commit/push했고 모두 exit 0이었다.

```powershell
git add -- docs/feynman-codex-handoff.md docs/feynman-codex-resume-prompt.md docs/feynman-work-status.md docs/feynman-remote-compatibility.md docs/feynman-work-log/LOG-046-three-model-runtime-and-read-boundary-20260912.md tests/test_feynman_subscription_tool_use_probe.py tests/test_feynman_rpc_compatibility.py tooling/feynman_rpc_discovery_diagnostic.py tooling/feynman_rpc_path_mapping.py tooling/feynman_rpc_path_proxy.py tooling/feynman_runner_job.py tooling/feynman_subscription_tool_use_probe.py tooling/feynman_guarded_rpc_preflight.py tooling/feynman_rpc_compat_prepare.py tooling/feynman_rpc_version_gate.py tooling/feynman_subscription_models.py tooling/docker/codex-remote/Dockerfile tooling/docker/codex-remote/.dockerignore
git diff --cached --check
git commit -m 'fix: gate subscription probes on runtime and actual read bounds'
git push origin feat/feynman-thinking-v0.5-draft
```

remote는 `af798a3..85a2815`로 갱신됐다. 마지막 전체 targeted 묶음도 41 tests OK.
hosted CI 결과는 조회하지 않았으므로 이번 commit의 CI green을 주장하지 않는다.
이 저장 사실을 기록하는 문서 전용 후속 commit/push 및 최종 확인 명령:

```powershell
git add -- docs/feynman-work-log/LOG-046-three-model-runtime-and-read-boundary-20260912.md
git diff --cached --check
git commit -m 'docs: record three-model compatibility checkpoint'
git push origin feat/feynman-thinking-v0.5-draft
git status --short
git log -1 --oneline
git ls-remote origin refs/heads/feat/feynman-thinking-v0.5-draft
```

최종 SHA는 self-referential hash를 이 문서에 삽입하지 않고 Git 결과로 확인한다.
현재 차단은 사용자 재로그인이나 모델 ID 미제공이 아니라 위 제한 read/tool adapter의
미완성이다. 다음 개발 세션은 이 checkpoint에서 시작하며 자동 model retry를 하지 않는다.
