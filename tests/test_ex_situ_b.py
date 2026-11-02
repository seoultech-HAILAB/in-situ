"""Retired B2 imports normalize to Ex-situ; active switching uses two IDs."""
from fastapi.testclient import TestClient
import backend.app as server


def test_ex_situ_b_persists_switches_and_has_unambiguous_event_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'STORE', tmp_path)
    c = TestClient(server.app)
    s = c.post('/api/demo', json={'condition': 'B2'}).json()
    sid, run = s['id'], s['run']
    assert s['condition'] == 'ex' and s['condition_variant'] == 'ex-situ-review-v2'
    assert c.get(f'/api/sessions/{sid}').json()['condition'] == 'ex'
    assert 'legacy_condition' not in s
    for condition in ['ex', 'in-situ', 'ex']:
        shown = c.post(f'/api/sessions/{sid}/condition', json={'condition': condition}).json()
        assert shown['condition'] == condition and shown['run'] == run
    participant = c.get(f'/api/sessions/{sid}', headers={'X-Trace-View': 'participant'}).json()
    assert 'comparison' not in participant['run'] and 'events' not in participant
    assert participant['run']['stages'] == run['stages']
    # Delayed events must describe their original presentation, not the new one.
    c.post(f'/api/sessions/{sid}/condition', json={'condition': 'in-situ'})
    assert c.post(f'/api/sessions/{sid}/events', json={
        'event': 'step_selected', 'condition': 'B2', 'execution_version': run['id'],
        'data': {'step_id': run['stages'][1]['id']}
    }).status_code == 200
    exported = c.get(f'/api/sessions/{sid}/export').json()
    assert exported['condition_variant'] == 'in-situ-review-v2'
    last = exported['events'][-1]
    assert last['condition'] == 'ex' and last['condition_variant'] == 'ex-situ-review-v2'
    assert last['execution_version'] == run['id']


def test_ex_situ_b_selected_step_revision_undo_and_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'STORE', tmp_path)
    c = TestClient(server.app)
    initial = c.post('/api/demo', json={'condition': 'B2'}).json()
    sid, old = initial['id'], initial['run']
    step = old['stages'][1]
    updated = c.post(f'/api/sessions/{sid}/generate', json={
        'request': '수량이 정확히 2인 주문도 포함', 'scope': 'step',
        'base_run_id': old['id'], 'context': {'step_id': step['id'], 'selection': None}
    }).json()
    assert updated['condition'] == 'ex' and updated['status'] == 'ready'
    assert updated['run']['comparison']['matches']
    assert [s['id'] for s in updated['run']['stages']] == [s['id'] for s in old['stages']]
    assert updated['run']['stages'][1]['table'] != step['table']
    assert updated['run']['stages'][-1]['table'] != old['stages'][-1]['table']
    exported = c.get(f'/api/sessions/{sid}/export').json()
    revision = next(e for e in exported['events'] if e['event'] == 'revision_requested')
    assert revision['data']['context']['step_id'] == step['id']
    assert revision['condition_variant'] == 'ex-situ-review-v2'
    replayed = c.post('/api/replay', json={'session': exported, 'condition': 'B2'}).json()
    assert replayed['condition'] == 'ex' and replayed['run']['code'] == old['code']
    assert c.get(f"/api/sessions/{replayed['id']}").json()['condition'] == 'ex'
    undone = c.post(f'/api/sessions/{sid}/undo', json={}).json()
    assert undone['condition'] == 'ex' and undone['run'] == old
