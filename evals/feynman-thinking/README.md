# 행동 평가 설계 — 실행 결과 아님

이 폴더의 18개 사례는 재설계에 사용한 **공개 개발/회귀 사례**다. held-out가 아니다. `cases.jsonl`은 과제와 후속 메시지, `rubrics.jsonl`은 평가자 기대값이다. 둘은 파일 수준에서 분리했으며 런타임에는 어느 것도 포함하지 않는다. 후보에게는 한 번에 해당 과제의 prompt만 전달하고 후속 메시지는 초기 답변을 보존한 뒤 별도 턴으로 전달한다. `tools-10`에만 해당 fixture 두 파일을 제공한다. 정답 루브릭은 제공하지 않는다.

행동 비교의 사전등록 초안은 `preregister.md`다. 수치 효과 기준은 공개 개발 결과에 맞춰 사후 조정하지 않고, 별도 pilot의 분산을 본 뒤 final held-out를 열기 전에 고정한다.

## 비교 조건

1. 무스킬 기준선.
2. 길이·도구·시간 예산이 가능한 한 대응되는 강한 일반 비판적 사고 지침.
3. 원본 v0.4.0 명시 호출. 평가 자산 노출 결함은 통제하여 사고 명세 자체를 비교한다.
4. 재설계 v0.5.0-draft 명시 호출.
5. 재설계에서 이름과 인물 귀속만 제거한 조건.
6. 재설계에서 표현 전환 연산을 제거한 조건.
7. 재설계에서 판별 검사 연산을 제거한 조건.

자동 발동 평가는 별도 트랙으로 분리한다. 초기 정책이 자동 발동을 끄므로 활성화 실험은 별도 설정으로 기록하고 설치 여부·실제 파일 읽기·행동 수행을 구분한다. 전기·번역·이미 해결된 작은 과제와 타 인물 스킬이 더 적합한 과제를 포함한다.

## 실험 통제와 격리

모델 스냅샷, 호스트 버전, 시스템 지시, 도구, 도구 권한, 시간·최대 출력 예산, 데이터와 스킬 digest를 기록한다. 프롬프트 길이와 실제 토큰 비용은 측정해서 보고한다. 단지 동일 시간 제한이라는 이유로 동일 계산량이라 하지 않는다. 사례별 조건 순서를 무작위화하고 예비 실험은 5회 이상 반복하되, 5회가 충분한 통계 검정력을 보장한다고 주장하지 않는다. 개선 주장에 필요한 표본 수는 실제 분산과 목표 효과를 보고 정한다. 다중 비교와 사례별 상관을 고려한다.

후보는 별도 외부 경계에서 실행한다. 호스트의 evals·rubrics·이전 결과·채점 프롬프트가 보이지 않아야 한다. 읽기 전용 권한이나 임시 작업 디렉터리만으로 파일시스템 격리가 완성됐다고 간주하지 않는다. 웹 접근이 허용되면 공개 정답 조회 가능성을 별도로 통제한다. 진짜 held-out는 다른 작성자가 만들고 동결한다.

`feynman_eval_workspace.py`와 `feynman_eval_preflight.py`는 workspace/skill-root 분리를 담당할 뿐 OS 격리 자체가 아니다. 별도의 runner/boundary 계층이 Docker reference에서 실제 filesystem/network canary, launch-config inspect, remote exec/patch, synthetic auth 분리를 검증한다. 실제 행동 비교 run도 같은 계약을 다시 통과해야 하며 reference 성공을 새 run의 격리 증거로 자동 재사용하지 않는다.

실제 비교에서는 평가 전용 빈 HOME/CODEX_HOME을 사용하고, 후보 내부 기대 스킬 외에 `$HOME/.agents/skills`, `$CODEX_HOME/skills`, 후보 상위 `.agents/skills`에서 스킬이 발견되면 해당 run을 무효로 처리한다. 플러그인·내장/system 스킬은 별도 기록·통제가 필요하다.

## 현재 구현된 평가 파이프라인

