# LOG-067 — Raw POSIX request namespace fix

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 선행 checkpoint: [LOG-066](LOG-066-approved-namespace-startup-result-20260913.md)
- 대상: Windows host proxy의 raw POSIX request 경로 해석
- 외부 진단: 실행하지 않음
- 실제 model turn: 실행하지 않음
- OpenAI Platform API/API key: 사용하지 않음

## 발견한 결함

`RpcPathMapper.host_to_container()`는 `/var/private.txt` 같은 raw POSIX 절대경로를
처음에는 container 경로로 시도했지만, declared mount 밖이면 예외를 삼키고
`_host_to_container_path()`로 재해석했다. native Windows host에서 이 동작은 이미
remote/container namespace인 경로를 host namespace로 오인하고 telemetry reason도
잘못 기록한다.

공식 App Server 문서는 remote environment 경로와 instruction source가 source
environment의 native absolute syntax를 사용한다고 규정한다. 따라서 raw POSIX
절대경로는 container namespace에 고정하고, host namespace 입력은 Windows 절대경로
또는 Windows file URI 경로 처리로 제한했다.

## 변경

`tooling/feynman_rpc_path_mapping.py`에서 raw POSIX absolute path가 declared
container mount 밖이면 즉시 `container-path-outside-declared-mount`로 종료하게
했다. fallback host parsing은 제거했다. `tests/test_feynman_rpc_path_proxy.py`에
raw POSIX 경로가 container reason으로 남는 회귀 fixture를 추가했다.

기존 네 개 mount, Docker 실행 인자, control home, auth gate, evaluator, 모델
설정은 변경하지 않았다. payload와 경로 문자열을 telemetry에 저장하지 않는다.

## 로컬 검증 명령과 결과

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest tests.test_feynman_rpc_path_proxy tests.test_feynman_rpc_compatibility
```

결과: `23 tests`, `OK`.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

결과: 전체 `373 tests`, `OK (skipped=11)`; whitespace error 없음.

오프라인 fixture 결과:

- `file:///var/private.txt` → `container-path-outside-declared-mount`
- raw `/var/private.txt` → 수정 후 `container-path-outside-declared-mount`
- raw `C:/private/example` → `host-path-outside-declared-mount`
- relative/traversal config path → `invalid-host-path`

이 fixture는 synthetic 값만 사용했고 Codex, Docker, 인증, 네트워크를 실행하지
않았다.

## 판정과 다음 작업

LOG-066의 `-03` artifact는 수정 전 실행 결과로 보존한다. 따라서 기존
`host-path-outside-declared-mount:4` 수치를 소급 변경하지 않는다. 이번 수정으로
향후 telemetry의 namespace 판정은 일관돼졌지만, startup 성공이나 실제 rejected
path의 허용 필요성을 증명하지는 않는다.

다음은 이 수정 이후의 별도 model-free startup 검증이다. 실행 전에는 새 산출물
경로를 만들고, `turn/start` 없는 단일 진단인지 확인한다. 결과가 성공하기 전에는
실제 model evaluation을 시작하지 않는다. mount를 넓히거나 누락된 config 응답을
만들어 startup을 통과시키지 않는다.

자동 retry, model fallback, Terra/Sol 전환, baseline 전달, main 병합, force push는
하지 않는다.

## 저장 상태

- mapper 변경, 회귀 테스트, 이 로그, 재개 포인터는
  `049c0abca914488a7a2bc6ca75802caa41054ae6`
  (`fix: preserve raw posix remote path namespace`)로 commit하고 feature branch에
  일반 push했다.
- 위 정확한 SHA의 고유 7개 GitHub Actions workflow가 모두 success였다.
- 사용자 PNG 2개는 untracked로 보존하고 stage하지 않는다.
- main merge와 force push는 하지 않는다.
