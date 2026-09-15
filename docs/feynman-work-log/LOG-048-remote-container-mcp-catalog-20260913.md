# LOG-048 — remote container MCP catalog의 model-free 확인

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `62db435`; 시작 tree는 LOG-047 변경 이후 clean
- 목적: LOG-047의 다음 한 행동인 새 Docker image와 격리 `/run/codex` 설정에서 MCP catalog를 확인한다.
- 모델 호출: 0회. ChatGPT auth gate: 0회. protected control home: 미접근.

## 구현

추가한 파일:

- `tooling/feynman_remote_mcp_catalog_preflight.py`
- `tests/test_feynman_remote_mcp_catalog_preflight.py`

preflight는 다음을 고정한다.

- image는 mutable tag가 아닌 `sha256:<64 hex>`만 허용한다.
- Docker config는 사용자 기본 설정이 아닌 명시된 empty config directory만 사용한다.
- candidate는 public fixture의 `candidate.py`가 있는 별도 디렉터리다.
- container는 `network=none`, `read-only`, `cap-drop=ALL`, `no-new-privileges`, user `1000:1000`으로 실행한다.
- `/run/codex`에는 새 MCP config만 만들고, `/run/home`과 candidate는 별도 scratch/mount다.
- App Server에는 `initialize`와 `mcpServerStatus/list(detail=toolsAndAuthOnly)`만 보낸다. thread/turn은 시작하지 않는다.
- 결과에는 server name, runtime status, tool names, 고정 schema booleans만 남기며 auth status·description·arguments·tool output은 저장하지 않는다.

첫 구현에서 Docker config를 file로 검사해 preflight가 exit 2였다. 실제 Docker `--config` 대상이 directory임을 확인하고 directory 검사로 수정했다. 첫 실패 root는 덮어쓰지 않았고 새 root에서 재실행했다.

후속 검토에서 candidate 부모 경로의 symbolic link도 허용하지 않도록 경로 구성요소 검사를 보강했다. mutable Docker tag를 거부하고 immutable image digest와 전용 Docker config directory를 요구하는 조건은 유지했다.

## 실제 검증

실행 명령:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_remote_mcp_catalog_preflight tests.test_feynman_mcp_catalog_preflight
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_remote_mcp_catalog_preflight --docker 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --image 'sha256:b9f516e194dd3c5ca240939eed6861ae66b8baab78962a239b86e10d179eb8d2' --candidate 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\candidate' --output-root 'C:\DevWorks\feynman-remote-compat-20260913-02' --output 'C:\DevWorks\feynman-remote-compat-20260913-02\remote-mcp-catalog.json' --timeout-seconds 30
```

관찰:

- targeted tests: `4 tests OK`.
- preflight verdict: `remote-container-mcp-catalog-visible`.
- image ID: `sha256:b9f516e194dd3c5ca240939eed6861ae66b8baab78962a239b86e10d179eb8d2` (`arm64/linux`).
- server 1개, tool `feynman_read_probe_byte` 1개, empty input schema 확인.
- `model_calls=false`, `thread_started=false`, `turn_started=false`, `authentication_used=false`, `network_mode=none`.
- report: `C:\DevWorks\feynman-remote-compat-20260913-02\remote-mcp-catalog.json`.
- Feynman container는 종료 후 남지 않았다.

## 해석과 한계

이번 결과는 **동일 Docker runtime 안에서 Codex App Server가 MCP adapter를 catalog에 등록할 수 있음**을 입증한다. 기존 canonical protected control home의 `environments.toml`에 이 adapter를 연결했다는 뜻은 아니며, `codex exec` ChatGPT subscription session의 실제 모델 prompt/tool catalog 또는 model tool call을 입증하지도 않는다.

one-byte adapter는 진단용이다. tools-10의 전체 파일 읽기·수정·테스트 실행을 대체하지 않으므로 frozen smoke와 baseline에는 연결하지 않았다. 다음에는 이 model-free 결과를 실행 gate에 반영할 때 canonical remote config를 덮어쓰지 않는 별도 diagnostic route를 설계해야 한다.

## 저장 상태

- 이번 변경은 아직 commit/push 전이다.
- 최종 회귀검증 시점에는 `332 tests OK, 10 skipped`, `compileall` exit 0, `git diff --check` exit 0이다.
- 기존 image·artifact·전용 로그인 홈은 삭제·수정하지 않았다.
- 다음 단계는 **보호된 로그인 홈을 건드리지 않고, 실제 `codex exec` 경로가 사용할 격리 diagnostic config에서 catalog와 bounded adapter의 lineage를 연결하는 설계 검토**다. 이 연결이 사람의 인증 또는 canonical config 변경을 요구하면 중단하고 요청한다.