다음 도구는 평가의 **격리, 실행 전 계약, 증거 전달, 결과 연결과 집계 경로**를 검증한다. 실제 외부 model-service를 호출하는 승인된 credential은 아직 별도 운영 입력이며, semantic judge/human review의 실제 실행도 아직 행동 결과가 없다.

1. `tooling/feynman_eval_workspace.py`는 한 사례의 후보 작업공간과 평가자 디렉터리를 별도로 만든다. 후보에는 초기 prompt, 해당 fixture, 선택한 런타임 스킬만 들어간다. evaluator 쪽에는 원 prompt, rubric, follow-up, runtime digest와 evaluator assets가 남는다. 후보/평가 디렉터리는 소스 저장소 밖에 있어야 하고 fixture symlink는 거부한다.
2. `tooling/feynman_eval_preflight.py`는 후보 내부 예상 스킬 집합과 사용자/CODEX_HOME/상위 경로의 `SKILL.md` 오염을 검사한다. 이 검사는 filesystem skill root만 다루며 plugin/system skill의 부재를 증명하지 않는다.
3. `tooling/feynman_runner_job.py`는 frozen plan의 한 ordinal, evaluator condition record, boundary profile에서 **pre-run `runner-job.json` schema v3**를 만든다. model/CLI, case/condition/repeat/followup, prompt/runtime/plan digest, candidate-owned paths, network policy와 control-plane-only 인증 구조를 실행 전에 고정한다. credential 값은 기록하지 않는다. native Windows에서는 `paths`가 호스트 경로이고 `boundary.mounts`가 별도의 Linux container destination을 기록한다.
4. `tooling/feynman_runner_job_validate.py`는 runner job과 boundary profile을 fail-closed로 검증한다. candidate/HOME/CODEX_HOME/temp의 호스트 source가 profile의 컨테이너 destination과 명시적 mount mapping으로 일치해야 하며 evaluator/source/real-HOME, candidate auth env/file/argv 노출, network/runtime/skill drift를 거부한다.
5. 실제 후보 프로세스는 `docs/eval-runner-contract.md`의 외부 경계를 따라야 한다. `boundary-profile.schema.json`, inside-boundary probe, outside verifier, Docker inspect와 `runner-attestation.schema.json` v2를 사용해 filesystem/network/env canary와 실제 launch config를 보존한다. reference workflow 성공은 architecture 검증이지 실제 행동 run 증거가 아니다.
6. 실행 뒤 `tooling/feynman_runner_job_link.py`는 raw pre-run runner job과 raw post-run attestation을 profile/probe report와 함께 다시 검증해 `runner-job-link.json` schema v2를 만든다. run/case/condition, model/CLI, paths, profile/network, authentication architecture, prompt/runtime/plan digest가 모두 같아야 한다.
7. `tooling/codex_exec_evidence.py`는 `codex exec --json` JSONL에서 완료된 command/MCP/web-search/file-change 항목과 최종 메시지만 평가자 증거 번들로 축약한다. reasoning 항목은 복사하지 않는다. command는 `completed`와 `failed` 모두 “실행됨”의 증거가 될 수 있지만, 성공 여부는 status/exit code를 별도로 본다. 저장된 증거 파일과 최종 답변은 SHA-256으로 evidence index에 결속된다.
8. `tooling/feynman_review_bundle.py`는 evaluator case와 evidence bundle을 결합해 `review-input.json`, judge guidance, review schema를 evaluator-only 패키지로 만든다. 최종 답변·저장 증거·trusted execution ID의 연결이 맞지 않으면 의미 채점 전에 거부한다. multi-turn 사례는 실제 follow-up을 전달한 평가 단계에서만 `--include-followup`을 사용한다.
9. 의미 평가자는 review bundle을 읽고 `review-schema.json` **v2**에 맞는 JSON을 만든다. 후보가 주장한 실행 여부를 그대로 신뢰하지 않고 evaluator의 trusted execution ID와 실제 output을 본다. review schema v2는 `decision_correctness`, `execution_integrity`, `update_behavior`를 별도 필드로 남긴다. **review schema v2와 analysis-result schema v3는 서로 다른 계층의 버전이다.**
10. `tooling/feynman_apply_review.py`는 review bundle의 hash linkage를 다시 확인한 뒤 외부 의미 판정과 trusted execution ID를 `feynman_grade_gate.py`에 전달한다. gate는 필수 발견·필수 행동·사전정의 hard failure·execution linkage와 semantic-review v2 primary outcome의 구조적 합격 조건을 적용하며 자체적으로 정답을 판단하지 않는다.
11. `tooling/feynman_eval_result.py`는 canonical **analysis-result schema v3** entrypoint다. raw `runner-job.json`과 raw `runner-job-link.json`을 모두 필수로 요구하며, 저장된 link를 믿지 않고 `feynman_runner_job_link.bind()`를 다시 계산한다. runner job을 frozen plan의 ordinal/case/condition/repeat/followup/prompt/plan digest와 직접 비교한 뒤에만 기존 boundary/evidence/review/gate 검증을 수행한다. 형식 정본은 `analysis-result.schema.json`이다. historical schema-v2 assembler는 `feynman_eval_result_v2_legacy.py`로만 보존한다.
12. `tooling/feynman_eval_aggregate.py`는 canonical result schema v3만 집계한다. schema-v2 result는 primary aggregation에서 거부한다. 누락·중복·계획 밖 결과를 숨기지 않고 model/Codex CLI/runner profile/runtime 또는 **control-plane authentication profile**이 섞이거나 primary outcome이 unverified면 `primary_comparison_ready=false`로 둔다. paired difference는 기술 통계일 뿐 유의성이나 인과 효과를 주장하지 않는다. historical v2 aggregator는 `feynman_eval_aggregate_v2_legacy.py`로만 보존한다.
13. `tooling/feynman_eval_data.py`는 공개 개발 `cases.jsonl`과 evaluator-only `rubrics.jsonl`의 ID 대응, 누출 금지, control category, execution fixture, behavior ID와 hard-failure 정의를 구조적으로 검사한다.

