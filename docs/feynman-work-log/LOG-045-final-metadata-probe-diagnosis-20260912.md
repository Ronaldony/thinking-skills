# LOG-045 — 마지막 metadata probe와 종료 진단

- 날짜/시각: 2026-09-12, KST 22:36 이후.
- repo: `C:\DevWorks\thinking-skills`, `Ronaldony/thinking-skills`.
- branch: `feat/feynman-thinking-v0.5-draft`; 시작 HEAD `8e4fd83`.
- 시작 working tree: clean. 기존 사용자 변경 없음; 기존 artifact/auth home 보존.
- 적용 AGENTS.md: ancestor 확인 및 `rg --files -g AGENTS.md`에서 발견되지 않음.
- 사용자 승인: 보정 metadata allowlist로 **모델 probe 추가 1회만** 실행하고,
  목표 미달이면 원인을 파악해 이번 작업을 종료한다.
- 목표: 비평가적 제한 probe에서 실제 candidate tool 호출 증거 확보.
  인증 성공이나 Codex process exit 0을 목표 달성으로 대체하지 않는다.

## 1. 정확한 명령과 입력

아래 PowerShell 변수는 이 로그에서 사용한 절대 경로의 축약이며, 실행 도구에는
각 경로를 literal 인수로 전달했다. 같은 command를 다시 실행하라는 지시가 아니다.

```powershell
$probePython = 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe'
$probeRoot = 'C:\DevWorks\feynman-smoke-gpt-5.6-luna-20260910-01'
$probeEvaluator = "$probeRoot\ordinal-1-feynman-v05\evaluator"
$probeJob = "$probeEvaluator\runner-job-20260912-codex-0.154.0.json"
$probeProfile = "$probeRoot\boundary-profile.json"
$probeRemote = 'C:\Users\wotmd\.codex-feynman-eval\environments.toml'
$probeDocker = 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
$probeDockerConfig = 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config'
$probeImage = 'sha256:dab903a5999b1d3165a70de99147029809fa26d3cb1881b7c7790aac185a4726'

git status --short
git branch --show-current
git log -1 --oneline
Get-Date -Format o
Get-Command codex.cmd | Select-Object -ExpandProperty Source

& $probePython tooling/feynman_subscription_tool_use_probe.py --plan "$probeRoot\frozen-subscription-smoke-plan.json" --ordinal 1 --evaluator-case "$probeEvaluator\case.json" --runner-job $probeJob --boundary-profile $probeProfile --remote-environment $probeRemote --output-dir "$probeEvaluator\tool-use-probe-20260912-07" --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --timeout-seconds 240
```

정확한 plan/case/job/profile의 존재를 확인한 뒤 실행했다. plan은
`frozen-subscription-smoke-plan.json`이며 과거에 잘못 지정한 `eval-plan.json`이 아니다.
Get-Command도 npm `codex.cmd`를 반환했다. probe는 새 output directory에 한 번만
실행했고 process exit 0. `subscription-tool-use-probe.json`은 22:37:25에 생성,
1811 bytes. 기존 -06 등 artifact는 덮어쓰지 않았다.

읽은 진단 코드/문서: LOG-044, LOG-036, work-status/resume/handoff,
subscription probe, RPC proxy/path mapper/preflight, 관련 tests.
사용 명령은 `Get-Content`, `rg --files`, 관련 method/field에 한정한 `rg` 검색이다.
`codex exec-server --help`도 모델 없이 확인했으며 stdio 서버 설명만으로는
실제 config RPC 스키마를 확정할 수 없었다.

## 2. 승인된 단일 모델 호출 결과

| 항목 | 관찰 |
|---|---|
| authentication | `chatgpt-subscription-authenticated` |
| model / Windows control CLI | `gpt-5.6-luna` / `codex-cli 0.154.0` |
| process verdict | `subscription-tool-use-probe-completed` |
| 목표 verdict | **`tool-use-not-observed`** |
| completed candidate tool items | 0 |
| response claim | `explicit-no-tool-claim` |
| conversation events / reasoning events | 5 / 0 |
| RPC requests seen / forwarded | 34 / 12 |
| mapping-or-scope rejections | 22 (이 중 method policy rejection 2) |
| server error counts | `-32004`: 6, `-32602`: 2 |
| `fs/readFile` / read-limit-applied | 0 / 0 |
| child exit | 0 |

