# LOG-051 — full-runner MCP contract model-free 검증

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `10d8dd11985ea9109a361a772fb011479e091973`
- 모델 호출: 0회
- 인증: 사용하지 않음
- OpenAI Platform API/API key: 사용하지 않음

## 목적

LOG-050의 성공은 no-argument 1-byte diagnostic MCP의 model-facing 노출만
입증했다. 다음 단계는 tools-10 full runner에 필요한 권한을 임의 filesystem/shell
도구로 넓히지 않고, 모델 없이 계약을 고정·검증하는 것이었다.

이번 계약은 다음 세 도구만 제공한다.

1. `feynman_read_candidate`: 인자 없이 고정 `candidate.py`만 읽는다.
2. `feynman_write_candidate`: `content`만 받아 고정 `candidate.py`에 쓴다. path,
   shell, argv는 받지 않는다.
3. `feynman_run_tests`: 인자 없이 고정 `test_candidate.py`를 실행한다. adapter가
   고정 Docker argv를 만들며 모델은 command/image/network를 선택하지 않는다.

모든 도구는 호출 횟수와 payload/output 크기를 제한한다. test Docker는
`--network none`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, `env -i`,
candidate directory read-only mount를 사용한다.

## 첫 실행과 원인 분리

추가한 첫 adapter 구현으로 disposable fixture preflight를 실행했다.

명령:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_full_runner_docker_preflight --node-bin 'C:\Program Files\nodejs\node.exe' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:dab903a5999b1d3165a70de99147029809fa26d3cb1881b7c7790aac185a4726' --output 'C:\DevWorks\feynman-full-runner-compat-20260913-01\full-runner-docker-preflight.json'
```

관찰 결과: exit code 1, sanitized `ValueError`.

원인 분리 명령은 pinned image에서 `python --version`을 고정 network-none
container로 실행했다. 결과는 `env: 'python': No such file or directory`였다.
동일 image의 OS는 Debian 12/bookworm이고 `apt-get`은 있었지만 Python 실행
파일은 없었다. 따라서 모델이나 auth 문제가 아니라 test runtime 누락이었다.

## 수정

변경 파일:

- `tooling/feynman_full_runner_contract.py`: 3-tool override, fixed limits, image
  digest 및 payload-free lineage
- `tooling/docker/codex-remote/feynman_full_runner_adapter.mjs`: 고정 read/write/
  Docker test MCP 구현
- `tooling/feynman_full_runner_preflight.py`: Codex App Server catalog/schema gate
- `tooling/feynman_full_runner_catalog_preflight.py`: disposable catalog 실행기
- `tooling/feynman_full_runner_docker_preflight.py`: disposable 실제 Docker protocol
  실행기
- `tooling/feynman_mcp_catalog_preflight.py`: 여러 target tool schema의 sanitized 요약
- `evals/feynman-thinking/full-runner-mcp-contract.schema.json`: contract schema
- `tooling/docker/codex-remote/Dockerfile`: Debian `python3`만 추가 설치하고 apt 목록
  제거, Python 3.11을 고정 확인

수정 이유: candidate가 Python 코드인 tools-10 고정 test를 실제 network-disabled
container에서 실행하려면 runner image에 Python runtime이 필요하다. `python3`를
고정 argv로 사용해 shell resolution과 모델 제공 command를 제거했다.

새 image 빌드:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' build --tag 'feynman-codex-remote:full-runner-local' 'tooling\docker\codex-remote'
```

결과: 성공. 새 immutable image ID:

`sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a`

## 검증 결과

### 실제 Docker protocol

새 image로 같은 preflight를 disposable synthetic candidate에 실행했다.

결과 artifact:

`C:\DevWorks\feynman-full-runner-compat-20260913-01\full-runner-docker-preflight-02.json`

판정: `full-runner-mcp-docker-preflight-passed`, `model_calls=0`.

고정 catalog, read, write, network-none test, write 후 read 반영 등 6개 check가
모두 true였다. synthetic fixture와 container는 실행기 cleanup으로 제거됐다.

### Codex App Server catalog

명령:

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m tooling.feynman_full_runner_catalog_preflight --codex-bin 'C:\Users\wotmd\AppData\Roaming\npm\codex.cmd' --node-bin 'C:\Program Files\nodejs\node.exe' --adapter 'C:\DevWorks\thinking-skills\tooling\docker\codex-remote\feynman_full_runner_adapter.mjs' --docker-bin 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --docker-image-id 'sha256:2b5c626cca0edbf1338b1adb31bcb941f20ac32e354d1973f1756d6b66933b3a' --output 'C:\DevWorks\feynman-full-runner-compat-20260913-01\full-runner-catalog-preflight.json'
```

판정: `full-runner-mcp-contract-ready`, `model_calls=0`.

Codex App Server catalog에서 server 1개와 정확한 3개 도구를 확인했다. read/test는
빈 object schema, write는 `content` 하나만 required인 string schema였다. transient
CLI override를 사용했으며 user config와 인증 home 파일은 사용하지 않았다.

### 자동화 테스트

- targeted: `10 tests OK`, `1 skipped` (Windows local App Server integration test는
  test discovery 환경의 image lookup 조건으로 skip; 동일 catalog 검증은 위 CLI에서
  성공)
- Node syntax check: 성공
- full regression: `347 tests OK`, `11 skipped`

## 해석과 제한

확인한 것:

- 모델이 선택할 수 있는 path/command/network가 없는 3-tool MCP catalog
- candidate.py write가 고정 파일에만 적용되는 adapter protocol
- 실제 Docker `--network none`에서 Python fixed test가 실행되고 성공하는 경로
- Docker rootfs/privilege/env 정책과 fixed test contract의 연결

아직 확인하지 않은 것:

- 실제 ChatGPT subscription 모델이 이 3-tool catalog를 사용하는 model trace
- tools-10 평가 prompt 전달
- baseline/feynman-v05 실행 및 비교
- post-run canary/attestation/link/evidence/review/result-v4
- explicit reasoning-effort가 고정된 behavioral pilot

따라서 이 checkpoint는 full-runner 구조 preflight 성공이지 모델 평가 성공이나
Feynman 효과 근거가 아니다. 다음은 실제 평가를 시작하지 않고, 이 contract를
existing tools-10 runner-job/profile의 model-free artifact chain에 결속하는 작업이다.

## 저장 상태

- 시작 HEAD: `10d8dd11985ea9109a361a772fb011479e091973`
- 구현 checkpoint commit: `17390e5bf192a0a4d516644b08da634d7cec6252`
- push: `origin/feat/feynman-thinking-v0.5-draft`에 완료
- 해당 SHA의 PR workflow: 7개 모두 success
- main merge: 하지 않음
- force push: 하지 않음
- 사용자 기존 untracked PNG 2개: 보존, stage하지 않음
