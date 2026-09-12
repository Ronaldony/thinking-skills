# LOG-049 — protected auth home을 보존한 transient MCP exec preflight

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `f391249660067b81580db885da4041729998dbf3`
- 시작 상태: clean, 원격 feature branch와 일치
- 구현 commit: `49214500ba959a14b0063d4d72bbb9a0e452fa4b`
- 사용자 환경: Windows PowerShell, Python `3.12.10` ARM64, Node `v24.14.1`, Codex CLI `0.154.0`
- 모델 호출: 0회. auth gate 호출: 0회. Platform API/API key: 미사용.

시작 확인 명령:

```powershell
git status --short --branch
git log -3 --oneline --decorate
Get-Command node
node --version
& 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' exec --help
& 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' app-server --help
```

적용되는 상위/저장소 `AGENTS.md`는 없었다. branch와 원격이 `f391249`에서
일치했고 사용자 로컬 변경은 없었다.

## 목적과 공식 계약 확인

LOG-048 다음 행동은 protected control `CODEX_HOME`을 수정하지 않고 실제
`codex exec`에 bounded MCP를 연결할 수 있는지 확인하는 것이었다.

공식 Codex 문서에서 다음을 확인했다.

- CLI flag와 `-c/--config` override가 config precedence의 최상위다.
- `-c`는 dotted key와 TOML 값을 받아 한 실행에만 임의 설정을 덮어쓴다.
- STDIO MCP는 `command`, `args`, `env`, `cwd`, `required`, `enabled_tools`,
  timeout 및 approval mode를 설정할 수 있다.

로컬 `codex exec --help`에서 0.154.0 전용 안전장치도 확인했다.

```text
--ignore-user-config
Do not load `$CODEX_HOME/config.toml`; auth still uses `CODEX_HOME`
```

따라서 protected 홈을 인증 출처로 유지하면서 config 파일은 읽지 않고, 고정 MCP
설정을 CLI override로만 주입하는 diagnostic route를 선택했다. project `.codex`
설정과 protected `config.toml`/`environments.toml` 수정은 사용하지 않았다.

공식 자료:

- https://learn.chatgpt.com/docs/config-file/config-basic
- https://learn.chatgpt.com/docs/config-file/config-advanced
- https://learn.chatgpt.com/docs/extend/mcp?surface=cli

## 구현

추가/수정 파일:

- `tooling/feynman_transient_bounded_mcp.py`
- `tooling/feynman_mcp_catalog_preflight.py`
- `tooling/feynman_subscription_tool_use_probe.py`
- `tests/test_feynman_transient_bounded_mcp.py`
- `tests/test_feynman_mcp_catalog_preflight.py`
- `tests/test_feynman_subscription_tool_use_probe.py`

새 builder는 Node executable, adapter, candidate와 `candidate.py`가 모두 실재하고
symlink 구성요소가 없는지 검사한다. 모델이 선택할 인자는 없으며 server/tool,
절대 실행 경로, tool allowlist, approval mode, timeout, 고정 파일을 11개 CLI
override로 고정한다. adapter 및 candidate digest만 sanitized lineage에 남기고
path/환경값/파일 본문은 report에 남기지 않는다.

catalog preflight는 새 빈 `CODEX_HOME`에서만 transient mode를 허용한다. 기존 파일이
하나라도 있으면 App Server 시작 전에 실패한다. 실제 tool-use probe는 같은 builder와
`codex exec --ignore-user-config`를 사용한다.

기존 exec-server `fs/readFile`은 117 bytes를 읽어 proxy가 차단한 상태다. 새 probe는
그 read 경로를 사용하지 않는다. 다만 다른 파일/config/traversal/process/walk/
canonicalize 거부 등 기존 security control은 계속 model-free gate로 요구한다.
`--preflight-only`는 이 모든 gate와 transient catalog까지 실행한 뒤 auth/model 이전에
종료한다.

frozen smoke executor의 canonical remote 규칙은 바꾸지 않았다. 비평가적 probe만
protected `control_codex_home`을 향후 인증 출처로 유지하고, evaluator의 digest-검증된
`environments.toml`을 Docker 경계 문서로 사용하는 분리 검사를 갖는다.

## 실제 명령과 관찰

### 1. 로컬 help와 model-free standalone catalog

```powershell
& 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' exec --help
& 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' app-server --help
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_mcp_catalog_preflight --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --codex-home 'C:\DevWorks\feynman-transient-mcp-20260913-01\codex-home' --output 'C:\DevWorks\feynman-transient-mcp-20260913-01\transient-mcp-catalog.json' --node-bin 'C:\Program Files\nodejs\node.exe' --bounded-adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_bounded_read_adapter.mjs' --candidate 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\candidate' --timeout-seconds 30
```

관찰:

- verdict: `bounded-mcp-catalog-visible`
- server/tool 각 1개, empty input schema
- config transport: `cli-overrides`; user config file required: false
- model/auth: 0회
- adapter SHA-256: `2d3b41015f2ed859e43214732f0eef462881a645f9a48689f301a5379af6ce61`
- candidate SHA-256: `fdd57e3f10146bfe0ecdc7a41d33d20c2b3dfbcb51382aaa1a35fc7821582aab`

