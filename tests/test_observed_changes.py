from copy import deepcopy
import json

import pytest
import httpx

from backend.engine import parse_table
from backend.pipeline import prepare,assemble
from backend.python_runtime import run as native_run
from backend.transformations import annotate_run
from backend import observed_changes as changes,explanations


def execute(code,csv='x,y\n1,10\n2,20'):
    plan=prepare(code,[{'statement_indices':list(range(len(__import__('ast').parse(code).body))),'output_variable':'result'}],engine='python')
    stages,ops=assemble(native_run(code,parse_table(csv),{},plan),plan)
    return annotate_run(dict(id='executed',code_version=1,code=code,pipeline=plan,stages=stages,operations=ops))


def links(run):
    return [{'step_no':step['step_no'],'change_id':event['id'],'status':'linked' if event['code_evidence']=='executed-effect' else 'ambiguous',
        'operations':[{'candidate_id':cid,'text':'이 코드에서 선택한 값을 계산하거나 선택합니다.'} for cid in event['candidate_ids']]}
        for step in changes.public_contracts(run) for event in step['changes']]


def test_observed_changes_remain_explainable_when_ast_analyzer_cannot_extract_operation(monkeypatch):
    monkeypatch.setattr('backend.transformations.extract',lambda *args,**kwargs:[])
    run=execute("result = input_df.copy()\nresult.columns = ['new', 'other']")
    stage=run['stages'][1]
    assert not any('new' in effect['columns']['added'] for t in stage['transformations'] for effect in t['execution_effects'])
    before=deepcopy(stage['table']);contract=changes.public_contracts(run)[0]
    created=next(event for event in contract['changes'] if event['kind']=='added' and event['column']=='new')
    assert created['code_evidence']=='executed-effect'
    source=next(c for c in contract['code_candidates'] if c['id']==created['candidate_ids'][0])
    assert source['code']=="result.columns = ['new', 'other']" and source['code_location']['start']==2
    changes.apply(run,links(run))
    item=next(t for t in stage['transformations'] if t.get('observed_change_id')==created['id'])
    assert item['code']==source['code'] and item['execution_effects'][0]['columns']['added']==['new']
    assert stage['table']==before and len(run['stages'])==2
    fingerprint=explanations.fingerprint(run)
    annotate_run(run)
    assert any(t['id']==item['id'] for t in stage['transformations'])
    assert explanations.fingerprint(run)==fingerprint


def test_model_cannot_choose_sort_for_deleted_column_or_an_unexecuted_branch():
    run=execute("result = input_df.copy()\nif False:\n    result = result[['y']]\nresult = result[['x']]\nresult = result.sort_values('x')")
    contract=changes.public_contracts(run)[0]
    assert all("[['y']]" not in candidate['code'] for candidate in contract['code_candidates'])
    removal=next(event for event in contract['changes'] if event['kind']=='removed' and event['column']=='y')
    candidates={c['id']:c for c in contract['code_candidates']}
    assert all(candidates[cid]['code']=="result = result[['x']]" for cid in removal['candidate_ids'])
    proposed=links(run)
    proposed[0]['operations']=[{'candidate_id':next(c['id'] for c in contract['code_candidates'] if 'sort_values' in c['code']),'text':'이 열을 제외합니다.'}]
    with pytest.raises(ValueError,match='실행 코드 후보 밖'):changes.apply(run,proposed)
    proposed=links(run);proposed[0]['operations'][0]['candidate_id']='invented-code'
    with pytest.raises(ValueError):changes.apply(run,proposed)


def test_unknown_rows_are_not_reported_as_additions_or_deletions_and_llm_cannot_add_them():
    run=execute("result = input_df.apply(lambda row: row, axis=1)\nresult['new'] = result['x'] * 3")
    contract=changes.public_contracts(run)[0]
    assert not contract['row_correspondence_known']
    assert not any(event['axis']=='rows' for event in contract['changes'])
    proposed=links(run)+[{'step_no':1,'change_id':'invented-deleted-row','status':'unresolved','operations':[]}]
    with pytest.raises(ValueError,match='목록이 일치'):changes.apply(run,proposed)


