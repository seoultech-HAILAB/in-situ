# TRACE — 테이블 변환 검수 프로토타입

In-situ 작업 화면은 **http://127.0.0.1:8002/in-situ** 에서 별도로 엽니다(현재 로컬 실행 포트 기준). 기존 `/` 화면과 실행 세션을 별도로 기억하며, 동일한 분할 패널을 사용합니다. 선택 Step의 결과 표에서 추가는 초록색, 변경은 노란색, 삭제는 빨간색으로 표시합니다. 삭제된 행·열·값은 표에 남겨 비교할 수 있고 실제 결과나 CSV에는 추가하지 않습니다. 색이 있는 셀, 행 번호, 열 제목을 누르면 관련 자연어 설명과 실행 코드가 말풍선으로 열립니다. Esc·닫기 버튼·바깥 클릭으로 닫을 수 있습니다. Input·추가 입력·Target 표에는 변경 표시를 적용하지 않습니다.

Step 내부의 개별 변환은 `backend/transformations.py`가 현재 실행 코드의 AST에서 추출합니다. 코드 생성·수정 때마다 코드 범위, 대상 열, 현재 실행·코드 버전을 다시 만들고, LLM 설명은 `(step_no, transformation_no)`의 전체 대응을 검증한 뒤 붙입니다. 상세 셀 추적이 지원되지 않는 Python도 개별 코드 위치를 제공합니다. 여러 변환이 연결되거나 정적 분석만으로 한 개를 고를 수 없으면 말풍선의 선택기에서 해당 변환을 고릅니다. 메서드 체인에서는 선택한 호출 부분을 강조합니다. 기존 저장 실행은 자기 코드로 분석하며, 예전 설명 묶음이나 API 실패 시에는 코드 분석 설명임을 표시합니다. 이 AST 정보는 코드상의 대응이며 실행되지 않은 분기나 셀 출처를 증명하지 않습니다.

새 LLM 코드 생성·수정 후에는 개별 변환 설명을 포함한 응답을 요청합니다. 기존 실행은 말풍선의 **설명 갱신**으로 이전 Step 설명 캐시 대신 새 변환별 LLM 설명을 받을 수 있습니다. 동일 실행·코드·위치의 새 형식 캐시는 재사용하며, 갱신 실패는 코드 실행 결과를 바꾸지 않습니다.

열 생성 설명은 `backend/source_dependencies.py`에서 사용 시점 이전의 임시 변수·열 정의를 거슬러 원본 열까지 추적합니다. 예를 들어 `location_parts[0].str.strip()`은 원본 `Location` 열을 어떤 구분자로 나누고 첫 부분을 선택했는지까지 설명하며, 필요한 정의는 팝오버의 **원본 열까지의 변수 정의**에 참고용 코드로 표시합니다. 정의가 바뀌면 기존 설명을 재사용하지 않습니다. 조건부·미해결 정의는 완전한 경로로 단정하지 않습니다. 팝오버에서 선택한 **현재 연산**은 채팅 수정 대상으로 유지되고, 해당 범위의 수정에서는 참고 정의나 형제 열의 변경을 서버가 거부합니다. 앞선 정의까지 수정하려면 사용자가 **전체 코드** 범위를 명시적으로 선택해야 합니다.

`python scripts/audit_transformation_locations.py`로 동봉 과제의 Step·개별 변환 위치 수를 확인할 수 있습니다. `--json`은 Step별 코드 범위도 출력합니다.

현재 기본 화면은 `myeonggi`의 Next.js·shadcn을 기반으로 한 분할 작업 화면입니다. 왼쪽 위에는 Step별 코드와 선택 Step의 실제 중간 테이블, 오른쪽에는 자연어 수정 요청, 왼쪽 아래에는 빈 영역을 둡니다. 경계선을 드래그하거나 키보드 방향키로 크기를 조절할 수 있습니다.

과제 선택 후 **실행**을 누르면 저장된 코드를 실행합니다. 코드의 Step을 누르면 중간 테이블과 요청 대상이 함께 바뀝니다. 표 선택기에서 Input·추가 입력·Target도 확인할 수 있습니다. 수정 요청은 **Enter**로 전송하고 **Shift+Enter**로 줄을 바꿉니다. 선택 Step 또는 전체 코드 수정, 수정 후 전체 재실행, 되돌리기, 결과 CSV 다운로드를 지원합니다. LLM 연결은 기존 `.env`의 `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`을 사용합니다. 화면을 열거나 초기 코드를 실행할 때 설명 생성 API를 호출하지 않습니다.

