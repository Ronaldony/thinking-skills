# LOG-086 — probe 입출력·응답 중복·namespace 판정 보강 (2026-09-14)

## 작업 상태

- 작업 ID: LOG-086 / 상태: DONE (probe 보강 및 오프라인 검증), BLOCKED (Docker peer startup)
- 저장소: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 기준 HEAD: `90d6bbe92ab5e4c2410d635a88af67b34dc905b3`
- 보안 범위: 테스트 fixture, 임시 디렉터리, pinned image만 사용했다. 구독 로그인 홈·토큰·API key·전체 환경변수·candidate payload는 읽거나 출력하지 않았다.

## 사전 분석에서 확인한 결함

직전 계획의 검토 결과, path probe에는 다음 진단 신뢰성 공백이 있었다.

1. stderr를 소비하지 않아 큰 stderr 출력이 pipe를 가득 채우면 RPC peer가 자체적으로 막힐 수 있었다.
2. stdout reader를 종료 시 join/close하지 않아 `ResourceWarning`과 잔여 reader가 남을 수 있었다.
3. 같은 response ID가 반복되면 마지막 응답으로 덮어써 중복을 성공처럼 보일 수 있었다.
4. response를 이미 path role shape로 바꾼 뒤 namespace를 계산해 원래 Windows host와 Linux container 표현을 구분하지 못했다.
5. `file:///C:/...` Windows file URI가 host namespace로 정규화되지 않았다.

## 구현 내용

`tooling/feynman_rpc_path_contract_probe.py`를 수정했다.

- stdout/stderr reader를 별도 thread로 실행하고 모두 제한된 시간 안에 join한다.
- stderr는 원문을 저장하지 않고 바이트 수, reader 오류, drain 완료 여부만 기록한다.
- stdout reader 오류를 고정 상태로 기록한다.
- 중복 response ID를 별도 counter로 기록하고, 첫 응답만 보존한다.
- 원본 JSON response에서 namespace shape를 만든 뒤 payload shape와 분리해 보존한다.
- Windows file URI, URL encoding, case-insensitive Windows host root를 안전하게 정규화한다.
- path probe report schema를 v2로 올리고, 성공 조건에 중복·reader 오류·stderr drain 완료를 포함했다.

`tests/feynman_rpc_path_contract_probe` 관련 회귀에는 다음을 추가했다.

- 1MiB stderr 폭주 fixture가 RPC를 막지 않고 모두 소비되는지 확인
- 중복 initialize response가 `response_id_duplicates=1`로 기록되는지 확인
- Windows host namespace와 container namespace가 서로 다른 digest shape를 만드는지 확인

## 검증 명령과 결과

### 변경 영역

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m py_compile tooling/feynman_rpc_path_contract_probe.py tests/feynman_subscription_lifecycle_fixture.py tests/test_feynman_rpc_compatibility.py
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -W error::ResourceWarning -m unittest tests.test_feynman_rpc_compatibility tests.test_feynman_rpc_path_proxy tests.test_feynman_subscription_startup_diagnostic -q
git diff --check
```

결과: `69 tests`, `OK`; `ResourceWarning` 없음; compile 및 diff check 통과.

### pinned Docker offline probe

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_rpc_path_contract_probe --docker 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --image 'sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6' --proxy 'C:\DevWorks\thinking-skills\tooling\feynman_rpc_path_proxy.py' --output 'C:\DevWorks\thinking-skills\.tmp\rpc-path-contract-20260914-expanded-v3.json' --timeout 1
```

artifact: [`rpc-path-contract-20260914-expanded-v3.json`](../../.tmp/rpc-path-contract-20260914-expanded-v3.json)

관찰:

- verdict: `rpc-path-contract-blocked`
- failure stage: `docker-peer-startup-timeout`
- direct/proxy 모두 `response_ids=[]`, `initialize_response_observed=false`, `timed_out=true`, exit `1`
- direct/proxy 모두 `stderr_drained=true`, `stdout_read_error=false`, `stderr_read_error=false`, `stderr_bytes=0`
- request shape digest는 일치하지만 response shape가 비어 있어 path 의미 동등성은 판정하지 않았다.

이번 결과는 probe의 stderr/stdout 교착·중복 집계 결함이 아니라, Docker peer가 initialize 응답 전에 실행 완료되지 않는 현상을 확인한다. Docker daemon/image metadata 확인 성공만으로 image process 실행 성공을 추론하지 않는다.

### 전체 회귀·스키마

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -W error::ResourceWarning -m unittest discover -s tests
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m py_compile tooling/feynman_rpc_path_contract_probe.py tooling/feynman_rpc_path_proxy.py tooling/feynman_subscription_startup_diagnostic.py
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -c "from pathlib import Path; import json; from jsonschema import Draft202012Validator; files=sorted(Path('evals').rglob('*.schema.json')); [Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; schema=json.loads(Path('evals/feynman-thinking/subscription-startup-diagnostic.schema.json').read_text(encoding='utf-8')); report=json.loads(Path('.tmp/startup-diagnostic-20260913-v3.json').read_text(encoding='utf-8')); Draft202012Validator(schema).validate(report); print(f'schema_files={len(files)} errors=0 actual_startup_report_errors=0')"
git diff --check
```

결과: 전체 `426 tests`, `OK (skipped=11)`; schema `17개 errors=0`; actual startup report instance `errors=0`; ResourceWarning 없음.

## 커밋·push

- probe 코드, fixture, 회귀 테스트, 최신 인계 문서와 이 로그만 선택한다.
- `.tmp/`와 사용자 PNG 2개는 stage하지 않는다.
- 이번 변경을 기존 `feat/feynman-thinking-v0.5-draft`에 commit하고 일반 push한 뒤 local/remote SHA를 확인한다.

## 미완료 사항과 다음 행동

- Docker peer가 `/bin/echo`, `node --version`, exec-server initialize를 완료하지 못하는 내부 원인은 미확정이다.
- direct Linux와 Windows proxy의 실제 path response semantics는 initialize 응답 부재로 아직 비교할 수 없다.
- Codex 0.154.0 subscription `thread/start -32603` 원인도 별도로 미확정이며, 실제 startup 재실행은 하지 않는다.
- 다음 단계는 별도의 제한된 Docker runtime probe로 CLI 종료 코드, container 종료 상태, OOM 여부를 분리 기록하는 것이다. 그 probe가 통과하면 확장 path contract를 새 output으로 1회 실행한다.
