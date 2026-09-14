# LOG-094 — Docker runtime 복구, stdin lifecycle 수정, path contract 통과 (2026-09-14)

## 상태

- 작업 ID: LOG-094 / 상태: DONE
- 저장소: `C:\DevWorks\thinking-skills`
- 브랜치: `feat/feynman-thinking-v0.5-draft`
- 시작 HEAD: `0c247a85efd8d0f6e5ac9e4a65db19ed940f2cec`
- 구현 commit: `dcdd49699ebdef0b5329e41601f6086fe2a5cd00`
- 보호된 구독 로그인 홈, 인증 파일, 모델, candidate 평가 payload는 사용하지 않았다.

## 목적

사용자의 Docker lifecycle API 재시도 요청에 따라 우리 label 범위만 확인했다. lifecycle 회복이 확인된 뒤 schema v3 runtime probe와 direct Linux 대 Windows proxy path-contract fixture를 실행하고, 새로 드러난 probe/CI 결함을 회귀 테스트와 함께 수정했다.

## 1. Docker lifecycle API 재확인

처음 작성한 Python `-c` timeout wrapper는 literal `\n` 인용 오류로 `SyntaxError`가 발생해 Docker에 도달하지 않았다. 이 로컬 명령 조립 오류를 Docker 실패로 계산하지 않았다.

그 뒤 다음 두 요청을 직접 실행했다.

```powershell
docker --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --host 'npipe:////./pipe/docker_engine' ps -a --filter 'label=com.openai.feynman.control' --format '{{.Names}}|{{.Status}}|{{.Image}}'
docker --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --host 'npipe:////./pipe/docker_engine' ps -a --filter 'label=com.openai.feynman.runtime-probe' --format '{{.Names}}|{{.Status}}|{{.Image}}'
```

두 요청 모두 약 0.23초에 exit 0, 출력 0건으로 완료됐다. 이전 lifecycle list blocker는 해소됐고 우리 control/runtime label의 잔존 container도 없었다. 다른 container 조회·삭제와 broad prune은 하지 않았다.

## 2. Runtime probe v5 실패 원인과 수정

회복 증거 뒤 수정 전 runtime probe를 새 artifact로 1회 실행했다.

```powershell
python -B -m tooling.feynman_docker_runtime_probe `
  --docker 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' `
  --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' `
  --docker-host 'npipe:////./pipe/docker_engine' `
  --image 'sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6' `
  --output 'C:\DevWorks\thinking-skills\.tmp\docker-runtime-probe-20260914-v5.json' `
  --timeout 30
```

결과는 `docker-runtime-blocked`, 최초 실패 `exec-server-initialize`였다. 앞선 create/start/node는 통과했다. 실패 stage는 Docker CLI exit 0, container exit 0, OOM false, cleanup verified true, 718ms, stdout 0바이트, stderr 167바이트였다.

로컬과 pinned image의 `codex exec-server --help`를 비교해 `--listen stdio`가 양쪽에서 지원됨을 확인했다. image의 stderr 경고가 167바이트와 일치했고, runtime probe가 initialize request를 flush한 직후 stdin을 닫아 exec-server가 응답 전에 EOF로 정상 종료한 것이 원인이었다.

수정:

- stdout 첫 응답 또는 child 조기 종료/timeout까지 stdin을 유지한다.
- stdout reader가 첫 chunk를 event로 알리되 원문 보존 정책은 바꾸지 않는다.
- exec-server initialize stage에만 이 동작을 적용한다.
- child가 EOF를 먼저 관찰하면 exit 7, stdin이 열려 있으면 initialize response를 내는 회귀 fixture를 추가했다.

수정 후 새 artifact:

- `.tmp/docker-runtime-probe-20260914-v6.json`
- schema 3
- verdict `docker-runtime-ready`
- 4 stages 모두 통과, failure stage 없음
- 실제 실행 횟수: 수정 전 v5 1회, 수정 후 v6 1회

## 3. Path contract 실패와 수정

runtime 통과 뒤 direct Linux와 Windows proxy 비교를 실행했다.

