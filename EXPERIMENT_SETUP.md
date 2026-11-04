# 사용자 실험 운영

## 참가자 주소와 서버 API

참가자용 주소는 `/in-situ`, `/ex-situ`이다. 두 조건은 같은 백엔드와 같은 설명·수정 LLM을 사용한다. 참가자 노트북에는 키를 넣지 않는다. 기존 서버의 `.env`에 설정한 `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_EXPLANATION_MODEL`을 사용하며 키는 브라우저·로그·내보내기 파일에 전달하지 않는다.

1. 서버 노트북에서 `run-local.cmd`를 실행한다. 기존 실행 중인 서버가 있으면 유지한다.
2. 프런트엔드를 수정한 경우 먼저 `npm.cmd --prefix web run build`를 실행한다.
3. 같은 네트워크에서 진행하면 `run-study.cmd`를 실행하고 `http://서버노트북IP:8003/in-situ`, `http://서버노트북IP:8003/ex-situ`를 공유한다. 방화벽과 네트워크의 장치 간 접속 허용이 필요하다.
4. 외부 인터넷에서 접속하려면 `share-study.cmd`를 실행한다. Cloudflare의 공식 `cloudflared` 실행 파일을 `.local`에 내려받고, 참가자 전용 8003 포트로 임시 HTTPS 주소를 생성한다. 출력된 주소 뒤에 `/in-situ`, `/ex-situ`를 각각 붙인다.

서버와 공유 창을 실험 내내 켜 두고 절전 모드를 해제한다. 임시 터널은 재시작 시 주소가 바뀌므로 참가자 진행 중에 재시작하지 않는다. 브라우저 복원 정보가 주소별로 저장되기 때문이다. 정식 실험에서는 동일한 게이트웨이에 고정 도메인/고정 터널을 연결해 주소를 유지한다. Cloudflare Quick Tunnel의 운영 보장과 사용 조건은 [공식 문서](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)를 따른다.

서버는 연구자의 API 키가 있는 PC에서 실행한다. 참가자 노트북에서는 서버를 실행하거나 레포를 설치하지 않고 주소만 연다. 연구자 PC의 같은 프로젝트 폴더에서 두 터미널을 열어 각각 `run-local.cmd`, `run-study.cmd`를 실행한다. 이미 실행 중이면 중복 실행하지 않는다. 같은 네트워크의 링크는 `ipconfig`의 서버 PC IPv4 주소를 사용하고, 인터넷 공유는 두 번째 창에서 대신 `share-study.cmd`를 실행해 출력된 HTTPS 주소를 사용한다. 실행 창은 실험 중 유지한다. 서버 IP가 바뀌면 LAN 링크도 갱신한다.

8002 포트는 로컬 작업용으로 유지한다. 외부에는 `backend/share.py`의 8003 포트만 연결한다. 이 게이트웨이는 연구자 화면, 기존 과제 선택·등록, 전체 로그 내보내기, 세션 목록, replay와 임의 코드 등록 API를 전달하지 않는다. 참가자별 서버 발급 토큰으로 본인 실험과 세션만 접근하며, 과제·조건 변경도 거부한다. URL만 알아도 다른 참가자의 기록을 열 수 없다. 연구자용 기존 화면은 로컬 `http://127.0.0.1:8002/in-situ?research=1`, `/ex-situ?research=1`에 남아 있다.

## 진행 규칙

