# LOG-007 — synthetic control-plane auth separation 실제 E2E 성공

- **시각(KST)**: 2026-09-08 21:12
- **검증 대상 head**: `68a58227dd7933ccf1f461034b824a9c451a97d2`
- **workflow**: `validate-feynman-synthetic-auth-reference`
- **run**: #2, run id `34224614768`
- **artifact**: id `10055161917`
- **artifact ZIP SHA-256**: `b17acdcde808fc7096bcb028cd72ac5e337a552c776ada3687722aa9d5d08cc8`

## 목적

실제 외부 model-service credential을 사용하기 전에, 매 run마다 생성한 랜덤 synthetic bearer가 host-side Codex model control plane에서 실제 Authorization bearer로 사용되고, 동일 raw credential이 remote tool 환경과 candidate/evidence 파일로 복제되지 않는지 실제 GitHub runner에서 검증한다.

## 전체 workflow 상태

동일 head `68a58227...`에서 다음 6개 workflow가 모두 **success**:

- `validate-feynman` run #330
- `validate-feynman-docker-reference` run #62
- `validate-feynman-codex-reference` run #52
- `validate-feynman-remote-exec-reference` run #53
- `validate-feynman-remote-patch-reference` run #15
- `validate-feynman-synthetic-auth-reference` run #2

synthetic-auth job의 전용 unit/regression tests는 **71개 통과**.

## control-plane credential 생성/보호

- raw bearer는 workflow에서 Python `secrets.token_urlsafe(48)`로 매 run 새로 생성.
- prefix는 `FYN_SYNTH_`.
- raw 값은 `/tmp/feynman-synthetic-auth-reference/protected-control/secret.txt`에만 저장.
- 파일 권한 `0600`.
- Codex host control plane에 `OPENAI_API_KEY` environment variable로 전달.
- checkout은 `persist-credentials: false`.
- artifact upload 전 `protected-control/secret.txt` 삭제 및 부재 확인 step 성공.
- 업로드 artifact 26개 파일 중 secret 이름이 들어간 파일은 `synthetic-secret-sha256.txt` 하나뿐이며 raw secret file은 없음.
- 추출 artifact 전체에서 raw secret prefix `FYN_SYNTH_` exact bytes를 검색한 결과 0건.

## bearer SHA 증거

synthetic secret SHA-256:

`bfaa45247e520c878da0b39837999c9dd000d11a945c403c46bf229ba17380f2`

`mock-state.json`:

- schema version: `4`
- expected bearer SHA: 위와 동일
- validation error: `null`
- 정확히 2 model request

두 request 모두:

- `authorization_bearer_present = true`
- `authorization_bearer_sha256 = bfaa45247e520c878da0b39837999c9dd000d11a945c403c46bf229ba17380f2`
- `authorization_matches_expected = true`

두 번째 request에는 remote exec output이 존재하고:

- `exec_output_contains_auth_env_marker = true`
- `exec_output_contains_auth_value_marker = true`

따라서 mock endpoint가 단순히 열려 있었던 것이 아니라, **보호된 synthetic secret과 동일한 SHA를 갖는 bearer를 실제 Responses request에서 수신**했다.

## remote tool 내부 증거

`codex-trace.jsonl` 실제 command output에 다음 marker가 모두 존재:

```text
AUTH_ENV_CLEAN
AUTH_VALUE_CLEAN
NETWORK_BLOCKED
REMOTE_EXEC_OK
```

의미:

- `AUTH_ENV_CLEAN`: remote tool env에 auth/token/secret/password/API-key 계열 key 이름 없음.
- `AUTH_VALUE_CLEAN`: remote tool env의 모든 value를 SHA-256해도 synthetic bearer SHA와 동일한 값 없음.
- `NETWORK_BLOCKED`: control-plane에서 reachable한 같은 mock endpoint로 remote tool TCP 연결 실패.
- `REMOTE_EXEC_OK`: 실제 candidate workspace command 실행/쓰기 성공.

최종 model-side message `REMOTE_EXEC_REFERENCE_OK`도 trace에서 확인.

## Docker/profile 증거

`tool-container-inspect-check.json`:

- verdict: `docker-inspect-matches-profile`
- container id: `75758292d6ecee4775cff42eed882589ce0c047a239ece401521268a75accdd8`
- image id: `sha256:9b3098cff332f30d3dee25d18279842c3ed035bcb2ca248062db19cd0a840a71`
- network mode: `none`
- rw mounts는 정확히 4곳:
  - candidate
  - candidate-home
  - tool-codex-home
  - tool-temp
- tmpfs: `/tmp`
- candidate env key allowlist:
  - `CODEX_HOME`
  - `HOME`
  - `PATH`
  - `PYTHONDONTWRITEBYTECODE`
  - `TMPDIR`

boundary profile SHA-256:

`1ee8fbb86774f1340ec930d41ebbb5e0c83a72e2a81d85bd076365dcf4cb0a96`

## evaluator-side exact-byte leak scan

`credential-leak-scan.json`:

- verdict: `credential-exact-bytes-not-found`
- scan secret SHA: bearer SHA와 동일
- exact secret found: `false`
- symlinks allowed: `false`
- scanned file count: **10**
- scanned total bytes: **11,507**

