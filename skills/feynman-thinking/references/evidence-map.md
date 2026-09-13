# 근거 지도 — 확인 범위와 일반화 한계

검토일: 2026-09-08. [E] 직접 발언, [P] 출판된 연구 행동에서 도출한 해석, [X] 현대적 운영 설계. 아래 자료는 스킬의 역사적 영감을 설명하며 AI 성능 향상의 증거가 아니다. 인터뷰는 자기보고이고, 성공한 출판물의 표본에는 선택 편향이 있다. 공동 연구의 행동을 한 사람에게 독점 귀속하지 않는다.

| 규칙 | 층위와 자료 | 확인한 위치/내용 | 허용되는 일반화와 경계 |
|---|---|---|---|
| 명칭을 이해로 오인하지 않기 | E, S1 | 새 이름 일화와 바로 뒤의 이름이 의사소통에 유용하다는 보완 | 이름을 지우는 의례가 아니라 관계를 설명한다. 용어 자체를 거부하지 않는다. |
| 같은 현상의 다른 표현 만들기 | P, S2 | 초록: 익숙한 정식화와 수학적으로 동치인 다른 정식화 | 표현 전환을 시도하되 동치 조건을 확인한다. 모든 표현이 경쟁 이론인 것은 아니다. |
| 상상과 검사를 함께 사용하기 | E, S3 | 1–1 Introduction: 실험과 상상에 관한 연속 문단 | 생성과 비판을 병행한다. 모든 문제를 물리 실험으로 판단하지 않는다. |
| 불리한 조건·대안 설명 공개 | E, S4 | scientific integrity를 설명하는 문단 및 결과에 불리한 조건을 보고하라는 부분 | 자기기만 방지. 평가자가 원하는 결론을 만들라는 뜻이 아니다. |
| 산출물별 정확도와 근사 관리 | P, S5/S6 | 두 논문의 초록: 유효질량 정확도 판단의 어려움, 근사·보정과 한계 | 하나의 성공을 모든 산출물의 정확성으로 일반화하지 않는다. 근사 원장 양식은 X다. |
| 증거 없는 변경 강요 금지 | E, S1 | Hoyle 대화에서 알려진 법칙으로 우선 설명하고 계속 실패하면 바꾼다는 부분 | 정당한 유지와 정당한 수정을 모두 허용한다. 변화 자체를 점수화하지 않는다. |
| 작은 모델의 효용과 한계 | E, S1 / X | 체스의 일부 말로 단순한 경우를 이해하는 비유와 복잡성 논의 | 최소 모델이 새로운 귀결을 드러내는지 확인한다. 임의의 장난감이 현실을 증명하지 않는다. |

## 1차 자료와 접근 범위

- **S1**: Richard Feynman, *Take the World from Another Point of View*, 1973년 Yorkshire Television 인터뷰의 1974년 축약 전사. Caltech 제공 HTML의 해당 발언을 확인했다. `https://calteches.library.caltech.edu/35/2/PointofView.htm`
- **S2**: R. P. Feynman (1948), *Space-Time Approach to Non-Relativistic Quantum Mechanics*, Reviews of Modern Physics 20, 367–387. DOI: 10.1103/RevModPhys.20.367. 이번 검토는 출판사 초록 범위다. 본문 전체를 새로 재검증했다고 주장하지 않는다. `https://journals.aps.org/rmp/abstract/10.1103/RevModPhys.20.367`
- **S3**: Feynman, Leighton & Sands, *The Feynman Lectures on Physics*, Vol. I, Ch. 1, §1–1. Caltech HTML의 해당 문단을 확인했다. `https://www.feynmanlectures.caltech.edu/I_01.html`
- **S4**: Richard Feynman (1974), *Cargo Cult Science*, Engineering and Science 37(7), 10–13. Caltech HTML을 확인했다. 연설의 과학적 정직성 원칙만 사용하며 역사·문화 묘사를 현대적 사실로 재사용하지 않는다. `https://calteches.library.caltech.edu/51/2/CargoCult.htm`
- **S5**: R. P. Feynman (1955), *Slow Electrons in a Polar Crystal*, Physical Review 97, 660–665. DOI: 10.1103/PhysRev.97.660. 확인 범위: 출판사 초록. `https://journals.aps.org/pr/abstract/10.1103/PhysRev.97.660`
- **S6**: R. P. Feynman, R. W. Hellwarth, C. K. Iddings & P. M. Platzman (1962), *Mobility of Slow Electrons in a Polar Crystal*, Physical Review 127, 1004–1017. DOI: 10.1103/PhysRev.127.1004. 확인 범위: 출판사 초록. 공동 연구다. `https://journals.aps.org/pr/abstract/10.1103/PhysRev.127.1004`

## 현대적 확장 — 역사적 규칙으로 주장하지 않는 것

작업 모드, 스킬 라우팅, 증거 ID, 인계 계약, 상태 열거형, 개인정보·권한 가드레일, 코드 실행 로그, 위험 기반 검토, 편향·분배 영향 점검, 평가 격리, 행동 평가와 배포 기준은 모두 X다. 설명 후 전이 문제를 푸는 절차 역시 현대적 구현이며 파인만이 공식 발표한 고정 학습법으로 귀속하지 않는다.

더 많은 논문을 추가하기 전에 어느 규칙의 귀속·경계·검증 가능성이 개선되는지 설명해야 한다. 근거를 반박하는 자료가 나오면 출처 귀속과 규칙을 좁히거나 제거한다.
