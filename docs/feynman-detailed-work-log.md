# feynman-thinking 상세 작업 로그

이 문서는 `feat/feynman-thinking-v0.5-draft`에서 수행하는 작업을 **중단 후에도 정확히 이어갈 수 있도록** 기록한다.

## 기록 규칙

각 작업 단위마다 아래를 남긴다.

- **시각(KST)**: 작업 판단/완료 시각
- **기준 head**: 작업을 시작할 때의 branch SHA
- **목적**: 무엇을 검증하거나 바꾸는가
- **입력/관찰**: 실제 코드·CI·artifact에서 확인한 사실
- **변경**: 생성/수정한 파일과 계약
- **검증**: unit/CI/실행 결과
- **결론**: 사실로 주장 가능한 범위
- **다음 작업**: 이어서 해야 할 정확한 한 단계
- **남은 위험**: 아직 닫히지 않은 경로

성능 개선, 격리 성공, 인증 안전성은 실제 검증 근거가 없으면 완료로 기록하지 않는다.

---

## LOG-001 — 중단 상태 재확인 및 remote-exec 실패 원인 고정

- **시각(KST)**: 2026-09-08 20:20
- **기준 head**: `2540035d0b1fdc0f06df9fcde96bb2dc93cc8b02`
- **목적**: 이전 작업이 어디서 중단됐는지 정확히 복원한다.
- **입력/관찰**:
  - PR #1은 open/draft이며 head는 위 SHA였다.
  - 같은 head에서 `validate-feynman`, `validate-feynman-docker-reference`, `validate-feynman-codex-reference`는 성공했다.
  - `validate-feynman-remote-exec-reference` run #24만 실패했다.
  - 해당 workflow의 remote-exec 관련 44 unit tests는 모두 통과했다.
  - host control-plane Codex와 Docker tool-boundary Codex는 둘 다 `codex-cli 0.153.4`였다.
  - frozen baseline plan/job/profile 생성도 성공했다.
  - 첫 실제 E2E 모델 도구 호출에서 `unsupported custom tool call: apply_patch`로 종료됐다.
- **판단**:
  - Docker/network/profile 계약의 선행 실패가 아니라, mock model이 생성한 `apply_patch` custom-tool 호출과 현재 Codex 0.153.4 remote path 사이의 integration incompatibility가 최초 실패다.
  - `apply_patch + exec_command`를 한 테스트에 묶은 현재 구조는 원인 격리에 불리하다.
- **결론**: remote `exec_command` 자체가 실패했다고 볼 근거는 아직 없다. 먼저 apply-patch를 제거한 exec-only E2E를 통과시켜 transport/tool boundary를 독립 검증해야 한다.
- **다음 작업**: mock Responses server와 reference-result를 `exec-only` 시나리오를 지원하도록 분리하고 CI를 그 시나리오로 먼저 녹색화한다.
- **남은 위험**:
  - remote exec transport가 실제로 성공하는지 미확인.
  - `apply_patch`의 올바른 현재 Codex wire/tool 형식 미확인.
  - 실제 credential/model service는 사용하지 않았음.

---

## LOG-002 — remote reference 시나리오 분리

