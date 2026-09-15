# LOG-111 — model-free remote RPC proxy cleanup/privacy hardening

작성: 2026-09-15 18:12:12 +09:00

상태: 완료. 이번 단계는 model-free 코드·fixture·회귀 검증만 수행했다.
ChatGPT subscription startup과 모델 실행은 수행하지 않았다.

## 기준점과 범위

- 저장소: C:\DevWorks\thinking-skills
- 브랜치: feat/feynman-thinking-v0.5-draft
- 작업 시작 시 HEAD와 origin/feature: 592070b4effb2a1e46104a5fc5830acac11295b3
- 코드 수정 commit: 0825cf832706bdbf2c39a3658f013c2527eafcb0
- main merge, force push, 모델 fallback, mount 확대, broad Docker prune은 하지 않았다.
- OpenAI Platform API/API key를 사용하지 않았고, login file·token·전체 환경변수를
  읽거나 출력하지 않았다.
- 개발 대화·인계 문서를 candidate에 전달하지 않았다.
- 기존 .tmp/, 사용자 PNG 2개, LOG-099, evaluator-owned 자료와 기존 로그인 홈은
  stage하거나 삭제하지 않고 보존했다.

## 재현

### 정리 순서 결함

proxy child가 먼저 종료하여 response worker가 끝난 뒤에도 parent stdin reader가
살아 있는 조건을 고정 fixture로 만들었다. 기존 구현은 두 worker가 동시에 살아
있을 때만 reader를 join했으므로, reader가 아직 종료되지 않은 채 run_proxy가
돌아오는 회귀 테스트가 먼저 실패했다.

실패한 테스트는
test_proxy_joins_parent_reader_when_child_stdout_ends_first이며,
관찰값은 reader_finished가 false인 AssertionError였다.

### 고정 오류의 request ID 경계

Windows source path 밖으로 나가는 경로 매핑 요청과 JSON object request ID를 함께
보냈다. 기존 고정 mapping error가 object 전체를 JSON-RPC id로 그대로 반사하여
요청 ID 안의 임의 payload가 오류 응답에 포함되는 것을 재현했다.

## 최소 수정

변경 파일은 tooling/feynman_rpc_path_proxy.py와
tests/test_feynman_rpc_path_proxy.py 두 개다.

1. response worker가 먼저 끝나는 경우에도 살아 있는 parent stdin reader를
   bounded deadline 안에서 join하도록 조건을 고쳤다. 이미 종료한 worker에 대한
   불필요한 join은 하지 않으며 기존 deadline·child 종료 관찰·telemetry 흐름은
   유지했다.
2. proxy 고정 오류 응답에는 JSON-RPC scalar인 정확한 int 또는 str request ID만
   허용하는 _safe_request_id 경계를 추가했다. bool, object, list 등은 id를
   생략하며, 정상적인 string/int ID의 기존 동작은 유지한다.

## 검증 결과

재현 → 최소 수정 → targeted regression → 전체 회귀 → schema와 통합 경계 확인
순서로 진행했다.

- 새 정리 회귀는 수정 전 실패했고 수정 후 1 test OK가 됐다.
- 새 non-scalar request ID privacy 회귀는 수정 전 object payload 반사를 확인했고
  수정 후 payload와 id가 오류 응답에 반영되지 않았다.
- proxy 관련 targeted integration 4 tests OK.
- 전체 unittest: 505 tests OK, 11 skipped.
- 전체 회귀는 ResourceWarning을 오류로 승격해 실행했으며 ResourceWarning은 0건이다.
- evals/feynman-thinking의 schema 19개를 검사한 결과 errors=0이다.
- 보존된 기존 remote-child differential report는 schema v1에 유효한 것으로
  read-only 확인했다. 최종 external Docker report는 재실행하지 않았다.
- 수정된 Python 파일 py_compile과 git diff --check를 통과했다.
- skip은 성공으로 세지 않았다. skip은 Windows FIFO/symlink/ambient skill root와
  명시적 Docker integration opt-in 경계에 해당한다.

## 통합 경계와 미해결 사항

이번 단계에는 실제 Docker remote-child differential 재실행, App Server 호출,
subscription startup 재실행, model smoke를 포함하지 않았다. LOG-109에서 정확히
1회 수행된 실제 startup의 initialize 성공 후 thread/start -32603 /
remote-environment-error 실패는 그대로 유효하지만, 새 증거 없이 반복하지 않았다.
따라서 App Server 내부 remote environment envelope과 thread/start 원인은 아직
미확정이다.

현재 production proxy는 child stderr를 DEVNULL로 버린다. 이번 변경은 cleanup과
고정 오류의 request ID privacy에 한정했으므로 이 observability gap은 의도적으로
남겼다. stderr 노출 정책을 바꾸는 작업은 별도의 재현·보안 검토가 필요한 다음
경계다.

다음 조사도 model-free static/fixture 비교를 우선한다. 실제 ChatGPT subscription
startup 또는 모델 smoke가 필요해지는 순간에는 별도 승인 없이 실행하지 말고,
정확한 명령·예상 결과·중단 조건을 먼저 제시한 뒤 그 지점에서 멈춘다.