- 최초 방문은 시간 제한 없는 기존 **학생 행사 참여 내역 연결** Tutorial(`PILOT4-TRAIN`)이다. 학생 명부와 행사 기록, 기존 코드와 4개 Step을 그대로 사용한다. 입력 확인, Step 이동, 설명 확인, 자연어 수정과 후보 승인·거부를 실제 화면에서 연습한다. 앞서 다른 예제로 생성된 튜토리얼 세션은 새로고침 시 기존 과제로 전환하며 이전 실행·수정 기록은 보존한다.
- **본실험 시작**을 누르면 **T07 → T01 → T03** 순서로 진행한다. 화면에는 원본 과제 번호 대신 **Task 1, Task 2, Task 3**과 남은 시간을 표시한다. 원본 과제 ID와 순서 번호는 로그에 함께 기록한다.
- 이 순서는 `timed-study-v2`이며 실험별 `task_order`로 고정한다. 이전 T01 → T03 → T05 실험은 원래 과제 번호·코드·실행 결과·로그를 보존하고 새 실험과 연결해 보관한다. 이전 버전으로 접속한 참가자는 새로고침 시 새 튜토리얼로 전환된다. 브라우저 미전송 기록도 이전 실험 ID로 저장하며 새 실험의 로그와 섞지 않는다.
- 튜토리얼과 각 본실험 과제의 시작 창에는 제공된 참가자용 PDF의 해당 페이지를 그대로 표시한다. 입력 자료·처리 조건·목표 결과 표를 확인할 수 있으며, 긴 안내는 본문만 스크롤하고 시작 버튼은 하단에 고정한다. 페이지 배정은 튜토리얼 1쪽, Task 1(T07) 4쪽, Task 2(T01) 2쪽, Task 3(T03) 3쪽이다. 원본 파일의 SHA-256과 페이지 배정은 `web/components/trace/task-guides/manifest.json`에 기록한다. 앱에 이미지가 포함되므로 다른 노트북에서 접속할 때 연구자 PC의 Downloads 경로에 접근할 필요가 없다.
- 튜토리얼은 **튜토리얼 시작**을 눌러 연습에 진입하며, 같은 실험에서 확인한 안내는 새로고침 시 반복하지 않는다. 시간 제한은 없다. 본실험은 실행과 설명 준비가 끝나면 안내와 **시작** 버튼을 표시한다. 안내 이미지가 로드돼야 시작할 수 있으며, 참가자가 시작 버튼을 눌러야 서버에서 **900초**를 부여한다. 안내를 읽거나 시작 전 새로고침해도 시간이 흐르지 않는다. 준비 중의 모델 대기 시간은 제한 시간에 포함되지 않는다. 과제 시작 후 수정·설명 대기 시간은 포함된다. 화면 하단의 **과제 안내**를 펼치면 동일한 PDF 페이지를 다시 볼 수 있다.
- **과제 종료**를 누르면 **확인/취소** 창이 열린다. 확인해야 종료하며 취소나 Escape를 누르면 같은 과제를 계속한다. 확인 창이 열린 동안에도 타이머는 흐르며 시간 만료 시에는 자동 종료한다.
- 과제 사이에는 **60초** 휴식을 안내하지만 **Task 2 시작 / Task 3 시작**을 바로 눌러 건너뛸 수 있다. 다음 과제에서도 별도 시작 창의 시작 버튼을 눌러야 타이머가 작동한다. 마지막 과제 이후에는 완료 화면이다.
- 브라우저 새로고침·백그라운드 전환·연결 끊김으로 시간이 초기화되지 않는다. 서버 기준 종료 시각과 서버/브라우저 시계 차이를 사용한다. 오프라인 중 만료되면 재접속했을 때 과제를 종료하고, 참가자가 휴식 화면에 도달한 때부터 휴식 시간을 준다.
- 제한 시간이 끝나거나 수동 종료된 과제는 수정할 수 없다. 진행 중이던 후보 생성·승인도 결과를 확정하기 전에 종료 상태를 다시 검사한다. 승인되지 않은 후보는 최종 확정 코드에 포함하지 않는다.
- 여러 탭에서 같은 참가자를 복원할 경우 phase/index 조건부 요청으로 종료·시작의 중복 적용을 막는다. 기존 파일 기반 세션 저장소와 동일하게 **단일 서버 worker**로 실행한다. 참가자가 다른 기기·다른 브라우저·시크릿 창으로 옮기면 자동으로 동일 인물이라고 추정하지 않는다.

## 수집 기록

범위는 이 웹 앱에서 관찰 가능한 동작이다. 다른 앱, 운영체제 전체 입력, 앱 밖의 클립보드, 카메라·마이크·시선은 수집하지 않는다. 포인터는 500ms 간격, 스크롤은 180ms 정지 후 기록한다. 브라우저가 강제 종료되기 직전 아직 전달하지 못한 이벤트의 완전한 수집은 보장할 수 없다.