- **시각(KST)**: 2026-09-08 20:45
- **시작 head**: `2540035d0b1fdc0f06df9fcde96bb2dc93cc8b02`
- **목적**: remote exec transport와 apply-patch custom-tool 호환성을 독립적으로 검증한다.
- **변경**:
  - `tooling/feynman_mock_responses_server.py`
    - `exec-only` / `patch-then-exec` 두 시나리오를 명시적으로 분리.
    - `exec-only`는 첫 모델 응답에서 바로 `exec_command`를 요청하고, 두 번째 모델 요청에서 remote command output을 확인한 뒤 final을 반환.
    - `exec-only` command는 patch 파일에 의존하지 않음.
    - remote command 안에서 `REMOTE_EXEC_OK`, `AUTH_ENV_CLEAN`, `NETWORK_BLOCKED`를 각각 증명하도록 유지.
    - `patch-then-exec`는 기존 `apply_patch → exec_command` 계약을 보존하되 별도 시나리오로 격리.
    - mock state를 schema version 3으로 올리고 `scenario`를 기록.
  - `tooling/feynman_remote_exec_reference_result.py`
    - mock-state scenario에 따라 서로 다른 증거 계약 적용.
    - `exec-only`: 정확히 2 model requests, patch output 없음, exec output + workspace/network/auth marker 필수.
    - `patch-then-exec`: 정확히 3 model requests, patch output + patch proof + exec output 모두 필수.
    - `exec-only`에서 patch proof를 공급하면 오히려 거부하도록 fail-closed 처리.
    - reference result schema를 3으로 올리고 scenario 및 patch digest nullable 여부를 기록.
  - `tests/test_feynman_mock_responses_server.py`
    - exec-only command가 patch filename/marker에 의존하지 않는지 검사.
    - patch-then-exec command는 patch marker를 요구하는지 별도 검사.
  - `tests/test_feynman_remote_exec_reference_result.py`
    - exec-only valid path를 primary synthetic fixture로 전환.
    - patch-then-exec stronger path도 별도 regression으로 유지.
    - exec-only에 patch proof를 주는 경우, patch scenario에서 proof가 없는 경우를 각각 거부.
  - `.github/workflows/validate-feynman-remote-exec-reference.yml`
    - 실제 reference run을 `--scenario exec-only`로 명시.
    - `remote-patch-proof.txt`를 성공 조건과 artifact 목록에서 제거.
    - patch 파일이 생성되지 않았음을 반대로 확인.
    - reference result 생성에서도 `--patch-proof`를 제거.
- **관련 커밋**:
  - `847fb07fabdf7795446100cdac377dd5232e07ab` — mock server scenario 분리
  - `1bfb5094bc8ac8ac98e0060561bb3cf415915db4` — result validator scenario 분리
  - `50d810b7dd0440508bb39b588d18bac8dbe0a6eb` — mock server regression 갱신
  - `3adb7f81d8e6c41913bc53fdfac86958aaa6f730` — reference-result regression 갱신
  - `11e4d8f5c713f4588b70f510b894592e5d526db0` — CI exec-only 전환
- **검증 상태**: 코드/테스트/CI 계약 변경은 커밋됨. 실제 GitHub Actions 결과는 아직 이 로그 시점에 확정하지 않음.
- **결론**: apply-patch 실패가 remote exec transport 판정을 막지 않도록 평가 주장을 분리했다. 아직 exec-only가 실제 통과했다고 주장하지 않는다.
- **다음 작업**: `11e4d8f5…`에 연결된 `validate-feynman-remote-exec-reference` 실행 결과를 확인하고, 실패하면 최초 실패 지점부터 수정한다.
- **남은 위험**:
  - `exec_command`가 remote exec-server에서 실제 실행되는지 아직 미확정.
  - tool command trace의 `aggregated_output` 형식이 current Codex 0.153.4에서 validator 예상과 다를 가능성.
  - apply-patch compatibility는 의도적으로 미해결 상태로 유지.
  - 실제 credential/model service는 여전히 사용하지 않음.

---

## LOG-003 — exec-only remote model/tool split 실제 E2E 성공

- **시각(KST)**: 2026-09-08 20:47
- **검증 대상 head**: `11e4d8f5c713f4588b70f510b894592e5d526db0`
- **목적**: host-side mock model/Codex control plane과 network-disabled Docker remote exec-server 사이의 도구 실행 분리를 실제 GitHub runner에서 검증한다.
- **GitHub Actions 결과**:
  - `validate-feynman-remote-exec-reference` run #35, run id `34222374937`: **success**.
  - 같은 head에서 `validate-feynman`, `validate-feynman-docker-reference`, `validate-feynman-codex-reference`도 모두 **success**.
  - remote-exec contract unit tests는 **47개 통과**.
  - control-plane Codex와 tool-boundary Codex 버전은 모두 `codex-cli 0.153.4`.