- v4: 양쪽 exit 0이지만 request/response/namespace 비교가 모두 false.
- 첫 수정: `configPaths`·`requirementsPaths`를 path collection으로 비교하고, direct container namespace가 proxy 응답에서 host namespace로 변환되는 방향만 정상 계약으로 허용했다. Linux에서 Windows literal을 정규화하지 못하던 candidate 비교도 수정했다.
- v5: request와 namespace는 통과했고 response만 실패.
- fixed ID별 payload-free 계측을 추가했다. v6에서 ID 2 `environmentConfig/read`만 불일치하고 나머지 ID 1, 3~7은 일치했다.
- synthetic/empty-home fixture의 redacted shape만 추가 확인했다. ID 2의 유일한 차이는 Docker가 각 임시 container에 부여한 12자 `hostname`이었다. config, requirements, CODEX_HOME, HOME 구조는 동일했다.
- `sessionId`와 `hostname`만 allowlisted opaque runtime identity로 정규화했다. 다른 문자열은 계속 SHA-256과 길이로 비교한다.
- 필드명과 무관하게 명백한 file URI/POSIX/Windows 절대경로 문자열은 semantic path role로 비교한다.

최종 artifact:

- `.tmp/rpc-path-contract-20260914-expanded-v8.json`
- schema 3
- verdict `rpc-path-contract-equivalent`
- direct/proxy exit 0
- request shapes, response shapes, response namespace contract 모두 일치
- response IDs 1~7, 모두 result
- process exit 0, sandboxDenied false
- 실제 비교 횟수: v4, v5, v6, v7, v8 및 ID 2 redacted shape 진단 1회. 같은 실패를 정보 없이 반복하지 않았고 각 재실행은 새 판정 또는 계측 변경 뒤 수행했다.

## 4. 원격 CI 실패와 보정

이전 `0c247a8` CI에서 다음 실패를 확인했다.

- Linux: Windows literal candidate를 POSIX `Path`로 해석해 `outside-declared-mount`가 된 path contract 테스트 2건.
- Windows: temp 경로가 long form과 8.3 short form으로 달라 `.absolute()` 비교가 실패한 tool-use probe 테스트 1건.

수정:

- production path role/namespace 비교에서 candidate 문자열도 slash·drive 형식으로 정규화했다.
- canonical directory를 반환하는 코드 계약에 맞게 Windows 테스트 기대값을 `.resolve()`로 변경했다.

`dcdd49699ebdef0b5329e41601f6086fe2a5cd00`의 push/PR workflow는 각각 다음 7종이 모두 success다.

- validate-feynman
- validate-feynman-unit-diagnostic (Linux + Windows jobs)
- validate-feynman-subscription-readiness
- validate-feynman-docker-reference
- validate-feynman-codex-reference
- validate-feynman-remote-exec-reference
- validate-feynman-remote-patch-reference

총 14개 push/PR run이 success다.

## 5. 로컬 검증

```powershell
python -B -W error::ResourceWarning -m unittest discover -s tests
python -B -m py_compile tooling/feynman_docker_runtime_probe.py tooling/feynman_rpc_path_contract_probe.py tooling/feynman_subscription_startup_diagnostic.py tooling/feynman_subscription_smoke_exec.py
git diff --check
```

결과:

- `446 tests OK, 11 skipped`
- ResourceWarning 없음
- compile 성공
- diff check 성공
- runtime v6/path v8 artifact 불변조건 검사 통과

## 보안·범위

- OpenAI Platform API/API key를 사용하지 않았다.
- 구독 auth gate, 실제 App Server subscription startup, `codex exec`, Luna/Terra/Sol model turn, baseline/evaluation을 실행하지 않았다.
- 로그인 파일·토큰·전체 환경변수·raw RPC payload를 읽거나 보존하지 않았다.
- runtime/path fixture는 새 임시 candidate와 빈 runtime home만 사용했다.
- `.tmp/`와 사용자 PNG 2개는 stage하지 않았다.

## 커밋·push와 다음 행동

- 구현 commit `dcdd49699ebdef0b5329e41601f6086fe2a5cd00`을 feature branch에 일반 push했다.
- main merge와 force push는 하지 않았다.
- 다음 단계는 실제 실행기와 동일한 최종 startup gate를 이용한 ChatGPT 구독 model-free startup diagnostic 1회다. 이는 보호된 기존 구독 로그인 상태를 정상 Codex가 사용하는 외부 실행이므로, 앞서 정한 사람 승인 경계에서 멈춘다.
- startup이 통과하기 전에는 Luna smoke나 모델 평가를 시작하지 않는다. 실패 시 자동 재시도나 Terra/Sol fallback도 하지 않는다.
