# LOG-090 — runtime/path probe 판정 보강과 Docker 재검증 (2026-09-14)

## 상태와 범위

- 작업 ID: LOG-090 / 상태: DONE (코드·회귀 검증), BLOCKED (Docker `create`)
- 저장소: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `a9428267203caf81110289922fb996fc56e636e8`
- 이번 변경은 인증·모델·candidate payload를 사용하지 않는 offline probe에 한정했다.
- 보호된 ChatGPT 구독 로그인 홈, 토큰, 전체 환경변수, API key는 읽거나 출력하지 않았다.

## 원인 분석

직전 계획의 결함 재현을 코드와 fixture로 확인했다.

1. runtime probe의 create marker는 이미 newline을 포함한 문자열을 `/bin/echo`에 넘겨 echo의 newline이 한 번 더 붙었다. 정상 출력인데도 marker 검사가 실패할 수 있었다.
2. `docker inspect` 실패를 container 부재로 취급할 여지가 있었고, 삭제 뒤 조회 실패에서도 cleanup verified를 true로 만들 수 있었다. 조회 불능과 부재 확인은 서로 다른 증거다.
3. initialize 판정은 JSON의 `id=true`를 정수 `1`과 같다고 보고, id `1`의 성공·오류 응답이 함께 있어도 성공으로 판정했다.
4. path contract probe는 문자열을 비어 있음/존재함으로만 줄여, 서로 다른 설정 표식과 file response가 같은 shape로 비교됐다.

## 구현한 수정

`tooling/feynman_docker_runtime_probe.py`:

- marker 인자에서 terminal newline을 제거했다.
- create 출력이 container ID 형식인지 확인한다.
- container presence를 `present`와 `unavailable`로 구분한다.
- 삭제 후 성공한 `docker ps -a --filter name` 조회에서 부재를 확인할 때만 cleanup verified를 true로 한다.
- initialize response는 정확한 정수 ID `1`이 정확히 한 번 나타나고, result가 있으며 error가 없을 때만 통과한다.
- create 이외 단계도 내부 container state가 `exited`, exit code가 `0`이어야 통과한다.
- `--docker-host`를 추가하고 `npipe://`·`unix://` local endpoint만 허용한다. 전역 Docker context는 변경하지 않는다.
- 새 runtime report schema는 v3이다. 이전 v4 artifact는 schema v2 historical evidence로 보존한다.

`tooling/feynman_rpc_path_contract_probe.py`:

- response namespace shape도 direct/proxy 간 동일해야 통과하도록 했다.
- 경로를 제외한 문자열은 원문 대신 SHA-256과 길이로 보존해 서로 다른 fixture 설정·파일 내용이 같은 shape가 되지 않게 했다.
- `--docker-host`와 local endpoint 검증을 추가했다.
- 변경된 path report schema는 v3이다.

## 검증

집중 회귀:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m unittest tests.test_feynman_docker_runtime_probe tests.test_feynman_rpc_compatibility
```

결과: `33 tests OK`.

검증한 사례:

- echo marker의 extra newline 차단
- 256 KiB bounded output drain
- 비정상 내부 exit code `7` 차단
- boolean/중복/conflicting initialize ID 차단
- 삭제 후 inspect 불능을 cleanup 성공으로 승격하지 않음
- non-local TCP Docker endpoint 차단
- 서로 다른 `ROOT_CONFIG`/`SUB_CONFIG`, `A`/`B` response 값의 shape 불일치

전체 suite와 정적 검사:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -W error::ResourceWarning -m unittest discover -s tests
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m py_compile tooling/feynman_docker_runtime_probe.py tooling/feynman_rpc_path_contract_probe.py tooling/feynman_subscription_startup_diagnostic.py tooling/feynman_subscription_auth_gate.py
git diff --check
```

결과: `441 tests OK, 11 skipped`, ResourceWarning 없음, compile·diff check 통과.

schema 검증:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -c "from pathlib import Path; import json; from jsonschema import Draft202012Validator; files=sorted(Path('evals').rglob('*.schema.json')); [Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; schema=json.loads(Path('evals/feynman-thinking/subscription-startup-diagnostic.schema.json').read_text(encoding='utf-8')); report=json.loads(Path('.tmp/startup-diagnostic-20260913-v3.json').read_text(encoding='utf-8')); Draft202012Validator(schema).validate(report); runtime=json.loads(Path('.tmp/docker-runtime-probe-20260914-v4.json').read_text(encoding='utf-8')); assert runtime['schema_version'] == 2; print('schema_files=17 errors=0 actual_startup_report_errors=0 runtime_artifact_schema=2 historical')"
```

결과: `schema_files=17 errors=0 actual_startup_report_errors=0 runtime_artifact_schema=2 historical`.

## 실제 Docker 재검증

수정 후 새 artifact에 runtime probe를 **1회** 실행했다.

```powershell
$out = 'C:\DevWorks\thinking-skills\.tmp\docker-runtime-probe-20260914-v4.json'
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_docker_runtime_probe --docker 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-host 'npipe:////./pipe/docker_engine' --image 'sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6' --output $out --timeout 30
```

결과: exit `1`, verdict `docker-runtime-blocked`, 최초 실패 `container-create`, elapsed 약 30초. stdout/stderr는 `0/0`, `container_id_observed=false`, presence `unavailable`, inspect exit `1`, cleanup `not-observed/verified=false`였다. `container-start`, node, exec-server initialize는 실행되지 않았다.

Docker 29.7.2 CLI help로 probe가 사용하는 create 옵션(`--label`, `--entrypoint`, `--network`, `--cap-drop`, `--security-opt`, `--read-only`, `--user`, `--tmpfs`)이 지원됨도 읽기 전용으로 확인했다. 따라서 현재 실패는 미지원 CLI 옵션으로 분류하지 않는다.

## 판정과 다음 작업

코드 결함 두 가지는 수정·회귀 검증됐다. Docker create 자체의 30초 timeout은 명시 local endpoint에서도 재현됐으므로, 현재 남은 blocker는 Docker client→engine create 요청 처리다. 이 단계의 증거만으로 Docker Desktop backend 내부 원인을 확정하지 않는다.

runtime probe 성공 전에는 path contract 실제 Docker 비교를 실행하지 않는다. path probe는 코드상 의미 비교를 강화했지만 실제 direct/proxy artifact는 새 runtime 선행 조건을 통과한 뒤 생성한다. 구독 startup, 인증 gate, Luna smoke, baseline/model evaluation은 실행하지 않았다.

## 커밋·push

- 커밋 `fc9a896bb179fee389290da676ff0ed2aa87a705` (`fix: harden runtime and path probe verdicts`)를 생성하고 `origin/feat/feynman-thinking-v0.5-draft`에 일반 push했다. push 후 local HEAD와 remote ref가 동일 SHA임을 확인했다. 이 receipt 보정은 별도 문서 커밋으로 기록한다.
- `.tmp/`와 사용자 PNG 2개는 stage하지 않는다.
- main merge와 force push는 하지 않는다.