scan roots:

- candidate
- candidate-home
- tool-codex-home
- tool-temp

explicit scanned files:

- `codex-trace.jsonl`
- control `config.toml`
- control `environments.toml`
- control-plane network reference
- mock state
- remote reference result
- runner job
- synthetic secret SHA file

실제 file manifest:

| source | bytes | sha256 | file |
|---|---:|---|---|
| root | 15 | `b95df8af34190814b55f57d5b20a58233422cd160c380c49acb8d9e116ac397d` | candidate/remote-tool-proof.txt |
| root | 145 | `8b7f8c279e36737d112f40fdf6035bcac87010006fee2f54237864e1a02a1653` | candidate/task.txt |
| explicit | 3290 | `3f4e9e1964cdce763b7b20f943098bd7b9dcbe7dd701c834c2804443f856dc63` | codex-trace.jsonl |
| explicit | 637 | `14a844cc4c553b78b8fde630503a9e69daa5519e7768faa9729b427b3e5dcd7b` | control config.toml |
| explicit | 1272 | `4814a7a7ceb36722456b56bd7a75094f2b2a411acd223cc1e86f03a14b3e8518` | environments.toml |
| explicit | 241 | `04794401cff097ee1c3b81c89349535d05b6419801ced6e1f0a5ccfb15d81438` | network reference |
| explicit | 1939 | `0ecaeb1f4e24115ecbc5ebe8ef99a46649003f93f73a80686493e4ea17a983ae` | mock-state.json |
| explicit | 1870 | `5827c758fd277694068495ae7589f5941afb5d5743ceb166cf9844d633351fdc` | remote-reference-result.json |
| explicit | 2033 | `44e74b683faf18e156013be040a09d8c6db23b801075c553531e31ff9f23b804` | runner-job.json |
| explicit | 65 | `ae4faa126cb2045b64f69f4ca8d405c1ba7a2567b499be7316a464268845ec56` | synthetic-secret-sha256.txt |

주의: exact-byte scanner는 raw secret byte sequence 부재만 주장한다. base64/hash/encryption 등 변형 representation 전체 부재는 주장하지 않는다.

## synthetic auth result hash chain

`synthetic-auth-result.json`:

- schema version: `1`
- verdict: `synthetic-control-plane-auth-reference-passed`
- secret SHA: `bfaa45247e520c878da0b39837999c9dd000d11a945c403c46bf229ba17380f2`

bound digests:

- remote reference result: `5827c758fd277694068495ae7589f5941afb5d5743ceb166cf9844d633351fdc`
- mock state: `0ecaeb1f4e24115ecbc5ebe8ef99a46649003f93f73a80686493e4ea17a983ae`
- credential leak scan: `cf2d5b2dd28f9d3540fb55f67c67b67df8216553a17621f9ed0742abbd0867c4`
- remote Codex trace: `3f4e9e1964cdce763b7b20f943098bd7b9dcbe7dd701c834c2804443f856dc63`
- boundary profile: `1ee8fbb86774f1340ec930d41ebbb5e0c83a72e2a81d85bd076365dcf4cb0a96`
- runner job: `44e74b683faf18e156013be040a09d8c6db23b801075c553531e31ff9f23b804`

all assertions true:

- all model requests used expected synthetic bearer
- mock contract stores no raw bearer
- remote tool auth-like env keys absent
- remote tool matching credential env value absent
- tool network blocked
- local execution disabled
- exact secret bytes absent from scanned artifacts
- scan symlinks disallowed

## 결론

사람 개입 없이 가능한 authentication separation reference가 실제로 통과했다.

현재 확인된 구조:

```text
host-side Codex model control plane
  └─ synthetic bearer 보유 + mock model endpoint 통신 성공

selected remote stdio exec-server
  └─ Docker network=none
  └─ credential key/value 미노출
  └─ local execution disabled
  └─ candidate workspace tool 실행만 수행
```

따라서 별도 custom credential proxy를 반드시 새로 구현해야 한다는 이전 가정은 약해졌다. 다만 현재 runner-job의 authentication mode가 여전히 `external-broker`라고 선언되어 있어 **실제 검증 구조와 계약 명칭이 불일치**한다. 실제 model pilot 전에 이를 바로잡아야 한다.

## 이 결과가 증명하지 않는 것

- 실제 OpenAI/model-service credential이 동일하게 작동함
- refresh/account/organization/project headers 등의 실제 인증 semantics
- encoded/transformed credential representation 부재
- host-side control-plane 자체에서 credential을 메모리에 보유하지 않음 — control-plane 보유는 의도됨
- Feynman skill 성능 향상

## 다음 작업

runner-job authentication contract를 실제 검증 구조에 맞게 수정한다.

현재 잘못된 선언:

`mode = external-broker`

실제 검증된 의미:

`control-plane-only credential ownership + remote tool credential exclusion`

계약 변경 후 synthetic/exec/patch references를 다시 회귀시키고, 그 뒤 실제 model-service pilot에 필요한 사람 개입 범위를 확정한다.
