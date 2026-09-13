# LOG-084 — startup 정리 증거 보강과 다음 경계 (2026-09-13)

## 작업 상태

- 작업 ID: LOG-084 / 상태: DONE (코드 보강), BLOCKED (실제 startup 원인)
- 시각: 2026-09-13 23:53 이후, Asia/Seoul
- 저장소: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `990f265ede5f32a1372ae7e38f34bb256c4f73bf`
- 시작 dirty 상태: 기존 `.tmp/`, 사용자 PNG 2개만 untracked; 기존 커밋 변경은 수정하지 않음
- 보안 범위: 기존 ChatGPT 구독 control home을 사용한 startup 진단만 수행했다. 인증 파일·토큰·전체 환경변수·API key·candidate payload는 읽어 출력하거나 보존하지 않았다.

## 목적과 실행 횟수

직전 계획에 따라 실제 ChatGPT 구독 startup diagnostic을 새 최종 gate로 **1회** 실행했다. 이 실행은 `initialize`와 `thread/start`까지만 수행하며 `turn/start`, prompt, model generation, MCP tool, 평가를 포함하지 않는다. 같은 입력의 자동 재시도와 모델 fallback은 수행하지 않았다.

## 사전 입력 검증

실행 설정은 다음 고정 입력을 담은 `.tmp/feynman-subscription-checkpoint-20260913-v3.json`으로 만들었다. 경로와 image digest는 저장했지만 인증정보는 포함하지 않았다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_subscription_startup_diagnostic --checkpoint 'C:\DevWorks\thinking-skills\.tmp\feynman-subscription-checkpoint-20260913-v3.json' --validate-only
```

관찰: `subscription-checkpoint-valid`, `binding_valid=True`, `binding_config_override_count=13`, `model=gpt-5.6-luna`, `subprocesses_started=0`, `authentication_material_present=False`, exit `0`.

## 실제 startup 진단 1회

실제 실행 명령은 다음과 같다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_subscription_startup_diagnostic --checkpoint 'C:\DevWorks\thinking-skills\.tmp\feynman-subscription-checkpoint-20260913-v3.json' --timeout-seconds 60
```

관찰: exit `1`, verdict `subscription-startup-thread-blocked`.

- App Server `initialize` 완료: `True`
- `thread/start`: 시작되지 않음, error code `-32603`
- local 분류: `remote-environment-error` (오류 문구의 공식 원인명이 아니라 제한된 로컬 분류)
- request mapping rejection: `0`
- response mapping rejection: `0`
- request: `6/6` forward
- response: `5/5` match; initialized는 notification이므로 response record와 분리
- pending/write/duplicate/malformed: 모두 `0`
- `turn/start`: `0`
- model generation: `0`
- child exit code: 당시 telemetry에 `null`

보고서는 `C:\DevWorks\thinking-skills\.tmp\startup-diagnostic-20260913-v3.json`, proxy telemetry는 `C:\DevWorks\thinking-skills\.tmp\startup-diagnostic-20260913-v3-rpc.json`에 보존했다. report를 subscription schema v3로 검증한 결과 `actual_startup_report_errors=0`이다.

## 원인 판단

확정된 사실은 입력 검증과 초기화·RPC 전달이 통과했지만 App Server가 `thread/start`에서 `-32603`으로 원격 환경 시작을 거부했다는 것이다. child 응답 error code가 없고 mapping rejection도 없으므로, 이번 로그만으로 Windows path mapping 거부를 원인으로 확정할 수 없다.

별도로 확인한 `child_exit_code=null`은 원격 실패의 원인이 아니라 **증거 수집 순서의 결함**이다. App Server가 소유한 proxy descendant가 최종 telemetry를 쓰기 전에 진단기가 부모 process tree 정리를 시작할 수 있었다. 따라서 기존 startup 결과는 thread/start 실패와 cleanup evidence 불완전성을 함께 가진다. App Server↔exec-server의 응답 의미·환경 lifecycle 호환성은 아직 미확정이며, 이를 해결했다고 기록하지 않는다.

