# LOG-047 — 제한 읽기 adapter와 MCP catalog의 model-free 검증

- 시각: 2026-09-13 01:06 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `e80dd3b`; 시작 dirty 상태: clean
- 목적: LOG-046의 두 blocker 중 `fs/readFile`의 실질적 1바이트 제한과 모델-facing 도구 연결을 분리해, 모델 호출 없이 다음 단계까지 진행한다.
- 정책: ChatGPT subscription 경로만 유지, OpenAI Platform API/API key 미사용, protected `C:\Users\wotmd\.codex-feynman-eval` 미접근, baseline/evaluator 문서 candidate 미전달.

## 1. 선행 계약 확인

실행한 명령:

```powershell
& 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --version
& 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' app-server --help
& 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' app-server generate-json-schema --help
```

관찰:

- CLI는 `codex-cli 0.154.0`이다.
- App Server의 `generate-json-schema`가 실제 설치된 CLI에 존재한다.
- 생성한 version-specific schema에서 App Server `fs/readFile`은 필수 `path`만 받고 반환은 `dataBase64`이며 `offset`/`len`은 계약 필드가 아니다.
- 동일 버전의 현재 exec-server diagnostic에서도 `offset=0,len=1`을 넣었지만 117-byte 응답을 관찰했다. App Server schema와 exec-server schema가 같다고 확정하지 않으며, 기존 응답 보호 gate는 유지한다.

schema 생성은 저장소 내부 임시 디렉터리에서 blank `CODEX_HOME`으로만 수행했고, 원문 schema를 source/evaluator artifact로 사용하지 않는다.

## 2. 제한 읽기 adapter 구현

변경 파일:

- `tooling/docker/codex-remote/feynman_bounded_read_adapter.mjs`
- `tooling/docker/codex-remote/Dockerfile`
- `tooling/docker/codex-remote/.dockerignore`
- `tooling/feynman_mcp_catalog_preflight.py`
- `tests/test_feynman_bounded_read_adapter.py`
- `tests/test_feynman_mcp_catalog_preflight.py`

구현 이유:

- 기존 remote `fs/readFile`의 요청 인자만 보정하는 방법으로는 server-side read bound를 입증할 수 없었다.
- 새 adapter는 model-facing MCP STDIO 도구 `feynman_read_probe_byte` 하나만 노출한다.
- 모델은 path, offset, command를 전달할 수 없다. 실행 환경이 고정한 root/file만 사용한다.
- 시작 시 root/file의 절대 경로·root 하위 여부·symbolic link component·directory/regular-file 조건을 검사한다.
- 호출은 process당 1회, 실제 `fs.readSync`는 최대 1 byte, offset은 0으로 고정한다.
- 반환에는 `byteBase64`와 `bytesRead`만 있고, 전체 파일·경로·환경·인자·실패 payload를 기록하지 않는다.
- 이는 diagnostic adapter이며 tools-10의 전체 읽기·수정·실행 능력을 제공하지 않는다. 따라서 frozen smoke나 baseline을 이 adapter로 실행하지 않았다.

## 3. 검증 결과

### Local protocol test

실행:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_bounded_read_adapter tests.test_feynman_rpc_compatibility tests.test_feynman_rpc_path_proxy
node --check tooling/docker/codex-remote/feynman_bounded_read_adapter.mjs
git diff --check
```

처음 Node subprocess에 비밀 없는 Windows system variables가 빠져 CSPRNG 초기화가 exit 134였다. 전체 환경을 넘기지 않고 `PATH/SystemRoot/WINDIR/ComSpec/PATHEXT/TEMP/TMP`만 테스트 환경에 추가했다. 이후 `22 tests OK`, Node syntax check exit 0, diff check exit 0.

### Docker protocol test

첫 build는 build context 밖의 adapter를 `COPY`하려 해 exit 1이었다. adapter를 recipe의 명시적 context로 이동한 뒤 Docker Engine 외부 권한을 1회 승인받아 다음을 실행했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' build --pull=false -t feynman-codex-remote:0.154.0-bounded-read-20260913 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote'
```

관찰: build exit 0, image ID `sha256:b9f516e194dd3c5ca240939eed6861ae66b8baab78962a239b86e10d179eb8d2`, `arm64/linux`; container 내부 Codex 0.154.0 및 adapter syntax check exit 0. JSON-RPC initialize/tools-list 성공, 대상 tool 1개만 노출. 첫 tools/call은 `bytesRead=1`, 두 번째는 `bounded read call limit reached`로 거부했다. public candidate 전체 본문은 출력·저장하지 않았다.

### Codex App Server MCP catalog test

blank `C:\DevWorks\thinking-skills\.tmp-feynman-mcp-home`에만 MCP 설정을 두고 `codex app-server`를 실행했다. `mcpServerStatus/list(detail=toolsAndAuthOnly)` 결과는 sanitized report로만 저장했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_mcp_catalog_preflight --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --codex-home 'C:\DevWorks\thinking-skills\.tmp-feynman-mcp-home' --output 'C:\DevWorks\thinking-skills\.tmp-feynman-mcp-catalog.json'
```

결과: `bounded-mcp-catalog-visible`, server 1개, `feynman_read_probe_byte` visible, empty input schema 확인, `model_calls=0`, `authentication_used=false`, auth status/tool payload 비보존.

이 결과는 local App Server가 adapter를 catalog에 올릴 수 있다는 뜻이다. 현재 canonical protected control home의 subscription job에 MCP 설정을 추가했다는 뜻도, exec-server의 기존 code-mode model이 이 tool을 실제 사용했다는 뜻도 아니다.

## 4. 저장·미완료 상태

- 이번 단계는 아직 commit/push하지 않았다.
- 임시 schema/catalog 파일은 source artifact가 아니며 최종 저장 전에 제거한다.
- Docker image tag `feynman-codex-remote:0.154.0-bounded-read-20260913`은 기존 image를 삭제하지 않고 로컬에 보존했다.
- 실제 auth gate, model turn, baseline, 성능 평가는 0회다.

남은 문제와 다음 한 행동:

1. 현재 adapter는 진단용이다. 다음은 **동일한 새 image와 격리된 `/run/codex` 설정에서 App Server/exec-server remote 경로가 이 MCP catalog를 노출하는지 model-free로 확인**해야 한다.
2. 그 검사가 통과해도 `model_tool_contract_ready`를 자동으로 true로 바꾸지 않는다. 실제 도구 호출을 안전하게 관찰할 수 있는 별도 제한 model probe 조건을 정의해야 한다.
3. tools-10 실제 smoke에는 one-byte diagnostic adapter를 사용하지 않는다. 전체 task에 필요한 읽기·수정·실행 adapter와 별도 security contract가 필요하다.
4. 이후 기존 Luna를 먼저 단일 제한 probe로 검토하고, 실패 시 자동 retry나 Terra/Sol 순회를 하지 않는다.

## 5. 보안 범위

이번 단계는 OpenAI Platform API/API key, login/token 파일, 전체 환경 dump, protected control home, baseline/evaluator 문서를 사용하지 않았다. Docker network는 none이었고, container는 read-only rootfs·cap-drop ALL·no-new-privileges 설정으로 실행했다. `main` 병합·force push는 하지 않았다.
