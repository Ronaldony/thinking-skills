# LOG-093 — Windows 순수 회귀 CI 보강과 로컬 검증 (2026-09-14)

## 상태

- 작업 ID: LOG-093 / 상태: DONE (저장소 범위)
- 저장소: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `435cbdd`
- Docker lifecycle blocker는 유지 중이며 Docker·인증·모델 실행은 하지 않았다.

## 목적과 수정 이유

기존 `.github/workflows/validate-feynman-unit-diagnostic.yml`의 전체 unittest job은 `ubuntu-latest`만 대상으로 했다. Windows/Docker 호환성 계획 중 Docker에 의존하지 않는 순수 회귀 계층을 Windows에서도 실행하도록 별도 `unit-diagnostic-windows` job을 추가했다. 이 job은 저장소 checkout, Python 3.12 설치, `python -m unittest discover -s tests -v`만 수행하며 Docker, Codex login, subscription startup, candidate/model evaluation을 호출하지 않는다.

## 실제 검증 명령과 결과

로컬 Windows PowerShell에서:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -W error::ResourceWarning -m unittest discover -s tests
```

결과: `Ran 441 tests in 22.542s`, `OK (skipped=11)`.

변경 대상 tooling compile:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m py_compile tooling/feynman_docker_runtime_probe.py tooling/feynman_rpc_path_contract_probe.py tooling/feynman_subscription_startup_diagnostic.py tooling/feynman_subscription_smoke_exec.py
```

결과: 성공.

Schema 및 workflow 정적 검증:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -c "from pathlib import Path; import json; from jsonschema import Draft202012Validator; files=sorted(Path('evals').rglob('*.schema.json')); [Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; schema=json.loads(Path('evals/feynman-thinking/subscription-startup-diagnostic.schema.json').read_text(encoding='utf-8')); report=json.loads(Path('.tmp/startup-diagnostic-20260913-v3.json').read_text(encoding='utf-8')); Draft202012Validator(schema).validate(report); runtime=json.loads(Path('.tmp/docker-runtime-probe-20260914-v4.json').read_text(encoding='utf-8')); assert runtime['schema_version'] == 2; print('schema_files=17 errors=0 actual_startup_report_errors=0 runtime_artifact_schema=2 historical')"
```

결과: `schema_files=17 errors=0 actual_startup_report_errors=0 runtime_artifact_schema=2 historical`.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -c "from pathlib import Path; text=Path('.github/workflows/validate-feynman-unit-diagnostic.yml').read_text(encoding='utf-8'); assert '\\t' not in text; assert 'unit-diagnostic-windows:' in text; assert 'runs-on: windows-latest' in text; assert 'python -m unittest discover -s tests -v' in text; print('unit-workflow-static-check=passed')"
git diff --check
```

결과: `unit-workflow-static-check=passed`, diff check 성공. 마지막 Git diff에서 발생한 사용자 config ignore 접근 경고는 sandbox 권한 경고이며 변경 파일 오류가 아니다.

## 검증 범위와 한계

- 검증한 것: Windows 로컬 순수 unittest 441개, 11개 skip, ResourceWarning 차단, 대상 tooling compile, 17개 JSON Schema 구조와 기존 실제 startup report, 새 workflow 핵심 문자열.
- 검증하지 않은 것: GitHub Actions의 실제 `windows-latest` 실행, Docker container lifecycle, path contract direct/proxy 비교, subscription auth/startup, Luna/Terra/Sol model turn, baseline/evaluation.
- 기존 `docker-runtime-probe-20260914-v4.json`은 schema v2 historical artifact이며 새 schema v3 runtime 성공 증거로 사용하지 않았다.

## 미완료와 다음 행동

Docker container lifecycle list/create API가 응답하지 않는 외부 blocker가 남아 있다. lifecycle 회복 증거가 생기기 전에는 runtime probe를 반복하지 않는다. 회복 후 고유 control label 잔존 여부를 확인하고, 수정된 schema v3 runtime probe를 새 artifact로 1회 실행하는 것이 다음 행동이다.

## 커밋·push

- 이번 변경은 `.github/workflows/validate-feynman-unit-diagnostic.yml`과 이 로그, 최신 상태 포인터 문서에만 포함한다.
- `.tmp/`와 사용자 PNG 2개는 stage하지 않는다.
- feature branch에 일반 commit/push하며 main merge와 force push는 하지 않는다.
