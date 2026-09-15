# LOG-006 — synthetic control-plane auth reference 구현

- **시각(KST)**: 2026-09-08 21:10
- **시작 head**: `112af096053171d4f3f99d3891fb236609edc29e`
- **목적**: 실제 model-service credential을 사용하기 전에, 매 run마다 생성한 synthetic bearer가 host-side model control plane에서 실제 사용되면서 remote tool/candidate/evidence 쪽으로 raw credential이 노출되지 않는지 검증한다.

## 설계 원칙

1. synthetic bearer는 매 GitHub Actions run마다 랜덤 생성한다.
2. raw bearer는 `/tmp/.../protected-control/secret.txt` 한 파일에만 저장하고 artifact 업로드 전에 삭제한다.
3. mock Responses server는 raw `Authorization` header/token을 저장하지 않는다.
4. server는 bearer token의 SHA-256만 계산해 request record에 남긴다.
5. remote command에는 raw bearer가 아니라 expected bearer SHA-256만 전달한다.
6. remote command는 auth-like env **key 이름**과 모든 env **value hash**를 각각 검사한다.
7. evaluator-side scanner가 candidate-owned roots와 trace/config/result 파일에서 raw bearer exact bytes를 별도로 검색한다.
8. synthetic-auth result builder가 secret SHA → mock request auth SHA → remote reference mock-state SHA → leak-scan SHA를 결속한다.
9. 이 reference가 성공해도 real external model authentication을 검증했다고 주장하지 않는다.

## 변경

### `tooling/feynman_mock_responses_server.py`

commit: `3a9f99b53b1b73ee6a32d73f92c3d969f9984d60`

- mock-state schema v4.
- optional `--expected-bearer-sha256` 추가.
- `Authorization: Bearer ...`를 읽되 raw 값은 저장하지 않고 다음만 기록:
  - `authorization_bearer_present`
  - `authorization_bearer_sha256`
  - `authorization_matches_expected`
- expected digest가 있는데 bearer가 없거나 SHA mismatch이면 401 + validation error.
- remote tool command에 raw secret 대신 expected SHA만 전달.
- 모든 remote env value의 SHA-256을 계산해 control credential SHA와 같으면 fail.
- 성공 marker `AUTH_VALUE_CLEAN` 추가.
- 기존 expected bearer가 없는 exec/patch reference는 `AUTH_VALUE_CLEAN`을 요구하지 않아 의미 호환 유지.

### `tooling/feynman_remote_exec_reference_result.py`

commit: `54d9ee92e0dd148ba18e8018a774d9ca719b56b4`

- core remote-tool validator는 mock-state v3와 v4를 모두 수용.
- v4의 authentication-specific 의미는 synthetic-auth 전용 validator에서 별도 강제.
- 기존 exec-only / patch-then-exec reference assertion 수준은 완화하지 않음.

### `tooling/feynman_credential_leak_scan.py`

commit: `7065659e9f9802c04c2813929b30ece3d6663a45`

- secret은 `--secret-file`로만 읽음. raw secret을 argv에 넣지 않음.
- root walk는 symlink를 follow하지 않고 **발견 즉시 실패**.
- special/non-regular file도 실패.
- per-file/total byte limit 초과는 skip하지 않고 실패.
- duplicate root/file coverage 거부.
- 정확한 raw secret byte sequence가 한 파일이라도 있으면 실패.
- report에는 secret SHA-256/길이와 scanned file SHA/size만 저장.
- transformed/encoded secret 부재는 주장하지 않는다고 scope 명시.

### `tests/test_feynman_credential_leak_scan.py`

commit: `cc61c4fd705d3f593e4422ff473bf1cd296575c3`

회귀:
- clean root + trace pass
- candidate 직접 leak reject
- trace leak reject
- symlink reject
- oversized file reject
- total limit reject
- duplicate coverage reject
- duplicate root reject
- empty/newline-only secret reject
- special file/FIFO reject

### `tooling/feynman_synthetic_auth_reference_result.py`

commit: `67030fb9f6bd6e5b4d8470473185e6e421b97e25`

필수 결속:
- remote reference result schema v3 + passed + exec-only
- remote reference의 raw `mock_state_sha256` == supplied mock-state bytes
- mock-state schema v4
- protected synthetic secret SHA == mock expected bearer SHA
- 정확히 2 model requests 모두 bearer present/matching/same SHA
- 최종 exec output에 `AUTH_ENV_CLEAN` + `AUTH_VALUE_CLEAN`
- leak scan secret SHA가 같은 값
- leak scan exact_secret_found=false / symlinks_allowed=false
- nonempty scanned file/byte manifest

### `tests/test_feynman_synthetic_auth_reference_result.py`

commit: `f3f407ffd43519fcdfcb4cebcb1ee7e098f336bb`

거부 회귀:
- bearer SHA mismatch
- 한 request bearer 누락
- AUTH_VALUE marker 누락
- 다른 secret에 대한 leak scan
- 다른 mock-state에 바인딩된 remote result
- remote network assertion 실패
- mock-state v3 사용
- empty scan manifest

### `tests/test_feynman_mock_responses_server.py`

commit: `551056aa49ec67b422cabee69cc5366c2df7dc49`

- bearer digest 함수가 raw token 대신 SHA만 반환하는지 확인.
- expected SHA를 remote command에 넣을 때 `AUTH_VALUE_CLEAN` 검사가 생성되고 raw secret은 command에 포함되지 않는지 확인.
- malformed SHA reject.

### `.github/workflows/validate-feynman-synthetic-auth-reference.yml`

commit: `68a58227dd7933ccf1f461034b824a9c451a97d2`

실제 run 순서:

1. checkout은 `persist-credentials: false`.
2. host/tool Codex 동일 npm version 구성.
3. random synthetic bearer 생성 + protected 0600 file 저장.
4. SHA만 별도 파일에 기록.
5. frozen baseline job + network-none Docker profile + local-disabled remote environment 생성.
6. mock server를 expected bearer SHA와 함께 시작.
7. host Codex에 raw bearer를 `OPENAI_API_KEY` env로만 전달.
8. remote exec command에서 key-name/value-hash/network/workspace checks 수행.
9. Docker inspect/profile 검증.
10. normal remote reference result 생성.
11. evaluator leak scanner 실행:
    - candidate
    - candidate-home
    - tool-codex-home
    - tool-temp
    - codex trace
    - mock state
    - remote reference result
    - runner job
    - network reference
    - control config
    - environments.toml
    - synthetic-secret SHA file
12. synthetic-auth result 생성.
13. protected raw secret 삭제를 확인한 후 artifact upload.

## 검증 상태

이 문서 작성 시점에는 구현 커밋만 완료. 실제 GitHub Actions synthetic-auth run 결과는 아직 확정하지 않음.

## 다음 작업

- `68a58227...` 또는 이후 최신 head의 `validate-feynman-synthetic-auth-reference` 실제 run을 확인한다.
- 실패 시 최초 실패 step과 exact log를 LOG-007로 기록 후 수정한다.
- 성공 시 artifact를 다운로드해 raw-secret 파일이 artifact에 없는지, mock request bearer SHA, remote output markers, leak-scan coverage/digests를 직접 대조한다.

## 남은 위험

- synthetic credential은 real model-service credential과 동일한 인증 구현/refresh/account semantics를 검증하지 않는다.
- exact-byte scanner는 encoded/transformed representations를 탐지하지 않는다.
- control-plane 자체가 credential을 메모리에 보유하는 것은 의도된 구조이며 이 reference의 금지 대상이 아니다.
- 실제 FYN-08 model comparison은 여전히 미실행.
