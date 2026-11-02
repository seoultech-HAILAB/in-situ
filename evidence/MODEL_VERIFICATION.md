# 모델 식별자와 실호출 검증 상태

## Input·Target만의 초기 생성과 수정 — 2026-11-01

설정된 `gpt-6-luna`를 실제 Responses API로 호출했다. 별도 작성한 합성 확인용 Input·Target만 사용했으며 기존 파일럿 과제나 팀원 로그는 보내지 않았다. 초기 요청에는 과제별 자연어 요구사항·저장된 P0 코드가 없다. 설명 API는 기존 코드/Step 전용 전송 방식을 유지한다.

- 첫 생성 1회는 모델이 준 임시 Step ID가 신규 ID 정책과 맞지 않아 실행 대응 검증에 실패했다. 초기 Step ID를 서버에서 발급하도록 정리하고, 의미 Step 지침을 보완했다. 모델 코드의 규칙 기반 교체는 하지 않았다.
- 이후 API 4회(초기 코드·Step 생성, 초기 설명, 자연어 수정 패치, 수정 설명)가 모두 완료됐다. 모델이 2개 의미 Step을 생성했다. 실제 실행과 중간 표를 확인하고 A/C 전환이 동일 실행을 유지함을 확인했다.
- 마지막 Step에 지역 내림차순 정렬을 요청하여 수정·전체 재실행·결과 순서 변경과 되돌리기를 확인했다. Target과 달라져도 자동으로 복구하지 않는다. 이 비교는 연구자 검증이며 참가자 화면에는 나타나지 않는다.
- 총 실제 호출은 **5회**이며 처음 실패한 생성 호출도 포함한다. 성공 흐름 보고서: `.local/prototype-validation/report.json`. 검증 세션은 `.local/prototype-validation/sessions`에 분리했다.
- 원래 실호출에서 공통 추적이었던 집계는 이후 실제 반환형 추적을 보완해 저장 코드만 재실행했다. 보고서의 `post_adapter_replay`는 추가 LLM 호출 없는 추적 검증이다.

`scripts/verify_prototype_live.py`는 새 실호출을 수행하는 검증 도구다. 표 하나의 기능 검증이며 본실험 과제 선정·일반 생성 정확도·모든 Step 분할 품질의 평가가 아니다. 기존 코드만 받아 별도로 Step 주석을 생성하는 API는 이번 검증 범위에 포함하지 않았다. 아래 기록은 이전 날짜의 상태다.

## Ex-situ 설명 API — 2026-10-30

gpt-6-luna의 실제 설명 요청을 확인했다. 현재 코드 전용 경로에서 과제 01의 9개 Step 제목·한국어 설명 생성 1회가 성공했다. 초기 시험의 중간 관측 포함 요청 1회도 성공했으나 해당 전송 방식은 운영에 사용하지 않는다. 전체 후보 일괄 요청은 실행하지 않았다. 다른 과제는 A/B 진입 시 코드만 전송해 설명을 준비한다. [전송 범위·캐시·검증 상세](../docs/LLM_EXPLANATIONS.md)를 참고한다.

## 실제 댓글 수정 호출 — 2026-10-30

- 서버에 사용자가 설정한 API 키로 gpt-6-luna / reasoning_effort=low의 Responses 수정 호출 **1회 성공**을 확인했다. 새로운 초기 코드 생성과 기존 코드의 Step 주석 API 실호출은 아직 미검증이다.
- 독립 QA 세션에서 실제 P0 기반 CASE-03 v1의 Director_ID 결측 셀을 선택하고, 전체 열 결측 검사로 변경하되 정렬과 Title 출력을 유지하라는 댓글을 보냈다. 모델은 첫 Step의 dropna(subset=...)를 dropna()로 수정했다.
- v2는 mode=api로 저장됐다. 첫 Step 코드만 바뀌었고 후속 정렬·열 선택 코드는 같았다. 전체 재실행에서 출력 10→8행·전체 Target 일치, 후속 결과·경로 변경, 기존 Step ID 유지를 확인했다.
- 초기 v1은 보존된 P0 프로그램의 관찰용 코드이며 이번에 새로 생성한 코드가 아니다. 이 한 번의 수정 성공을 초기 생성·전체 과제·자연어 수정의 일반 정확도로 해석하지 않는다. 새 API 요청 1회와 기존 P0 호출 기록도 구분한다.
- 사용자 작업과 별도 세션 842f4e06-4544-46a6-8d45-f02da417017f를 사용했다. 원본 입력·Target·선택 값이 포함된 검증 JSON과 스크린샷은 로컬 evidence/.local 폴더에 보관하며 자격정보를 포함하지 않는다.

아래는 2026-10-29 당시의 미연결 기록이다.

확인일: 2026-10-29.

- 사용자 명칭: GPT6 Luna.
- [OpenAI 공식 모델 목록](https://developers.openai.com/api/docs/models)의 표기: GPT-6 Luna, API 식별자 gpt-6-luna.
- [모델 가이드](https://developers.openai.com/api/docs/guides/latest-model)와 [Responses 구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)도 확인했다.
- 기본값은 위에서 확인한 식별자다. OPENAI_MODEL로 교체 가능하며 OPENAI_REASONING_EFFORT와 OPENAI_BASE_URL도 설정한다.
- 검증 시 .env 및 OPENAI_API_KEY가 없었고 health의 api_configured=false였다. [관찰 상태 JSON](model-status-v3.json)에 저장했다. 이 값은 키 존재 여부이며 인증 성공 검사가 아니다.
- 실제 네트워크 모델 생성/수정 요청은 실행하지 않았다. 계정 접근권한·모델 응답 품질·실제 코드 생성 성공률은 미검증이다.
- Responses HTTP 요청/응답 계약, 선택 맥락 전달, 구조화 응답 적용은 대역으로 테스트했다. 사전 작성 데모는 실호출 검증에 포함하지 않는다.

자격정보가 준비되면 서버를 재시작하고 확장 예제의 Input/Target/추가 표로 실제 초기 생성, 선택 Step 수정, 전체 구조 수정, 범위 위반·미지원 연산 실패를 검증해야 한다. 원본·목표·수정 맥락은 설정된 모델 API에 전송된다. 실행 자식에는 키와 Target을 전달하지 않는다.

V3 추가 확인: 코드+Step 1회 생성 및 기존 코드의 메타데이터 주석 API를 구현했다. 기존 코드 주석은 원문을 변경하지 않으며 별도 요청 1회다. 실제 모델 호출은 여전히 미검증이고, 주석 계약은 HTTP 대역으로만 검증했다.