- **실제 artifact 확인**:
  - artifact id: `10054284915`
  - artifact zip digest: `sha256:8f08dae3b2f21e1ecacbf2793fbf76324c82bc8bdd5dc0242c1c06c6f8c63964`
  - `reference-result.json`:
    - `schema_version=3`
    - `verdict=mock-remote-tool-reference-passed`
    - `scenario=exec-only`
    - model requests = 2
    - `exec_output_round_trip=true`
    - `workspace_marker=true`
    - `tool_network_blocked=true`
    - `auth_env_clean=true`
    - `command_execution_observed=true`
    - `final_agent_message_observed=true`
    - `docker_inspect_matches_profile=true`
    - `local_execution_disabled=true`
    - `apply_patch_round_trip=false` / patch proof digest `null` — 의도된 exec-only 범위.
  - `codex-trace.jsonl`:
    - 하나의 nonempty thread id: `01a080d6-efce-7840-a7be-9afccfd36b6c`
    - `command_execution`이 `completed`, `exit_code=0`.
    - 실제 aggregated output: `AUTH_ENV_CLEAN`, `NETWORK_BLOCKED`, `REMOTE_EXEC_OK`.
    - 최종 agent message: `REMOTE_EXEC_REFERENCE_OK`.
  - `tool-container-inspect-check.json`:
    - `verdict=docker-inspect-matches-profile`.
    - `network_mode=none`.
    - rw mount는 candidate / candidate-home / tool-codex-home / tool-temp 네 곳만 존재.
    - candidate env key는 `CODEX_HOME`, `HOME`, `PATH`, `PYTHONDONTWRITEBYTECODE`, `TMPDIR`.
  - `candidate/remote-tool-proof.txt`: 정확히 `REMOTE_EXEC_OK`.
- **주요 digest**:
  - boundary profile: `fc4064a9114926e601da6020b999bb4623b345110585b1de4733fee549861f11`
  - runner job: `848439e21a37e9756aa62981adb1d238dec9667997f77fded26420937eb61db6`
  - remote environment: `41ada289238bcfde4d6b0e556e054dbf625b6338477fa7785cdcdbfccd2ca03a`
  - network reference: `8ab470cb881a427aa8d1a7a2361ecaf50c5173faf5c4d8139bc3c6a7b5937451`
  - mock state: `1149649371fb983afc3437b9198f64e39e74163614a97166ec50e10979932080`
  - Codex trace: `20e8d5a7e56531c01e19be45ec784d515cae7e8113b00e9a737b7896d1dbdc56`
  - Docker inspect: `f0672519aa4f60eeb8c8dc1292df8280322cabc1026dc77232f68bd2bc92d12b`
  - candidate proof: `b95df8af34190814b55f57d5b20a58233422cd160c380c49acb8d9e116ac397d`
- **결론**:
  - credential-free mock model control plane에서 Codex가 local execution을 사용하지 않고 stdio remote exec-server를 통해 실제 command를 실행하고 결과를 다시 model loop에 전달하는 경로가 확인됐다.
  - tool boundary의 network 차단과 auth-like env 비노출도 동일 command에서 확인됐다.
  - 이 결과는 실제 OpenAI/model-service 인증 안전성이나 Feynman skill 성능을 증명하지 않는다.
- **다음 작업**: current Codex 0.153.4에서 remote `apply_patch`가 어떤 tool representation/route를 요구하는지 소스와 실제 reference를 분리 조사한다. exec-only 녹색 상태는 유지한다.
- **남은 위험**:
  - 실제 credential을 가진 control plane의 end-to-end 검증은 미실행.
  - `apply_patch` custom-tool remote compatibility 미해결.
  - 실제 baseline/generic/legacy/v0.5 행동 비교는 미실행.
