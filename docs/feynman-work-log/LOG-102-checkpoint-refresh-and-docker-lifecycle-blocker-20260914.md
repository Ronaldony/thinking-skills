# LOG-102 — checkpoint 갱신과 Docker lifecycle blocker 재확인 (2026-09-14)

## 범위와 중단 규칙

이번 작업의 목적은 새 코드가 요구하는 실행 입력을 보정하고, 실제 구독
startup을 시작하기 전에 model-free Docker path contract를 확인하는 것이었다.
보호된 `C:\Users\wotmd\.codex-feynman-eval`은 디렉터리 존재만 확인하고 내부 파일은
읽지 않았다. 인증·모델·평가 입력을 사용하지 않았고, 개발 대화·인계 문서를
candidate에 전달하지 않았다. Docker lifecycle이 initialize 전에 막혔으므로 실제
구독 startup과 모델 smoke는 실행하지 않았다.

## 실제 명령과 관찰

### 1. 실행 입력 존재 확인

확인한 대상은 Python, `codex.cmd`, 기존 checkpoint, full-runner binding 디렉터리,
빈 Docker config 디렉터리, Docker 실행 파일, 보호된 평가 홈이다. 모든 대상이
각각 기대한 file/directory로 존재했다. 보호된 평가 홈 내부 목록·내용은 읽지 않았다.

기존 checkpoint는 다음 명령으로 읽기 전용 검증했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_subscription_startup_diagnostic --checkpoint 'C:\DevWorks\thinking-skills\.tmp\feynman-subscription-checkpoint-20260913-v3.json' --validate-only
```

관찰: exit `1`, `startup-diagnostic-input-invalid-value-error`. 내부 고정 검증을
payload 없이 직접 확인한 결과 기존 `telemetry`와 `output`이 이미 존재해
`checkpoint output must be a new path: output`으로 거부됐다. 이는 이전 증거를
덮어쓰지 않는 새 검증기가 정상적으로 차단한 것이다.

### 2. 새 checkpoint 보정

기존 checkpoint를 덮어쓰지 않고
`.tmp/feynman-subscription-checkpoint-20260914-v4.json`을 만들었다. 처음에는 새
출력을 저장소 `.tmp`에 두었으나, 새 계약이 evaluator 소유 경계를 요구해
`checkpoint output must be evaluator-owned: telemetry`로 거부됐다. runner-job의
evaluator 경계인
`C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator` 아래의
새 `startup-diagnostic-20260914-v5-rpc.json`과
`startup-diagnostic-20260914-v5.json`으로 수정했다. 기존 `.tmp`·evaluator
산출물은 삭제·덮어쓰지 않았다.

수정한 checkpoint로 다음을 실행했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_subscription_startup_diagnostic --checkpoint 'C:\DevWorks\thinking-skills\.tmp\feynman-subscription-checkpoint-20260914-v4.json' --validate-only
```

관찰: exit `0`, verdict `subscription-checkpoint-valid`,
`binding_valid=true`, `binding_config_override_count=13`, model `gpt-5.6-luna`,
`subprocesses_started=0`, `authentication_material_present=false`.

### 3. Docker 엔진과 이미지 메타데이터

