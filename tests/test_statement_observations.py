import ast
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend.engine import parse_table
from backend.pipeline import prepare,assemble
from backend.python_runtime import run as native_run
from backend.transformations import annotate_run

CODE="""result = input_df.copy()
for c in ['x']:
    result[c] = pd.to_numeric(result[c], errors='coerce')
result = result[result.apply(lambda row: row['x'] > 1, axis=1)]
keep = ['x']
result = result[keep]
result = result.sort_values('x').reset_index(drop=True)
"""
CSV='x,y\n3,30\n1,10\n2,20'


def run(code=CODE,csv=CSV):
    plan=prepare(code,[{'statement_indices':list(range(len(ast.parse(code).body))),'output_variable':'result'}],engine='python')
    stages,operations=assemble(native_run(code,parse_table(csv),{},plan),plan)
    return annotate_run(dict(id='observed',code_version=1,code=code,pipeline=plan,stages=stages,operations=operations))


def test_search_inside_common_step_finds_implicit_row_and_column_removals():
    stage=run()['stages'][1]
    assert stage['trace_level']=='common'
    assert stage['row_correspondence_complete']
    assert list(stage['row_correspondence'].values())==['r0003','r0001']
    assert len(stage['operation_observations'])>=3
    filter_op=next(item for item in stage['transformations'] if 'apply(lambda row:' in item['code'] and item['kind']=='filter')
    select_op=next(item for item in stage['transformations'] if item['code']=='result[keep]')
    assert any(binding['rows']['removed']==['r0002'] for binding in filter_op['execution_effects'])
    assert select_op['removed_columns']==['y']
    assert all(not binding['columns']['removed'] for binding in filter_op['execution_effects'])
    assert all(not binding['rows']['removed'] for binding in select_op['execution_effects'])


def test_slice_and_computed_mask_without_drop_are_observed():
    for selection in ("result.iloc[:2]", "result.loc[mask]"):
        code="result = input_df.copy()\nmask = result['x'].map(lambda value: value != 1)\nresult = "+selection
        stage=run(code)['stages'][1]
        assert stage['row_correspondence_complete']
        item=next(item for item in stage['transformations'] if item['code']==selection)
        assert any(binding['rows']['removed'] for binding in item['execution_effects'])


def test_loop_deletion_search_excludes_an_unexecuted_branch():
    code="result = input_df.copy()\nfor c in ['y']:\n    if False:\n        result = result[['y']]\n    del result[c]"
    stage=run(code)['stages'][1]
    deleted=next(item for item in stage['transformations'] if item['kind']=='drop')
    inactive=next(item for item in stage['transformations'] if item['method']=='select')
    assert deleted['removed_columns']==['y']
    assert not inactive['execution_effects']


def test_unknown_rebuilt_rows_never_acquire_identity_from_equal_indexes_or_values():
    code="result = input_df.apply(lambda row: row, axis=1)\nresult = result.iloc[:2]"
    stage=run(code)['stages'][1]
    assert not stage.get('row_correspondence_complete')


def test_one_to_one_merge_keeps_verified_main_row_correspondence():
    code="main = input_df.copy()\nmain['x'] = main['x'].map(lambda value: value)\nmain = main[main['x'] > 1]\nlookup = input_df[['x','y']]\nresult = main.merge(lookup, on='x', how='left', suffixes=('', '_lookup'))"
    stage=run(code)['stages'][1]
    assert stage['row_correspondence_complete']
    assert set(stage['row_correspondence'].values())=={'r0001','r0003'}


def test_temporary_period_values_do_not_break_successful_native_execution():
    code="result = input_df.copy()\nresult['date'] = pd.to_datetime(result['date'])\nresult['month'] = result['date'].dt.to_period('M')\nresult['month'] = result['month'].astype(str)\nresult = result[['month']]"
    observed=run(code,'date\n2024-01-03\n2024-02-05')
    import json
    json.dumps(observed,allow_nan=False)
    assert [row['values']['month'] for row in observed['stages'][1]['table']['rows']]==['2024-01','2024-02']