UI 소스는 `web/`에 있습니다. `cd web && npm ci && npm run build`로 빌드하며, Windows의 Turbopack CSS 처리 오류를 피하기 위해 Webpack과 Tailwind PostCSS를 사용합니다. `start.cmd`·`start.sh`도 시작 시 UI를 다시 빌드합니다. 기존 연구용 화면은 `/legacy`에 유지됩니다. 아래 검수 조건 설명은 이 기존 연구용 화면에 해당합니다.

현재 구현을 다른 개발자가 실행·수정하기 위한 저장소입니다. **로그인 없이 접속**합니다.

## 빠른 실행 (macOS)

Python 3.13을 설치한 뒤 실행하세요. 초기 과제 검수에는 API 키나 Node.js가 필요하지 않습니다.

```bash
git clone https://github.com/seoultech-HAILAB/in-situ.git
cd in-situ
bash start.sh
```

http://127.0.0.1:8001/?research=1 에서 과제를 선택하고 변환 시작을 누릅니다. 기존 설치는 `git pull origin main` 후 실행 중인 서버를 종료하고 `bash start.sh`로 다시 시작하세요.

## 빠른 실행 (Windows)

Python 3.13과 Node.js 22 이상, Git을 설치하고 다음을 실행하세요.

```powershell
git clone https://github.com/seoultech-HAILAB/in-situ.git
cd in-situ
Copy-Item .env.example .env
# .env의 OPENAI_API_KEY와 사용할 수 있는 OPENAI_MODEL을 설정
.\start.cmd
```

브라우저: http://127.0.0.1:8000/ . 연구자 옵션: http://127.0.0.1:8000/?research=1 .
`start.cmd`가 가상환경·의존성 설치와 프론트엔드 빌드를 수행합니다. `.env`는 Git에 포함하지 않습니다.

계속 켜두는 팀 서버는 `powershell -ExecutionPolicy Bypass -File scripts/start-team.ps1`로 실행합니다. 주소는 http://127.0.0.1:8001/ 이며 계정이나 비밀번호가 필요하지 않습니다.

## 포함된 자료와 실행 흐름

- `tasks/candidates/`: 현재 로컬의 **연습용 1개 + 후보 10개 + 현재 화면의 VERIFY2-M4-A** 스냅샷. 전체 Input·Target, 추가 입력 표, 초기 코드, 의미 Step과 연구자 검증 자료가 포함됩니다.
- 사진과 같은 영화 삼부작 검수 화면은 **VERIFY2-M4-A**를 선택해 시작합니다. 현재 실행에서 생성된 Step·열 자연어 설명도 `tasks/explanations/`에 포함했으며 동일 코드·입출력에만 재사용합니다. 모든 동봉 과제의 초기 검수 설명은 새 API 호출 없이 재현합니다. 세션 ID·사용자 선택·개인 이벤트 로그는 복사하지 않습니다.
- 처음 과제 목록을 읽으면 `.local/pilot/candidates/`에 복사합니다. 기존 로컬 과제는 덮어쓰거나 복구하지 않습니다. `TRACE_TASK_DIR`로 별도 과제 폴더를 지정할 수 있습니다.
- 과제 선택 → 전체 Input·Target 확인 → **저장된 초기 코드·Step 실제 실행** → 검수 → 자연어 수정 → 전체 재실행 → 되돌리기·최종 확정.
- 초기 코드는 재생성하지 않습니다(Wizard of Oz). Step 설명과 자연어 수정은 설정한 모델 API를 사용하므로 API 키가 필요합니다. 배포된 12개 과제의 초기 설명은 모두 포함되어 새 PC에서도 API 호출 없이 검수할 수 있습니다. 수정 후 새 코드 설명과 자연어 수정에는 API가 필요합니다.
- Downloads의 원본 Luna 실험 폴더나 `output/`은 이 과제 실행에 필요하지 않습니다. 출처에 기록된 원본 경로는 실행 의존성이 아닙니다.
- 과제는 선별·개발용이며 본실험 선정과 구분합니다. 오류 해설·참조 코드는 연구자용입니다.

