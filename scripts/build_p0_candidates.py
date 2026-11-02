"""Publish locally validated real P0 programs as review fixtures; never regenerate them."""
import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.analyze_p0_synth import read_frame
from scripts.build_synth_candidates import frame_csv
from scripts.audit_p0_programs import wrapper,replay
from scripts.structure_p0_program import structure,groups_from_observations
from backend.pipeline import prepare,assemble,patch
from backend.isolation import isolated_run
from backend.engine import table,parse_table,compare

SELECTED=[
    ('CASE-01','spider_bb0df1c0','지역 조건 조회',
     'Name이 InvalidDistrict로 시작하는 무효 행을 제외하고, Population이 4000보다 크거나 Area_km이 3000보다 큰 지역의 District_ID와 Name을 입력 순서로 출력하세요.',
     'p0_df_1 = input_df',"p0_df_1 = input_df.loc[~input_df['Name'].str.startswith('InvalidDistrict', na=False)].copy()",
     '무효 이름 정제 누락'),
    ('CASE-02','spider_c449ff01','지역의 중심 도시',
     'Region_ID가 중복되면 첫 행만 남긴 뒤, Area가 10000보다 큰 지역의 Capital을 입력 순서로 출력하세요.',
     'p0_df_1 = input_df',"p0_df_1 = input_df.drop_duplicates(subset=['Region_ID'], keep='first')",
     '동일 지역 ID 중복 처리 누락'),
    ('CASE-03','spider_528b8b8e','프로그램 연도순 조회',
     '모든 열에 결측이 없는 행을 사용해 Start_Year가 최근인 프로그램부터 Title을 출력하세요. 같은 연도는 입력 행 순서를 유지하세요.',
     "p0_df_2 = p0_df_1.dropna(subset=['Start_Year', 'Title'])",'p0_df_2 = p0_df_1.dropna()',
     '일부 열만 결측 검사하여 불완전한 행 포함'),
]


