# P0 Synth 데이터와 실제 Luna 코드 검토

확인일: 2026-10-30. 복구된 P0 결과 번들, 기존 158개 과제 대응표, 원본 Synth manifest·Input·Target을 대조했다. 원본 파일은 수정하지 않았고 새 모델 호출은 0회다.

## 실제 P0 기록에서 확인한 내용

| 기술평가 150개 | 확인 결과 |
|---|---:|
| 실행 완료 | 141 |
| 정답 | 72 |
| 실행 완료·오답 | 69 |
| 실행 실패 | 9 |
| model_calls=1 | 150 |
| 보존된 program.py | 149 |

출처는 `Luna_P0_results_dev8_technical150_20261027T171038Z/luna_python_technical150_20261027T150459Z/results.json` 및 task별 program.py·output_table.json·prompt.json이다. 기록된 API 모델 식별자는 gpt-6-luna다. 개발 8개는 기술평가 150개와 분리했다. 별도 L0/L1 코드를 P0로 대신 사용하지 않았다.

중요한 차이: 원본 P0는 **Input 앞 20행 + 전체 메타데이터 + Target 스키마**를 프롬프트에 제공했다. **Target 값은 제공하지 않았다.** 150개 prompt.json 모두에서 이 조건과 Input 20행 표기를 확인했다. 실행에는 전체 Input DataFrame을 사용했다. 현재 앱의 Input + Target 전체 기반 생성 조건과 다르므로 P0의 48%를 현재 조건의 생성 정확도로 직접 사용하지 않는다.

## 데이터 선별

150개 모두 Synth-Spider test 과제다. Input/Target 전체를 데이터 전용 제한 로더로 읽었으며, 입력 수는 1개 101과제·2개 34과제·3개 14과제·4개 1과제다.

| 1차 구조 검사 | 수 |
|---|---:|
| 현재 행/열·열 라벨·중첩 셀 제약에 맞는 후보 | 134 |
| 작은 표 후보 | 83 |
| 작은 표 후보 중 P0 오답 표기 | 41 |
| 이 중 원본 실행 완료·오답 검증 대상 | 40 |
| 현재 앱에서 원본 저장 출력과 동일하게 재현 | 31 |

작은 표는 입력 각각 20행·8열 이하, Target 12행·8열 이하다. 구조상 보류 사유는 중복 열 라벨 7개, 현재 CSV로 손실 없이 전달하기 어려운 중첩 셀 4개, 행/열 제한 6개다. 사유가 겹쳐 고유 제외는 16개다. 134개는 최종 실험 적합성이나 전체 프로그램 실행을 확인한 수가 아니다.

40개 검증 대상 중 9개는 선행 0·혼합 값 타입·빈 문자열 등 CSV 왕복의 충실성 검사에서 보류했다. 이를 원래 P0 실행 실패로 다시 분류하지 않는다. 처음 막혔던 datetime 포맷의 내부 import 호환을 보완하고 strftime/strptime을 검증했으며 사용자 time 직접 import·파일·네트워크 제한은 유지했다. 나머지 31개는 코드의 연산을 변경하지 않고 입력 바인딩과 transform 호출만 붙여 원본 저장 출력과 일치함을 확인했다. 전부 현재 Target과는 달랐다. 31개 전부의 오류 원인·과제 적합성을 확정한 것은 아니다.

참조 tol_ops에는 Join 69회, GroupBy 49회, Filter 61회, Sort 50회, Deduplicate 54회 등이 있었다. 이는 데이터셋의 참조 연산 분포이며 Luna 생성 코드 분포나 현재 앱의 지원율이 아니다.

## 제외한 기준 불일치 사례

`spider_c505dea4`는 질문이 ERP_kW > 150 또는 < 30인 송신기를 요구하지만 저장 Target에는 조건 밖 행까지 7개가 들어 있다. 유효한 조건 일치 행은 4개이며 실제 Luna 코드도 해당 조건과 송신기 결측 제외로 4개를 출력했다. 이 경우 Target 불일치를 그대로 모델의 논리 오류로 취급하기 어렵다. 참조 tol_ops에도 조건 필터가 빠져 있어 검수 과제로 제외했다. 이 한 사례로 전체 benchmark의 문제 비율을 추정하지 않는다.

## 기본 웹 후보: 실제 P0 코드 3개

| 후보 | 원본 task | 관찰된 Target 불일치 | 초기/Target 행 수 | 검수 Step |
|---|---|---|---|---:|
| CASE-01 지역 조건 조회 | spider_bb0df1c0 | InvalidDistrict 이름 정제 누락 | 6 / 4 | 2 |
| CASE-02 지역의 중심 도시 | spider_c449ff01 | Region_ID 중복 처리 누락 | 9 / 7 | 2 |
| CASE-03 프로그램 연도순 조회 | spider_528b8b8e | Start_Year·Title만 결측 검사하여 다른 열이 비어 있는 행 포함 | 10 / 8 | 3 |

세 후보 모두 원래 Input·Target 전체를 유지했고 전 단계 상세 추적이 확인됐다. 보존된 response.txt와 program.py의 구문 트리 일치도 확인했다(응답의 Markdown 코드 울타리만 제거). 최초 잘못된 출력은 원본 P0 프로그램의 출력과 같다. 별도 mock 오류를 추가하지 않았다. 원본 스키마만으로는 명확하지 않았던 정제 규칙과 동률 정렬 정책은 **검수 과제의 고정 설명**에 명시했다. 이 설명은 원래 P0 프롬프트와 같지 않으므로 당시 모델이 명시된 정제 요구를 무시했다고 주장하지 않는다.