def test_t01_city_assignment_and_location_selection_survive_other_statements_failing_to_trace():
    import json
    from pathlib import Path
    candidate=json.loads(Path('tasks/candidates/PILOT4-T01.json').read_text(encoding='utf-8-sig'))
    code=candidate['initial_code'].replace("stores['Potential Store Location'].astype(str)","stores['Potential Store Location'].map(lambda value: str(value))")
    plan=prepare(code,candidate['steps'],engine='python')
    stages,operations=assemble(native_run(code,parse_table(candidate['input_csv']),
        {name:parse_table(csv) for name,csv in candidate.get('sources',{}).items()},plan),plan)
    observed=annotate_run(dict(id='T01-partial',code_version=1,code=code,pipeline=plan,stages=stages,operations=operations))
    assert len(observed['stages'])==5
    assert [stage['code'] for stage in stages[1:]]==[step['code'] for step in plan['steps']]
    first,last=observed['stages'][1],observed['stages'][4]
    assert first['trace_level']=='common'
    city=next(item for item in first['transformations'] if item['method']=='assignment' and item['output_columns']==['City'])
    assert city['code']=="stores['City'] = location_parts[0].str.strip()"
    assert '공백' in city['description']['text'] and 'City' in city['description']['text']
    assert all(word not in city['description']['text'] for word in ('Location','쉼표','분할','Country'))
    assert any('City' in effect['columns']['added'] for effect in city['execution_effects'])
    assert any(effect['cells']['added'].get('City') for effect in city['execution_effects'])
    location=next(item for item in last['transformations'] if item['method']=='select' and 'Location' in item['removed_columns'])
    assert location['code'].startswith("result[['City', 'Country'")
    assert 'sort_values' not in location['code']
    assert all(word not in location['description']['text'] for word in ('정렬','공백','문자열'))
    assert all('source_context' not in item for stage in stages[1:] for item in stage['transformations'])


@pytest.mark.parametrize('failed_index',[1,2])
def test_an_observation_failure_keeps_other_executed_assignments(monkeypatch,failed_index):
    from backend.statement_observations import Observations
    observe=Observations._observe
    def fail_one(self,node,index,*args):
        if index==failed_index:raise ValueError('Optional trace adapter failed')
        return observe(self,node,index,*args)
    monkeypatch.setattr(Observations,'_observe',fail_one)
    code="result = input_df.copy()\nresult['City'] = result['x'].astype(str)\nresult['Other'] = result['x'].map(lambda value: value)\nresult = result[['City','x']]"
    observed=run(code)
    stage=observed['stages'][1]
    city=next(item for item in stage['transformations'] if item['method']=='assignment' and item['output_columns']==['City'])
    assert city['execution_effects']
    selected=next(item for item in stage['transformations'] if item['method']=='select' and "[['City','x']]" in item['code'])
    assert 'y' in selected['removed_columns']
    assert stage.get('execution_observation_failures')


def test_loop_column_creation_maps_only_to_its_executed_assignment():
    code="result = input_df.copy()\nfor c in ['x','y']:\n    result[c + ' text'] = result[c].map(lambda value: str(value))\n    if False:\n        result[c + ' unused'] = 'not executed'\nresult = result.drop(columns=['y'])"
    stage=run(code)['stages'][1]
    assignment=next(item for item in stage['transformations'] if item['method']=='assignment' and "c + ' text'" in item['code'])
    assert set(assignment['output_columns'])=={'x text','y text'}
    assert assignment['code']=="result[c + ' text'] = result[c].map(lambda value: str(value))"
    assert assignment['code_location']['start']==3
    assert any(set(effect['columns']['added'])=={'x text','y text'} for effect in assignment['execution_effects'])
    assert not any(item['execution_effects'] for item in stage['transformations'] if 'unused' in item['code'])


