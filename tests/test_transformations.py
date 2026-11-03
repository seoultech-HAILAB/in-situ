import ast
import copy
import json
from pathlib import Path

import pytest
from backend.transformations import extract, annotate_run
from backend.pipeline import prepare, patch, assemble
from backend.python_runtime import run as native_run
from backend.engine import parse_table
from backend import explanations


def snapshot(code, csv='x,y\n2,3'):
    plan=prepare(code,[{'statement_indices':list(range(len(ast.parse(code).body))),'output_variable':'result'}],engine='python')
    stages,ops=assemble(native_run(code,parse_table(csv),{},plan),plan)
    return annotate_run({'id':'execution-1','code_version':1,'code':code,'pipeline':plan,'stages':stages,'operations':ops})


def test_individual_chained_calls_and_multi_column_assignments_have_exact_source_ranges():
    code="result = input_df.assign(a=input_df['x'] * 2, b=input_df['y'].astype(str).str.strip())"
    items=extract(code,[0])
    assert [i['method'] for i in items]==['formula','astype','strip']
    assert [i['output_columns'] for i in items]==[['a'],['b'],['b']]
    assert items[0]['code']=="a=input_df['x'] * 2"
    assert items[1]['focus_code']=='.astype(str)'
    assert items[2]['focus_code']=='.strip()'
    assert all(i['code']!=code for i in items)
    assert len({i['id'] for i in items})==3


def test_unicode_offsets_multiline_expressions_and_semicolon_statements():
    code="이름 = input_df['x'].astype(str); result = input_df.assign(\n    값=이름.str.strip(),\n    두배=input_df['y'] * 2\n)"
    items=extract(code,[0,1]);lines=code.splitlines(keepends=True)
    for item in items:
        loc=item['code_location'];a=loc['start']-1;b=loc['end']-1
        raw=b''.join(line.encode() for line in lines[a:b+1])
        end=sum(len(line.encode()) for line in lines[a:b])+loc['end_column']
        assert raw[loc['start_column']:end].decode()==item['code']
    assert any(i['output_columns']==['값'] for i in items)
    assert items[0]['focus_code']=='.astype(str)'


def test_common_trace_gets_source_annotations_without_fabricating_cell_lineage():
    code="result = input_df.copy()\nresult['x'] = result['x'].apply(lambda v: v * 2)\nresult['y'] = result['y'].map(lambda v: v + 7)"
    run=snapshot(code)
    stage=run['stages'][1]
    assert stage['trace_level']=='common'
    assert [t['output_columns'] for t in stage['transformations']]==[['x'],['y']]
    assert all(t['execution_version']==run['id'] for t in stage['transformations'])
    assert not any(refs for cols in stage['lineage'].values() for refs in cols.values())
    assert stage['table']['rows'][0]['values']=={'x':4,'y':10}


def test_loop_column_bindings_and_helper_body_locations_are_static_not_execution_claims():
    code="def tidy(df):\n    df['x'] = df['x'].astype(str)\n    return df\nresult = tidy(input_df)\nfor c in ['x','y']:\n    result[c] = result[c].map(str)"
    items=extract(code,[1,2])
    assert items[0]['code_location']['start']==2 and items[0]['call_location']['start']==4
    assert items[1]['output_columns']==['x','y']
    assert all(item['syntax_only'] for item in items)


def test_patching_rebuilds_absolute_locations_and_never_carries_old_descriptions():
    run=snapshot("result = input_df.assign(x=input_df['x'] * 2)")
    run['stages'][1]['transformations'][0]['description']={'text':'옛 설명','source':'llm'}
    old=copy.deepcopy(run)
    plan=patch(run,[{'action':'replace','step_id':run['pipeline']['steps'][0]['id'], 'code':"factor = 3\nresult = input_df.assign(x=input_df['x'] * factor)"}],run['id'])
    stages,ops=assemble(native_run(plan['code'],parse_table('x,y\n2,3'),{},plan),plan,run)
    revised=annotate_run({'id':'execution-2','code_version':2,'code':plan['code'],'pipeline':plan,'stages':stages,'operations':ops})
    item=revised['stages'][1]['transformations'][0]
    assert item['code_location']['start']==2 and 'factor' in item['code']
    assert item['execution_version']=='execution-2' and item['description']['text']!='옛 설명'
    assert run==old
    assert explanations.fingerprint(run)!=explanations.fingerprint(revised)


def test_transformation_explanations_require_every_exact_ordinal_and_snapshot():
    run=snapshot("result = input_df.assign(x=input_df['x'] * 2,y=input_df['y'] * 3)")
    data={'steps':[{'step_no':1,'title':'두 열 계산','text':'두 열의 값을 계산합니다.'}], 'columns':[
        {k:t[k] for k in ('step_no','operation_no','column')}|{'text':'열 값을 계산합니다.'} for t in explanations.column_targets(run)],
        'transformations':[{k:t[k] for k in ('step_no','transformation_no')}|{'text':f'{t["output_columns"][0]} 열의 값을 계산합니다.'} for t in explanations.transformation_targets(run)]}
    explanations.validate_steps(data,1,run,require_transformations=True)
    invalid=copy.deepcopy(data);invalid['transformations'].pop()
    with pytest.raises(ValueError,match='AST'):explanations.validate_steps(invalid,1,run,require_transformations=True)
    invalid=copy.deepcopy(data);invalid['transformations'].reverse()
    with pytest.raises(ValueError,match='AST'):explanations.validate_steps(invalid,1,run)
    bundle={**data,'fingerprint':explanations.fingerprint(run),'model':'test','prompt_version':explanations.PROMPT_VERSION}
    explanations.attach(run,bundle,False)
    assert all(t['description']['source']=='llm' for t in run['stages'][1]['transformations'])
    assert all(t['execution_version']==run['id'] for t in run['stages'][1]['transformations'])


