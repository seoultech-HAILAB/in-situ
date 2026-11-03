import ast
from copy import deepcopy

import pytest

from backend import candidates, observed_changes
from backend.engine import parse_table
from backend.pipeline import prepare, assemble
from backend.python_runtime import run as native_run
from backend.transformations import annotate_run


def execute(code, csv, sources=None, groups=None):
    groups = groups or [{'statement_indices':list(range(len(ast.parse(code).body))), 'output_variable':'result'}]
    plan = prepare(code, groups, engine='python')
    records = native_run(code, parse_table(csv), {k:parse_table(v) for k,v in (sources or {}).items()}, plan)
    stages, ops = assemble(records, plan)
    return annotate_run(dict(id='constructed', code_version=1, code=code, pipeline=plan, stages=stages, operations=ops))


@pytest.fixture(scope='module')
def selected():
    runs = {}
    for tid in ('PILOT4-T01','PILOT4-T03','PILOT4-T05'):
        task = candidates.load(tid)
        runs[tid] = execute(task['initial_code'], task['input_csv'], task.get('sources'), task['steps'])
    return runs


def candidate_lines(contract, column, kind):
    event = next(e for e in contract['changes'] if e['column']==column and e['kind']==kind)
    lookup = {c['id']:c for c in contract['candidates']}
    return {lookup[cid]['code_location']['start'] for cid in event['candidate_ids']}


def test_t05_construction_keeps_real_code_and_removes_false_menu_deletions(selected):
    run = selected['PILOT4-T05']
    contracts = observed_changes.contracts(run)
    assert len(run['stages'])==5
    assert [(len(s['table']['rows']),len(s['table']['columns'])) for s in run['stages'][1:]]==[(28,2),(28,3),(13,5),(4,4)]
    assert candidate_lines(contracts[0], 'Item', 'added') == {13}
    assert candidate_lines(contracts[0], 'Price', 'added') == {13}
    assert 14 not in candidate_lines(contracts[0], 'Organic Coffee', 'removed')
    third = contracts[2]
    assert len(third['changes'])==5
    assert all(e['kind']=='added' for e in third['changes'])
    assert run['stages'][3]['comparison_input_kind']=='constructed'
    assert run['stages'][3]['input']['columns']==[]
    for column in ('Person','Item','Price','Weekly Cost'):
        assert candidate_lines(third, column, 'added')=={36}
    assert candidate_lines(third, 'Count', 'added')=={30}
    fourth = contracts[3]
    assert candidate_lines(fourth,'Monthly Spend','added')=={43}
    assert candidate_lines(fourth,'Potential Savings','added')=={44}
    assert candidate_lines(fourth,'Worthwhile?','added')=={45}
    for column in ('Item','Count','Price','Weekly Cost'):
        assert candidate_lines(fourth,column,'removed')=={47}


def test_t05_links_produce_local_calculation_snippets_and_reject_unrelated_code(selected):
    run = deepcopy(selected['PILOT4-T05'])
    links = []
    for contract in observed_changes.contracts(run):
        for event in contract['changes']:
            assert event['candidate_ids'], (contract['step_no'], event['column'])
            links.append({'step_no':contract['step_no'],'change_id':event['id'],'status':'linked',
                'operations':[{'candidate_id':cid,'text':'선택한 값을 계산하거나 출력 표를 구성합니다.'} for cid in event['candidate_ids']]})
    observed_changes.apply(run,links)
    fourth = run['stages'][4]
    monthly = next(t for t in fourth['transformations'] if t.get('method')=='observed_change' and t['output_columns']==['Monthly Spend'])
    assert monthly['code']=='monthly_spend = round(weekly_spend * 4, 2)'
    assert 'source_context' not in monthly and monthly['mapping_status']=='matched'
    assert any(e['columns']['added']==['Monthly Spend'] for e in monthly['execution_effects'])
    assert all(s['status']!='unresolved' for stage in run['stages'][1:] for s in stage['observed_change_status'])
    original_links={t['id']:(t['code'],t['code_location']) for stage in run['stages'][1:] for t in stage['transformations'] if t.get('method')=='observed_change'}
    for _ in range(2):
        annotate_run(run)
        assert {t['id']:(t['code'],t['code_location']) for stage in run['stages'][1:] for t in stage['transformations'] if t.get('method')=='observed_change'}==original_links
    contract = observed_changes.contracts(run)[3]
    sort = next(c for c in contract['candidates'] if c['code_location']['start']==49)
    wrong = deepcopy(links)
    next(link for link in wrong if link['step_no']==4)['operations']=[{'candidate_id':sort['id'],'text':'정렬합니다.'}]
    with pytest.raises(ValueError,match='실행 코드 후보 밖'):
        observed_changes.apply(run,wrong)


