# LOG-011 — pre-auth 이후 정확한 사람 개입 지점

- **시각(KST)**: 2026-09-08 22:48
- **코드/reference 최종 검증 head**: `fed6ff976f827539a829c4087670da58d3439fe9`
- **상태 문서 갱신 commit**: `29640c9098bb6ca663afea540252b417b940dd38`
- **PR**: #1 `feat: add Feynman thinking skill research preview`
- **PR 상태**: open / draft / not merged

## 이 단계에서 완료된 자동 작업

1. runtime/evaluator 분리
2. public-development eval data/rubric/hard failure 구조
3. boundary profile/canary/host verifier
4. Docker inspect/profile consistency
5. remote exec E2E reference
6. remote apply-patch E2E reference
7. synthetic control-plane auth separation reference
8. runner-job v2 / attestation v2 / runner-job-link v2
9. evidence/review/gate chain
10. analysis-result schema v3 + v3-only aggregator
11. real-run readiness schema/preflight
12. integration-only real-model smoke spec
13. 실제 GitHub runner에서 baseline/feynman-v05 두 frozen job을 credential boundary 직전까지 생성/검증
14. full unittest 310 tests OK
15. 총 8개 structural/reference workflow 모두 success
16. PR body를 현재 `control-plane-only` / result-v3 / readiness 상태로 갱신

## 현재 정확한 중단 지점

다음 실행은 실제 외부 model-service에 요청을 보내야 한다.

그 전까지 자동으로 준비 가능한 구조는 모두 준비됐다.

다음 missing input은:

```text
operator-controlled control-plane model-service credential/account access
```

기본 env-key 이름:

```text
OPENAI_API_KEY
```

중요: 이는 **키 이름**이지 secret 값이 아니다.

## 사람이 해야 하는 최소 작업

승인된 runner/secret store에서 실제 model-service credential을 control-plane process가 읽을 수 있도록 설정한다.

예상 구조:

```text
control-plane environment
  └── OPENAI_API_KEY=<secret value owned by approved secret store>

remote candidate tool environment
  └── OPENAI_API_KEY must be absent
```

credential 값은 다음 위치에 쓰지 않는다.

- GitHub repository file
- issue/PR comment
- ChatGPT 대화
- candidate workspace
- candidate HOME/CODEX_HOME
- command argument
- runner-job.json
- runner-attestation.json
- runner-job-link.json
- analysis-result.json

## 사람이 하지 않아도 되는 것

다음은 이미 코드/로그에 고정됐으므로 다시 설계하거나 값을 손으로 작성할 필요가 없다.

- smoke case 선택
- smoke condition 선택
- 반복 수
- seed
- runner job 구조
- boundary profile contract
- remote environment contract
- real-model control config contract
- evidence/review/result schema
- performance inference 금지 규칙

## 실제 credential 준비 후 첫 실행 범위

처음부터 four-condition pilot을 돌리지 않는다.

고정된 integration smoke만 실행한다.

```text
case: tools-10
conditions:
  - baseline
  - feynman-v05
repeats: 1 each
analysis use: not-for-skill-performance-inference
```

목적은 성능 비교가 아니라 실제 model-service/control-plane/tool/evidence plumbing 확인이다.

## credential 준비 후 검증 순서

각 job마다:

1. pre-auth readiness artifact를 재확인
2. 동일 profile의 실제-run boundary canary/report 생성
3. control-plane에서 actual model request 전송
4. model/account entitlement 및 응답 성공 여부 기록
5. candidate tool trace 저장
6. post-run runner-attestation v2 생성
7. raw pre-run runner-job과 runner-job-link v2 재계산
8. evidence extraction
9. evaluator review bundle
10. semantic review v2
11. grade gate
12. analysis-result v3
13. 두 smoke job의 lineage가 모두 완전한지 확인

이 smoke 결과의 baseline/v0.5 차이는 **skill effect로 해석하지 않는다.**

## smoke 이후에만 가능한 다음 단계

smoke가 완전히 녹색일 경우에만:

```text
baseline / generic / legacy-clean / feynman-v05
```

four-condition public-development pilot로 이동한다.

그 결과로 분산/비용을 보고 final threshold를 frozen한 뒤 independent held-out를 작성/동결한다.

## 현재 판단

**현재 시점에서는 사람/승인된 운영 환경 개입이 필요하다.**

이유는 코드 결함이나 설계 미완료가 아니라 실제 외부 model-service credential/account 권한이 이 대화/저장소에서 자동 생성 가능한 입력이 아니기 때문이다.

credential이 설정되기 전에는 실제 model behavior를 추가로 검증했다는 주장을 하지 않는다.
