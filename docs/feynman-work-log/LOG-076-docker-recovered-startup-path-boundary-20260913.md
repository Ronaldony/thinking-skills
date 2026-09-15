# LOG-076 — Docker recovery 후 startup path boundary 보정

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `fd7b6b1 docs: record thread schema and docker blocker`
- 시작 dirty 상태: 사용자 PNG 2개 untracked; 보존하고 stage하지 않음
- 작업 성격: Docker recovery 확인, 승인된 model-free startup diagnostic 1회, local path-boundary 보정
- OpenAI Platform API/API key: 사용하지 않음
- actual model turn/baseline/evaluation: 0회
- protected control home: `C:\Users\wotmd\.codex-feynman-eval` 보존; login file/token/full environment 미출력

## 목적

사용자가 Docker Desktop 정상화를 알렸으므로, LOG-075에서 Docker blocker로 중단된
수정된 Codex 0.154.0 `thread/start` startup gate를 재개했다. Docker 정상 여부와
subscription auth, remote thread startup, 실제 model/evaluation을 서로 분리해
판정한다.

## 공식 기준

공식 [Codex App Server 문서](https://learn.chatgpt.com/docs/app-server)는
`initialize` 뒤 `initialized`를 보내고 `thread/start`를 별도 호출하는 lifecycle,
실행한 Codex version에 맞는 JSON Schema 생성, remote environment의 native path
syntax를 설명한다. 이 문서와 설치된 0.154.0 schema를 기준으로 startup payload에는
비공식 `environments`/`runtimeWorkspaceRoots`를 넣지 않는다.

## 실제 명령과 관찰

저장소/브랜치/AGENTS 상태:

```powershell
rg --files -g 'AGENTS.md' -g '!Codex 이미지*'
git status --short --branch
git log -1 --oneline --decorate
```

관찰: 적용되는 `AGENTS.md`는 없었다. branch는
`feat/feynman-thinking-v0.5-draft`이고 HEAD/원격은 `fd7b6b1`이었다. 사용자 PNG
2개만 untracked였다.

Docker read-only preflight:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}|{{.Containers}}|{{.Images}}|{{.Driver}}|{{.OperatingSystem}}'
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' image inspect 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --format '{{.Id}}|{{.Os}}|{{.Architecture}}|{{json .Config.Entrypoint}}|{{json .Config.Cmd}}'
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' ps -a --filter name=feynman --format '{{.Names}}|{{.Status}}'
```

관찰:

```text
29.7.2|linux|aarch64|0|14|overlayfs|Docker Desktop
sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a|linux|arm64|["docker-entrypoint.sh"]|["node"]
feynman_containers=0
```

`feynman-codex-remote:local` tag는 별도 새 digest를 가리켰지만, binding이 고정한
digest image가 로컬에 남아 있어 기존 binding을 변경하지 않았다. 고정 image의
기본 `WorkingDir`는 빈 값(컨테이너 기본 `/`)이었다. image 전체 환경변수는 읽거나
출력하지 않았다.

canonical structure preflight:

```text
remote_environment_verdict=remote-exec-environment-valid include_local=false environment_id=candidate
report_exists=false telemetry_exists=false
```

## 승인된 startup diagnostic 1회

새 output/telemetry 경로를 사용해 다음 명령을 정확히 1회 실행했다. `initialize`,
`initialized`, ephemeral `thread/start`만 포함하며 `turn/start`, prompt, model
generation은 포함하지 않는다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_subscription_startup_diagnostic --runner-job 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json' --boundary-profile 'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json' --remote-environment 'C:\Users\wotmd\.codex-feynman-eval\environments.toml' --binding 'C:\DevWorks\feynman-full-runner-binding-20260913-01\gpt-5.6-luna-full-runner-binding.json' --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --telemetry 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-08-rpc.json' --output 'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\startup-diagnostic-20260913-08.json' --timeout-seconds 60
```

종료 코드는 `0`이지만 gate verdict는 다음과 같았다.

```text
verdict=subscription-startup-thread-blocked
thread_started=false
error_code=-32603
error_category=remote-environment-error
initialize_completed=true
turn_requests_sent=0
model_generation_requests_sent=0
process_tree_reaped=true
proxy_telemetry_status=available
```

