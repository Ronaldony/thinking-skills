# LOG-071 — Canonical remote binding verification

- 시각: 2026-09-13 KST
- 저장소: `C:\DevWorks\thinking-skills`
- branch: `feat/feynman-thinking-v0.5-draft`
- 확인 시작 HEAD: `7b8ca4d docs: record RPC attribution checkpoint`
- 작업 성격: read-only structural verification
- 외부 startup/model 실행: 없음
- OpenAI Platform API/API key: 사용하지 않음
- 기존 변경: 사용자 PNG 2개 untracked; stage하지 않음

## 목적

LOG-070에서 추가한 `method→reason→field` telemetry가 다음 startup diagnostic에서
실제로 사용될 현재 proxy 파일과 연결돼 있는지 확인했다. 이전 실행이 구형
proxy/config를 사용해 새 계측이 보이지 않는 상황을 배제하기 위한 검사다.

## 실제 명령과 관찰

아래 구조 검증을 수행했다. remote environment 문서의 전체 내용, 인증 파일,
token, 전체 환경변수는 출력하지 않았다.

```powershell
@'
import tomllib
from pathlib import Path
from tooling.feynman_remote_exec_environment import validate_files
job = Path(r'C:\DevWorks\feynman-remote-compat-20260912-01\gpt-5.6-luna\evaluator\runner-job.json')
profile = Path(r'C:\DevWorks\feynman-remote-compat-20260912-01\boundary-profile.json')
remote = Path(r'C:\Users\wotmd\.codex-feynman-eval\environments.toml')
result = validate_files(job, profile, remote)
document = tomllib.loads(remote.read_text(encoding='utf-8'))
environment = document['environments'][0]
args = environment['args']
print('verdict=', result['verdict'])
print('include_local=', document.get('include_local'))
print('environment_count=', len(document.get('environments', [])))
print('uses_rpc_separator=', '--' in args)
print('proxy_arg_matches_current_repo=', str(Path(r'C:\DevWorks\thinking-skills\tooling\feynman_rpc_path_proxy.py')) in args)
print('docker_run_present=', 'run' in args)
print('program_is_python=', str(environment.get('program','')).lower().endswith(('python.exe','python')))
'@ | & 'C:\Users\wotmd\AppData\Local\Programs\Python\Python312-arm64\python.exe' -
```

결과:

```text
verdict= remote-exec-environment-valid
include_local= False
environment_count= 1
uses_rpc_separator= True
proxy_arg_matches_current_repo= True
docker_run_present= True
program_is_python= True
```

따라서 canonical remote binding은 현재 repository proxy path와 일치하며, 다음
진단이 `be18755`의 attribution code를 사용하게 된다. 이 검사는 실제 Python
proxy subprocess, Docker child, Codex App Server, login, network를 실행하지 않았다.

## 판정

구성 drift나 구형 proxy 참조는 현재 관찰된 blocker의 원인이 아니다. 남은
원인은 startup 시 control-plane이 생성하는 실제 request의 method/reason/field
조합이며, 그 값은 실제 diagnostic request 없이는 결정할 수 없다. raw path와
payload를 보존하지 않는 현재 보안 경계를 유지한다.

## 다음 행동

다음 외부 행동은 새 attribution telemetry를 포함한 model-free startup diagnostic
정확히 1회다. `initialize`와 `thread/start`까지만 수행하고 `turn/start`, prompt,
model generation, baseline/evaluation은 금지한다. 결과가 나오기 전에는 mount를
넓히거나 config response를 제조하지 않는다. 해당 외부 실행은 별도 명시 승인이
필요하다.

이 문서는 별도 docs-only checkpoint로 저장한다. main merge와 force push는 하지
않는다.