일반 sandbox 컨텍스트의 읽기 전용 `docker info`는 named pipe 권한 거부였다.
Docker Desktop이 실행 중이라는 사용자 관찰과 분리하기 위해 권한 상승 컨텍스트에서
동일한 읽기 전용 명령을 1회 확인했다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' info --format '{{.ServerVersion}}|{{.OSType}}|{{.Architecture}}|{{.Containers}}|{{.Images}}|{{.Driver}}|{{.OperatingSystem}}'
```

관찰: `29.7.2|linux|aarch64|0|14|overlayfs|Docker Desktop`.

고정 path-contract image inspect 결과는
`sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6`,
`linux|arm64`, `WorkingDir` 공백, `User=1000:1000`, entrypoint
`docker-entrypoint.sh`, cmd `node`였다. 이미지 digest와 아키텍처 불일치는 아니다.

### 4. model-free Docker path contract 1회

다음 고정 fixture를 1회 실행했다. fixture는 임시 candidate·빈 home/codex/temp,
`--network none`, capability drop, read-only rootfs를 사용한다.

```powershell
& 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -B -m tooling.feynman_rpc_path_contract_probe --docker 'C:\Users\wotmd\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' --docker-config 'C:\Users\wotmd\AppData\Local\Temp\feynman-empty-docker-config' --image 'sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6' --proxy 'C:\DevWorks\thinking-skills\tooling\feynman_rpc_path_proxy.py' --output 'C:\DevWorks\thinking-skills\.tmp\feynman-path-contract-20260914-v1.json' --timeout 45 --docker-host 'npipe:////./pipe/docker_engine'
```

관찰: exit `1`, verdict `rpc-path-contract-blocked`, failure stage
`docker-peer-startup-timeout`. direct/proxy 모두 response ID 0건,
initialize 관찰 `false`, timeout `true`, peer close `true`, process exit code
목록 공백, stderr drain `true`, stdout/stderr read error `false`였다.
반면 request shape와 response shape digest 비교는 `true`로 남았지만 실제 peer
응답이 없으므로 path 의미 동등성의 합격 근거로 사용하지 않는다.

### 5. Docker create/run lifecycle 분리 시험

동일 이미지와 제한 조건으로 `codex --version`, entrypoint를 우회한 `node --version`,
그리고 `docker create`를 각각 시험했다. 세 호출 모두 Docker CLI가 반환하지 않는
현상을 보였다. 제가 시작한 CLI PID만 각각 `18048`, `22688`, `4012`, `31644`를
정리했고, 각 정리 뒤 `docker ps -a`는 빈 결과였다. 사용자 Docker Desktop
backend 프로세스는 종료하지 않았다.

`docker ps -a` 자체와 image inspect는 즉시 응답했으므로, 현재 증거는 엔진 전체
접속 불가가 아니라 container create/run lifecycle API가 반환하지 않는 상태를
가리킨다. 이미지 내부 `codex` 오류나 Windows path mapping 오류로 확대 해석하지
않는다.

## 수정 이유와 검증 범위

- 새 checkpoint의 출력 경로는 재사용하지 않고 evaluator 경계 안의 새 경로로
  분리했다. 이는 기존 증거 보존과 출력 경계 검사를 동시에 만족한다.
- Docker fixture 실패는 path mapping 수정으로 우회하지 않았다. initialize 응답
  이전에 양쪽 peer가 막혔으므로 `configPaths`, `cwd`, canonical path의 의미는
  아직 검증 보류다.
- 실제 startup gate, ChatGPT 구독 인증, 모델 smoke는 실행 횟수 `0`이다.
- 이번 변경은 checkpoint 파일과 이 로그·최신 포인터 문서뿐이며, Python 코드와
  기존 evaluator 산출물은 수정하지 않았다.

## Git·push 상태

작업 시작 시 branch는 `feat/feynman-thinking-v0.5-draft`, HEAD는
`7625a7c3fbc1aedd0dd7a86a7a778661123ae58b`였고 tracked 변경은 없었다.
`.tmp/`, 사용자 PNG 2개, 기존 untracked `LOG-099`는 보존·stage 제외한다.
이번 로그와 포인터 문서만 별도 commit/push 대상으로 삼는다. `git ls-remote`는
이번 재확인에서 Windows Schannel `SEC_E_NO_CREDENTIALS`로 실패했으나, 직전
push·CI receipt에서 같은 feature branch의 remote SHA는 확인돼 있었다.
실제 문서 변경은 `cde3196 docs: record checkpoint and docker lifecycle blocker`로
커밋했고 `git push origin HEAD:feat/feynman-thinking-v0.5-draft`가
`7625a7c..cde3196`으로 성공했다. 이후 working tree에는 보존 대상 untracked
항목만 남았다. 이 docs-only 커밋에 대해 `gh run list --commit cde3196`를 즉시
조회하고 20초 후 한 번 재조회했지만 새 workflow run은 없었다.

## 미완료와 다음 행동

미완료는 Docker container create/run lifecycle 반환 문제와 그에 따른 실제 path
contract 비교다. 따라서 구독 startup diagnostic과 Luna smoke를 지금 실행하지
않는다. Docker lifecycle이 실제로 회복됐다는 새 증거가 생긴 뒤에만 동일한 수정
probe를 1회 재실행하고, 그 결과가 통과할 때 새 구독 startup diagnostic 1회를
사람 경계로 검토한다. startup 실패 시 모델 smoke를 실행하지 않으며, 자동 재시도·
모델 fallback·mount 확대·로그인 홈 변경은 하지 않는다.
