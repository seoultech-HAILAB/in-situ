"""Author provisional mock candidates from actual P0-cohort data, never impersonate Luna output."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.analyze_p0_synth import read_frame
from backend.engine import parse_table,table,compare
from backend.pipeline import prepare,assemble,patch
from backend.isolation import isolated_run

# These are authored counterfactuals, not original model programs or generation rules.
CASES=[
    ('SYN-01','spider_bb0df1c0','지역 조건 조회',
     'Name이 InvalidDistrict로 시작하는 무효 행을 제외하고, Population이 4000보다 크거나 Area_km이 3000보다 큰 지역의 District_ID와 Name을 입력 순서로 출력하세요.',
     ["s1 = input_df.loc[~input_df['Name'].str.startswith('InvalidDistrict', na=False)].copy()",
      "s2 = s1.loc[(s1['Population'] > 4000) | (s1['Area_km'] > 3000)].copy()",
      "result = s2[['District_ID', 'Name']]"],
     ['이름 검사','조건 선택','결과 열 선택'],(1,' | ',' & '),'OR 조건을 AND로 변경'),
    ('SYN-02','spider_af4faf78','항공기 종류별 건수',
     'pilot_name, plane_name, age 중 결측이 있는 행을 제외하고, plane_name별 행 수를 count(*)로 집계하세요. 출력 열은 count(*), plane_name이며 종류 이름 오름차순입니다.',
     ["s1 = input_df.dropna(subset=['pilot_name', 'plane_name', 'age'])",
      "s2 = s1.groupby(['plane_name'], as_index=False, dropna=False).agg(n=('age', 'count'))",
      "result = s2.rename(columns={'n': 'count(*)'})[['count(*)', 'plane_name']]"],
     ['결측 처리','종류별 집계','출력 열 구성'],(1,"'count'","'nunique'"),'전체 건수 대신 서로 다른 나이 수를 집계'),
    ('SYN-03','spider_528b8b8e','프로그램 연도순 조회',
     '모든 열에 결측이 없는 행을 사용해 Start_Year가 최근인 프로그램부터 Title을 출력하세요. 같은 연도는 입력 행 순서를 유지하세요.',
     ["s1 = input_df.dropna()",
      "s2 = s1.sort_values(by=['Start_Year'], ascending=False, kind='stable')",
      "result = s2[['Title']]"],
     ['결측 처리','연도 정렬','제목 선택'],(1,'ascending=False','ascending=True'),'정렬 방향을 반대로 변경'),
    ('SYN-04','spider_f35023ce','상자 금액 요약',
     'Code가 영문과 숫자로 된 4자리인 행을 사용해 Value의 평균과 합계를 avg(value), sum(value) 두 열의 한 행으로 출력하세요.',
     ["s1 = input_df.loc[input_df['Code'].str.contains(r'^[A-Za-z0-9]{4}$', regex=True, na=False)].copy()",
      "s2 = s1[['Value']].copy()",
      "result = pd.DataFrame({'avg(value)': [s2['Value'].mean()], 'sum(value)': [s2['Value'].sum()]})"],
     ['코드 형식 검사','금액 열 선택','금액 요약'],(2,"['Value'].sum()","['Value'].max()"),'합계 위치에서 최댓값을 계산'),
    ('SYN-05','spider_6685769c','고객별 주문 수량',
     '고객 Name의 바깥 공백·큰따옴표를 제거하고 단어 첫 글자를 대문자로 정리하세요. orders의 Quantity 결측은 최빈값(동률이면 작은 값)으로 채우세요. 주문이 있는 고객만 연결해 Name별 Quantity 합계를 sum(t2.quantity)로 출력하고 Name 오름차순으로 정렬하세요.',
     ["customers = input_df.assign(Name=input_df['Name'].str.strip().str.strip('\"').str.title())",
      "orders = tables['orders'].assign(Quantity=tables['orders']['Quantity'].fillna(tables['orders']['Quantity'].mode().iloc[0]))",
      "joined = customers.merge(orders, on='Customer_ID', how='inner')",
      "grouped = joined.groupby(['Name'], as_index=False, dropna=False).agg(total=('Quantity', 'sum'))",
      "result = grouped.rename(columns={'total': 'sum(t2.quantity)'}).sort_values(by=['Name']).reset_index(drop=True)"],
     ['고객 이름 정리','주문 수량 정리','고객과 주문 연결','고객별 집계','출력 정렬'],(2,"how='inner'","how='left'"),'내부 조인 대신 왼쪽 조인을 사용'),
]


def frame_csv(frame):
    text=frame.to_csv(index=False)
    restored=parse_table(text).reset_index(drop=True)
    expected=frame.reset_index(drop=True).copy()
    expected.columns=list(map(str,expected.columns))
    pd.testing.assert_frame_equal(restored,expected,check_dtype=False,check_index_type=False,check_column_type=False)
    return text


def execute(code,groups,inp,sources):
    plan=prepare(code,groups,engine='python')
    stages,ops=assemble(isolated_run(code,inp,sources,engine='python',plan=plan),plan)
    return plan,stages


def build(inventory,out):
    rows={r['task_id']:r for r in json.loads(inventory.read_text(encoding='utf-8'))}
    out.mkdir(parents=True,exist_ok=True)
    results=[]
    for cid,original,title,description,blocks,labels,mutation,explanation in CASES:
        r=rows[original]
        assert r['cohort']!='development' and not r['structural_exclusions']
        folder=Path(r['manifest']).parent
        frames=[read_frame(folder/f) for f in r['inputs']]
        inp=frame_csv(frames[0]);target=frame_csv(read_frame(folder/r['target']))
        sources={'orders':frame_csv(frames[1])} if len(frames)>1 else {}
        groups=[{'statement_indices':[i],'label':label,'output_variable':block.split(' = ',1)[0]} for i,(block,label) in enumerate(zip(blocks,labels))]
        correct='\n'.join(blocks)
        bad=list(blocks);index,old,new=mutation
        assert bad[index].count(old)==1
        bad[index]=bad[index].replace(old,new)
        initial='\n'.join(bad)
        good_plan,good_stages=execute(correct,groups,inp,sources)
        bad_plan,bad_stages=execute(initial,groups,inp,sources)
        target_table=table(parse_table(target))
        good_comparison=compare(good_stages[-1]['table'],target_table)
        bad_comparison=compare(bad_stages[-1]['table'],target_table)
        if not good_comparison['matches']:
            raise ValueError(f'{cid} authored reference does not match full original Target: {good_comparison}')
        if bad_comparison['matches']:
            raise ValueError(f'{cid} injected change has no observable effect')
        previous={'id':'initial-validation','code':initial,'pipeline':bad_plan,'stages':bad_stages}
        repaired_plan=patch(previous,[{'action':'replace','step_id':bad_plan['steps'][index]['id'],'code':blocks[index]}],
            previous['id'],scope='step',target=bad_plan['steps'][index]['id'])
        repaired_stages,_=assemble(isolated_run(repaired_plan['code'],inp,sources,engine='python',plan=repaired_plan),repaired_plan,previous)
        assert compare(repaired_stages[-1]['table'],target_table)['matches']
        assert [s['id'] for s in repaired_plan['steps']]==[s['id'] for s in bad_plan['steps']]
        assert [s['code'] for i,s in enumerate(repaired_plan['steps']) if i!=index]==[s['code'] for i,s in enumerate(bad_plan['steps']) if i!=index]
        payload={'schema_version':1,'id':cid,'title':title,'description':description,
            'input_csv':inp,'target_csv':target,'sources':sources,'initial_code':initial,'steps':groups,
            'reference_code':correct,'provenance':{'initial_origin':'authored_mock','actual_luna_program':False,
                'original_task_id':original,'dataset':'Synth-Spider','cohort':r['cohort'],
                'p0_recorded_matches':r['p0_recorded_matches'],'original_p0_program_status':'artifact_unavailable',
                'new_model_calls':0,'task_description_clarified':True,'full_original_tables':True,
                'source_hashes':{f:hashlib.sha256((folder/f).read_bytes()).hexdigest() for f in r['inputs']+[r['target']]}},
            'researcher_notes':{'injected_change':explanation,'changed_step_index':index,
                'initial_target_match':False,'reference_target_match':True,
                'initial_trace_levels':[s.get('trace_level') for s in bad_stages[1:]],
                'reference_trace_levels':[s.get('trace_level') for s in good_stages[1:]],
                'repair':{'stable_step_ids':True,'selected_step_only_code_change':True,
                    'full_reexecution_matches':True,'stage_diffs':[s.get('diff') for s in repaired_stages[1:]]},
                'input_profiles':r['input_profiles'],'target_profile':r['target_profile']}}
        (out/f'{cid}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        files=out/'exports'/cid
        files.mkdir(parents=True,exist_ok=True)
        for filename,text in [('input.csv',inp),('target.csv',target),('initial.py',initial),('reference.py',correct)]:
            (files/filename).write_text(text,encoding='utf-8')
        for name,text in sources.items():(files/(name+'.csv')).write_text(text,encoding='utf-8')
        (files/'steps.json').write_text(json.dumps(groups,ensure_ascii=False,indent=2),encoding='utf-8')
        (files/'researcher_only.json').write_text(json.dumps({'provenance':payload['provenance'],'notes':payload['researcher_notes']},ensure_ascii=False,indent=2),encoding='utf-8')
        result={'id':cid,'original_task_id':original,'initial_matches':False,'reference_matches':True,
            'stages':len(blocks),'initial_rows':bad_stages[-1]['table']['stats']['rows'],
            'target_rows':r['target_profile']['rows'],'trace_levels':payload['researcher_notes']['initial_trace_levels']}
        results.append(result);print(json.dumps(result))
    (out/'validation.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inventory',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();build(a.inventory,a.out)