원본은 `transform(tables)` 함수라 그대로 실행하면 함수 전체를 한 관찰 단계로만 수집한다. 따라서 코드 관찰용 도구가 제한된 직선형 함수에 대해 입력 바인딩, 함수 본문 펼치기, 로컬 변수 SSA 이름, 단일 사용 mask 대입, loc 행/열 및 연쇄 호출의 관찰 경계를 구조화한다. 조건·컬럼·정제 규칙·정렬 방향을 추가하거나 고치지 않는다. **화면 코드는 원본과 바이트 단위로 같지 않다.** 원본 코드와 저장 출력은 별도 보존하며 변경 코드의 출력이 원본과 동일해야 후보로 채택한다.

지원하지 않는 제어 흐름·동적 tables 접근·in-place 대입 등을 임의 변환하지 않는다. 이것을 모든 Python 함수의 자동 의미 분해나 LLM이 제안한 Step이라고 보고하지 않는다. Step은 관찰된 DataFrame 변화와 구문 범위를 묶고 전체 코드 대응을 검증한 결과다. 원본 줄 대응은 연구자 provenance에 저장한다.

정상 참조 코드는 연구자가 정제 누락을 보완해 작성했다. 선택 Step만 수정한 후 전체 재실행하여 전체 Target 일치, 기존 Step ID 유지, 코드가 같은 후속 단계의 결과·기여 경로 갱신을 확인했다. 원본 P0 오류가 Target을 보고 자동 수정된 채로 초기 화면에 올라가지 않는다.

## mock 보조 자료와 참가자 표시

원본 복구 전 임시 작성한 SYN-01…05는 모두 초기 실행 오답·수정 후 전체 정답을 확인했으나 현재는 `enabled=false`로 기본 목록에서 분리했다. 실제 P0 코드를 확보했으므로 이를 Luna 결과로 대체하지 않는다. 향후 오류 종류를 통제하는 내부 시험에서만 별도 출처를 표시하고 사용할 수 있다.

팀 계정의 **연구 설정 → P0 synth 과제 후보**에서 CASE-01…03을 불러온다. 연구자에게 실제 P0 기반과 관찰용 구조화 여부를 표시한다. 참가자는 후보 목록·출처·오류 주석·참조 코드 API에 접근하지 못하며 중립 ID, 고정 과제 설명, Input/Target과 실제 실행만 받는다.

**참조 코드로 새 세션**은 별도 연구자 점검이다. 초기 실행을 덮어쓰거나 참가자 자연어 수정 성공으로 집계하지 않는다. 참가자 수정 방법은 자연어 요청이다. 후속 검증에서 실제 gpt-6-luna 댓글 수정 1회로 CASE-03의 선택 Step 수정과 전체 Target 일치를 확인했다. 새로운 초기 생성과 Step 주석 실호출은 아직 미검증이다. [실호출 기록](../evidence/MODEL_VERIFICATION.md)을 참고하며 작성한 참조 수정과 실제 모델 수정은 구분한다.

## 파일과 재현

원본 데이터·생성 fixture·모델 프로그램은 GitHub에 커밋하지 않는다. 관리자 PC의 `.local/pilot/candidates/CASE-01.json` 등에 저장한다. `.local/pilot/candidates/exports/CASE-01/`에는 원본 바이트를 보존한 `original_luna.py`, 관찰용 `initial_observed.py`, 연구자 `reference.py`, Input/Target CSV·Step JSON·연구자 기록이 있다. source hash와 원본 출력 hash도 기록한다.

분석 inventory와 전체 원본 감사 결과는 `.local/p0_synth/inventory.json`, `original_program_audit.json`, `original_summary.json`에 있다. 표본·실행 여부·바인딩/CSV 한계와 실제 P0 오류를 구분한다.

```powershell
.\.venv\Scripts\python.exe scripts/analyze_p0_synth.py --data-root <autoprep_publish> --p0-matrix <TASK_SUCCESS_MATRIX_158.csv> --p0-root <복구된P0상위폴더> --out .local/p0_synth
.\.venv\Scripts\python.exe scripts/audit_p0_programs.py --inventory .local/p0_synth/inventory.json --run-root <기술평가150폴더> --out .local/p0_synth
.\.venv\Scripts\python.exe scripts/build_p0_candidates.py --inventory .local/p0_synth/inventory.json --run-root <기술평가150폴더> --out .local/pilot/candidates
```

현재 3개는 누락된 정제 규칙을 검수하는 우선 파일럿 후보다. 오류 종류가 넓게 분포한다고 보지 않는다. 정상 과제 포함, 행·열 수는 같고 셀 값만 다른 사례, 문자열/날짜/조인·집계 오류의 추가 선정, 조건 배정과 난도는 후속 pilot에서 결정한다. 정식 과제 확정이나 사람 pilot 완료를 뜻하지 않는다.

검증: 전체 회귀 테스트 100개와 TypeScript/Vite 빌드가 통과했다. 이 수치와 별도로 실제 원본 31개 재현 및 선택 3개 원본/관찰/수정 코드 실행을 수행했다. 브라우저·공유 주소 점검 기록은 관리자 PC에 보관한다.
