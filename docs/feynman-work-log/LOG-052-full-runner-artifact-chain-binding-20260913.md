# LOG-052 — full-runner artifact chain model-free binding

- 시각: 2026-09-13 03:52 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 작업 상태: DONE (model-free checkpoint)
- 시작 HEAD: `1775dc3ccf87efbaa86f552b792f5413efed8c45`
- 모델 호출: 0회
- 인증 호출: 0회
- OpenAI Platform API/API key: 사용하지 않음

## 목적

LOG-051에서 검증한 fixed full-runner MCP contract를 기존 tools-10
runner-job/profile chain에 연결한다. 기존 evaluation artifacts와 protected
`C:\Users\wotmd\.codex-feynman-eval`은 수정·복사·덤프하지 않고, Windows host
path와 Linux container destination의 결속 및 full-runner preflight evidence만
model-free로 확인한다.

## 사전 확인

명령:

```powershell
rg --files -g 'AGENTS.md' -g '!node_modules'
git status --short
git branch --show-current
git log -3 --oneline
```

관찰:

- 적용되는 `AGENTS.md` 없음
- branch는 `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD는 `1775dc3...`
- 기존 사용자 PNG 2개만 untracked였고 stage하지 않음

기존 실제 artifacts에서 읽은 요약:

- Luna/Terra/Sol job 모두 schema v3, `tools-10`, `feynman-v05`, repeat 1
- Codex CLI `0.154.0`, Docker backend `29.7.2`, `network=none`
- `/run/candidate`, `/run/home`, `/run/codex`, `/run/temp` 네 native mapping
- `api_key_auth_allowed=false`, `candidate_auth_exposed=false`
- profile image는 기존 remote-exec image이며 full-runner image와 별도임

작업 전 세 job에 실행한 명령:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_runner_job_validate --job <model>\evaluator\runner-job.json --boundary-profile <root>\boundary-profile.json
```

결과: 세 job 모두 `runner-job-valid`. 이는 login/token 파일을 읽지 않는 구조
검사이며 model/auth 증거가 아니다.

## 구현

추가 파일:

- `tooling/feynman_full_runner_binding.py`
- `evals/feynman-thinking/full-runner-binding.schema.json`
- `tests/test_feynman_full_runner_binding.py`

binding validator는 다음을 fail-closed로 확인한다.

1. strict runner-job/profile validation과 `tools-10 × {baseline,feynman-v05}`
2. native Windows host source → canonical Linux destination 네 개의 explicit rw mount
3. 실제 candidate의 고정 `candidate.py`/`test_candidate.py`와 full-runner override
4. model-free App Server catalog preflight의 exact lineage
5. network-disabled Docker preflight의 fixed catalog/read/write/test/security policy
6. catalog/Docker preflight의 `model_calls=0`, `authentication_used=false`,
   credential/payload non-preservation

기존 profile image와 full-runner image가 다를 수 있으므로 manifest에서 두 digest를
별도 기록한다. mismatch를 무시하고 기존 profile이 새 image를 실행했다고 표시하지
않는다. 기존 runner job/profile JSON은 쓰지 않았다.

## 실제 실행 명령과 관찰

모델별 실제 candidate를 사용해 빈 disposable Codex home에서 catalog preflight를
실행했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_full_runner_preflight --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --codex-home <disposable-empty-home> --output <model-catalog-preflight.json> --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --candidate <model>\candidate --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a'
```

첫 shell 시도는 PowerShell 예약 변수 `$HOME`을 `$home`으로 재사용해 인자 조립
전에 실패했다. Codex/auth/Docker preflight는 시작되지 않았다. 변수명을
`$catalogHomePath`로 바꾼 재실행에서 세 모델 모두 다음을 얻었다.

```text
verdict: full-runner-mcp-contract-ready
model_calls: 0
```

그 다음 binding 명령을 세 모델에 각각 실행했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_full_runner_binding --runner-job <model>\evaluator\runner-job.json --boundary-profile <root>\boundary-profile.json --catalog-preflight <model-catalog-preflight.json> --docker-preflight <full-runner-docker-preflight-02.json> --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --output <model-full-runner-binding.json>
```

결과: Luna/Terra/Sol 모두 `full-runner-mcp-artifact-chain-bound`, native mounts 4,
catalog/Docker checks true, `model_calls=0`, `authentication_used=false`.

## 검증 범위

단위 테스트:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest -v tests.test_feynman_full_runner_binding
```

결과: `2 tests OK`.

전체 회귀:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_*.py'
```

결과: `349 tests OK, 11 skipped`, exit 0. Git ignore 권한 경고가 일부 있었지만
테스트 결과에는 실패가 없었다.

검증하지 않은 것:

- ChatGPT subscription auth gate 재실행 및 실제 model turn
- baseline/Feynman smoke
- candidate가 MCP 도구를 실제 호출하는 trace
- post-run boundary canary, attestation, link, evidence, review, result-v4
- behavior/performance 또는 Feynman skill 효과

## 저장 상태

- 이번 구현과 문서 변경은 아직 commit 전이며 다음 단계에서 diff 확인 후 commit한다.
- push 전에는 사용자 PNG 2개가 계속 untracked인지 확인한다.
- main merge와 force push는 하지 않는다.

## 다음 정확한 행동

`tooling/feynman_full_runner_binding.py`에 연결된 artifact를 기반으로 skill
exposure와 fixed command wiring을 model-free preflight하고, 그 결과를 새 log에
기록한다. 해당 선행 조건 전에는 subscription smoke나 baseline을 시작하지 않는다.