def build(inventory,run_root,out):
    inventory={r['task_id']:r for r in json.loads(inventory.read_text(encoding='utf-8'))}
    originals={r['task_id']:r for r in json.loads((run_root/'results.json').read_text(encoding='utf-8'))}
    results=[];out.mkdir(parents=True,exist_ok=True)
    for cid,tid,title,description,old,new,diagnosis in SELECTED:
        info=inventory[tid];original=originals[tid]
        assert original['condition']=='P0' and original['model_calls']==1 and original['workflow_completed'] and not original['matched']
        source_folder=run_root/'runs'/tid/str(original['seed'])/'P0'
        source_bytes=(source_folder/'program.py').read_bytes()
        source=source_bytes.decode('utf-8-sig')
        response_bytes=(source_folder/'response.txt').read_bytes()
        response=response_bytes.decode('utf-8-sig').strip()
        fence=re.fullmatch(r'```(?:python)?\s*\n(.*?)\n```',response,re.DOTALL)
        if fence: response=fence.group(1)
        assert ast.dump(ast.parse(response))==ast.dump(ast.parse(source)), 'Saved program differs from the model response'
        data_folder=Path(info['manifest']).parent
        inputs=[frame_csv(read_frame(data_folder/f)) for f in info['inputs']]
        assert len(inputs)==1
        target=frame_csv(read_frame(data_folder/info['target']))
        _,untouched=replay(wrapper(source,1),inputs)
        initial,mapping=structure(source,1)
        syntax=prepare(initial,engine='python')
        observations=isolated_run(initial,inputs[0],engine='python',plan=syntax)
        groups=groups_from_observations(initial,observations)
        plan,bad=replay(initial,inputs,groups)
        saved=json.loads((source_folder/'output_table.json').read_text(encoding='utf-8'))['data']
        archived=table(pd.DataFrame(saved['data'],columns=list(map(str,saved['columns']))))
        assert compare(untouched[-1]['table'],archived)['matches']
        assert compare(bad[-1]['table'],archived)['matches']
        expected=table(parse_table(target))
        assert not compare(bad[-1]['table'],expected)['matches']
        assert initial.count(old)==1
        reference=initial.replace(old,new)
        _,good=replay(reference,inputs,groups)
        assert compare(good[-1]['table'],expected)['matches']
        changed=[i for i,(a,b) in enumerate(zip(ast.parse(initial).body,ast.parse(reference).body)) if ast.dump(a)!=ast.dump(b)]
        target_index=next(i for i,g in enumerate(groups) if any(j in g['statement_indices'] for j in changed))
        assert all(i in groups[target_index]['statement_indices'] for i in changed)
        statements=ast.parse(reference).body
        block='\n'.join(ast.get_source_segment(reference,statements[i]) for i in groups[target_index]['statement_indices'])
        previous={'id':'p0-original-validation','code':initial,'pipeline':plan,'stages':bad}
        repaired=patch(previous,[{'action':'replace','step_id':plan['steps'][target_index]['id'],'code':block}],
            previous['id'],scope='step',target=plan['steps'][target_index]['id'])
        stages,_=assemble(isolated_run(repaired['code'],inputs[0],engine='python',plan=repaired),repaired,previous)
        assert compare(stages[-1]['table'],expected)['matches']
        assert [s['id'] for s in repaired['steps']]==[s['id'] for s in plan['steps']]
        provenance={'initial_origin':'luna_p0_observed','actual_luna_program':True,
            'display_code_is_original_bytes':False,'observational_adaptation':True,
            'original_task_id':tid,'dataset':'Synth-Spider','cohort':original['cohort'],
            'model_calls_in_original_run':1,'new_model_calls':0,'original_workflow_completed':True,
            'recorded_model_id':original['model_spec'].get('model_id'),
            'p0_recorded_matches':False,'original_program_sha256':hashlib.sha256(source_bytes).hexdigest(),
            'original_response_sha256':hashlib.sha256(response_bytes).hexdigest(),
            'program_matches_response_ast':True,
            'original_output_sha256':hashlib.sha256((source_folder/'output_table.json').read_bytes()).hexdigest(),
            'same_as_archived_output':True,'task_description_clarified':True,
            'original_prompt_target':'schema_only','review_target':'full_original_target',
            'adaptation_source_map':mapping,
            'adaptation':'source binding, straight-line lifting, local SSA names, single-use mask inlining, loc/chain observation boundaries; output checked against unchanged original and archive',
            'source_hashes':{f:hashlib.sha256((data_folder/f).read_bytes()).hexdigest() for f in info['inputs']+[info['target']]}}
        validation={'initial_target_match':False,'reference_target_match':True,'original_output_preserved':True,
            'changed_step_index':target_index,'diagnosis':diagnosis,
            'initial_trace_levels':[s['trace_level'] for s in bad[1:]],
            'input_profiles':info['input_profiles'],'target_profile':info['target_profile'],
            'repair':{'stable_step_ids':True,'selected_step_only_code_change':True,'full_reexecution_matches':True,
                'stage_diffs':[s['diff'] for s in stages[1:]]}}
        payload={'schema_version':1,'id':cid,'title':title,'description':description,'input_csv':inputs[0],
            'target_csv':target,'sources':{},'initial_code':initial,'reference_code':reference,'steps':groups,
            'original_program':source,'provenance':provenance,'researcher_notes':validation}
        (out/f'{cid}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        export=out/'exports'/cid;export.mkdir(parents=True,exist_ok=True)
        (export/'original_luna.py').write_bytes(source_bytes)
        for name,text in [('initial_observed.py',initial),('reference.py',reference),('input.csv',inputs[0]),('target.csv',target)]:
            (export/name).write_text(text,encoding='utf-8')
        (export/'steps.json').write_text(json.dumps(groups,ensure_ascii=False,indent=2),encoding='utf-8')
        (export/'researcher_only.json').write_text(json.dumps({'provenance':provenance,'validation':validation},ensure_ascii=False,indent=2),encoding='utf-8')
        result={'id':cid,'task_id':tid,'steps':len(groups),'trace_levels':validation['initial_trace_levels'],
            'original_output_preserved':True,'initial_incorrect':True,'reference_correct':True,
            'initial_rows':bad[-1]['table']['stats']['rows'],'target_rows':len(parse_table(target))}
        results.append(result);print(json.dumps(result),flush=True)
    # Keep provisional mocks, but do not mix them into the active real-P0 pool.
    for file in out.glob('SYN-*.json'):
        c=json.loads(file.read_text(encoding='utf-8'));c['enabled']=False
        file.write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'validation.json').write_text(json.dumps(results,indent=2),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inventory',type=Path,required=True);p.add_argument('--run-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();build(a.inventory,a.run_root,a.out)
