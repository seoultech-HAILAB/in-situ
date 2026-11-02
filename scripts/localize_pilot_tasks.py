"""Faithful Korean task descriptions; preserve original prompts and frozen P0 code."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DESCRIPTIONS={
1:'각 학회 ID에 대해 학회 이름, 개최 연도, 참가자 수를 출력하세요.',
2:'동력 장치 유형별 도심 연비와 고속도로 연비의 평균을 출력하세요.',
3:'평균 대출 금액보다 많은 학자금 대출을 받은 학생의 인적 사항과 상세 정보를 출력하세요.',
4:'모든 유화 작품을 제작 시기순으로 정렬하고 작품 ID, 소장 위치, 제목을 출력하세요.',
5:'주문별 주문 ID, 주문 날짜, 결제 총액을 출력하세요.',
6:'각 행성의 이름과 전체 배송 건수를 출력하세요.',
7:'시험의 전체 개수를 구하세요.',
8:'TV 프로그램의 이름과 최초 방영일을 출력하세요.',
9:'국적별 고객 수를 구하고 국적과 고객 수를 출력하세요.',
10:'모든 차량의 연간 연료비에 대해 최솟값, 최댓값, 평균을 구하세요.',
11:'고객별 이름, 고객 ID, 주문 건수를 출력하세요.',
12:'가격이 최고가가 아닌 모든 제품의 색상, 설명, 크기를 출력하세요.',
13:'해당 연도 순위가 3위 이내인 선수의 수를 구하세요.',
14:'지역 인구의 평균을 구하세요.',
15:'회의 ID별 참석 직원 수를 구하세요.',
16:'고객 주문의 총 건수를 구하세요.',
}


def main():
    for number,text in DESCRIPTIONS.items():
        file=ROOT/'.local/pilot/candidates'/f'R500-{number:03}.json'
        c=json.loads(file.read_text(encoding='utf-8-sig'))
        c.setdefault('description_original',c['description'])
        c['description']=text;c['participant_description']=text
        c['description_locale']='ko';c['description_translation']='faithful-original-question-v1'
        temp=file.with_suffix('.tmp');temp.write_text(json.dumps(c,ensure_ascii=False),encoding='utf-8');temp.replace(file)
    print('Localized 16 descriptions; original code, tables and English prompts preserved.')


if __name__=='__main__':main()