### 2. 전체 preflight의 두 fail-closed 경로

첫 전체 실행은 evaluator의 `environments.toml`을 주었고 기존 canonical 검사에서
`remote environment must be the canonical control CODEX_HOME/environments.toml`로
종료했다. artifact `...\evaluator\transient-preflight-01`은 보존했다. 이 시점까지
version/Docker/legacy guard/transient catalog는 실행됐지만 auth/model은 시작하지 않았다.

두 번째 실행은 protected canonical 경로를 직접 전달했지만 내용을 출력하지 않았다.
기존 protected 문서는 새 evaluator/profile과 달라
`environments.toml differs from canonical runner-job/profile remote exec document`로
fail-closed 됐다. artifact `...\evaluator\transient-preflight-02`는 보존했고 protected
파일을 덮어쓰지 않았다. 이 충돌을 근거로 diagnostic 전용 auth/runtime 분리를 구현했다.

### 3. 실제 Luna model-free 전체 preflight

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_subscription_tool_use_probe --plan 'C:\DevWorks\feynman-remote-compat-20260912-01\frozen-subscription-smoke-plan.json' --ordinal 1 --evaluator-case 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\case.json' --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote-environment 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\environments.toml' --output-dir 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\transient-preflight-03' --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --node-bin 'C:\Program Files\nodejs\node.exe' --bounded-adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_bounded_read_adapter.mjs' --timeout-seconds 240 --preflight-only
```

결과:

- verdict: `ready-for-subscription-tool-use-probe`
- structural: `ready-for-local-chatgpt-session-check`
- legacy RPC security controls: ready; legacy 117-byte positive read는 미사용
- transient MCP catalog: visible, exact lineage 일치
- model calls: 0, authentication used: false
- protected control home modified: false
- 종료 후 `docker ps -a --filter name=feynman-`: 0개
- artifact: `...\evaluator\transient-preflight-03`

## 회귀 검증과 저장 상태

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_transient_bounded_mcp tests.test_feynman_mcp_catalog_preflight tests.test_feynman_subscription_tool_use_probe
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m compileall -q tooling tests
git diff --check
```

- targeted: `16 tests OK`
- full: `340 tests OK, 10 skipped`
- compileall: exit 0
- diff check: exit 0
- 구현 commit: `49214500ba959a14b0063d4d72bbb9a0e452fa4b`
- 문서 commit: `d6603c233cc82c6ab1551661a6fc06170233db98`
- 첫 push 뒤 local/remote feature SHA가 모두 `d6603c233cc82c6ab1551661a6fc06170233db98`로 일치했다.

## push 후 CI reference 결함과 수정

`d6603c2`의 PR workflow를 한 번 조회했을 때 core/docker/subscription/unit은
success였고 codex/remote-exec은 진행 중, remote-patch는 failure였다. 실패 로그의
마지막 원문은 다음과 같았다.

```text
Error: No such object: feynman-tool-mock-remote-patch-34706244436-1
```

최근 remote-patch 실행 5개가 같은 failure였으므로 이번 MCP 변경의 회귀가 아니라
기존 reference 수집 순서의 결함으로 판정했다. canonical remote Docker 명령은
종료 시 정리되는 `--rm`을 사용하지만 workflow가 `codex exec` 종료 뒤 컨테이너를
inspect하려 했다.

production의 `--rm`을 제거하지 않았다. 대신 다음 두 workflow에서 Codex 실행 전에
bounded inspect watcher를 시작해 컨테이너가 실행 중일 때 atomic snapshot을 저장하고,
종료 뒤 컨테이너 존재를 가정한 `docker inspect`를 제거했다.

- `.github/workflows/validate-feynman-remote-patch-reference.yml`
- `.github/workflows/validate-feynman-remote-exec-reference.yml`

watcher는 최대 200회, 0.05초 간격으로 이름이 고정된 컨테이너를 찾는다. 성공 시
임시 JSON을 rename하고 종료하며, 시간 내 snapshot을 못 얻으면 workflow가 실패한다.
cleanup은 watcher PID도 종료한다.

검증:

```powershell
python -c "import yaml, pathlib; [yaml.safe_load(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['.github/workflows/validate-feynman-remote-patch-reference.yml','.github/workflows/validate-feynman-remote-exec-reference.yml']]; print('yaml-ok')"
python -m unittest discover -s tests
git diff --check
```

- YAML parse: `yaml-ok`
- full: `340 tests OK, 10 skipped`
- diff check: exit 0
- workflow fix commit/push 및 새 CI 결과는 이 기록 이후 완료한다.

## 미완료와 다음 한 행동

이번 checkpoint는 실제 `codex exec`가 사용할 동일 transient MCP override와 모든
model-free gate가 준비됐음을 입증한다. 실제 모델 tool-call 증거는 아직 없고, 실제
evaluation runner의 전체 read/write/test 권한 문제도 해결하지 않았다.

다음 한 행동은 Luna에서 **비평가적 구독 모델 probe 1회**를 새로 명시적 승인받아
`--preflight-only`를 제거하고 실행하는 것이다. 이전 승인 횟수는 소진된 것으로
취급하며 자동 반복하지 않는다. 성공해도 baseline이나 frozen evaluation을 자동
시작하지 않는다.
