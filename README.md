# thinking-skills

역사적으로 알려진 인물들의 **검증 가능한 사고 행동**에서 영감을 얻어, 문제 해결에 재사용할 수 있는 Agent Skills를 설계·평가하는 저장소입니다.

유명인의 말투나 성격을 흉내 내거나 그 인물의 내부 사고를 복제한다고 주장하지 않습니다. 각 스킬은 출처에서 관찰 가능한 행동, 그 행동을 실무에 옮긴 현대적 확장, 적용 한계를 구분하고 실제 과제에서 효과가 있는지 별도로 평가합니다.

## 현재 상태

첫 번째 통합 대상은 `feynman-thinking`의 **v0.5.0-draft**입니다. 기존 `Ronaldony/feynman-thinking` v0.4.0을 감사한 뒤, 다중 스킬 저장소에 맞게 역할 경계·런타임 패키징·평가 격리를 재설계했습니다.

- 런타임: `skills/feynman-thinking/`
- 통합 설계: `docs/feynman-integration.md`
- 기존 구현 감사: `docs/feynman-audit-2026-09-08.md`
- 공개 개발 평가: `evals/feynman-thinking/`
- 행동 비교 사전등록 초안: `evals/feynman-thinking/preregister.md`
- 패키징·workspace·증거·구조 게이트: `tooling/`
- 회귀 테스트: `tests/`

현재 버전은 **research preview**입니다. 정적·구조 테스트 통과를 실제 LLM 성능 향상으로 간주하지 않습니다. 모델 비교 평가와 비공개 held-out 검증이 끝나기 전에는 v1.0 또는 "성능 검증 완료" 상태를 부여하지 않습니다.

## 설계 원칙

1. **역사적 귀속과 현대적 확장을 분리한다.** 유명인의 이름을 정확성의 근거로 쓰지 않는다.
2. **형식보다 작업을 평가한다.** 체크리스트를 채운 흔적이 아니라 계산·검사·증거·결론 갱신을 본다.
3. **편향을 실패 모드로 취급한다.** 자기확증뿐 아니라 반대를 위한 반대, 권위 편향, 평가자 정답 노출도 통제한다.
4. **다중 스킬에서는 역할 경계를 둔다.** 한 스킬이 모든 중요한 문제를 독점하지 않는다.
5. **평가 자산은 런타임에서 분리한다.** 후보 모델이 루브릭·정답·이전 결과를 읽을 수 있는 구조를 피한다.
6. **구조 검증과 행동 검증을 분리한다.** 패키징·CI 성공은 모델 성능을 입증하지 않는다.

## 로컬 구조 검증

Python 3.10+ 기준으로 외부 Python 패키지 없이 현재 구조 검사를 실행할 수 있습니다.

```bash
python -m unittest discover -s tests -v
python audit/legacy_probes.py
python tooling/feynman_package.py --root . --output /tmp/feynman-preview
python tooling/feynman_eval_workspace.py --root . --case tools-10 \
  --candidate-dir /tmp/feynman-candidate --evaluator-dir /tmp/feynman-evaluator
mkdir -p /tmp/feynman-home /tmp/feynman-codex-home
python tooling/feynman_eval_preflight.py \
  --candidate-dir /tmp/feynman-candidate \
  --expected-skill feynman-thinking \
  --home /tmp/feynman-home --codex-home /tmp/feynman-codex-home
```

- `feynman_package.py`는 런타임 허용 목록만 패키징합니다.
- `feynman_eval_workspace.py`는 후보와 평가자 파일을 다른 디렉터리에 배치합니다.
- `feynman_eval_preflight.py`는 후보/사용자/CODEX_HOME/상위 경로의 예상하지 않은 skill root를 검사합니다.
- `codex_exec_evidence.py`는 실제 `codex exec --json` trace가 있을 때 reasoning을 복사하지 않고 실행·도구 증거와 final만 평가자 번들로 축약합니다.

이 도구들은 운영체제·컨테이너·네트워크 수준의 보안 샌드박스를 제공하지 않습니다. 실제 비교 실행은 별도 보안 경계와 평가 전용 HOME/CODEX_HOME을 사용해야 합니다.

## 라이선스

아직 저장소 라이선스를 정하지 않았습니다. 공개 저장소라는 사실만으로 재사용 라이선스가 자동 부여된다고 가정하지 않습니다.
