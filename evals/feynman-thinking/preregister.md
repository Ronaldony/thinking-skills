# feynman-thinking 행동 비교 사전등록 초안

상태: **protocol draft — no behavioral results yet**. 이 문서는 공개 개발 사례의 결과를 성능 근거로 재사용하지 않고, 비공개 final set을 보기 전에 비교 조건·주요 지표·판정 원칙을 고정하기 위한 초안이다.

기계적으로 실행할 4개 주 비교 조건의 정확한 prompt prefix·skill source는 `conditions.json`에 고정한다. `tooling/feynman_eval_plan.py`가 그 파일과 `cases.jsonl`의 SHA-256을 실행계획에 기록하고 seed로 case × condition × repeat 순서를 결정한다. 실행계획 자체는 모델 결과가 아니다.

## 1. 검증할 주장

다음 주장을 분리한다.

- **H1 결과 품질**: v0.5.0-draft 명시 호출은 동일 모델·도구·자원 조건에서 강한 일반 비판적 사고 지침보다, 파인만 스킬의 목표 과제에서 정답/결정 타당성과 필수 발견 충족을 개선하는가?
- **H2 검증 진실성**: v0.5.0-draft는 실행하지 않은 검사·출처·파일 확인을 수행했다고 주장하는 비율을 늘리지 않는가?
- **H3 정당한 갱신**: 불리한 새 증거에는 결론을 수정하고, 지지 증거에는 근거 없이 결론을 뒤집지 않는가?
- **H4 비용**: 추가 토큰·시간·도구 호출 비용이 결과 개선에 비해 과도하지 않은가?
- **H5 특이 기여**: 인물 이름을 제거하거나 표현 전환/판별 검사 연산을 제거했을 때 결과가 어떻게 변하는가? 이는 역사적 인물의 고유한 내면 사고를 증명하는 검사가 아니라 구현 요소의 기여도를 보는 ablation이다.

자동 발동 성능은 위 주장과 분리한다. 초기 v0.5.0-draft의 암묵 호출이 꺼져 있기 때문이다.

## 2. 후보 조건

최소 비교 조건은 다음 네 개다.

1. `baseline`: 추가 사고 지침·파인만 스킬 없음.
2. `generic`: 스킬 없음 + `conditions.json`에 고정한 강한 일반 비판적 사고 지침. 사실/추론 구분, 대안 설명, 직접 확인, 불확실성, 다음 행동을 요구하되 파인만 이름이나 스킬 호출은 사용하지 않는다.
3. `legacy-clean`: v0.4.0 고정 커밋 `1609b8b6909f9ab596c1ecf298fbec4a0c70d6b4`의 명시 호출. `tooling/feynman_legacy_package.py`가 `evals/`, `scripts/`, `.git`, `references/evaluation.md`를 후보 런타임에서 제외하고 SKILL.md의 `references/evaluation.md` 링크 한 줄만 제거한다. 따라서 **byte-for-byte v0.4가 아니라 evaluator/harness 노출을 제거한 sanitized 비교 조건**이다. manifest에 변환 내역을 남긴다.
4. `feynman-v05`: 현재 allowlist로 만든 v0.5.0-draft 명시 호출.

`tooling/feynman_condition_workspace.py`는 위 조건별 candidate prompt와 runtime을 준비하고 condition metadata는 evaluator-side `case.json`에만 남긴다. `feynman_review_bundle.py`가 만드는 semantic review input에는 condition id와 skill source를 넣지 않는다.

원인 탐색을 위한 보조 조건은 `v05-no-name`, `v05-no-representation`, `v05-no-discrimination`이다. 이 ablation은 주효과 4조건 결과와 같은 분석으로 조용히 합치지 않는다.

## 3. 사례 분리

- 현재 `cases.jsonl`과 `rubrics.jsonl` 18개는 공개 개발·회귀 자료다. 프로토콜과 코드를 만드는 데 이미 사용했으므로 final 성능 추정에 포함하지 않는다.
- 최종 비교 세트는 다른 작성자가 새로 만들고, candidate prompt와 evaluator rubric을 서로 다른 저장 위치에 동결한다.
- 각 final 사례는 고유 ID, domain/category, 위험 수준, 실행 필요 여부, 필수 발견, 필수 행동, hard failure를 가진다.
- 올바른 결론 유지, 잘못된 결론 수정, 식별 불가능, 생성적 설계, 수학/코드/실증/정책, 단순 비발동 과제를 균형 있게 포함한다.
- final rubric을 본 뒤 스킬 규칙을 수정하면 해당 final set은 더 이상 held-out가 아니므로 폐기하거나 새 세트를 만든다.

## 4. 실행 격리와 동등 조건

각 case × condition × repeat는 별도 후보 디렉터리에서 실행한다.