def test_unresolved_and_out_of_scope_prose_leave_other_change_links_intact():
    run=execute("result = input_df.copy()\nparts = result['Location'].str.split(',', expand=True)\nresult['City'] = parts[0].str.strip()\nresult = result[['City']]",'Location\n" Seoul , Korea "')
    contract=changes.public_contracts(run)[0];proposed=links(run)
    city=next(e for e in contract['changes'] if e['column']=='City')
    selected=next(link for link in proposed if link['change_id']==city['id'])
    selected['operations'][0]['text']='Location을 쉼표로 나눈 뒤 City를 만듭니다.'
    changes.apply(run,proposed)
    assert not any(t.get('observed_change_id')==city['id'] for t in run['stages'][1]['transformations'])
    assert any(t['method']=='observed_change' and 'Location' in t['removed_columns'] for t in run['stages'][1]['transformations'])
    assert next(s for s in run['stages'][1]['observed_change_status'] if s['change_id']==city['id'])['status']=='unresolved'
    selected.update(status='unresolved',operations=[])
    changes.apply(run,proposed)
    assert not any(t.get('observed_change_id')==city['id'] for t in run['stages'][1]['transformations'])


def test_links_do_not_survive_changed_code_results_or_execution_version():
    base=execute("result = input_df.copy()\nresult['new'] = result['x'] * 3")
    changes.apply(base,links(base))
    for field in ('code','data','version'):
        run=deepcopy(base)
        if field=='code':run['code']=run['code'].replace('* 3','* 4')
        elif field=='data':run['stages'][1]['table']['rows'][0]['values']['new']=99
        else:run['id']='another-execution'
        annotate_run(run)
        assert 'observed_change_links' not in run
        assert not any(t['method']=='observed_change' for t in run['stages'][1]['transformations'])


def test_changed_row_outside_model_samples_also_invalidates_persisted_links():
    run=execute("result = input_df.copy()\nresult['new'] = result['x'] * 3",'x\n1\n2\n3\n4\n5\n6')
    changes.apply(run,links(run))
    run['stages'][1]['table']['rows'][5]['values']['new']=123
    annotate_run(run)
    assert 'observed_change_links' not in run


def test_observed_links_support_revision_output_comparison_without_duplicate_ast_ownership():
    from backend.transformation_effects import revision_effects
    baseline=execute("result = input_df.copy()\nresult['new'] = result['x'] * 2")
    candidate=execute("result = input_df.copy()\nresult['new'] = result['x'] * 3")
    changes.apply(candidate,links(candidate))
    revision_effects(candidate,baseline['stages'][1])
    mapped=next(t for t in candidate['stages'][1]['transformations'] if t['method']=='observed_change' and t['output_columns']==['new'])
    assert any('new' in effect['columns']['changed'] for effect in mapped['revision_effects'])
    assert all('new' not in effect['columns']['added'] for effect in mapped['revision_effects'])


def test_cleared_cell_explains_its_changed_row_without_attributing_that_row_to_a_new_column():
    run=execute("result = input_df.copy()\nresult['x'] = result['x'].where(result['x'] > 1)\nresult['new'] = 0")
    changes.apply(run,links(run))
    items=[item for item in run['stages'][1]['transformations'] if item['method']=='observed_change']
    cleared=next(item for item in items if item['output_columns']==['x'] and any(e['cells']['removed'] for e in item['execution_effects']))
    assert any(e['rows']['changed'] for e in cleared['execution_effects'])
    added=next(item for item in items if item['output_columns']==['new'])
    assert all(not e['rows']['changed'] for e in added['execution_effects'])


