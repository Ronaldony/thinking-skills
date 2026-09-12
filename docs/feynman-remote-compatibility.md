# Remote compatibility checkpoint — Luna, Terra, Sol

이 문서는 개발 담당자용이다. candidate/baseline에 전달하지 않는다.

## 모델 선택

`tooling/feynman_subscription_models.py`의 선택 목록:

- `gpt-5.6-luna`
- `gpt-5.6-terra`
- `gpt-5.6-sol` (`gpt-5.6 sol` 사용자 표기를 정규 식별자로 반영)

각 runner job은 `--model` 하나를 명시한다. 자동 fallback/순회/실패 재시도는 없다.
기존 frozen plan/job/result의 모델명을 바꾸지 않는다. generic runner schema는
미래의 명시적 선택과 synthetic test model을 계속 지원하며 이 목록으로 과도하게
제한하지 않는다. 준비는 사용 승인·계정 접근·모델 실행 성공의 증명이 아니다.

공식 [Codex models](https://learn.chatgpt.com/docs/models)에서 세 ID를 확인했다.
`codex debug models --bundled`를 빈 별도 홈에서 실행한 CLI 0.154.0의 관찰:
세 모델 모두 `shell_type=unified_exec`, `tool_mode=code_mode_only`,
`node_repl_disabled=false`. bundled 정보는 실제 계정의 접근 권한이나 해당 세션에
전달된 tool catalog가 아니다. 모델을 바꾸면 remote 문제가 해결된다고 추론하지 않는다.

## 새 검사 자료

`C:\DevWorks\feynman-remote-compat-20260912-01` 아래 모델별 candidate/evaluator/
home/codex-home/temp와 runner-job/environments를 새로 만들었다. baseline fixture는
만들지 않았고 실제 모델 호출은 0회다. 기존 Luna 자료와 보호된 로그인 홈은 보존했다.

## LOG-047 후속 checkpoint — model-free bounded adapter

기존 `fs/readFile`은 요청에 `offset/len`을 넣어도 117-byte `dataBase64` 응답을
반환했다. 이 사실을 감추기 위해 자르지 않고 기존 proxy의 fail-closed 응답 검사를
유지한다. 별도로 Docker image에 `feynman_read_probe_byte` MCP STDIO adapter를
넣었다. adapter는 실행 환경이 고정한 candidate 파일만 열고 실제 1 byte를 최대
1회 읽으며, 모델이 path/offset/command를 넘길 수 없다. 로컬 protocol과
network-disabled Docker protocol이 통과했다.

blank `CODEX_HOME`의 Codex 0.154.0 App Server `mcpServerStatus/list`에서도 이
도구가 catalog에 보이는 것을 model-free로 확인했다. 이는 local App Server
catalog 계약의 증거이지 기존 exec-server remote 환경이나 실제 모델 tool-use의
증거가 아니다. 이 diagnostic adapter는 tools-10 전체 평가 실행기에 연결하지
않는다.

새 Docker image:

- 태그: `feynman-codex-remote:0.154.0-20260912`
- ID: `sha256:36b6f50b88a3e5054e1943ef8a40bc80e1629ad0821b4657ec8a33d468179db6`
- 실행 profile의 `image`와 `image_id` 모두 위 immutable ID를 사용한다.
- Windows CLI, server, job 모두 `codex-cli 0.154.0` 일치 확인.
- recipe는 `tooling/docker/codex-remote/Dockerfile`; 이전 로컬 ARM64 image를
  기반으로 하는 **로컬 업그레이드 recipe**이며 다른 머신용 범용 build가 아니다.
  .dockerignore와 COPY 없는 최소 context로 repo/auth 자료가 image에 들어가지 않는다.

## 확인한 RPC 계약과 보정

`environmentConfig/read`의 검사에서 통과한 최소 형태:

```json
{
  "cwd": "file:///run/candidate",
  "configPaths": [["file:///run/candidate/.feynman-diagnostic-absent.toml"]],
  "requirementsPaths": []
}
```

두 경로 목록을 모두 비우면 서버는 거부한다. flat string list가 아니라 중첩
경로 그룹을 요구한다. `cwd`, 각 그룹의 Windows 경로를 declared Linux mount로
변환하며, 상대 경로/보호 영역/parent traversal은 거부한다.
`fs/canonicalize.path` 변환도 추가했다. 보정 후 일반 모드 canonicalize는 성공했다.

**config 조회는 파일 내용을 읽을 수 있으므로 metadata-only로 간주하면 안 된다.**
guard는 존재하지 않음을 확인한 고정 sentinel만 config 경로로 허용한다.
실제 config/candidate/skill 파일을 config RPC로 읽는 우회는 차단한다.
`fs/canonicalize`, `fs/walk`, `process/start`를 무조건 허용하도록 바꾸지는 않았다.

## 현재 실패하는 선행 조건

1. `offset=0,len=1` 요청을 보냈지만 서버의 decoded 응답은 117 bytes였다.
   fixture `candidate.py` 크기도 117 bytes다. 기존 요청 인자만으로는 1바이트
   계약이 성립하지 않는다. 새 proxy는 응답 ID와 요청 method를 연결해 실제
   base64 decoded 길이를 검사하고 초과/불명확 응답을 **client 전달 전에 거부**한다.
   잘라서 성공처럼 보이게 하지 않는다. 이 검사는 응답 전달 경계의 보호이며
   서버 내부에서 1바이트만 읽게 만든 구현은 아직 아니다.
2. filesystem-only probe와 code-mode 모델의 도구 연결이 검증되지 않았다.
   `process/start` 일반 허용은 읽기 범위 제한을 무력화할 수 있으므로 하지 않는다.
   `fs/*` 서버 기능과 모델 도구 이름은 별개다.

`feynman_guarded_rpc_preflight.py`는 실제 guard의 positive/negative 경로를 검사한다.
현재 결과는 `blocked-byte-read-contract`; 전체 discovery 및 model tool readiness는
false다. 정상 검사 결과와 실패 조건을 함께 남기고 모델 요청을 하지 않는다.

`feynman_subscription_tool_use_probe.py`에는 실행 전 version gate와 guarded gate를
연결했다. 새 CLI는 `--docker-config`가 필수다. 선행 조건 실패 시 auth check와
`codex exec` model 호출 **이전**에 종료한다. 기존 일반 smoke executor까지 전체
readiness gate가 통합됐다는 뜻은 아니며, baseline/smoke 직접 실행도 보류한다.

## 다음 구현 단위

실제 서버-side 단일 바이트 읽기를 제공하고 code-mode와 연결되는 제한된 read
adapter가 필요하다. 성공 조건은 고정 fixture 경로·symlink/traversal 검증,
실제 읽기 범위 및 응답 크기 제한, 임의 argv/process 차단, 허용된 discovery의
완결성, 모델에게 제공되는 도구 계약 검증이다. 일반 shell 권한을 여는 방식이나
단순 prompt 수정·모델 변경만으로 통과시키지 않는다.

이 adapter/도구 계약을 모델 없이 검증한 다음에야 별도 제한 model probe를
검토한다. 현재 checkpoint로 Feynman 효과 또는 baseline 비교 결과를 주장하지 않는다.
