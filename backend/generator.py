"""Public generation interface and explicit, non-LLM demo fixtures."""
from .generation import Generator, OpenAIGenerator, Proposal, StepSpec, Change, GRAMMAR, DEFAULT_MODEL

DEMO_INPUT = '''order_id,region,status,quantity,price
O-101,서울,완료,2,10000
O-102,서울,완료,3,10000
O-103,부산,취소,4,15000
O-104,부산,완료,2,15000
O-105,서울,완료,1,20000
O-106,부산,완료,5,10000
O-107,서울,완료,4,5000
O-108,부산,대기,3,12000
'''
DEMO_TARGET = '''region,total
부산,80000
서울,70000
'''
DEMO_REQUIREMENTS = '완료 주문 중 수량이 2 이상인 주문의 지역별 매출 합계를 구해주세요. 매출은 수량 × 단가입니다.'


def demo_code(correct=False):
    op = '>=' if correct else '>'
    return f'''s1 = input_df.loc[(input_df['status'] == '완료') & (input_df['quantity'] {op} 2)].copy()
s2 = s1.assign(amount=s1['quantity'] * s1['price'])
result = s2.groupby(['region'], as_index=False, dropna=False).agg(total=('amount', 'sum'))'''


def revise_demo(code, request):
    # Deliberately NOT an LLM: a small documented set of sample revisions.
    if any(word in request for word in ('2인', '2도', '2 이상', '2인 주문', '정확히 2', '2를 포함', '2인 행')):
        return Proposal(code=code.replace("['quantity'] > 2", "['quantity'] >= 2"),
                        assumptions=['데모 규칙: 수량의 > 2를 ≥ 2로 변경했습니다.'])
    if '평균' in request:
        return Proposal(code=code.replace("'sum'", "'mean'"), assumptions=['데모 규칙: 합계를 평균으로 변경했습니다.'])
    if '합계' in request or '합산' in request:
        return Proposal(code=code.replace("'mean'", "'sum'"), assumptions=['데모 규칙: 평균을 합계로 변경했습니다.'])
    raise ValueError('데모는 “수량이 정확히 2인 주문도 포함”, “평균으로 계산”, “합계로 계산” 요청만 지원합니다. 일반 수정은 API 모드에서 가능합니다.')


WRANGLING_INPUT = '''order_id,customer_id,order_date,quantity,price,status
O1,C1,2026-01-01,2,10, done 
O2,C1,2026-02-01,3,10,Done
O3,C2,2026-01-03,4,5,done
O4,C2,2026-01-04,bad,5,done
O5,C2,2026-02-01,1,5,cancelled
O2,C1,2026-02-01,3,10,Done
'''
WRANGLING_SOURCES = {'customers': 'customer_id,city\nC1, Seoul \nC2,Busan\n'}
WRANGLING_TARGET = 'city,2026-01,2026-02\nBusan,20,\nSeoul,20,30\n'
WRANGLING_CODE = '''customers = tables['customers'].assign(city=tables['customers']['city'].str.strip())
s1 = input_df.assign(quantity=pd.to_numeric(input_df['quantity'],errors='coerce'),status=input_df['status'].str.strip().str.lower())
s2 = s1.dropna(subset=['quantity']).drop_duplicates(subset=['order_id'])
s3 = s2.assign(order_date=pd.to_datetime(s2['order_date'],errors='coerce'))
s4 = s3.loc[s3['status'] == 'done'].copy()
s5 = s4.assign(amount=s4['quantity'] * s4['price'],month=s4['order_date'].dt.strftime('%Y-%m'))
s6 = s5.merge(customers,how='left',on=['customer_id'])
s7 = s6.groupby(['city','month'],as_index=False,dropna=False).agg(total=('amount','sum'))
result = s7.pivot(index='city',columns='month',values='total').reset_index()'''
WRANGLING_STEPS = [
    {'statement_indices':[0], 'label':'고객명 정리'},
    {'statement_indices':[1,2,3], 'label':'주문 데이터 정리'},
    {'statement_indices':[4,5], 'label':'완료 주문 매출'},
    {'statement_indices':[6], 'label':'고객 지역 연결'},
    {'statement_indices':[7], 'label':'지역·월 집계'},
    {'statement_indices':[8], 'label':'월별 표 재구조화'},
]
