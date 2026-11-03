import json

import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend.generation import Proposal
from backend.review_context import resolve_review_target


@pytest.fixture
def review_session(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'STORE', tmp_path)
    monkeypatch.delenv('TRACE_ACCESS_FILE', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    client = TestClient(server.app)
    session = client.post('/api/sessions', json={
        'input_csv': 'qty,price\n1,10\n2,20\n3,30',
        'target_csv': 'qty,price,value\n2,20,40\n3,30,90', 'condition': 'C',
    }).json()
    session = client.post(f"/api/sessions/{session['id']}/research-code", json={
        'code': "s1 = input_df.loc[input_df['qty'] > 2].copy()\nresult = s1.assign(value=s1['qty'] * s1['price'])",
        'execution_engine': 'python',
    }).json()
    assert session['status'] == 'ready'
    first = session['run']['stages'][1]['id']

    class Generator:
        calls = []
        def generate(self, inp, target, requirements, code, request, context):
            self.calls.append(context)
            return Proposal(base_run_id=context['base_run_id'], changes=[{
                'action': 'replace', 'step_id': first,
                'code': "s1 = input_df.loc[input_df['qty'] >= 2].copy()", 'label': 'Filter',
            }])
    generator = Generator()
    monkeypatch.setattr(server, 'generator', generator)
    return client, session, generator


def request_for(session, target, scope='step'):
    return {'request': '수량 2인 행도 유지해 주세요.', 'scope': scope,
            'base_run_id': session['run']['id'],
            'context': {'step_id': target['step_id'], 'review_target': target, 'interaction': 'anchored-comment-v1'}}


def test_before_table_column_selection_uses_current_step_and_verified_input(review_session):
    client,session,fake=review_session
    step=session['run']['stages'][1]
    actual_input=step['inputs'][0]
    target={'kind':'column','step_id':step['id'],'column':'qty',
            'table_role':'input','input_ref':actual_input['ref'],'selected_data':'FORGED'}
    result=client.post(f"/api/sessions/{session['id']}/generate",json=request_for(session,target)).json()
    assert result['status']=='ready'
    selected=fake.calls[-1]['review_target']
    assert selected['target']['step_id']==step['id']
    assert selected['target']['table_role']=='input'
    assert [row['values']['qty'] for row in selected['selected_data']['rows']]==[1,2,3]
    for invalid in ({**target,'input_ref':'not-an-input'},{**target,'table_role':'unknown'},
                    {**target,'table_role':'output'}):
        with pytest.raises(ValueError):
            resolve_review_target(session['run'],{'step_id':step['id'],'review_target':invalid},'step')


def test_disjoint_cells_preserve_only_exact_selected_values(review_session):
    client,session,fake=review_session
    step=session['run']['stages'][1];source=step['inputs'][0];rows=source['table']['rows']
    points=[{'row_id':rows[0]['id'],'column':'qty'},{'row_id':rows[-1]['id'],'column':'price'}]
    target={'kind':'cells','step_id':step['id'],'table_role':'input','input_ref':source['ref'],'cells':points}
    resolved=resolve_review_target(session['run'],{'step_id':step['id'],'review_target':target},'step')
    assert [row['values'] for row in resolved['selected_data']['rows']]==[{'qty':1},{'price':30}]
    assert len(resolved['selected_data']['cells'])==2
    assert resolved['target']['cells']==points
    result=client.post(f"/api/sessions/{session['id']}/generate",json=request_for(session,target)).json()
    assert result['status']=='ready'
    assert fake.calls[-1]['review_target']['selected_data']==resolved['selected_data']
    for invalid in ({**target,'cells':[points[0],points[0]]},{**target,'cells':[{'row_id':'missing','column':'qty'}]},
                    {**target,'row_ids':[rows[0]['id']],'columns':['price']},{**target,'cells':[]}):
        with pytest.raises(ValueError):resolve_review_target(session['run'],{'step_id':step['id'],'review_target':invalid},'step')


@pytest.mark.parametrize('kind', ['step', 'column', 'row', 'cell'])
def test_comment_selection_is_resolved_and_revision_reexecutes(review_session, kind):
    client, s, fake = review_session
    stage = s['run']['stages'][1]
    target = {'kind': kind, 'step_id': stage['id'], 'selected_data': 'FORGED-CLIENT-VALUE'}
    if kind in ('column', 'cell'): target['column'] = 'qty'
    if kind in ('row', 'cell'): target['row_id'] = stage['table']['rows'][0]['id']
    result = client.post(f"/api/sessions/{s['id']}/generate", json=request_for(s, target)).json()
    assert result['status'] == 'ready' and result['run']['comparison']['matches']
    context = fake.calls[-1]['review_target']
    assert context['execution_version'] == s['run']['id']
    assert 'FORGED-CLIENT-VALUE' not in json.dumps(context)
    if kind != 'step':
        assert context['selected_data']['rows'][0]['values']['qty'] == 3
        assert context['selected_data']['columns'] == (['qty'] if kind in ('column', 'cell') else ['qty', 'price'])
    else: assert context['selected_data'] is None
    assert [p['id'] for p in result['run']['pipeline']['steps']] == [p['id'] for p in s['run']['pipeline']['steps']]
    downstream = result['run']['stages'][2]
    assert not downstream['diff']['code_changed'] and downstream['diff']['output_changed'] and downstream['diff']['provenance_changed']
    assert result['run']['review_comment']['base_run_id'] == s['run']['id']
    assert result['run']['review_comment']['target']['kind'] == kind
    # Participant response retains the user's comment but never the evaluator verdict.
    public = client.get(f"/api/sessions/{s['id']}", headers={'X-Trace-View': 'participant'}).json()
    assert 'comparison' not in public['run'] and public['run']['review_comment']['request']
    stale = client.post(f"/api/sessions/{s['id']}/generate", json=request_for(s, target))
    assert stale.status_code == 409 and len(fake.calls) == 1
    undone = client.post(f"/api/sessions/{s['id']}/undo").json()
    assert undone['run']['id'] == s['run']['id'] and 'review_comment' not in undone['run']


def test_removed_row_and_source_column_use_actual_tables(review_session):
    client, s, _ = review_session
    stage = s['run']['stages'][1]
    removed = next(r for r in stage['removed']['rows'] if r['values']['qty'] == 2)
    resolved = resolve_review_target(s['run'], {'step_id': stage['id'], 'review_target': {
        'kind': 'row', 'step_id': stage['id'], 'row_id': removed['id'], 'removed': True,
    }}, 'step')
    assert resolved['selected_data']['rows'][0]['values']['qty'] == 2
    target = {'kind': 'column', 'step_id': 'input', 'column': 'qty'}
    response = client.post(f"/api/sessions/{s['id']}/generate", json=request_for(s, target, 'pipeline')).json()
    assert response['status'] == 'ready' and response['run']['review_comment']['scope'] == 'pipeline'


@pytest.mark.parametrize('change', [
    {'kind': 'unknown'}, {'kind': 'row', 'row_id': 'missing'},
    {'kind': 'column', 'column': 'missing'}, {'removed': 'false'},
    {'operation_id': 'not-in-this-step'}, {'step_id': 'missing'},
])
def test_invalid_selection_never_calls_model(review_session, change):
    client, s, fake = review_session
    sid = s['run']['stages'][1]['id']
    target = {'kind': 'step', 'step_id': sid, **change}
    body = request_for(s, target)
    body['context']['step_id'] = sid
    response = client.post(f"/api/sessions/{s['id']}/generate", json=body)
    assert response.status_code == 422 and not fake.calls
    assert client.get(f"/api/sessions/{s['id']}").json()['run']['id'] == s['run']['id']


def test_operation_is_scoped_and_events_are_versioned(review_session):
    client, s, _ = review_session
    stage = s['run']['stages'][1]
    foreign = s['run']['stages'][2]['operations'][0]['id']
    with pytest.raises(ValueError):
        resolve_review_target(s['run'], {'step_id': stage['id'], 'review_target': {
            'kind': 'step', 'step_id': stage['id'], 'operation_id': foreign}}, 'step')
    for event in ('column_selected', 'review_comment_opened'):
        assert client.post(f"/api/sessions/{s['id']}/events", json={
            'event': event, 'execution_version': s['run']['id'], 'condition': 'C',
            'data': {'interaction': 'anchored-comment-v1', 'column': 'qty'},
        }).status_code == 200
    exported = client.get(f"/api/sessions/{s['id']}/export").json()
    assert exported['events'][-1]['execution_version'] == s['run']['id']


def test_preview_keeps_current_run_until_applied(review_session):
    client, s, _ = review_session
    step = s['run']['stages'][1]['id']
    body = {'request': 'qty 2 포함', 'scope': 'step', 'base_run_id': s['run']['id'], 'context': {'step_id': step}, 'preview': True}
    previewed = client.post(f"/api/sessions/{s['id']}/generate", json=body).json()
    assert previewed['run']['id'] == s['run']['id'] and len(previewed['runs']) == 1
    candidate = previewed['preview']['run']
    assert len(candidate['stages'][-1]['table']['rows']) == 2
    hidden = client.get(f"/api/sessions/{s['id']}", headers={'X-Trace-View': 'participant'}).json()
    assert 'comparison' not in hidden['preview']['run']

    assert client.post(f"/api/sessions/{s['id']}/preview/apply", json={'run_id': 'other'}).status_code == 409
    discarded = client.post(f"/api/sessions/{s['id']}/preview/discard", json={'run_id': candidate['id']}).json()
    assert 'preview' not in discarded and discarded['run']['id'] == s['run']['id']

    candidate = client.post(f"/api/sessions/{s['id']}/generate", json=body).json()['preview']['run']
    applied = client.post(f"/api/sessions/{s['id']}/preview/apply", json={'run_id': candidate['id']}).json()
    assert applied['run']['id'] == candidate['id'] and applied['run']['parent_run_id'] == s['run']['id']
    assert 'preview' not in applied
    events = [e['event'] for e in json.loads((server.STORE / f"{s['id']}.json").read_text(encoding='utf-8'))['events']]
    assert events.count('revision_preview_ready') == 2
    assert 'revision_preview_discarded' in events and 'revision_preview_applied' in events


def test_admin_tracks_events_and_moves_deleted_sessions_aside(review_session):
    client, s, _ = review_session
    log = client.get(f"/api/admin/sessions/{s['id']}/events").json()
    assert log['events'] and log['status'] == 'ready'
    last = log['events'][-1]['id']
    client.post(f"/api/sessions/{s['id']}/events", json={'event': 'step_selected', 'data': {'step_id': 'x'}})
    newer = client.get(f"/api/admin/sessions/{s['id']}/events", params={'after': last}).json()['events']
    assert [e['event'] for e in newer] == ['step_selected']

    deleted = client.post('/api/admin/sessions/delete', json={'session_ids': [s['id']]}).json()
    assert deleted == {'deleted': [s['id']]}
    assert client.get(f"/api/sessions/{s['id']}").status_code == 404
    assert (server.STORE.parent / 'deleted-sessions' / f"{s['id']}.json").exists()
