# LOG-106 — Docker/path gate 통과와 commit/push 영수증

Date: 2026-09-14 KST. Repository: `Ronaldony/thinking-skills`.
Branch: `feat/feynman-thinking-v0.5-draft`.

## 결과 요약

새 Docker-ready 증거가 생긴 뒤 runtime probe와 Windows direct/proxy path
contract를 재검증했다. runtime은 `docker-runtime-ready`, path contract는
`rpc-path-contract-equivalent`로 통과했다. 이에 따라 ENV-01 Docker create/run
lifecycle blocker는 현재 권한 상승 실행 경계에서 해소된 것으로 갱신한다.

이번 단계는 model-free offline 검증만 수행했다. ChatGPT 구독 auth, 최종 startup
diagnostic, `thread/start`, model command, Luna smoke, Terra/Sol fallback,
baseline, EVAL-01/02 행동평가는 실행하지 않았다. 과거 `thread/start -32603`은
별도 외부 계약 차단으로 아직 미확정이다.

## 검증 증거

runtime report:

```text
.tmp/feynman-docker-runtime-probe-20260914-v3.json
verdict=docker-runtime-ready
stages=container-create, container-start, default-node-version, exec-server-initialize
all stage exit=0; timeout=false; OOM=false; sandboxDenied=false
stdout/stderr drained=true; cleanup verified=true for run stages
```

path report:

```text
.tmp/feynman-path-contract-20260914-v6.json
verdict=rpc-path-contract-equivalent
direct_exit_code=0; proxy_exit_code=0
request_shapes_match=true
response_shapes_match=true
response_namespace_shapes_match=true
response IDs 1..7 all match
process_exit_codes=0; sandbox_denied=False; stderr_drained=true
```

그 과정에서 다음 결함을 재현·수정했다.

- runtime probe stage 예외가 generic 오류로 탈출해 report를 잃던 문제: 고정
  error code/stage report와 bounded reap을 추가했다.
- path probe가 colon-separated PATH를 파일 경로로 오인하던 문제: path 판별을
  보정했다.
- fixture Docker process의 기본 cwd가 candidate가 아니던 문제: `/run/candidate`
  workdir을 명시했다.
- initialize 응답의 알려진 `shell.path`, `tempDir`,
  `temporaryDirectories`를 임의 외부 mount와 혼동하던 문제: 정확한 구조 위치만
  `system/shell`·`system/temp`로 분류하고 unknown outside path는 계속 차단했다.

회귀 결과:

```text
runtime probe tests: 16 OK
RPC compatibility tests: 32 OK
full suite: 486 tests OK, 11 skipped
schema: 17 errors=0
ResourceWarning: 없음
py_compile: OK
git diff --check: 0
```

## 실제 실행 횟수와 개인정보 경계

- 일반 sandbox `docker info`: 1회, named-pipe permission denied
- 권한 상승 `docker info`: 1회 성공
- 권한 상승 image inspect: 1회 성공
- runtime probe: 초기 generic failure 1회, 수정 후 ready 1회
- path probe: 진단/수정 전 blocked v2~v5 4회, 최종 equivalent v6 1회
- 실제 Docker container lifecycle: 최종 runtime stage 4개 통과
- 실제 subscription auth/startup/model: 0회
- API key·Platform API·credential/token·전체 환경변수: 사용/출력 0회

probe는 고정 image, network none, 제한된 fixture, 고유 label만 사용했다. 사용자
로그인 홈과 기존 증거를 변경하지 않았고, probe 소유 container cleanup을
검증했다. broad prune, Docker Desktop 전체 종료, mount 확대, main merge,
force push는 수행하지 않았다.

## commit/push

```powershell
git commit -m "fix: recover Docker runtime and path contract probes"
```

결과:

```text
[feat/feynman-thinking-v0.5-draft 0c5c6b8] fix: recover Docker runtime and path contract probes
8 files changed, 564 insertions(+), 53 deletions(-)
```

```powershell
git push origin feat/feynman-thinking-v0.5-draft
```

결과:

```text
cbb614b..0c5c6b8  feat/feynman-thinking-v0.5-draft -> feat/feynman-thinking-v0.5-draft
```

이번 영수증과 최신 포인터를 추가한 뒤 최종 문서 commit/push는 별도 receipt로
남긴다. 보호 대상 `.tmp/`, 사용자 PNG 2개, `LOG-099`는 stage하지 않는다.

## 다음 사람 승인 경계

이제 자동으로 진행할 수 있는 offline gate는 통과했다. 다음 단계는 evaluator-owned
출력 경로와 기존 ChatGPT 구독 로그인 홈을 사용한 최종 startup gate 1회이며,
최신 사용자 승인이 별도로 필요하다. startup gate가 통과하기 전에는 model
command를 시작하지 않는다. startup 실패 시 자동 재시도·모델 fallback은 하지
않으며, `thread/start -32603`이 재현되면 새 원인 증거만 기록하고 중단한다.