payload-free telemetry는 다음을 보였다.

```text
request_methods={environmentConfig/read:1, fs/getMetadata:8, initialize:1, initialized:1}
request_mapping_rejections=9
request_mapping_rejection_reasons={host-path-outside-declared-mount:9}
request_mapping_rejection_method_reason_fields={environmentConfig/read:{host-path-outside-declared-mount:{cwd:1}}, fs/getMetadata:{host-path-outside-declared-mount:{path:8}}}
requests_seen=11
requests_forwarded=2
responses_seen=1
responses_forwarded=1
response_mapping_rejections=0
malformed_requests=0
malformed_responses=0
child_exit_code=0
```

report schema errors는 `0`, report/telemetry 크기는 각각 `2824`/`1290` bytes였다.
privacy flags의 payload, thread id, instruction source path, raw stderr, credential
직접 읽기, control home serialization은 모두 `false`였다.

## 원인 판정과 수정 이유

이번 실행은 Docker engine, image 실행, protocol initialize, child reap까지 통과했다.
차단은 `thread/start`가 원격 환경 discovery를 시작한 뒤 request-side path mapping에서
발생했다. Docker image의 기본 working directory가 `/`인 것은 확인했지만, 과거 LOG-035의
실험 결과에 따라 `--workdir /run/candidate`를 즉시 되돌리지 않았다. 해당 변경은 image
startup compatibility를 별도 검증해야 하며, 현재 boundary를 넓히는 근거도 없다.

대신 startup diagnostic 자체가 저장소 root에서 실행되어 App Server의 implicit local
discovery가 repository/host namespace를 참조할 가능성을 제거했다. 다음 최소 변경을
적용했다.

- `tooling/feynman_subscription_startup_diagnostic.py`의 App Server `Popen`에
  `cwd=candidate`를 지정했다.
- 이는 protected auth home, remote environment file, Docker mounts를 수정하지 않는다.
- candidate 밖의 개발 repo와 handoff 문서가 startup context로 섞이지 않게 한다.
- 원격 thread `cwd=/run/candidate`와 네 개의 declared mount는 그대로 유지한다.

## 수정 후 검증

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_subscription_startup_diagnostic tests.test_feynman_rpc_path_mapping tests.test_feynman_rpc_path_proxy tests.test_feynman_remote_exec_environment tests.test_feynman_path_mapping -v
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m compileall -q tooling tests
git diff --check
```

관찰: targeted `55 tests OK`, compileall exit `0`, `git diff --check` exit `0`.
수정 후에는 동일 startup command를 자동 반복하지 않았다.

## 미완료와 다음 행동

- `thread/start` gate는 아직 green이 아니다.
- `host-path-outside-declared-mount`의 실제 path 값은 privacy 정책상 보존하지 않아,
  이번 로그만으로 App Server 내부 source를 단정하지 않는다.
- candidate 밖 immutable image namespace와 host-side implicit discovery를 각각
  어떻게 다룰지는 다음 model-free compatibility 검증에서 확인해야 한다.
- 실제 model turn, baseline, Feynman candidate, Terra/Sol fallback, 평가 결과는 없다.
- 다음 외부 실행은 새 수정의 효과를 검증하는 별도 승인 지점이며, 자동 재시도하지 않는다.

## 저장 상태

이 로그와 `cwd=candidate` code change를 검증 후 feature branch에만 commit/push한다.
main merge와 force push는 하지 않는다. 사용자 PNG 2개는 계속 untracked로 보존한다.

## Commit/push receipt

- code/docs commit: `6148093 fix: isolate startup diagnostic working directory`
- push: `fd7b6b1..6148093` to `origin/feat/feynman-thinking-v0.5-draft`
- remote SHA: `6148093278d65d5938aaa2cdcb3931a460f854ac`
- 해당 SHA의 GitHub Actions 7개 workflow: 모두 `completed / success`
  (`validate-feynman`, `validate-feynman-codex-reference`,
  `validate-feynman-docker-reference`, `validate-feynman-remote-exec-reference`,
  `validate-feynman-remote-patch-reference`, `validate-feynman-subscription-readiness`,
  `validate-feynman-unit-diagnostic`)
- main merge/force push: 하지 않음