| 라벨 | 동작과 기록 내용 |
| --- | --- |
| `study.*`, `tutorial.*` | 등록·복원·연습 시작/종료·전체 완료 |
| `task.preparing/started/finished` | 준비, 실제 시작과 deadline, 종료 사유 `participant/timeout`, 종료 시 확정 run·후보 ID |
| `task.start_prompt/start_confirmed`, `task.finish_prompt/finish_cancelled/finish_confirmed` | 시작 안내·시작 버튼, 종료 확인창 열기·취소·확인 |
| `instructions.open/close/loaded/failed`, `tutorial.instructions_confirmed` | 시작 전 안내 창 열기·닫기, 페이지 이미지 로드·실패, 튜토리얼 안내 확인. 과제 ID·원본 PDF 해시·페이지 정보를 함께 기록. 과제 진행 화면 하단의 안내 탭은 제공하지 않음 |
| `break.started/completed` | 휴식 시작과 종료, 건너뛰기 여부·실제 휴식 시간·남은 시간 |
| `workspace.ready`, `view.context` | 현재 session/run/코드 버전, Step, 입력·결과 테이블, 후보 관찰 여부, 코드 줄 범위 |
| `view.step/input/table/output` | 이전·다음 관찰 대상, 입력 표 이름, 최종 결과 선택 |
| `transformation.open/close` | 클릭한 생성·변환·삭제 종류, 열·행, 실제 연결된 연산 ID/줄 범위, 열린 시간 |
| `explanation.visible/hidden` | 두 조건에서 개별 연산 설명이 화면에 노출된 시간, 연산 ID·줄 범위·표시 영역. 화면 노출 기록이며 실제 읽기나 이해 여부를 뜻하지 않는다. |
| `revision.submitted/approve/deny/undo` | 자연어 수정 전문, 대상 Step, 기준 실행, 후보 ID, 승인·거부·되돌리기 요청 |
| `workspace.action_*` | 작업 시작/완료/실패, 소요 시간, 오류 메시지 |
| `ui.click/input/key/focus/blur` | 요소 역할·라벨·클래스, 클릭 좌표, 앱 입력 값, 조작 키, 초점 변화. 입력 전문과 붙여넣은 텍스트는 기록되며 비밀번호 입력은 제외한다. |
| `ui.pointer/scroll/resize/panel_resize` | 포인터 위치 표본, 영역별 스크롤과 크기, 패널 조절 전후와 입력 방식 |
| `ui.selection/copy/paste` | 앱에서 선택·복사·붙여넣은 텍스트와 대상 요소 |
| `page.enter/hide/visibility/focus/blur/heartbeat` | 새 진입/새로고침 구분, 화면 이탈·활성 상태, 15초마다 비활동 시간·온라인 상태·미전송 건수 |
| `network.online/offline`, `client.error/rejection` | 연결 상태와 브라우저 오류 |
| `http.completed/failed` | 서버 API 경로·상태·처리 시간·요청 ID, 권한·시간 만료 등의 거부와 서버 오류 종류 |
| `backend.event` | 원래 백엔드 이벤트 이름과 상세 데이터: 수정 후보 생성·실행·실패·승인·거부, 설명 캐시·실패 등 |
| `backend.snapshot` | 변경 API 처리 후 확정 run과 후보의 코드·실제 결과·설명 전체. 거부로 후보가 폐기되어도 앞선 스냅샷으로 분석 가능 |
| `llm.completed` | 코드 생성·수정/설명/설명 보정 용도, 모델, 응답 ID, 응답 상태, 제공된 token usage, 정확한 프롬프트와 출력 텍스트. 인증 헤더·키와 비공개 추론 내용은 제외 |