@pytest.fixture
def stored(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'STORE',tmp_path)
    session=server.create(server.Tables(input_csv=CSV,target_csv='x\n2\n3',execution_engine='python',condition='in-situ'))
    session.pop('run',None)
    server.execute(session,CODE,[],'research',groups=[{'statement_indices':list(range(6)),'output_variable':'result'}])
    def legacy(value):
        if isinstance(value,dict):
            for key in list(value):
                if key in ('execution_observations_version','operation_observations','row_correspondence','row_correspondence_complete','observation_row_aliases'):value.pop(key)
                else:legacy(value[key])
        elif isinstance(value,list):
            for item in value:legacy(item)
    legacy(session)
    server.save(session)
    return session,TestClient(server.app)


def test_saved_run_gets_observations_without_replacing_execution_code_or_tables(stored):
    session,client=stored
    base=deepcopy(session['runs'][0]);sid=session['id']
    response=client.post(f'/api/sessions/{sid}/execution-observations',json={'run_id':base['id']})
    assert response.status_code==200,response.text
    result=response.json();run=result['run']
    assert run['id']==base['id'] and run['code_version']==base['code_version'] and run['code']==base['code']
    assert len(result['runs'])==1 and run['stages'][1]['table']==base['stages'][1]['table']
    assert run['execution_observations_version']=='native-statements-v7'
    assert run['stages'][1]['row_correspondence_complete']
    assert any(item['removed_columns']==['y'] for item in run['stages'][1]['transformations'])


def test_direct_table_upgrade_preserves_existing_explanations_and_run_history(tmp_path,monkeypatch):
    from backend import explanations
    monkeypatch.setattr(server,'STORE',tmp_path)
    session=server.create(server.Tables(input_csv='key\na\nb',target_csv='key,rate\na,2\nb,3',sources={'rates':'key,rate\na,2\nb,3'},execution_engine='python',condition='in-situ'))
    session.pop('run',None)
    code="result = input_df.copy()\nfor column in ['rate']:\n    lookup = tables['rates'].copy()\n    result = result.merge(lookup, on='key', how='left')"
    server.execute(session,code,[],'research',groups=[{'statement_indices':[0,1],'output_variable':'result'}])
    current=server.current(session)
    current.update(explanation_status='ready',explanation_meta={'prompt_version':explanations.PROMPT_VERSION,'model':'preserved-test'})
    current['stages'][1]['nl_explanation']={'text':'기존 설명을 유지합니다.','title':'기존 제목','source':'llm'}
    def remove_calls(value):
        if isinstance(value,dict):
            for key in list(value):
                if key.startswith('direct_table_'):value.pop(key)
                else:remove_calls(value[key])
        elif isinstance(value,list):
            for item in value:remove_calls(item)
    remove_calls(session);server.save(session)
    baseline=deepcopy(current);fingerprint=explanations.fingerprint(current)
    client=TestClient(server.app)
    response=client.post(f"/api/sessions/{session['id']}/execution-observations",json={'run_id':current['id']})
    assert response.status_code==200,response.text
    result=response.json();upgraded=result['run']
    assert upgraded['id']==baseline['id'] and upgraded['code']==baseline['code'] and len(result['runs'])==1
    assert [s['table'] for s in upgraded['stages']]==[s['table'] for s in baseline['stages']]
    assert upgraded['explanation_status']=='ready' and upgraded['explanation_meta']==baseline['explanation_meta']
    assert upgraded['stages'][1]['nl_explanation']==baseline['stages'][1]['nl_explanation']
    assert explanations.fingerprint(upgraded)==fingerprint
    assert upgraded['direct_table_observations_version']=='native-table-calls-v1'
    assert len(upgraded['stages'][1]['direct_tables'])==1


def test_changed_or_failed_reobservation_preserves_saved_run(stored,monkeypatch):
    session,client=stored
    base=deepcopy(session['runs'][0])
    def fail(*args,**kwargs):raise ValueError('Test observation failure')
    monkeypatch.setattr(server,'isolated_run',fail)
    result=client.post(f"/api/sessions/{session['id']}/execution-observations",json={'run_id':base['id']}).json()
    assert result['run']['id']==base['id'] and result['run']['code']==base['code']
    assert result['run']['stages'][1]['table']==base['stages'][1]['table']
    assert result['run']['execution_observations_error']=='Test observation failure'
