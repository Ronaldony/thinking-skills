# LOG-040 — remote tool 조사 방향과 기존 결론 정정

2026-09-12 KST. 시작 HEAD f71ee5158351368e623e7b267388b116f4dbd6c1.
시작 작업 트리는 clean, branch feat/feynman-thinking-v0.5-draft.
사용자 요청: 모델/version 재시도 또는 Codex 0.154.0 설정 추가 조사의 방향 파악.

## 실제 조사와 관찰

- `git status --short --branch`: clean.
- `rg --files -g AGENTS.md` 및 C:\, C:\DevWorks, 저장소 root의 AGENTS.md 존재 검사:
  발견 없음 (rg no-match exit 1).
- `Get-Content tooling/feynman_subscription_tool_use_probe.py`,
  `tooling/feynman_rpc_path_mapping.py`, `tooling/feynman_rpc_path_proxy.py`,
  `tooling/codex_exec_evidence.py`: 정적 검토.
- `Get-Command codex -All`: npm ps1/cmd와 desktop 번들 exe 경로가 존재한다.
- `codex --version`: codex-cli 0.154.0.
- `codex features list | Select-String 'shell|exec|environment|skill|code_mode'`:
  현재 개발 프로세스 설정에서 shell_tool=true, unified_exec=true,
  code_mode=false, code_mode_host=true, skip_host_skill_discovery=false.
  이 값은 dedicated eval home의 effective config 증거가 아니다.
- 공식 configuration reference를 open/find로 확인:
  https://learn.chatgpt.com/docs/config-file/config-reference
  features.shell_tool, features.unified_exec, skills.config[].enabled/path,
  skills.max_context_tokens가 문서화되어 있다. 최신 문서는 설치된 0.154.0의
  모든 필드 지원을 보장하지 않으므로 적용 전 로컬 검증이 필요하다.
- app-server 문서 추정 URL은 404였다. 이를 기능 부재의 증거로 사용하지 않는다.

## 확인된 한계와 정정

1. 도구 event 0회는 remote tool 비노출의 확정 증거가 아니다. 미노출,
   모델 미선택, trace 누락/변환 불일치를 아직 구분하지 못했다.
2. exec-server RPC fs/readFile은 backend method다. 같은 이름의 filesystem tool이
   model-facing catalog에 제공된다는 보장이 현재 probe에 없다. shell을 통해
   파일을 읽는 구성이라면 filesystem-tool 전용 prompt는 적절한 검사가 아닐 수 있다.
3. proxy에는 method/count/error-code 전용 계측이 없다. CLI JSONL과 실제 RPC 호출을
   대조할 수 없고 startup skill 탐색과 model-triggered read도 구분하지 못한다.
4. probe는 subprocess stdout 전체를 codex-trace.jsonl에 저장한다. 별도
   candidate-final.txt가 없더라도 agent_message 원문이 trace 안에 남을 수 있다.
   raw_model_final_preserved=false라는 기존 보고는 부정확하다. 향후 호출 전에
   trace를 메모리에서 집계하거나 명시적 보존 계약으로 고쳐야 한다.
5. PROBE_TOOL_USED 고정 답은 prompt가 이미 제공한 문자열이다. 실제 파일 읽기
   성공의 독립 증거가 아니다. 기존 artifact를 성공으로 승격하지 않는다.
6. tools-10은 테스트 실행/실패 설명 과제다. fixture 변경 부재 자체는 실패 근거가
   아니다. 실행 증거와 의미 판정으로 판단해야 한다.

## 권장 순서와 분기 기준

우선 Codex 0.154.0 + gpt-5.6-luna를 유지하고 측정/설정을 조사한다.
먼저 raw trace 보존 설명과 구현을 일치시키고, model-free catalog/config 진단으로
모델에게 제공되는 tool 이름 및 후보 skill 목록을 count/allowlist 형태로 확인한다.
RPC 계측은 payload/path/credentials 없이 method/count/error-code만 수집해야 한다.

- 도구 catalog가 비어 있으면 환경 선택/feature/model capability 설정을 조사한다.
- catalog는 있고 RPC가 없으면 prompt/tool 선택 문제를 조사한다.
- RPC가 있으나 CLI event가 없으면 trace 수집기를 조사한다.
- RPC error가 있으면 해당 method의 Windows/Linux 경로 매핑을 조사한다.
- 위 조건이 정리된 뒤 같은 CLI/이미지/고정 diagnostic prompt에서 모델만 바꿔
  1회 비교한다. 대체 concrete ID는 전용 구독 세션에서 사용 가능 여부를 확인한다.
- CLI 비교는 모델과 이미지 등을 고정한 독립 run으로 한다. 기존 frozen job은
  보존하고 새 run/version 기록을 생성한다. 전역 CLI downgrade는 필요하지 않다.

## 검증·저장·다음 행동

이번은 read-only 조사와 로그 작성이다. 실행 코드/설정 변경, 모델 호출, 인증 검사,
Docker 실행, baseline, API key/Platform API 사용은 없었다. 동작 변경이 없어 테스트는
재실행하지 않는다. 로그는 git diff --check로 검증한다.
이 기록 작성 시 commit/push 미실행. 다음 구현 단위는 probe의 원문 보존 계약 및
도구 관측 경로 보강이다. 모델 교체만으로 root cause가 해결됐다고 가정하지 않는다.
