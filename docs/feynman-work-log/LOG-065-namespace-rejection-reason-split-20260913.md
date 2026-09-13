# LOG-065 — Namespace-specific request rejection reasons

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 선행 checkpoint: [LOG-064](LOG-064-corrected-startup-request-mapping-20260913.md)
- 대상: request-side path mapper의 payload-free reason 세분화
- 외부 진단: 추가 실행하지 않음
- 실제 model turn: 실행하지 않음
- OpenAI Platform API/API key: 사용하지 않음

## 문제와 변경 이유

LOG-064의 승인 실행은 `outside-declared-mount` 6건을 확인했지만, 기존 reason
label 하나가 host namespace와 container namespace를 합쳐 표현했다. 이 상태로는
다음 실행에서 Windows host mount 부족과 이미 container 안의 경로가 허용목록 밖인
경우를 구별할 수 없다.

`tooling/feynman_rpc_path_proxy.py`의 고정 allowlist를 다음처럼 분리했다.

- `host-path-outside-declared-mount`
- `container-path-outside-declared-mount`

경로 문자열·RPC payload·thread ID는 계속 telemetry에 저장하지 않는다. 기존
mount 범위, Docker 설정, auth home, executor gate는 변경하지 않았다.

## 실행한 로컬 검증

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_rpc_compatibility
```

결과: `22 tests`, `OK`.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

결과: 전체 `372 tests`, `OK (skipped=11)`; whitespace error 없음.

추가한 fixture는 Windows host 경로의 `host-path-outside-declared-mount`와
`file:///var/private.txt` container 경로의
`container-path-outside-declared-mount`가 서로 다른 고정 reason으로 집계되는지
확인한다.

## 검증 범위와 미완료

- 이번 변경은 관측 가능성 개선이지 startup 성공 수정이 아니다.
- LOG-064의 실제 `environmentConfig/read:1`과 `fs/getMetadata:6` 결과는 이미
  실행된 artifact의 역사값으로 유지하며 소급 변경하지 않는다.
- 다음 외부 실행에서만 namespace별 실제 분포를 확인할 수 있다. 새 외부 실행은
  이 checkpoint만으로 자동 승인되지 않는다.
- 현재 model response/tool-use/Feynman 효과성은 미검증이며 baseline candidate에
  개발 문서나 인계 문서를 전달하지 않는다.
- 자동 retry, fallback, Terra/Sol 전환, main 병합, force push는 하지 않는다.

## 저장 상태

- 이 checkpoint와 수정된 proxy/test를 feature branch에 일반 commit·push한다.
- 사용자 PNG 2개는 untracked로 보존하고 stage하지 않는다.
