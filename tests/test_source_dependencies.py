import ast
import copy
import json
from pathlib import Path
import pytest
from backend.transformations import extract,annotate_run
from backend.transformation_selection import selected_transformation,validate_selected_edit
from backend.pipeline import prepare,assemble
from backend.python_runtime import run as native_run
from backend.engine import parse_table
from backend import explanations


CITY_CODE="""stores = input_df.copy()
location_parts = stores['Location'].str.split(',', n=1, expand=True)
stores['City'] = location_parts[0].str.strip()
stores['Country'] = location_parts[1].str.strip()
result = stores
"""


def city(code=CITY_CODE,indices=None):
    return next(t for t in extract(code,indices or list(range(len(ast.parse(code).body)))) if t['output_columns']==['City'] and t['method']=='strip')


def snapshot(code=CITY_CODE):
    plan=prepare(code,[{'statement_indices':list(range(len(ast.parse(code).body))),'output_variable':'result'}],engine='python')
    stages,ops=assemble(native_run(code,parse_table('Location\n" Seoul , Korea "'),{},plan),plan)
    return annotate_run({'id':'current-run','code_version':1,'code':code,'pipeline':plan,'stages':stages,'operations':ops})


def test_city_tracks_location_split_part_and_strip_and_keeps_its_own_edit_identity():
    item=city();context=item['source_context']
    assert context['original_columns']==[{'table':'input_df','column':'Location'}]
    assert context['complete']
    assert [d['symbol'] for d in context['definitions']]==['stores','location_parts']
    assert all(d['read_only'] for d in context['definitions'])
    assert 'Country' not in str(context)
    for detail in ('Location',"','",'최대 1회','첫 번째','공백','City'):assert detail in context['text']
    assert item['code']=="location_parts[0].str.strip()"
    assert item['code_location']['start']==3
    assert item['output_columns']==['City']


def test_dependencies_cross_step_boundaries_and_do_not_use_future_reassignments():
    code=CITY_CODE+"location_parts = stores['Country'].str.split('-')\n"
    item=city(code,[2])
    assert item['source_context']['original_columns'][0]['column']=='Location'
    assert len(item['source_context']['definitions'])==2


def test_nearest_definition_and_aliases_reach_only_the_used_original_column():
    code="frame = input_df[['Location','Unrelated']]\nalias = frame.copy()\nparts = alias['Location'].str.split(';', expand=True)\nlocation_parts = parts\nresult = alias.copy()\nresult['City'] = location_parts[0].str.strip()"
    context=city(code)['source_context']
    assert context['original_columns']==[{'table':'input_df','column':'Location'}]
    assert "';'" in context['text'] and 'Unrelated' not in context['text']
    assert {d['symbol'] for d in context['definitions']}=={'frame','alias','parts','location_parts'}


def test_column_reassignment_is_traced_before_the_temporary_variable():
    code=CITY_CODE.replace("location_parts =", "stores['Location'] = stores['Location'].astype(str)\nlocation_parts =",1)
    context=city(code)['source_context']
    assert any(d['symbol']=="stores['Location']" for d in context['definitions'])
    assert '문자열' in context['text'] and 'Location' in context['text']


def test_assignment_destination_is_never_misidentified_as_an_original_input_column():
    code=CITY_CODE.replace("location_parts[0].str.strip()","location_parts[0]")
    item=next(t for t in extract(code,list(range(5))) if t['output_columns']==['City'])
    assert item['source_context']['original_columns']==[{'table':'input_df','column':'Location'}]
    assert item['source_context']['complete']


def test_helper_parameter_resolution_uses_call_site_instead_of_unrelated_global_name():
    code="def clean(parts):\n    return parts[0].str.strip()\nlocation_parts = input_df['Location'].str.split(',', expand=True)\nresult = input_df.assign(City=clean(location_parts))"
    item=city(code)
    assert item['source_context']['original_columns']==[{'table':'input_df','column':'Location'}]
    assert item['source_context']['definitions'][0]['symbol']=='location_parts'
    assert item['code_location']['start']==2


def test_temporary_created_by_helper_includes_helper_definition_and_original_split():
    code="def split_location(value):\n    return value.str.split(',', n=1, expand=True)\nstores = input_df.copy()\nlocation_parts = split_location(stores['Location'])\nstores['City'] = location_parts[0].str.strip()\nresult = stores"
    context=city(code)['source_context']
    assert context['original_columns']==[{'table':'input_df','column':'Location'}]
    assert context['complete']
    assert any(d['symbol']=='split_location' and d['code'].startswith('def split_location') for d in context['definitions'])
    assert '최대 1회' in context['text'] and '첫 번째' in context['text']


def test_conditional_or_unresolved_definitions_do_not_claim_complete_correspondence():
    code="location_parts = unknown\n"+CITY_CODE.split('\n',2)[2]
    assert not city(code)['source_context']['complete']
    code="stores = input_df.copy()\nif flag:\n    location_parts = stores['Location'].str.split(',')\nstores['City'] = location_parts[0].str.strip()"
    assert not city(code)['source_context']['complete']