공통 필드는 이벤트 UUID, 안정적인 `label`, 한글 `action_label`, 서버 수신 시각, 참가자 가명 ID, 실험 ID, 조건, phase, 과제 순서/원본 ID, session ID다. 브라우저 이벤트에는 클라이언트 시각, 페이지별 ID와 순번, 단조 증가 시계, 당시 관찰 맥락을 추가한다. 서버 수신 시점의 phase와 생성 당시 클라이언트 `context.phase`는 연결 지연 시 다를 수 있으므로 함께 해석한다. 서버/클라이언트 이벤트를 통합할 때 이벤트 순서와 시간, session/run/후보 ID를 함께 사용한다. 범용 클릭과 도메인별 이벤트는 하나의 행동을 서로 다른 수준에서 기록할 수 있다.

`server_at`은 서버에서 기록한 현재 UTC 시각, `client_at`은 브라우저에서 행동이 발생한 UTC 시각이다. `task.started.data.started_at`과 `deadline`은 실제 시작 버튼을 누른 뒤 서버가 확정한 Unix 시각이며, `task.finished.data`에는 `started_at`, `ended_at`, `detected_at`, 종료 사유가 들어간다. 시간 초과를 나중에 감지해도 실제 종료 시각과 감지 시각을 구분한다. 브라우저 로그의 수신 시각은 약 2초의 전송 간격이나 연결 지연만큼 행동 시각보다 늦을 수 있다.

브라우저 이벤트는 IndexedDB 전송 대기열에 보관하고 2초마다 배치 전송한다. 재연결·새로고침 시 미확인 이벤트를 재전송하며 서버는 `(experiment_id, event_id)`로 중복을 제거한다. 페이지 이탈 시에는 keepalive 전송을 시도한다. IndexedDB를 사용할 수 없는 브라우저에서는 메모리 대기열로 실시간 전송하므로 실험용 브라우저에서 영구 저장소를 허용한다.

## 저장과 내보내기

- 진행 상태: `.local/experiments/<experiment-id>.json`
- 행동 로그: `.local/experiments/events.sqlite3` (WAL, 트랜잭션 저장)
- 실행 코드·모든 확정 버전·입력·중간 결과·설명·백엔드 원래 이벤트: `.local/sessions/<session-id>.json`
- 브라우저에는 참가자별 접속 토큰과 미전송 로그만 보관한다. API 키는 보관하지 않는다.

연구자가 서버에서 다음을 실행한다.

```powershell
.\.venv\Scripts\python.exe scripts/export_experiment.py --output .local/experiment-export
# 특정 참가자 실험만:
.\.venv\Scripts\python.exe scripts/export_experiment.py --experiment-id <실험-ID> --output .local/one-participant
```

`participants.json`, `events.jsonl`, Excel에서 읽을 수 있는 UTF-8 BOM `events.csv`, `sessions/`가 생성된다. 진행 상태의 접속 토큰 해시를 제외하고, 별도 과제 입력이나 API 키 파일은 복사하지 않는다. `TRACE_DATA_DIR`로 세션 폴더를 변경한 경우 `--data-dir`에는 그 상위 폴더를 지정한다. 실험 자료와 내보내기 파일은 Git에 포함하지 않는다. 사전 점검 기록은 환경의 `qa:true`로 구분할 수 있다.

CSV에는 원본 시각을 유지하면서 `server_at_kst`, `client_at_kst`, `task_started_at_utc`, `task_started_at_kst`, `task_ended_at_utc`, `task_ended_at_kst` 열을 함께 제공한다. `_kst`는 한국 시간(`+09:00`)이다. 실제 행동의 순서는 `client_at`과 페이지 순번·단조 시계를, 과제 시간 제한과 시작·종료는 서버가 확정한 시각을 기준으로 분석한다. 원본 JSONL과 세션 파일에도 시각·코드·결과가 보존된다.

## 검증

`tests/test_experiment.py`에서 고정 과제 순서, 기존 학생 행사 튜토리얼 복원과 이전 기록 보존, 명시적 시작 전 시간·수정 차단, 서버 시간 복원, 만료 후 수정 거부, 휴식 건너뛰기, 중복 종료 방지, 참가자 분리, 로그 중복 제거·내보내기, 공개 게이트웨이 범위를 검증한다. 기존 개별 변환·설명·수정 후보 검증도 유지한다.
