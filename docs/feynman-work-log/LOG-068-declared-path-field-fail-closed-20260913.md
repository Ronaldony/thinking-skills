# LOG-068 — Declared RPC path fields fail closed

- 시각: 2026-09-13 14:41 KST 이후
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `c83796e docs: record raw posix mapping CI receipt`
- 시작 working tree: 기존 사용자 PNG 2개만 untracked; 기존 변경은 보존
- 적용 AGENTS.md: ancestor/repo 검색 결과 없음
- 외부 startup/model 실행: 없음
- OpenAI Platform API/API key: 사용하지 않음

## 목적

`environmentConfig/read.cwd`, filesystem `path`, resources `uri`처럼 매퍼에
선언된 경로 필드가 상대경로 또는 비문자열일 때 원격 서버로 조용히 전달되는
fail-open 공백을 닫는다. 이는 `environmentConfig/read`의 누락 field나 서버의
실제 설정 응답을 임의로 보정하는 작업이 아니며, Windows host→Linux container
namespace 매핑 전에 입력 형태를 엄격히 확인하는 로컬 경계 수정이다.

## 사전 오프라인 조사

공식 App Server 문서의 remote environment 경로 규칙과 로컬 인계 문서/LOG-045,
LOG-046을 읽었다. Codex 0.154.0의 생성 JSON Schema도 임시 디렉터리에 생성해
`runtimeWorkspaceRoots` 등 공개 schema 항목만 검색한 뒤 삭제했다. 이 schema에는
exec-server child의 `environmentConfig/read` 요청 계약이 직접 포함되지 않았으므로,
해당 RPC의 field/array mapping 계약은 현재 저장소의 제한 매퍼와 회귀 fixture로
검증해야 한다는 결론을 유지했다. schema 임시 파일과 인증 자료는 보존하지 않았다.

## 변경

`tooling/feynman_rpc_path_mapping.py`의 `map_request()`가 선언된 scalar path
field가 존재하면 항상 문자열인지 확인하고 `host_to_container()`를 호출하도록
변경했다. 따라서 다음을 원격 child에 전달하지 않는다.

- 상대경로 또는 불완전한 Windows 경로
- `None` 등 비문자열 path 값
- declared mount 밖 또는 traversal을 포함한 경로

`tooling/feynman_rpc_path_proxy.py`에는 payload-free 고정 사유
`invalid-path-field-type`을 추가했다. 거부 응답/telemetry에 실제 경로, request ID,
credential 또는 원문 payload를 넣지 않는다. `environmentConfig/read`의 nested
config/requirements path group mapping과 기존 raw POSIX container namespace fix는
그대로 유지했다.

## 실제 명령과 관찰

대상 파일을 수정한 뒤 다음 명령을 실행했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_path_proxy tests.test_feynman_rpc_compatibility
```

결과: `38 tests`, `OK`.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m compileall -q tooling tests
git diff --check
```

결과: 두 명령 모두 exit 0. Git global ignore 파일 접근 warning과 CRLF 변환
warning은 있었지만 변경 파일의 whitespace 오류는 없었다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_*.py'
```

결과: `376 tests`, `OK (skipped=11)`. skip은 실제 Codex tool-use 성공으로 세지
않았다.

추가로 실제 경로 문자열을 저장하지 않는 고정 synthetic fixture를 실행했다.
관찰 결과는 다음과 같다.

| 입력 분류 | 결과 |
|---|---|
| Windows host candidate path | `/run/candidate/x.txt` |
| declared container path | `/run/candidate/x.txt` 유지 |
| mount 밖 raw POSIX path | `container path is outside declared mounts` 거부 |
| relative path | `host path must be absolute and traversal-free` 거부 |
| non-string declared path | `declared path field must be a string` 거부 |

이 fixture는 synthetic 값만 사용했으며 Codex, Docker, 인증, 네트워크, 모델
subprocess를 실행하지 않았다.

## 판정과 검증 범위

완료한 범위는 declared scalar path field의 입력 검증, 고정 rejection reason,
기존 nested config group/raw POSIX mapping 회귀다. 이 변경은 원격 서버의
`environmentConfig/read` schema를 확정하지 않으며, 누락된 config response를
생성하지 않고, mount 범위를 넓히지 않는다.

아직 확인하지 않은 범위:

- 수정 후 실제 App Server startup 재검증
- server-side read 자체가 1 byte로 제한되는지 여부
- 실제 ChatGPT subscription session의 model-facing tool catalog/tool-use
- Terra/Sol 계정 접근 및 baseline/evaluation 결과

따라서 실제 model evaluation은 시작하지 않았다. 수정 후 외부 startup 진단은
별도 명시 승인이 있어야 하며, 기존 평가 전용 login home은 보존한다.

## 저장 상태와 다음 행동

이번 변경 파일은 이 로그 작성 시점에 commit하지 않았다. 다음 저장 단위는
이 로그와 재개 포인터를 함께 stage하여 테스트 결과 및 push 상태를 기록하는
것이다. 그 다음은 수정된 매퍼를 포함한 model-free startup 1회 재검토이며,
실제 모델 turn은 그 선행 조건이 성공하기 전까지 보류한다.

사용자 PNG 2개는 untracked로 유지하고 stage하지 않는다. main merge와 force push는
하지 않는다.