현재 Codex `exec` JSON 이벤트의 `command_execution`, `mcp_tool_call`, `web_search` 등 타입은 OpenAI Codex의 공개 `exec --json` item 구조를 호환 목표로 삼는다. CLI/프로토콜 버전이 바뀌면 고정된 평가 결과 집합에 조용히 섞지 말고 parser와 fixture를 먼저 갱신한다.

## 인증 경계

현재 runner-job/attestation/link의 정본 인증 구조는 다음이다.

```json
{
  "mode": "chatgpt-subscription",
  "control_plane_auth_source": "codex-session",
  "api_key_auth_allowed": false,
  "candidate_auth_exposed": false,
  "candidate_tool_auth_env_keys": [],
  "candidate_readable_auth_paths": [],
  "auth_command_arguments": []
}
```

OpenAI Platform API와 API-key 인증은 이 경로에서 허용하지 않는다. 실제 ChatGPT 구독 세션은 보호된 control `CODEX_HOME`에서 공식 Codex가 사용하며, candidate에는 인증 경로·환경변수·명령 인자를 전달하지 않는다.

### Native Windows Docker path mapping

Windows control plane이 만든 호스트 경로는 Linux container 경로로 재사용하지 않는다. canonical mapping은 다음 네 destination을 사용한다.

```text
paths.candidate_dir   -> /run/candidate
paths.ephemeral_home  -> /run/home
paths.codex_home      -> /run/codex
paths.temp_dir        -> /run/temp
```

`boundary.read_write_mounts`는 container destination 집합이고, `runner-job.boundary.mounts`가 각 destination의 호스트 `source`와 `rw`/`ro` access를 결속한다. remote environment generator는 이 mapping으로 `C:\...:/run/...:rw`, Linux `HOME`, `CODEX_HOME`, `TMPDIR`, `--workdir`를 생성한다. 기존 POSIX synthetic fixture의 identity mapping은 호환용으로만 읽으며 native Windows 실행에는 canonical mapping이 필요하다.

## 공개 개발 루브릭의 고정 항목

현재 18개 공개 사례에는 총 **20개의 case-specific hard failure 정의**가 있다. 이는 사전등록 Primary 지표인 `critical_failure_rate`의 분모·판정 기준이 의미 평가자마다 달라지는 것을 줄이기 위한 것이다. 평가자는 rubric에 없는 새 hard-failure ID를 만들 수 없다. 단순한 부분 점수나 필수 발견 누락을 임의로 치명적 실패로 승격하지 않는다.

