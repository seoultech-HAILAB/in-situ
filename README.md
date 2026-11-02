# TRACE — 테이블 변환 검수 프로토타입

현재 구현을 다른 개발자가 실행·수정하기 위한 저장소입니다. **로그인 없이 접속**합니다.

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
- 사진과 같은 영화 삼부작 검수 화면은 **VERIFY2-M4-A**를 선택해 시작합니다. 현재 실행에서 생성된 Step·열 자연어 설명도 `tasks/explanations/`에 포함했으며 동일 코드·입출력에만 재사용합니다. 이 과제의 초기 검수 설명은 새 API 호출 없이 재현합니다. 세션 ID·사용자 선택·개인 이벤트 로그는 복사하지 않습니다.
- 처음 과제 목록을 읽으면 `.local/pilot/candidates/`에 복사합니다. 기존 로컬 과제는 덮어쓰거나 복구하지 않습니다. `TRACE_TASK_DIR`로 별도 과제 폴더를 지정할 수 있습니다.
- 과제 선택 → 전체 Input·Target 확인 → **저장된 초기 코드·Step 실제 실행** → 검수 → 자연어 수정 → 전체 재실행 → 되돌리기·최종 확정.
- 초기 코드는 재생성하지 않습니다(Wizard of Oz). Step 설명과 자연어 수정은 설정한 모델 API를 사용하므로 API 키가 필요합니다. 초기 설명 캐시가 없는 새 PC에서도 설명 호출이 발생합니다.
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

`src/`는 React UI, `backend/`는 생성·실행·추적·수정 API, `tests/`는 회귀 검증입니다. 실행 기록은 `.local/sessions/`, 팀 서버 기록은 `.local/pilot/sessions/`에 저장됩니다. 기존 계정·세션·참가자 로그·설명 캐시·API 키는 이 저장소에 포함하지 않습니다. `.venv`, `node_modules`는 각 PC에서 다시 생성합니다. `dist/`에는 현재 서버에서 제공하는 화면 빌드를 함께 포함했으며 소스를 수정하면 `npm.cmd run build`로 갱신합니다.

로그인 없는 개발용 실행이므로 접속자는 개발자 기능도 사용할 수 있습니다. 외부 공유 URL은 신뢰하는 개발자에게만 전달하세요. 기존 인증 코드는 과거 기록/회귀 호환용이며 `TRACE_LEGACY_AUTH=1`을 명시하지 않는 한 옛 접속 파일도 읽지 않습니다. 기본 시작 스크립트는 계정을 생성하지 않습니다.

자세한 전달 안내: [개발 인계](docs/DEVELOPER_HANDOFF.md). 실행·모델 검증 이력: [VALIDATION](evidence/VALIDATION.md), [MODEL_VERIFICATION](evidence/MODEL_VERIFICATION.md). 과거 문서의 ABC·계정 배정·실생성 시작 안내보다 이 README의 현재 상태를 우선합니다.