- 후보에는 해당 condition-specific prompt, 필요한 fixture, 해당 조건의 런타임만 제공한다.
- evaluator rubric, judge prompt, 이전 답변·등급, 다른 조건의 런타임은 후보가 읽을 수 없어야 한다.
- `tooling/feynman_eval_workspace.py`의 파일 분리, `tooling/feynman_condition_workspace.py`의 조건 설치, `tooling/feynman_eval_preflight.py`의 skill-root 검사를 통과해야 한다.
- 실제 후보 프로세스는 별도 OS/컨테이너 경계에서 candidate dir만 읽을 수 있어야 한다. 현재 저장소는 이 경계를 아직 구현하지 않았다.
- HOME과 CODEX_HOME은 평가 전용 빈 디렉터리로 고정한다. `$HOME/.agents/skills`, `$CODEX_HOME/skills`, 후보 상위 디렉터리의 `.agents/skills`에서 추가 스킬이 발견되면 해당 run은 무효다.
- 내장/system skill과 플러그인 노출은 버전별로 기록하고 모든 조건에 동일하게 유지하거나, 가능하면 명시적으로 비활성화한다. 통제가 불가능하면 한계로 보고한다.
- 외부 웹이 과제 수행에 불필요하면 차단한다. 필요한 경우 모든 조건에 같은 정책을 쓰고 공개 정답 검색 가능성을 별도 위험으로 기록한다.
- 모델 식별자, Codex 버전, 시스템 지시, sandbox, 도구 목록/권한, 시간 제한, 최대 출력, runtime digest, cases/conditions digest를 run metadata에 저장한다.
- 인증 자격증명을 평가 workspace로 복사하는 것을 격리 방법으로 사용하지 않는다. 실제 runner는 별도의 허용된 인증 경로를 사용해야 한다.

## 5. 반복과 실행 순서

- 동일 모델 스냅샷 안에서 case × condition 순서를 무작위화하고 seed를 고정·기록한다. `feynman_eval_plan.py`는 동일 입력·seed에 동일 job order를 만들어야 하며 회귀 테스트로 고정한다.
- 공개 개발 단계에서 반복 수 5는 harness 안정성 확인에만 사용할 수 있으며 충분한 통계 검정력을 자동 보장하지 않는다.
- final 반복 수와 최소 실질 효과 크기는 **final 답변을 열기 전에**, 별도 pilot의 분산과 비용을 보고 정해 이 문서에 추가한다.
- 모델/CLI/스킬/conditions 버전이 바뀐 실행을 같은 모집단에 조용히 합치지 않는다.

## 6. 주요 결과 변수

### Primary

1. `decision_correctness`: 사례의 실제 결정/정답 타당성. 사람 블라인드 평가를 우선하고 필요하면 모델 보조 채점을 사용한다.
2. `required_finding_completion`: 필수 발견 ID별 supported 비율. 동등한 올바른 표현을 허용한다.
3. `critical_failure_rate`: case rubric의 hard failure 발생률.
4. `execution_integrity_failure_rate`: 실행·출처·파일 확인을 했다고 주장했지만 evaluator-trusted evidence와 맞지 않는 비율.

### Secondary

- required behavior 0/1/2 점수
- justified revision / justified retention
- underdetermined를 억지로 단정한 비율
- 실행 가능한 검사를 제안으로만 남긴 비율
- 토큰, wall time, 도구 호출 수
- 불필요한 장문/보류/거절
- automatic trigger precision/recall은 별도 트랙

하나의 종합 점수로 모든 실패를 숨기지 않는다. 특히 hard failure와 실행 진실성은 평균 품질 점수와 별도 보고한다.

## 7. 채점 절차

- 조건명과 skill source metadata를 제외한 candidate final + evaluator evidence bundle을 채점한다. 후보가 답변 안에서 스킬 이름을 자발적으로 언급해 조건을 유추할 가능성은 남으므로 완전한 블라인드라고 과장하지 않는다.
- `codex_exec_evidence.py`는 reasoning을 복사하지 않고 완료된 도구/실행 사건과 final만 축약한다. 저장된 evidence bytes는 별도 hash로 검증한다. 이 번들은 행동 증거이지 의미적 정답 판정 자체가 아니다.
- `feynman_review_bundle.py`가 원 prompt, rubric, candidate final, 검증된 evidence만 evaluator-only 입력으로 묶는다.
- 의미 평가자는 `judge-prompt.md`와 rubric을 사용하고, `feynman_apply_review.py`가 review bundle hash와 trusted execution linkage를 확인한 뒤 `feynman_grade_gate.py`를 적용한다.
- 모델 보조 채점만으로 결론내리지 않는다. 최소한 주요 오류·조건 차이가 큰 사례는 조건 블라인드 사람 검토를 수행한다.
- 평가자 간 불일치, 채점 수정, 제외 run은 이유와 함께 보존한다.

## 8. 채택 판정 원칙

`v0.5`를 “행동적으로 검증됨”으로 승격하려면 다음을 모두 만족해야 한다.

- 구조·격리 preflight에서 무효 run이 분석에 포함되지 않는다.
- primary 결과에서 generic 대비 실질적인 개선의 방향이 일관되고, 불확실성 구간을 함께 보고한다.
- `critical_failure_rate`와 `execution_integrity_failure_rate`가 generic 또는 legacy-clean보다 의미 있게 악화되지 않는다.
- positive-control과 justified-retention 사례에서 반대를 위한 반대가 증가하지 않는다.
- 비용 증가를 공개하고, 결과 이득이 없는데 비용만 늘어난 규칙은 축소한다.

구체적인 수치 최소 효과·비열등성 마진은 pilot 이전에 임의로 정하지 않는다. pilot을 본 뒤 final set을 열기 전에 값과 근거를 이 문서에 고정한다. 그 전에는 research preview 상태를 유지한다.

## 9. 결과 공개 규칙

좋아진 항목과 나빠진 항목을 모두 보고한다. 평균뿐 아니라 사례별 paired difference, 분산/불확실성, 최악 실패, 제외 사유, 실제 비용을 공개한다. 파인만의 이름이나 역사적 근거는 성능 결과를 대체하지 않는다.
