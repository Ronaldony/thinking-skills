# LOG-005 — remote apply-patch → remote exec 실제 E2E 성공

- **시각(KST)**: 2026-09-08 20:58
- **검증 대상 head**: `e761af40e95ce3374e639a5deb22939d7a0b58b8`
- **workflow**: `validate-feynman-remote-patch-reference`
- **run**: #2, run id `34223199407`
- **artifact**: id `10054612499`
- **artifact ZIP SHA-256**: `f8a3213fa9e61631989b81457a0e49ab461fb7738e7ada296c8d584e7d3c2957`

## 목적

이전 `unsupported custom tool call: apply_patch` 실패가 remote execution 자체의 한계인지, `mock-model` metadata 부재 때문인지 실제 E2E로 구분한다.

## 입력/설정

- control-plane Codex: `codex-cli 0.153.4`
- tool-boundary Codex: `codex-cli 0.153.4`
- model provider: 로컬 mock Responses server
- 실제 외부 모델/API credential: 사용하지 않음
- remote tool boundary: Docker `network_mode=none`
- local execution: canonical `environments.toml`에서 비활성화

### bundled model metadata 유도

`codex debug models --bundled`의 실제 0.153.4 catalog를 입력으로 사용했다.

`mock-model-catalog-manifest.json` 실제 값:

- bundled catalog SHA-256: `32bdd1fe3ffd82df3d03c6c9b9d9068087cd9640ded4377f604586d7a743749b`
- patch-capable candidate count: `11`
- 선택 source index: `0`
- source slug: `gpt-6-astra`
- source display name: `GPT-6-Astra`
- source `apply_patch_tool_type`: `freeform`
- source `shell_type`: `unified_exec`
- source modalities: `text`, `image`
- derived mock catalog SHA-256: `b34e83476f4ab68cd90b86efa4bae96e196bbb4c39853f9ab012eb50709a41f1`
- source metadata에서 변경한 필드는 `slug`, `display_name` 두 개뿐임을 helper가 검증함.

주의: 위 모델 목록/slug는 **이 run에서 설치된 Codex 0.153.4 bundled catalog에 대한 관찰**이다. 다른 시점/버전의 일반적인 모델 목록 주장으로 사용하지 않는다.

## unit regression

remote-patch workflow에서 **55개 unit tests 전부 통과**.

신규 catalog regression은 다음을 fail-closed로 확인한다.

- patch 지원 metadata가 없는 source
- disabled shell source
- text input 미지원 source
- duplicate source slug
- malformed model entry
- mock slug whitespace
- source metadata의 slug/display_name 외 변경

## 실제 E2E trace

`codex-trace.jsonl` thread id:

`01a080df-ab1c-7e31-9145-8500c65b3a39`

실제 이벤트 순서:

1. `thread.started`
2. `file_change` start — `remote-patch-proof.txt` add
3. `file_change` completed
4. `command_execution` start
5. `command_execution` completed, exit code `0`
6. final `agent_message` = `REMOTE_EXEC_REFERENCE_OK`
7. `turn.completed`

실제 command output:

```text
REMOTE_PATCH_OK
AUTH_ENV_CLEAN
NETWORK_BLOCKED
REMOTE_EXEC_OK
```

따라서 다음 네 조건이 한 command execution에서 동시에 확인됐다.

- 앞선 remote apply-patch 결과를 실제로 읽음
- remote tool env에서 auth-like key를 발견하지 않음
- control-plane mock endpoint로 TCP 연결 실패
- candidate workspace에 exec proof 생성

## proof files

- `candidate/remote-patch-proof.txt` = `REMOTE_PATCH_OK\n`
- patch proof SHA-256: `d114b086391ca62172857bdaf02717896696f320de0d4d101a53ebccfa140f41`
- `candidate/remote-tool-proof.txt` = `REMOTE_EXEC_OK\n`
- exec proof SHA-256: `b95df8af34190814b55f57d5b20a58233422cd160c380c49acb8d9e116ac397d`

## mock request round trip

`mock-state.json`은 정확히 3개의 model request를 기록했다.

1. tool output 없음 → mock server가 apply_patch 요청
2. matching patch output 존재 → mock server가 exec_command 요청
3. matching patch + exec output 존재, exec output 안에 patch/workspace/network/auth marker 모두 존재 → final 반환

`validation_error = null`.

## Docker/profile 검증

`tool-container-inspect-check.json`:

- verdict: `docker-inspect-matches-profile`
- image ID: `sha256:31da68b0531cc97a4bc6175f0e6ad816bac86824512530d12ca1796d94175dfc`
- network mode: `none`
- rw mounts는 정확히 다음 4개:
  - candidate
  - candidate-home
  - tool-codex-home
  - tool-temp
- tmpfs: `/tmp`
- candidate env keys:
  - `CODEX_HOME`
  - `HOME`
  - `PATH`
  - `PYTHONDONTWRITEBYTECODE`
  - `TMPDIR`

## content-bound result digests

`reference-result.json`:

- schema: `3`
- verdict: `mock-remote-tool-reference-passed`
- scenario: `patch-then-exec`
- boundary profile: `31a04eaa16bd3ff2520c35cf7ace3fd24e33f2262d0fafa6374acc5a93d0572b`
- runner job: `388972dcf99964bd2b2ac64a0f77d033a7ee9a8f122422fab5eca1f10f653b7c`
- remote environment: `2493ce012c032b17b238706b714368332055b403df992cc1ed9f77488a98033f`
- network reference: `c45a3086f9dc41cb856babf375ec46d82b8bdfd16f0e104a27031673bd6513d0`
- mock state: `d56da96662b074f438b67cf21c6bae04c8642317c5b0820b26420aefeb343d47`
- Codex trace: `2aa24ae3d1268d0de7b98223df7cc98d6cfb99981e51cdec2d0daa2833fa4b76`
- Docker inspect: `f26c74e1333d8077ee92d330968dcda68b9b7e70b8d27f7e30b1ae4d2e2c0efd`
- patch proof: `d114b086391ca62172857bdaf02717896696f320de0d4d101a53ebccfa140f41`
- candidate exec proof: `b95df8af34190814b55f57d5b20a58233422cd160c380c49acb8d9e116ac397d`
- mock server program: `dfd31de0caea53ebff387cddd9720ad87dcf5d06fd9f206932f1df3a7f179482`

## 결론

실패했던 patch reference는 remote exec의 구조적 한계가 아니었다. `mock-model`의 fallback metadata에는 apply-patch handler를 등록할 정보가 없었고, 설치된 Codex bundled metadata에서 실제 patch-capable model metadata를 안전하게 파생해 `model_catalog_json`으로 주입하자 **remote apply-patch → remote exec → model final** 전체 왕복이 성공했다.

이 결과가 증명하지 않는 것:

- 실제 외부 모델 서비스 인증 안전성
- 실제 OpenAI API key의 비노출
- Feynman skill의 행동 성능 개선
- production 배포 안전성

## 다음 작업

실제 credential을 요구하기 전에 synthetic bearer canary를 강화한다.

1. control-plane mock endpoint가 synthetic bearer를 실제 수신했는지 원문 없이 SHA-256으로 확인.
2. remote tool env에 auth-like key가 없을 뿐 아니라 동일 credential 값도 존재하지 않는지 hash 비교.
3. candidate-owned 파일 및 Codex trace에 synthetic credential 원문이 복제되지 않았는지 evaluator-side scanner로 확인.
4. 위 증거를 별도 reference result로 묶는다.

이 단계까지는 사람 개입이 필요 없다.