method counts: `initialize:1`, `initialized:1`, `environmentConfig/read:2`,
`fs/getMetadata:28`, `fs/canonicalize:1`, `fs/walk:1`.
현재 guard는 canonicalize/walk를 허용하지 않으므로 두 method는 고정 정책 오류로
반환된다. 나머지 20건의 거부는 허용된 method의 path/scope mapping 단계다.
거부된 실제 경로는 저장하지 않았으므로 개별 경로 원인을 추측하지 않는다.
server error count에는 proxy가 직접 생성한 거부 오류가 포함되지 않는다.

metadata 요청은 Codex control의 discovery 활동이지 모델이 호출한 candidate
tool event가 아니다. `fs/readFile`이 없으므로 해당 RPC를 통한 파일 본문 읽기는
관찰되지 않았다. 이는 모든 종류의 context 전달 부재를 증명하는 주장은 아니다.

원본 stderr는 비어 있지 않았지만 보존하지 않는다. 원본 final/trace/auth 상태는
출력·보존하지 않는다. 마지막 디렉터리 목록에는 safe JSON 하나만 존재했다.
현재 telemetry는 method별 request와 전체 error count만 제공하므로 실제 모델
실행의 특정 request에 특정 server error를 정확히 귀속할 수 없다.

## 3. 모델 없는 원인 분리

`tooling/feynman_rpc_discovery_diagnostic.py`를 추가했다. canonical boundary를
검증한 뒤 동일 exec-server에 고정 metadata/config 요청만 보낸다. 일반 모드와
실제 probe와 같은 제한 환경변수 모드를 비교하며 모델/auth 호출은 없다.
network-none/readonly/기존 mount 경계를 유지한다. 각각 unique `--rm` 컨테이너를
사용하고 telemetry output을 별도 파일로 지정해 실제 probe telemetry를 보존한다.
config/metadata 응답 본문은 메모리에서만 처리하며, 결과에는 error code,
고정 key 형태, 고정 오류 flag, 누락 schema field 식별자만 남긴다.

아래 4개 명령은 실제 실행한 **model-free 진단**이다. 모델 probe 4회가 아니다.
서버의 필수 field 오류를 분류해 진단 입력을 보완했으며 guard를 확대하지 않았다.

```powershell
& $probePython -m tooling.feynman_rpc_discovery_diagnostic --job $probeJob --profile $probeProfile --remote $probeRemote --docker-config $probeDockerConfig --output "$probeEvaluator\rpc-discovery-20260912-01.json"
& $probePython -m tooling.feynman_rpc_discovery_diagnostic --job $probeJob --profile $probeProfile --remote $probeRemote --docker-config $probeDockerConfig --output "$probeEvaluator\rpc-discovery-20260912-02.json"
& $probePython -m tooling.feynman_rpc_discovery_diagnostic --job $probeJob --profile $probeProfile --remote $probeRemote --docker-config $probeDockerConfig --output "$probeEvaluator\rpc-discovery-20260912-03.json"
& $probePython -m tooling.feynman_rpc_discovery_diagnostic --job $probeJob --profile $probeProfile --remote $probeRemote --docker-config $probeDockerConfig --output "$probeEvaluator\rpc-discovery-20260912-04.json"
& $probeDocker --config $probeDockerConfig run --rm --network none --read-only --user 1000:1000 --entrypoint codex $probeImage --version
```

- -01: initialize/metadata success; config requests rejected; sanitizer는 일부
  missing-field 이름을 숨겨 진단 분류가 불충분했다.
- -02: 제한된 schema identifier 분류를 추가. `{}`는 `cwd` 누락,
  `{cwd}`는 `configPaths` 누락으로 `-32602`. 실제 모델 request 본문을 복원한 것이
  아니라 고정 synthetic 요청의 결과다.