## 현재 화면과 구현 범위

조건 ID는 `ex`, `in-situ`입니다. 동일 실행의 코드·Step·결과·설명을 재사용합니다.

- Ex-situ: Step 자연어 설명, 읽기 전용 코드, 실제 중간 결과. 수정은 하단 입력창.
- In-situ: Step 자연어 설명, 실제 전후 표, 확인된 변화·기여 관계. 현재 코드는 숨김이며, 표 선택 후 근처 수정 버튼으로 요청.
- 표는 처음 최대 5행을 표시하고 펼치면 제한된 높이 안에서 스크롤합니다.
- 자연어 수정은 새 코드를 실행하고 후속 결과를 다시 계산합니다. 실패 시 마지막 성공 결과와 구분합니다. Target 불일치를 자동 수정하거나 참가자에게 오류 위치로 안내하지 않습니다.
- **최근 논의한 ‘두 조건 모두 코드 제공, In-situ의 코드·설명을 데이터 위치에 결합’은 설계 제안이며 아직 구현하지 않았습니다.**

native Python/pandas 실행과 상세 추적은 별개입니다. 함수·lambda·반복·분기 등 허용된 Python을 실행하되 라이브러리·파일/네트워크 접근·실행 자원을 제한합니다. 상세 어댑터가 지원하고 실제 실행과 일치하는 경우에만 셀 출처와 기여 관계를 제공합니다. 나머지는 실제 중간 표를 보여주고 미확인 계보를 만들지 않습니다. 모든 Python/pandas를 지원하지는 않습니다.

## 개발·검증·기록

```powershell
.venv\Scripts\python.exe -m pytest -q
npm.cmd run build
# 개발 시 두 터미널 사용
.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
npm.cmd run dev
```

### 참가자 화면 (web/)

`/`는 Next.js + shadcn/ui로 만든 참가자 화면(`web/`)이고, 기존 Vite 화면은 `/legacy`로 옮겼습니다. 과제 관리, 파일럿 로그, 코드 등록 같은 연구자 도구는 `/legacy?research=1`에서 씁니다. 새 화면에서 `?research=1`을 붙이면 조건 전환과 과제 변경 버튼이 보입니다.

```bash
cd web && npm ci && npm run build   # web/out 생성, FastAPI가 / 에서 제공
TRACE_API=http://127.0.0.1:8000 npm run dev   # 개발 서버, /api는 FastAPI로 전달
```

표 변화 계산·선택·계보 로직은 `src/`의 기존 모듈(`tableChanges`, `tableSelection`, `reviewGroups`, `workflowGraph`, `useTableDrag`)을 그대로 가져다 씁니다. 이 모듈을 고치면 두 화면에 함께 반영됩니다.

`src/`는 기존 React UI, `backend/`는 생성·실행·추적·수정 API, `tests/`는 회귀 검증입니다. 실행 기록은 `.local/sessions/`, 팀 서버 기록은 `.local/pilot/sessions/`에 저장됩니다. 기존 계정·세션·참가자 로그·설명 캐시·API 키는 이 저장소에 포함하지 않습니다. `.venv`, `node_modules`는 각 PC에서 다시 생성합니다. `dist/`에는 현재 서버에서 제공하는 화면 빌드를 함께 포함했으며 소스를 수정하면 `npm.cmd run build`로 갱신합니다.

로그인 없는 개발용 실행이므로 접속자는 개발자 기능도 사용할 수 있습니다. 외부 공유 URL은 신뢰하는 개발자에게만 전달하세요. 기존 인증 코드는 과거 기록/회귀 호환용이며 `TRACE_LEGACY_AUTH=1`을 명시하지 않는 한 옛 접속 파일도 읽지 않습니다. 기본 시작 스크립트는 계정을 생성하지 않습니다.

자세한 전달 안내: [개발 인계](docs/DEVELOPER_HANDOFF.md). 실행·모델 검증 이력: [VALIDATION](evidence/VALIDATION.md), [MODEL_VERIFICATION](evidence/MODEL_VERIFICATION.md). 과거 문서의 ABC·계정 배정·실생성 시작 안내보다 이 README의 현재 상태를 우선합니다.