def test_upstream_definition_changes_invalidate_the_description_with_unchanged_current_code():
    run=snapshot();stage=run['stages'][1]
    item=next(t for t in stage['transformations'] if t['output_columns']==['City'])
    old_code=item['code'];old_id=item['id'];old_context=item['source_context']['fingerprint']
    item['description']={'text':'stale isolated description','source':'llm'}
    old_fingerprint=explanations.fingerprint(run)
    run['code']=run['code'].replace("split(',',", "split(';',")
    annotate_run(run)
    current=next(t for t in run['stages'][1]['transformations'] if t['output_columns']==['City'])
    assert current['code']==old_code and current['id']==old_id
    assert current['source_context']['fingerprint']!=old_context
    assert current['description']['source']=='ast' and 'stale' not in current['description']['text']
    assert explanations.fingerprint(run)!=old_fingerprint


def test_llm_payload_gets_read_only_definitions_and_source_path_but_no_table_values():
    run=snapshot();payload=explanations.model_context(run)
    target=next(t for t in payload['transformation_targets'] if t['output_columns']==['City'])
    assert target['source_context']['original_columns'][0]['column']=='Location'
    assert 'split' in target['source_context']['definitions'][-1]['code']
    assert ' Seoul ' not in json.dumps(payload)


def test_reference_definitions_cannot_replace_the_selected_edit_target():
    run=snapshot();item=city()
    selection=selected_transformation(run,{'step_id':run['stages'][1]['id'],'transformation_id':item['id'],'execution_version':run['id']})
    assert selection['code']==item['code'] and selection['reference_definitions_read_only']
    validate_selected_edit(CITY_CODE.replace('location_parts[0].str.strip()',"location_parts[0].str.strip().str.title()"),run,selection,'step')
    with pytest.raises(ValueError,match='현재 선택한 연산 밖'):
        validate_selected_edit(CITY_CODE.replace("split(',',", "split(';',"),run,selection,'step')
    with pytest.raises(ValueError,match='현재 선택한 연산 밖'):
        validate_selected_edit(CITY_CODE.replace('location_parts[1].str.strip()',"location_parts[1].str.strip().str.upper()"),run,selection,'step')
    with pytest.raises(ValueError,match='실행 버전'):
        selected_transformation(run,{'step_id':run['stages'][1]['id'],'transformation_id':item['id'],'execution_version':'old-run'})


def test_actual_bundled_city_expression_has_location_context():
    for path in Path('tasks/candidates').glob('*.json'):
        candidate=json.loads(path.read_text(encoding='utf-8'))
        code=candidate.get('initial_code','')
        if "location_parts[0].str.strip()" not in code:continue
        context=city(code)['source_context']
        assert any(c['column']=='Location' for c in context['original_columns'])
        assert any('location_parts =' in d['code'] for d in context['definitions'])
        return
    pytest.fail('Bundled City regression fixture not found')


def test_chat_edit_receives_source_context_but_only_current_operation_can_change(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from backend import app as server
    from backend.generation import Proposal
    monkeypatch.setattr(server,'STORE',tmp_path)
    client=TestClient(server.app)
    s=client.post('/api/sessions',json={'input_csv':'Location\n" Seoul , Korea "','target_csv':'City\nSeoul','execution_engine':'python','condition':'in-situ'}).json()
    sid=s['id']
    groups=[{'statement_indices':list(range(5)),'output_variable':'result'}]
    s=client.post(f'/api/sessions/{sid}/research-code',json={'code':CITY_CODE,'steps':groups}).json()
    before=copy.deepcopy(s['run']);item=next(t for t in before['stages'][1]['transformations'] if t['output_columns']==['City'])
    class Model:
        bad=False
        def generate(self,inp,target,req,old,request,context):
            selected=context['selected_transformation']
            assert selected['code']=="location_parts[0].str.strip()"
            assert selected['source_context']['original_columns'][0]['column']=='Location'
            assert selected['reference_definitions_read_only']
            step=context['target_step']
            code=step['code'].replace("split(',',","split(';',") if self.bad else step['code'].replace('location_parts[0].str.strip()','location_parts[0].str.strip().str.lower()')
            return Proposal(base_run_id=context['base_run_id'],changes=[{'action':'replace','step_id':step['id'],'code':code}])
    model=Model();monkeypatch.setattr(server,'generator',model)
    def request(run,selection):
        return client.post(f'/api/sessions/{sid}/generate',json={'request':'현재 연산 수정','scope':'step','base_run_id':run['id'],'context':{'step_id':run['stages'][1]['id'],'transformation_id':selection['id'],'execution_version':run['id']}}).json()
    changed=request(before,item)
    assert changed['status']=='ready',changed.get('error')
    assert changed['run']['stages'][1]['table']['rows'][0]['values']['City']=='seoul'
    assert "split(',', n=1" in changed['run']['code']
    assert changed['run']['transformation_edit']['target_id']==item['id']
    model.bad=True
    selected=next(t for t in changed['run']['stages'][1]['transformations'] if t['output_columns']==['City'] and t['method']=='strip')
    rejected=request(changed['run'],selected)
    assert rejected['status']=='failed' and '현재 선택한 연산 밖' in rejected['error']['message']
    assert rejected['run']['id']==changed['run']['id']
