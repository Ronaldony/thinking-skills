# LOG-074 — Startup diagnostic telemetry 미생성 분류 보정

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `1a3c970 docs: record green checkpoint checks`
- 시작 dirty 상태: 사용자가 남긴 PNG 2개 untracked; 보존하고 stage하지 않음
- 작업 성격: 승인된 model-free startup 진단 `-07` 결과 수집 실패 분석 및 로컬 진단기 보정
- OpenAI Platform API/API key: 사용하지 않음
- actual turn/model/baseline/evaluation: 0회
- 보호된 로그인 홈: `C:\Users\wotmd\.codex-feynman-eval` 보존; 인증 파일·token·전체 환경변수 미출력

## 목적

직전 LOG-073에서 별도 승인을 받은 새 model-free startup diagnostic 정확히 1회를
실행하고, 실패 시 자동 반복하지 않는다. 이번 작업은 `thread/start` 이후 proxy
telemetry가 생성되지 않아 wrapper가 report를 만들지 못한 경우를 안전하게 분류하고,
그 부재를 startup 성공으로 오판하지 않도록 진단기와 schema를 보강하는 것이다.

## 승인된 `-07` 실행

사용자 승인 후 다음 명령을 정확히 1회 실행했다. 명령에는 기존 ChatGPT subscription
Codex session 경로만 사용하며 API key나 Platform API 호출은 없다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_subscription_startup_diagnostic --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote-environment 'C:\Users\wotmd\.codex-feynman-eval\environments.toml' --binding 'C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json' --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --telemetry 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-07-rpc.json' --output 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-07.json' --timeout-seconds 60
```

관찰된 안전 오류는 startup wrapper가 `startup proxy telemetry` 파일을 찾지 못해
report를 만들지 못했다는 고정 분류 대상이었다. `-07` report와 `-07-rpc` telemetry가
둘 다 생성되지 않았음을 별도 `Test-Path -PathType Leaf`로 확인했다. 원문 오류를
새 durable artifact나 공개 요약으로 복사하지 않았다.

이 실행은 진단기 내부 계약상 `initialize`와 ephemeral `thread/start`만 대상으로 하며
`turn/start`, prompt, model generation은 수행하지 않는다. telemetry가 없다는 사실만으로
인증 실패, Docker 실패, remote child 실패 또는 `thread/start` 성공을 단정하지 않는다.
이번 결과의 정확한 상태는 “진단 artifact 미생성”이며, 원인 분류를 위해 같은 명령을
자동 반복하지 않는다.

## 실행 후 안전 상태 확인

`-07` 산출물 충돌 확인:

```powershell
$report = 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-07.json'
$telemetry = 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-07-rpc.json'
[pscustomobject]@{report_exists = Test-Path -LiteralPath $report -PathType Leaf; telemetry_exists = Test-Path -LiteralPath $telemetry -PathType Leaf} | ConvertTo-Json -Compress
```

결과:

```text
{"report_exists":false,"telemetry_exists":false}
```

Docker 잔여 컨테이너 확인은 처음 sandbox named-pipe 접근이 거부됐다. 동일한 읽기 전용
`docker ps -a --filter name=feynman`를 권한 상승으로 재실행했고 출력이 비어 있어
`feynman` 관련 잔여 컨테이너 0개로 확인했다. 컨테이너를 삭제하지 않았다.

브랜치 확인 결과:

```text
branch=feat/feynman-thinking-v0.5-draft
HEAD=1a3c970
upstream=origin/feat/feynman-thinking-v0.5-draft
working-tree=사용자 PNG 2개만 untracked
```

## 로컬 보정

수정 파일:

- `tooling/feynman_subscription_startup_diagnostic.py`
- `evals/feynman-thinking/subscription-startup-diagnostic.schema.json`
- `tests/test_feynman_subscription_startup_diagnostic.py`

수정 이유와 보안 범위:

1. `_safe_proxy_telemetry`가 없는 파일을 고정 오류 `startup-proxy-telemetry-missing`으로
   분류한다. unreadable/invalid 입력도 고정 오류로 바꾸며, filesystem path나 peer가
   보낸 원문을 예외로 재출력하지 않는다.
2. `run()`은 이미 확보한 startup thread 결과를 버리지 않되, telemetry 부재를
   `proxy_telemetry_status="missing"` 및 `proxy_telemetry=null`로 명시한다. 따라서
   telemetry가 없을 때도 verdict가 ready로 승격되거나 mapping rejection 0으로
   위조되지 않는다.
3. CLI summary는 null telemetry를 빈 고정 counter처럼 처리한다. 일반 입력/파일 오류는
   `startup-diagnostic-input-invalid`만 출력해 경로·stderr·peer payload를 누설하지 않는다.
4. schema v1의 기존 artifact 호환성을 위해 새 status property는 optional로 두고,
   `proxy_telemetry`는 기존 object 또는 명시적 null을 허용한다. 새 report는 status를
   반드시 기록하지만 과거 `-02`~`-06` report는 계속 검증할 수 있다.

`proxy_telemetry=null`은 실행 성공이 아니라 telemetry 수집이 불완전하다는 의미다.
실제 startup verdict와 telemetry availability를 별도 축으로 보존한 것이 이번 보정의
핵심이다.

## 검증

대상 회귀:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_feynman_subscription_startup_diagnostic.py' -v
```

결과: `7 tests OK`.

전체 회귀:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -v
```

결과: `386 tests OK, 11 skipped`.

schema 확인은 `jsonschema.Draft202012Validator.check_schema`로 schema 자체를 검사하고,
기존 `-01`~`-06` report를 읽어 검증했다. `-01`은 새 필드가 생기기 전 prototype이라
현재 schema 오류 1건이 남고, `-02`~`-06`은 각 오류 0건이다. 기존 `-06` report를
메모리에서 `proxy_telemetry_status="missing"`, `proxy_telemetry=null`로 치환한
null telemetry sample도 오류 0건이었다. 실제 외부 artifact는 재작성하지 않았다.

추가 unit test는 synthetic private telemetry 경로가 fixed error 문자열에 포함되지
않음을 확인한다. 인증 파일, control home 내용, raw stderr, request/response payload,
thread ID, instruction source path는 읽어 저장하지 않았다.

## 판정과 미완료 사항

- 인증 gate 성공 여부와 이번 diagnostic artifact 생성 여부는 별개다. 이번 시도만으로
  새 auth 성공을 주장하지 않는다.
- Docker Desktop은 읽기 전용 잔여 컨테이너 조회에서 `feynman` 컨테이너 0개였다.
  이것은 full runner가 Windows/Docker에서 호환된다는 증명이 아니다.
- `thread/start` 통과, remote environment 연결 성공, 실제 model tool-use, baseline,
  frozen evaluation은 확인되지 않았다.
- `-07`는 승인된 1회 시도에서 artifact를 만들지 못했으므로 실제 fixed telemetry 값은
  여전히 미확정이다.
- 추가 startup diagnostic, model-turn, Luna/Terra/Sol fallback, baseline, 평가 실행은
  자동으로 하지 않는다. 새 외부 실행은 다시 명시 승인이 필요하다.
- mount 확대, 상대경로 자동 보정, config response 제조, 로그인 재실행은 하지 않았다.

## 저장 상태

- 이번 보정은 다음 commit으로 저장할 예정이다.
- push 후 원격 branch SHA와 해당 commit의 CI 결과를 확인한다.
- main 병합과 force push는 하지 않는다.

이 문서는 개발 담당 Codex용 작업 로그이며 baseline candidate나 평가 prompt로 전달하지
않는다.
