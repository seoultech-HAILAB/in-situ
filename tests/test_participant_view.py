"""Study blinding: observers receive transformations, never evaluator verdicts."""
from fastapi.testclient import TestClient
import backend.app as server

PARTICIPANT={'X-Trace-View':'participant'}
RESEARCHER={'X-Trace-View':'researcher'}


def test_participant_never_receives_grading_for_wrong_correct_or_confirmed_runs(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'STORE',tmp_path)
    c=TestClient(server.app)
    s=c.post('/api/demo',json={},headers=PARTICIPANT).json()
    sid=s['id'];rid=s['run']['id']
    assert 'comparison' not in s['run'] and all('comparison' not in r for r in s['runs'])
    assert 'events' not in s and s['status']=='ready'
    researcher=c.get(f'/api/sessions/{sid}',headers=RESEARCHER).json()
    assert not researcher['run']['comparison']['matches']
    assert s['run']['stages']==researcher['run']['stages']
    for condition in ('ex','in-situ'):
        visible=c.post(f'/api/sessions/{sid}/condition',json={'condition':condition},headers=PARTICIPANT).json()
        assert visible['run']==s['run']
    confirmed=c.post(f'/api/sessions/{sid}/confirm',json={},headers=PARTICIPANT).json()
    assert confirmed['confirmed']['run_id']==rid # User confirmation is not a correctness verdict.
    assert 'comparison' not in confirmed['run']
    revised=c.post(f'/api/sessions/{sid}/generate',json={'request':'수량이 정확히 2인 주문도 포함'},headers=PARTICIPANT).json()
    assert revised['status']=='ready' and 'comparison' not in revised['run']
    exported=c.get(f'/api/sessions/{sid}/export',headers=RESEARCHER).json()
    assert exported['runs'][-1]['comparison']['matches']
    assert not exported['runs'][0]['comparison']['matches']
    projected=c.get(f'/api/sessions/{sid}/export',headers=PARTICIPANT).json()
    assert all('comparison' not in r for r in projected['runs']) and 'events' not in projected


def test_projection_preserves_table_cells_and_hides_failure_localization(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'STORE',tmp_path)
    c=TestClient(server.app)
    csv='comparison,events,failure,partial_stages\n1,2,3,4'
    s=c.post('/api/sessions',json={'input_csv':csv,'target_csv':csv},headers=PARTICIPANT).json()
    sid=s['id']
    s=c.post(f'/api/sessions/{sid}/research-code',json={'code':'result = input_df.copy()'},headers=PARTICIPANT).json()
    assert s['run']['stages'][-1]['table']['rows'][0]['values']=={'comparison':1,'events':2,'failure':3,'partial_stages':4}
    good=s['run']['id']
    broken=c.post(f'/api/sessions/{sid}/research-code',json={'code':"result = input_df[['missing']].copy()"},headers=RESEARCHER).json()
    assert broken['error']['candidate_code'] and broken['failed_attempts']
    visible=c.get(f'/api/sessions/{sid}',headers=PARTICIPANT).json()
    assert visible['run']['id']==good and visible['status']=='failed'
    assert set(visible['error'])=={'phase','message'}
    assert 'missing' not in visible['error']['message']
    assert 'partial_stages' not in visible['error'] and 'failed_attempts' not in visible
    assert visible['input']['rows'][0]['values']['comparison']==1