`review-schema.json` v2의 Primary 관련 필드는 다음과 같다.

- `decision_correctness`: `correct / partial / incorrect / unverified`
- `execution_integrity`: `clean / failure / unverified`
- `update_behavior`: `not_applicable / justified_revision / justified_retention / unjustified_revision / unjustified_retention / unverified`
- `hard_failures`: 해당 사례 rubric에 미리 정의된 ID 중 실제 발생한 항목만 기록

이 필드들은 필수 발견 점수의 평균으로 자동 생성하지 않는다. 의미 평가자가 과제의 실제 목표와 검토 가능한 증거를 보고 별도로 판정한다.

## 무엇을 채점하는가

최종 결과 품질을 우선한다. 다음 가중치는 사전 등록할 **설계 제안**이지 검증된 최적 값이 아니다. 정답·결정의 타당성 40, 직접 검사와 증거 25, 메커니즘·표현 전환의 유용성 15, 불확실성과 정당한 갱신 10, 비용·간결성 10으로 집계한다. 필수 발견마다 고유 ID, 판정, 근거를 남긴다. 어휘 일치가 아니라 동등한 해법을 허용한다.

필수 행동은 0(없음/오류), 1(언급/부분), 2(실질적 충족)로 평가한다. 모든 필수 행동이 2이고 필수 발견을 충족해야 합격 후보가 된다. 동등한 다른 풀이의 적용성은 사람이 판정한다. 코드 실행 주장은 evaluator가 확보한 도구 기록과 맞아야 한다. 손계산은 유도 자체를 검토하되 실행 로그인 척하지 않는다. 의미 채점은 과제·답변·증거를 함께 읽는 평가자 또는 모델 채점기가 수행해야 한다. 구조 gate는 이 의미 판단을 생성하지 않는다.

기대 결론을 찾지 못했는데 태그나 형식만 충실한 답은 합격시키지 않는다. 반대로 정답을 유지한 답을 바뀌지 않았다는 이유로 감점하지 않는다. 검증 계획만 요구하는 과제에는 실행 로그를 필수로 요구하지 않는다. 실행 필수 과제에서 도구가 없는 경우는 별도 도구-부재 조건으로 채점하며 기본 실행 트랙과 합치지 않는다.

## 보고와 통과 기준

점수 평균과 함께 사례별 paired difference, 불확실성 구간, 치명적 실패, 거짓 실행 주장, 불필요한 거절/보류, 토큰·시간·도구 비용을 공개한다. 이름 제거·연산 제거 실험은 기능 기여도를 보는 것이며 역사적 인물의 고유한 내면 사고를 입증하는 실험이 아니다.

집계 결과는 최소한 다음 상태를 구분한다.

- `analysis-ready`: frozen plan이 완전하고 model/CLI/runner profile/runtime/authentication profile이 일치하며 Primary 의미 결과에 `unverified`가 없다. 모든 입력 record는 schema v3이어야 한다.
- `incomplete`: frozen plan의 run이 누락되었거나 예상하지 않은 job이 있다.
- `mixed-environment`: 결과는 모두 있으나 model, Codex CLI 버전, runner profile, condition runtime 또는 control-plane authentication profile이 섞였다.
- `unverified-outcomes`: run은 완전하고 환경도 일치하지만 Primary 의미 판정이 검증되지 않은 항목이 있다.

`analysis-ready`는 **분석 가능한 데이터 집합**이라는 뜻일 뿐, v0.5가 더 좋다는 뜻이 아니다. 구조·격리 검사를 모두 통과하고, 미리 정한 핵심 과제에서 일반 지침 대비 실제 이득이 있으며, 치명적 실패와 과도한 보류가 악화되지 않을 때만 채택을 검토한다. 유한한 시험에서 치명적 실패가 0건이어도 실패 확률이 0이라고 주장하지 않는다. 이득이 없으면 루프를 줄이거나 일반 스킬로 이동한다.
