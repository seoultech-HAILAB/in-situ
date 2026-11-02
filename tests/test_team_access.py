import json

import pytest
from fastapi.testclient import TestClient

import backend.app as server
import backend.access as access
from backend.access import password_hash


@pytest.fixture
def shared(tmp_path,monkeypatch):
    access._attempts.clear()
    cfg={'signing_key':'test-signing-key-'*4,'users':{
        'team':{'role':'researcher','password_hash':password_hash('test-team-password')},
        'participant':{'role':'participant','password_hash':password_hash('test-review-password')}},
        'allowed_origins':['https://pilot.example.test']}
    file=tmp_path/'access.json'
    file.write_text(json.dumps(cfg),encoding='utf-8')
    monkeypatch.setenv('TRACE_LEGACY_AUTH','1')
    monkeypatch.setenv('TRACE_ACCESS_FILE',str(file))
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    store=tmp_path/'sessions';store.mkdir()
    monkeypatch.setattr(server,'STORE',store)
    return TestClient(server.app,base_url='https://pilot.example.test'),file


def login(client,name='team',password='test-team-password'):
    return client.post('/auth/login',data={'username':name,'password':password},follow_redirects=False)


def test_entire_shared_surface_requires_authentication(shared):
    client,_=shared
    assert client.get('/',follow_redirects=False).headers['location']=='/login'
    assert '팀 파일럿' in client.get('/login').text
    for route in ('/api/health','/api/sessions/unknown','/openapi.json','/assets/anything.js'):
        assert client.get(route).status_code==401
    assert client.post('/api/demo',json={}).status_code==401
    assert client.get('/api/health',headers={'authorization':'Basic !!!!'}).status_code==401
    assert login(client,password='wrong').status_code==401
    assert not client.cookies


def test_signed_login_origin_guard_and_logout(shared):
    client,_=shared
    r=login(client)
    assert r.status_code==303 and r.headers['location']=='/?research=1'
    cookie=r.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
    h=client.get('/api/health').json()
    assert h['access_role']=='researcher' and h['team_mode'] and not h['api_configured']
    assert client.post('/api/demo',json={},headers={'origin':'https://evil.example'}).status_code==403
    assert client.post('/api/demo',json={},headers={'origin':'https://pilot.example.test'}).status_code==200
    assert client.post('/auth/logout',follow_redirects=False).status_code==303
    assert client.get('/api/health').status_code==401


def test_participant_cannot_enable_researcher_by_query_or_header(shared):
    client,_=shared
    assert login(client,'participant','test-review-password').headers['location']=='/'
    headers={'X-Trace-View':'researcher'}
    s=client.post('/api/demo',json={},headers=headers).json()
    sid=s['id']
    assert 'comparison' not in s['run'] and 'events' not in s
    assert 'comparison' in server.read(sid)['runs'][0]
    assert client.get(f'/api/sessions/{sid}?research=1',headers=headers).json()['run']==s['run']
    for route in (f'/api/sessions/{sid}/export','/openapi.json','/docs'):
        assert client.get(route).status_code==403
    for route,body in ((f'/api/sessions/{sid}/research-code',{'code':'result=input_df.copy()'}),
            ('/api/replay',{}),(f'/api/sessions/{sid}/condition',{'condition':'A'})):
        assert client.post(route,json=body).status_code==403
    changed=client.post(f'/api/sessions/{sid}/generate',json={'request':'수량이 정확히 2인 주문도 포함'}).json()
    assert changed['run']['code_version']==2 and 'comparison' not in changed['run']
    assert client.get(f'/api/sessions/{sid}/output.csv').status_code==200


def test_rotation_and_missing_config_fail_closed(shared):
    client,file=shared
    login(client)
    cfg=json.loads(file.read_text())
    cfg['users']['team']['password_hash']=password_hash('new-password')
    file.write_text(json.dumps(cfg),encoding='utf-8')
    assert client.get('/api/health').status_code==401
    assert login(client,password='new-password').status_code==303
    cfg['signing_key']='rotated-key-'*5
    file.write_text(json.dumps(cfg),encoding='utf-8-sig')
    assert client.get('/api/health').status_code==401
    file.unlink()
    assert client.get('/api/health').status_code==503


def test_each_demo_starts_an_independent_pilot_session(shared):
    client,_=shared
    login(client)
    first=client.post('/api/demo',json={}).json()
    second=client.post('/api/demo',json={}).json()
    assert first['id']!=second['id']
    client.post(f"/api/sessions/{first['id']}/generate",json={'request':'수량이 정확히 2인 주문도 포함'})
    other=client.get(f"/api/sessions/{second['id']}").json()
    assert other['run']['id']==second['run']['id']


def test_assigned_session_url_survives_login_without_external_redirect(shared):
    client,_=shared
    r=client.get('/?session=assigned-session&research=1',follow_redirects=False)
    assert r.headers['location'].startswith('/login?next=')
    page=client.get(r.headers['location'])
    assert 'assigned-session' in page.text and 'name="next"' in page.text
    r=client.post('/auth/login',data={'username':'participant','password':'test-review-password','next':'/?session=assigned-session'},follow_redirects=False)
    assert r.headers['location']=='/?session=assigned-session'
    r=client.post('/auth/login',data={'username':'team','password':'test-team-password','next':'//evil.example'},follow_redirects=False)
    assert r.headers['location']=='/?research=1'


def test_login_body_and_password_attempts_are_bounded(shared):
    client,_=shared
    assert client.post('/auth/login',content=b'x'*2001).status_code==413
    assert login(client).status_code==303
    # Existing signed sessions remain usable even when password work is throttled.
    for _ in range(28):
        assert login(client,password='wrong').status_code==401
    assert login(client,password='wrong').status_code==429
    assert client.get('/api/health').status_code==200
    client.cookies.clear()
    assert client.get('/api/health',auth=('team','wrong')).status_code==429
