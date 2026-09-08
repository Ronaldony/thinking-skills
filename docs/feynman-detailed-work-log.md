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