def test_legacy_bundles_can_use_fresh_ast_descriptions_without_claiming_llm_authorship():
    run=snapshot("result = input_df.assign(x=input_df['x'] * 2)")
    bundle={'fingerprint':explanations.fingerprint(run),'model':'old','prompt_version':explanations.PROMPT_VERSION,
            'steps':[{'step_no':1,'title':'계산','text':'값을 계산합니다.'}],
            'columns':[{k:t[k] for k in ('step_no','operation_no','column')}|{'text':'열 계산'} for t in explanations.column_targets(run)]}
    explanations.attach(run,bundle,True)
    assert run['stages'][1]['transformations'][0]['description']['source']=='ast'


def test_every_bundled_transform_location_points_into_its_own_executed_source():
    total=0
    for file in Path('tasks/candidates').glob('*.json'):
        task=json.loads(file.read_text(encoding='utf-8'))
        if 'initial_code' not in task:continue
        code=task['initial_code'];plan=prepare(code,task['steps'],engine='python')
        for step in plan['steps']:
            for item in step['transformations']:
                assert item['code'] and item['description']['text']
                assert item['statement_index'] in step['statement_indices']
                assert item['code_location']['start']<=item['code_location']['end']
                total+=1
    assert total>39


def test_same_column_in_an_unrelated_side_table_is_not_a_candidate_for_output():
    code="main = input_df.copy()\nside = tables['lookup'].copy()\nside['x'] = side['x'].astype(str)\nmain['x'] = main['x'].apply(lambda v: v * 2)\nresult = main"
    items=extract(code,list(range(5)),output_variable='result')
    assert next(i for i in items if i['method']=='astype')['contributes_to_output'] is False
    assert next(i for i in items if i['method']=='apply')['contributes_to_output'] is True


def test_in_place_edits_and_deleted_columns_remain_output_candidates():
    code="result = input_df.copy()\nresult.dropna(inplace=True)\ndel result['y']\nresult['x'] *= 2"
    items=extract(code,list(range(4)),output_variable='result')
    assert [t['kind'] for t in items]==['filter','drop','derive']
    assert all(t['contributes_to_output'] for t in items)
    assert '2' in items[-1]['description']['text']


def test_generation_revision_and_reopen_refresh_source_descriptions_for_the_current_run(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from backend import app as server
    from backend.generation import Proposal
    monkeypatch.setattr(server,'STORE',tmp_path)
    class Model:
        def generate(self,inp,target,requirements,old,request,context):
            if old:
                return Proposal(base_run_id=context['base_run_id'],changes=[{'action':'replace','step_id':context['target_step']['id'],
                    'code':"factor = 3\nresult = input_df.assign(x=input_df['x'].apply(lambda v: v * factor))"}])
            return Proposal(code="result = input_df.assign(x=input_df['x'].apply(lambda v: v * 2))")
    monkeypatch.setattr(server,'generator',Model())
    def descriptions(run):
        data={'fingerprint':explanations.fingerprint(run),'model':'test','prompt_version':explanations.PROMPT_VERSION,
            'steps':[{'step_no':i,'title':'값 계산','text':'선택한 열을 계산합니다.'} for i in range(1,len(run['stages']))],
            'columns':[{k:t[k] for k in ('step_no','operation_no','column')}|{'text':'열 값 계산'} for t in explanations.column_targets(run)],
            'transformations':[{k:t[k] for k in ('step_no','transformation_no')}|{'text':'수량을 세 배로 계산합니다.' if 'factor' in t['code'] else '수량을 두 배로 계산합니다.'} for t in explanations.transformation_targets(run)]}
        return data,False
    monkeypatch.setattr(explanations,'obtain',descriptions)
    client=TestClient(server.app)
    s=client.post('/api/sessions',json={'input_csv':'x\n2','target_csv':'x\n6','condition':'in-situ','execution_engine':'python'}).json()
    sid=s['id']
    initial=client.post(f'/api/sessions/{sid}/generate',json={}).json()['run']
    assert initial['stages'][1]['transformations']
    initial=client.post(f'/api/sessions/{sid}/explanations',json={'run_id':initial['id']}).json()['run']
    assert initial['stages'][1]['transformations'][0]['description']['text']=='수량을 두 배로 계산합니다.'
    changed=client.post(f'/api/sessions/{sid}/generate',json={'request':'세 배로 계산','scope':'step','base_run_id':initial['id'],'context':{'step_id':initial['stages'][1]['id']}}).json()
    assert changed['status']=='ready',changed.get('error')
    revised=client.post(f'/api/sessions/{sid}/explanations',json={'run_id':changed['run']['id']}).json()['run']
    item=revised['stages'][1]['transformations'][0]
    assert item['code_location']['start']==2
    assert item['description']['text']=='수량을 세 배로 계산합니다.'
    assert item['execution_version']==revised['id'] and item['code_version']==2
    assert revised['stages'][1]['table']['rows'][0]['values']['x']==6
    assert client.get(f'/api/sessions/{sid}').json()['run']['stages'][1]['transformations']==revised['stages'][1]['transformations']
    assert client.post(f'/api/sessions/{sid}/explanations',json={'run_id':initial['id']}).status_code==409
    history=client.get(f'/api/sessions/{sid}').json()['runs']
    assert history[0]['stages'][1]['transformations'][0]['description']['text']=='수량을 두 배로 계산합니다.'