## 코드 수정

`tooling/feynman_subscription_startup_diagnostic.py`에 `_wait_for_proxy_telemetry_exit()`를 추가했다.

- finally 진입 시 시작한 15초 cleanup deadline을 공유한다.
- App Server stdin 종료와 process wait 뒤, payload-free telemetry의 `child_exit_code`가 기록될 때까지 같은 deadline 안에서 기다린다.
- 그 뒤에도 App Server가 남아 있을 때만 알려진 process tree를 정리한다.
- final child exit snapshot을 얻지 못하면 이를 성공으로 만들지 않고 incomplete evidence로 유지한다.

`tests/test_feynman_subscription_startup_diagnostic.py`에는 final child exit snapshot 수락과 partial snapshot timeout 회귀 테스트를 추가했다. 이 수정은 path allowlist나 mount 범위를 넓히지 않았고, 인증 홈·실제 실행 입력을 변경하지 않았다.

## 보조 검증

1. model-free discovery diagnostic을 ordinary/guarded 각 1회씩 실행했다. child exit `0`, model requests `0`. ordinary mode에서 실제 fixture의 `environmentConfig/read`, `fs/getMetadata`, `fs/canonicalize` shape/error 계약을 확인했고 guarded mode의 제한은 유지됐다. 결과는 `C:\DevWorks\thinking-skills\.tmp\rpc-discovery-20260913-v3.json`이다.
2. Codex 0.154.0의 빈 임시 `CODEX_HOME`에서 `app-server generate-json-schema`를 실행했다. App Server schema 생성이 성공했고 `ThreadStartParams`의 `cwd`는 optional이며 `ThreadStartResponse`의 필수 구조를 확인했다. 이 schema 생성은 login home·모델·Docker를 사용하지 않았다.
3. 이전에 수행한 pinned Docker offline path probe의 최종 artifact는 `rpc-path-contract-equivalent`이며 direct Linux/proxy response shape digest가 일치한다. 이 결과는 실제 App Server startup 성공 증거가 아니다.

## 회귀·스키마 검증

실행 명령:

```powershell
python -B -W error::ResourceWarning -m unittest discover -s tests
python -B -m py_compile tooling/feynman_subscription_startup_diagnostic.py tooling/feynman_rpc_path_proxy.py tooling/feynman_rpc_path_mapping.py
git diff --check
python -c "from pathlib import Path; import json; from jsonschema import Draft202012Validator; files=sorted(Path('evals').rglob('*.schema.json')); [Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in files]; print(f'schema_files={len(files)} errors=0')"
```

결과: 전체 `421 tests` / `OK (skipped=11)`, `ResourceWarning` 없음, compile 및 diff check exit `0`, schema `17개 errors=0`이다. 실제 startup report instance도 schema error `0`이다. 11개 skip은 host capability·Windows/Node/Docker/symlink 조건이며 호환성 성공으로 세지 않는다.

## 저장·남은 문제·다음 행동

- 이 로그 작성 시점의 코드 수정은 아직 commit 전이다. 다음 작업은 수정 파일과 이 로그·최신 pointer 문서만 명시적으로 stage하여 feature branch에 commit하고 일반 push하는 것이다. main merge와 force push는 하지 않는다.
- 실제 startup은 이미 계획된 1회를 사용했으므로 같은 입력으로 재실행하지 않는다.
- 남은 문제: `thread/start -32603 remote-environment-error`의 내부 원인, 그리고 설치된 0.154.0 App Server가 기대하는 exec-server response namespace/shape가 현재 reverse mapping과 일치하는지 여부.
- 다음 한 행동: commit/push 후, `child_exit_code`가 완전하게 수집되는 offline lifecycle 회귀와 현재 실제 run artifact를 기준으로 최신 재개 지점을 갱신한다. 추가 startup 또는 Luna smoke는 새 결함 수정과 그 결함을 겨냥한 회귀 증거가 생길 때만 별도 판단한다.