def test_no_dataframe_reference_uses_empty_construction_input_not_last_source():
    code="values = input_df['original'].tolist()\nrows = [[value, value * 2] for value in values]\nresult = pd.DataFrame(rows, columns=['a','b'])"
    run = execute(code, 'original\n9', {'unrelated':'wrong\n10'},[
        {'statement_indices':[0],'output_variable':'input_df'},
        {'statement_indices':[1,2],'output_variable':'result'}])
    stage = run['stages'][2]
    assert stage['input']['columns']==[] and stage['inputs'][0]['ref']=='constructed'
    assert not any(event['kind']=='removed' for event in observed_changes.contracts(run)[-1]['changes'])
    assert stage['executed_statements'] and stage['operation_observations']


def test_unexecuted_container_calculation_and_unused_frame_are_not_producers():
    code="rows = []\nfor value in input_df['x'].tolist():\n    amount = value * 4\n    if False:\n        amount = value * 100\n    rows.append([amount])\nunused = pd.DataFrame([[99]], columns=['total'])\nresult = pd.DataFrame(rows, columns=['total'])"
    run = execute(code,'x\n1')
    contract = observed_changes.contracts(run)[0]
    assert candidate_lines(contract,'total','added')=={3}
    assert all('100' not in c['code'] for c in contract['candidates'])


def test_t01_t03_keep_steps_and_verified_key_links(selected):
    first = selected['PILOT4-T01']
    one = observed_changes.contracts(first)
    assert candidate_lines(one[0],'City','added')=={11}
    assert candidate_lines(one[3],'Location','removed')=={46}
    third = selected['PILOT4-T03']
    three = observed_changes.contracts(third)
    assert candidate_lines(three[2],'Revenue','added')=={26}
    for column in ('Weight (kg)','Quant per Q','Price (£) per pack'):
        assert candidate_lines(three[1],column,'added')=={19}
    assert len(first['stages'])==len(third['stages'])==5
    for contract in one+three:
        assert all(e['candidate_ids'] for e in contract['changes']), contract['step_no']


def test_saved_t05_upgrades_comparison_metadata_preserving_every_result(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import backend.app as server
    monkeypatch.setattr(server,'STORE',tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    loaded=server.start_study('PILOT4-T05',server.StudyStart(condition='in-situ'),preview=True,woz=True)
    session=server.read(loaded['id'])
    run=server.current(session)
    original=deepcopy(run)
    run['execution_observations_version']='native-statements-v3'
    for stage in run['stages'][1:]:
        stage['execution_observations_version']='native-statements-v3'
        stage.pop('executed_statements',None)
    run['stages'][3]['input']=deepcopy(session['sources']['table_2'])
    run['stages'][3]['inputs']=[{'ref':'source:table_2','variable':'tables:table_2','table':deepcopy(session['sources']['table_2'])}]
    server.save(session)
    response=TestClient(server.app).post(f"/api/sessions/{session['id']}/execution-observations",json={'run_id':run['id']})
    assert response.status_code==200,response.text
    upgraded=response.json()['run']
    assert upgraded['execution_observations_version']=='native-statements-v7'
    assert upgraded['id']==original['id'] and upgraded['code_version']==original['code_version'] and upgraded['code']==original['code']
    assert [s['table'] for s in upgraded['stages']]==[s['table'] for s in original['stages']]
    assert upgraded['stages'][3]['input']['columns']==[]
    assert upgraded['stages'][3]['executed_statements']
