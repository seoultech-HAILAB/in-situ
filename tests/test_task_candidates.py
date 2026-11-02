import io
import json
import pickle
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend.access import password_hash
from scripts.analyze_p0_synth import DataReader,read_frame,shape


@pytest.fixture
def client(tmp_path,monkeypatch):
    folder=tmp_path/'cases';folder.mkdir()
    fixture={'id':'SYN-01','title':'Fixture','description':'Keep quantities of at least two, then compute values.',
        'input_csv':'qty,price\n1,10\n2,20\n3,30','target_csv':'qty,price,value\n2,20,40\n3,30,90',
        'initial_code':"s1 = input_df.loc[input_df['qty'] > 2].copy()\nresult = s1.assign(value=s1['qty'] * s1['price'])",
        'reference_code':"s1 = input_df.loc[input_df['qty'] >= 2].copy()\nresult = s1.assign(value=s1['qty'] * s1['price'])",
        'steps':[{'statement_indices':[0],'label':'Filter','output_variable':'s1'},
                 {'statement_indices':[1],'label':'Calculate','output_variable':'result'}],
        'provenance':{'initial_origin':'authored_mock','original_task_id':'fixture-original','actual_luna_program':False},
        'researcher_notes':{'injected_change':'SECRET-RESEARCHER-ANNOTATION','initial_trace_levels':['detailed','detailed']}}
    (folder/'SYN-01.json').write_text(json.dumps(fixture),encoding='utf-8')
    store=tmp_path/'sessions';store.mkdir()
    monkeypatch.setattr(server,'STORE',store)
    monkeypatch.setenv('TRACE_TASK_DIR',str(folder))
    monkeypatch.delenv('TRACE_ACCESS_FILE',raising=False)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    return TestClient(server.app)


def test_candidates_execute_frozen_code_and_do_not_autofix(client):
    listing=client.get('/api/task-candidates').json()
    assert listing[0]['initial_origin']=='authored_mock'
    bad=client.post('/api/task-candidates/SYN-01/load',json={'condition':'C'}).json()
    assert bad['status']=='ready' and not bad['run']['comparison']['matches']
    assert bad['run']['mode']=='research' and bad['task_provenance']['actual_luna_program'] is False
    rid=bad['run']['id']
    for condition in ('ex','in-situ'):
        assert client.post(f"/api/sessions/{bad['id']}/condition",json={'condition':condition}).json()['run']['id']==rid
    good=client.post('/api/task-candidates/SYN-01/load',json={'variant':'reference'}).json()
    assert good['id']!=bad['id'] and good['run']['comparison']['matches']
    assert good['run']['code_version']==1 and good['task_provenance']['loaded_origin']=='authored_reference'
    original=client.get(f"/api/sessions/{bad['id']}").json()
    assert original['run']['id']==rid and not original['run']['comparison']['matches']
    failed=client.post(f"/api/sessions/{bad['id']}/generate",json={'request':'Include quantities of two.'}).json()
    assert failed['status']=='failed' and failed['run']['id']==rid


def test_participant_cannot_get_candidate_origins_or_reference_code(client,tmp_path,monkeypatch):
    s=client.post('/api/task-candidates/SYN-01/load',json={}).json()
    owned=server.read(s['id']);owned['participant_id']='viewer';server.save(owned)
    access=tmp_path/'access.json'
    access.write_text(json.dumps({'signing_key':'test-key-'*8,'users':{
        'viewer':{'role':'participant','password_hash':password_hash('test-password')}},'allowed_origins':[]}),encoding='utf-8')
    monkeypatch.setenv('TRACE_LEGACY_AUTH','1')
    monkeypatch.setenv('TRACE_ACCESS_FILE',str(access))
    client.post('/auth/login',data={'username':'viewer','password':'test-password'},follow_redirects=False)
    assert client.get('/api/task-candidates').status_code==403
    assert client.get('/api/woz-tasks').json()==[]
    assert client.get('/api/woz-tasks/SYN-01/input').status_code==404
    assert client.post('/api/woz-tasks/SYN-01/start',json={
        'input_csv':'qty,price\n1,10\n2,20\n3,30','target_csv':'qty,price,value\n2,20,40\n3,30,90'}).status_code==422
    assert client.post('/api/task-candidates/SYN-01/load',json={'variant':'reference'}).status_code==403
    response=client.get(f"/api/sessions/{s['id']}?research=1",headers={'X-Trace-View':'researcher'})
    assert response.status_code==200
    public=response.json()
    assert 'task_provenance' not in public and 'comparison' not in public['run']
    assert 'SECRET-RESEARCHER-ANNOTATION' not in json.dumps(public)
    assert public['run']['code']==s['run']['code']