- -03: `configPaths:[]` 추가 시 `requirementsPaths` 누락. 당시 label의
  `complete`는 잘못된 가정이어서 최종 코드에서 `config-paths`로 바꿨다.
- -04: 두 빈 목록을 모두 명시해도 host/container URI 요청 모두 `-32602`.
  현재 sanitizer로 세부 사유까지 특정하지 못했으며 valid config RPC를 확보했다고
  주장하지 않는다. 이 지점에서 추가 실험을 종료했다.
- 모든 비교에서 기존 `candidate.py` metadata는 일반/제한 모드 모두 성공.
  의도적으로 없는 diagnostic filename metadata는 두 모드 모두 `-32004`.
  따라서 실제 probe의 `-32004` 개수만으로 실행 인프라 고장을 단정하지 않는다.
- synthetic `fs/canonicalize {path: candidateURI}`는 일반 모드 `-32600`, 제한
  모드 proxy `-32001`. 메서드 미지원인지 해당 요청 형식 오류인지까지 확정하지 않는다.
- -04의 양쪽 child exit 0. config 오류는 단순히 allowlist 통과만으로 해결되지 않는다.
- 고정 Docker image의 `codex --version`은 **`0.153.4`**.
  readonly PATH-alias warning은 있었으나 version command exit 0.
  Windows 제어 CLI `0.154.0`과 서버 버전이 다르다는 사실을 직접 확인했다.

## 4. 원인 판단과 검증 공백

확인된 문제는 **제어 CLI와 exec-server의 버전 불일치**, **제한 정책과 discovery
요청의 충돌**, 그리고 **기존 preflight가 실제 제한-mode 초기화/모델 도구 노출을
검사하지 않았다는 점**이다. metadata path 보정 자체는 실기기 검사에서 동작한다.
그런데 config RPC 계약과 canonicalize 요청은 통과하지 못했다.

이는 remote discovery 경로가 아직 end-to-end 검증되지 않았다는 근거다.
다만 raw request params나 실제 model-facing tool catalog를 보존하지 않았으므로
버전 불일치 하나가 no-tool의 결정적 원인이라고 단정할 수 없다. 모델의 tool 선택,
노출된 도구 종류와 fixed filesystem-read prompt의 대응도 미확정이다.
backend `fs/readFile`이 존재한다는 사실만으로 같은 이름의 도구가 모델에게
제공된다고 가정하면 안 된다.

LOG-044의 “원래 guard가 진행을 막은 결과”라는 단일 원인 단정은 정정했다.
인증 실패, Docker Desktop 정지, Luna 자체의 도구 불능으로 결론 내릴 근거도 없다.
기존 일반 preflight의 task/skill read 및 harmless process 성공은 유지되지만,
제한 probe가 동작한다는 증거로 사용할 수 없다. metadata summary의 top-level key
검사는 모든 응답의 비밀정보 부재나 전체 read-scope 안전성 증명도 아니다.

