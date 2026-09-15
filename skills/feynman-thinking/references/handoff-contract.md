# 인계 계약 — thinking-skills에 제안하는 최소 인터페이스 [X]

상태: 제안, 버전 0.1. 다른 인물 스킬이 이미 이 계약을 구현했다고 가정하지 않는다.
스킬 단독 설치도 가능하도록 이 문서에 필요한 정의를 포함한다. 외부 공통 문서에 필수 의존하지 않는다.
다른 스킬 호출을 도구가 지원하지 않으면 호출했다고 주장하지 말고 필요한 전문 작업을 기록한다.

인계 또는 감사 요청 때만 아래 구조를 사용한다. 일반 사용자 답변에 JSON을 강요하지 않는다.

```json
{
  "contract_version": "0.1",
  "skill": "feynman-thinking",
  "role": "primary",
  "task": "실제로 판단한 문제",
  "scope": "대상과 유효 조건",
  "status": "underdetermined",
  "model_summary": "입력에서 출력까지의 핵심 관계",
  "claims": [],
  "checks": [],
  "decision": "현재 판단과 행동",
  "revision": {"changed": false, "reason": "새 판별 증거가 없음"},
  "open_questions": [],
  "next_capability": "필요한 경우에만 특정 전문 기능"
}
```

`role`: primary/support. `status`: supported/refuted/underdetermined/blocked.
`claims` 항목: id, statement, kind(given/observed/derived/assumed/choice/unknown), evidence_ids, conditions.
`checks` 항목: id, claim_ids, method, input, prediction, result, status, evidence_ids.
검사 `status`: planned/executed_pass/executed_fail/underdetermined/not_applicable.
`planned`는 실행 완료가 아니다. 손계산은 입력과 유도가 있으면 수행된 계산으로 기록할 수 있으나 코드 실행이라고 쓰지 않는다.
증거 위치에는 파일·행, 도구 이벤트, 데이터 버전·해시, 또는 출처·확인일을 붙인다.

## 책임 경계

현재 스킬은 작동 모델과 직접 검사를 책임진다. 실증 인과의 확정, 가치 선택, 전문 분야의 승인,
실행 권한 승인은 별도 책임이다. 다른 관점과 충돌하면 같은 task/scope/evidence를 비교한다.
서로 다른 조건을 말한 것인지 먼저 확인하고 인물의 명성을 타이브레이커로 쓰지 않는다.