def test_catalog_input_validation_and_empty_catalog(client,tmp_path,monkeypatch):
    assert client.post('/api/task-candidates/not-present/load',json={}).status_code==404
    assert client.post('/api/task-candidates/SYN-01/load',json={'variant':'something'}).status_code==422
    assert client.post('/api/task-candidates/SYN-01/load',json={'condition':'not-a-condition'}).status_code==422
    monkeypatch.setenv('TRACE_TASK_DIR',str(tmp_path/'empty'))
    assert client.get('/api/task-candidates').json()==[]


def test_error_guide_is_initial_ground_truth_and_not_participant_task_data(client):
    file=server.candidates.directory()/'SYN-01.json'
    candidate=json.loads(file.read_text(encoding='utf-8'))
    assert client.get('/api/task-candidates').json()[0]['diagnostics']['status']=='unknown'
    candidate['researcher_notes'].update(fault_steps=[1],error_explanation='SECRET-ERROR-GUIDE: excludes qty=2')
    file.write_text(json.dumps(candidate),encoding='utf-8')
    guide=client.get('/api/task-candidates').json()[0]['diagnostics']
    assert guide['status']=='error' and guide['fault_steps']==[1]
    error=guide['errors'][0]
    assert error['label']=='Filter' and error['code_location']=={'start':1,'end':1}
    assert 'SECRET-ERROR-GUIDE' in error['problem']
    assert '-s1' in error['code_diff'] and '+s1' in error['code_diff'] and '>= 2' in error['code_diff']
    # Published task summaries and Input/Target previews retain explicit allowlists.
    client.post('/api/task-candidates/SYN-01/publication',json={'visible':True})
    for url in ('/api/study-tasks','/api/woz-tasks','/api/study-tasks/SYN-01/input','/api/woz-tasks/SYN-01/input'):
        response=client.get(url)
        assert response.status_code==200
        assert 'SECRET-ERROR-GUIDE' not in response.text and 'diagnostics' not in response.json()
    # An explicitly empty key is a normal control, distinct from missing information.
    candidate['researcher_notes']['fault_steps']=[]
    candidate['initial_code']=candidate['reference_code']
    file.write_text(json.dumps(candidate),encoding='utf-8')
    guide=client.get('/api/task-candidates').json()[0]['diagnostics']
    assert guide['status']=='normal' and guide['errors']==[] and guide['fault_steps']==[]


def test_data_only_reader_and_nested_profile(tmp_path):
    frame=pd.DataFrame({'x':[[1,2],[1,2]],'y':[1,2]})
    # The archived Synth artifacts use object column indexes, not pandas 3 StringArray.
    frame.columns=pd.Index(['x','y'],dtype=object)
    file=tmp_path/'data.pkl';file.write_bytes(pickle.dumps(frame))
    pd.testing.assert_frame_equal(read_frame(file),frame)
    assert shape(frame)['nested_values'] and shape(frame)['duplicate_rows'] is None
    # Merely referring to a process primitive is rejected, without executing it.
    with pytest.raises(pickle.UnpicklingError):
        DataReader(io.BytesIO(b'cos\nsystem\n.')).load()