def test_step_only_attribution_is_explicitly_a_candidate_and_targets_are_server_owned():
    run=execute("result = input_df.copy()\nresult['new'] = result['x'] * 3")
    for stage in run['stages'][1:]:
        stage['operations']=[]
        stage['operation_observations']=[dict(op,kind='observed',code_location=stage['code_location'],expression_location=None) for op in stage['operation_observations']]
    contract=changes.public_contracts(run)[0]
    assert contract['changes'][0]['code_evidence']=='executed-step-only'
    proposed=links(run)
    proposed[0]['status']='linked'  # Cannot promote the model's confidence to execution evidence.
    proposed[0]['operations']=proposed[0]['operations'][-1:]
    proposed[0]['operations'][0]['execution_effects']={'columns':{'added':['invented']}}
    changes.apply(run,proposed)
    item=next(t for t in run['stages'][1]['transformations'] if t['method']=='observed_change')
    assert item['mapping_status']=='candidate'
    assert item['execution_effects'][0]['columns']['added']==['new']
    assert item['execution_effects'][0]['attribution']=='llm-step-candidate'


def test_bounded_model_context_excludes_target_requirements_and_unrelated_values():
    run=execute("result = input_df.copy()\nresult['new'] = result['x'] * 3",'x,note\n1,PRIVATE_UNRELATED_NOTE')
    run.update(target_csv='SECRET_TARGET',requirements='SECRET_REQUIREMENT',comparison={'answer':'SECRET_EVALUATION'})
    payload=json.dumps(explanations.model_context(run))
    assert all(value not in payload for value in ('SECRET_TARGET','SECRET_REQUIREMENT','SECRET_EVALUATION','PRIVATE_UNRELATED_NOTE'))
    assert 'observed_changes' in payload and '"new": 3' in payload


@pytest.mark.parametrize('repair_succeeds',[True,False])
def test_scope_repair_requests_only_invalid_prose_and_keeps_other_links(monkeypatch,repair_succeeds):
    run=execute("result = input_df.copy()\nparts = result['Location'].str.split(',', expand=True)\nresult['City'] = parts[0].str.strip()\nresult = result[['City']]",'Location\n" Seoul , Korea "')
    proposed=links(run)
    target=next(link for link in proposed if link['change_id']==next(event['id'] for event in changes.public_contracts(run)[0]['changes'] if event['column']=='City'))
    target['operations'][0]['text']='Location을 분리한 값의 공백을 제거합니다.'
    data={'steps':[{'step_no':1,'title':'열 변환','text':'현재 열을 처리합니다.'}],
        'columns':[{**{k:t[k] for k in ('step_no','operation_no','column')},'text':'현재 값 처리'} for t in explanations.column_targets(run)],
        'transformations':[{**{k:t[k] for k in ('step_no','transformation_no')},'text':'현재 값을 처리합니다.'} for t in explanations.transformation_targets(run)],
        'change_links':deepcopy(proposed)}
    monkeypatch.setenv('OPENAI_API_KEY','test-api-key')
    calls=[]
    def post(self,url,headers,json):
        calls.append(json)
        issues=__import__('json').loads(json['input'])
        assert len(issues)==1 and issues[0]['code']=="result['City'] = parts[0].str.strip()"
        assert 'Location' in issues[0]['forbidden_columns']
        if not repair_succeeds:return httpx.Response(503)
        return httpx.Response(200,json={'status':'completed','output':[{'content':[{'type':'output_text',
            'text':__import__('json').dumps({'operations':[{'key':issues[0]['key'],'text':'선택한 값의 양끝 공백을 제거해 City 열에 저장합니다.'}]})}]}]})
    monkeypatch.setattr(httpx.Client,'post',post)
    explanations.repair_change_prose(run,data)
    assert len(calls)==1
    assert [l for l in data['change_links'] if l['change_id']!=target['change_id']]==[l for l in proposed if l['change_id']!=target['change_id']]
    changes.apply(run,data['change_links'])
    city=[t for t in run['stages'][1]['transformations'] if t.get('observed_change_id')==target['change_id']]
    assert bool(city)==repair_succeeds
    assert any(t['method']=='observed_change' and 'Location' in t['removed_columns'] for t in run['stages'][1]['transformations'])
