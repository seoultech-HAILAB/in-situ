# Ex-situ 실제 LLM 설명

A/B 설명은 실행 추적기의 summary 문장 대신 실제 API로 작성한 한국어 제목·설명을 사용한다. 전체 실행 코드와 Step 경계·의존 단계 번호를 바탕으로 처리 대상·조건·계산·정렬·형식 변환을 자연어로 풀어쓴다.

## 모델과 전송 범위

- 기존 OPENAI_API_KEY/OPENAI_BASE_URL을 사용한다. OPENAI_EXPLANATION_MODEL이 있으면 사용하고, 없으면 기존 OPENAI_MODEL을 유지한다.
- [공식 Structured Outputs 형식](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)을 사용한다. 서버는 실제 Step 번호·개수·순서를 검사하고 코드 문법을 설명으로 반환한 응답을 거절한다.
- 현재 운영 요청은 **실행된 코드와 Step 대응만** 전송한다. Input/중간 표/Output의 값, Target, 요구사항, 오류 해설, lineage는 전송하지 않는다. 실제 행수나 범주를 추측하지 않도록 지시한다.
- 초기 확인에서 코드와 일부 중간 관측을 포함한 단일 호출이 1회 성공했다. 14개 후보의 중간 표 포함 일괄 요청은 자동 승인 검토에서 외부 전송 범위를 이유로 거부됐다. 이후 코드 전용으로 축소한 단일 호출 1회가 실제 성공했다. 거부된 일괄 전송을 우회 실행하지 않았다.
- 현재 프롬프트 버전은 executed-code-korean-prose-v2다. 실제 gpt-6-luna 호출은 과제 01의 9개 Step을 확인했다. 다른 과제는 A/B 실행을 열 때 설명을 생성한다. 전체 14개 설명 사전 생성 성공으로 보고하지 않는다.

## 실행·캐시·실패

POST /api/sessions/{sid}/explanations를 추가했다. 프론트엔드는 A/B 세션 표시 전에 해당 실행의 설명을 준비한다. 기존 A/B 세션도 새로고침하면 적용된다. C의 표현·lineage와 기존 자연어 수정 방식은 유지한다.

설명은 run_id에 연결하고 코드·Step·실제 중간 결과의 로컬 fingerprint 및 모델/프롬프트 버전으로 캐시한다. fingerprint에 사용하는 테이블 값은 로컬에만 남는다. 런타임 UUID가 다른 동일 초기 실행은 설명을 재사용하며, 수정 후 코드/중간 데이터가 달라지면 새 설명을 준비한다. API 호출 중 실행 버전이 바뀌면 409로 거절하며 오래된 설명을 새 결과에 붙이지 않는다. 되돌리기는 해당 실행의 설명을 재사용한다.

설명 모델은 코드를 수정하거나 정답/오류를 판정하지 않는다. LLM 문장의 의미 정확성을 완전히 보장하는 것은 아니다. 실패는 실행 실패와 분리하며 추적기의 코드식 문장으로 몰래 대체하지 않는다. ‘설명 다시 불러오기’로 재시도할 수 있다. A/B review_started는 설명 준비 이후 기록한다.

캐시는 .local/pilot/explanations/에 저장한다. 모델·프롬프트 버전·응답 ID·usage·설명을 보관하고 세션에 explanation_meta와 step_explanations_ready/failed 이벤트를 남긴다. 설명 API와 코드 생성/수정 API 호출을 별도로 기록한다. 단일 관리 도구 `scripts/prewarm_explanations.py --task R500-001`은 참가자 세션을 생성하지 않는다.

검증: 코드 전용 실제 API 호출 1회 성공, payload·캐시 재사용·실행 버전·실패 분리·Step 대응 테스트 및 기존 Ex-situ/배정 테스트 총 13개 통과, 웹 빌드 통과. 브라우저 확인은 수행하지 않았다.