OpenAI Docs 스킬에 따라 공식 설정 문서를 검색·열람했다:
[Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
이 문서는 이번 exec-server RPC의 상세 스키마나 설치 버전 간 호환성을 확정하지
않으므로 원인 판단은 위 로컬 관찰로 제한했다. 문서 검색은 Platform API 호출이 아니다.

## 5. 수정 이유와 검증

production proxy/mapping/allowlist, 모델 ID, Docker image, 로그인 설정은 이번
진단에서 변경하지 않았다. 새 diagnostic helper와 테스트만 추가하고, 상태/재개/
인계 문서를 실패·종료 상태에 맞췄다. helper는 기존 output/telemetry 덮어쓰기와
잘못된 boundary에서의 launch를 거부한다. 진단 실패를 tool-use 성공으로 승격하지 않는다.

```powershell
& $probePython -m unittest tests.test_feynman_rpc_discovery_diagnostic tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_path_proxy tests.test_feynman_rpc_preflight tests.test_feynman_subscription_tool_use_probe
& $probePython -m unittest discover -s tests -p 'test_*.py'
& $probePython -m compileall -q tooling tests
git diff --check
& $probeDocker --config $probeDockerConfig ps -a --filter name=feynman --format '{{.Names}} {{.Status}}'
Get-ChildItem -LiteralPath "$probeEvaluator\tool-use-probe-20260912-07" -Force | Select-Object Name,Length
Get-Content -LiteralPath "$probeEvaluator\tool-use-probe-20260912-07\subscription-tool-use-probe.json"
```

- targeted: 30 tests OK; 새 6 tests는 summary 비밀값 비보존, schema identifier 제한,
  잘못된 error 처리, 고정 flag, invalid-boundary launch 방지, 기존 결과 보존 검사.
- full suite: 312 tests, OK (skipped=10), 11.636초. 302개 통과/10개 skip이며
  skip을 실기기 성공으로 계산하지 않는다. compileall도 exit 0.
- Feynman Docker container 목록 0행. unique diagnostic containers는 `--rm`으로
  제거됐다. 기존 image/volume/다른 컨테이너/로그인 홈은 삭제하지 않았다.
- 일부 Git command의 전역 ignore 파일 접근 warning은 관찰됐고 설정을 변경하지 않았다.

## 6. 종료 및 남은 일

이번 승인된 모델 호출은 1회로 종료했다. 목표 미달을 성공으로 처리하지 않는다.
추가 model retry, baseline, 새로운 ordinal smoke 및 Feynman 성능 평가는 실행하지
않았다. API key/Platform API 사용, credential 열람·복사·해시·업로드, 개발 대화의
candidate 전달도 하지 않았다. 재로그인을 요청하지 않는다.

향후 별도 재개 시 순서는 다음과 같다(이번 작업에서는 실행하지 않음).

1. 양쪽 Codex 버전을 함께 고정하고 실제 config/filesystem RPC 계약을 확인한다.
   image 재빌드 시 image ID/profile/job binding을 함께 갱신해야 한다.
2. 모델 없는 **제한 모드** discovery preflight를 만들고 실제 model-facing tool과
   허용 RPC가 대응하는지 확인한다. 그냥 allowlist를 넓히지 않는다. config path
   범위, metadata traversal/symlink, 읽기 응답 제한도 전체 경계 감사에 포함한다.
3. 위 조건을 통과한 뒤에만 별도 승인된 model probe를 고려한다.
   baseline은 실제 tool-use 증거 확보 전 계속 보류한다.

## 7. 실제 저장 결과

```powershell
git add -- tooling/feynman_rpc_discovery_diagnostic.py tests/test_feynman_rpc_discovery_diagnostic.py docs/feynman-work-log/LOG-045-final-metadata-probe-diagnosis-20260912.md docs/feynman-work-log/LOG-044-guarded-probe-metadata-discovery-20260912.md docs/feynman-work-status.md docs/feynman-codex-resume-prompt.md docs/feynman-codex-handoff.md
git diff --cached --check
git commit -m 'diagnose: close final guarded probe with RPC evidence'
git push origin feat/feynman-thinking-v0.5-draft
```

- 진단/테스트/문서 commit: **`76320ed`**, 7 files changed.
- ordinary push 성공: remote branch가 `8e4fd83..76320ed`로 갱신됐다.
- `git diff --check`, staged diff check 모두 exit 0. CRLF 변환 warning만 있었고
  formatting 오류는 없었다. 새 HEAD의 hosted CI 결과는 이번에 조회하지 않았다.
- 이 저장 결과를 기록하는 문서 전용 후속 checkpoint를 별도로 커밋/push한다.
  최종 SHA는 self-referential hash를 문서에 넣지 않고 `git log -1`로 확인한다.

종료 저장/검증 명령:

```powershell
git add -- docs/feynman-work-log/LOG-045-final-metadata-probe-diagnosis-20260912.md
git diff --cached --check
git commit -m 'docs: record final probe diagnostic checkpoint'
git push origin feat/feynman-thinking-v0.5-draft
git status --short
git log -1 --oneline
git ls-remote origin refs/heads/feat/feynman-thinking-v0.5-draft
```

main merge/force push는 하지 않는다. 남은 기술 목표는 위 6절에 기록했으며,
이번 요청의 진단 작업 종료와 Feynman 평가 프로젝트 완료는 구분한다.
