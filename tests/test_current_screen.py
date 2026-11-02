"""Reproduce the actual open movie review, without session logs or a model call."""
import copy
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import backend.app as server
from backend import explanations


def test_current_movie_screen_reexecutes_and_reuses_observed_descriptions(tmp_path,monkeypatch):
    monkeypatch.setenv('TRACE_TASK_DIR',str(Path(__file__).resolve().parents[1]/'tasks/candidates'))
    monkeypatch.setenv('TRACE_EXPLANATION_DIR',str(tmp_path/'empty-cache'))
    monkeypatch.delenv('TRACE_LEGACY_AUTH',raising=False)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    (tmp_path/'sessions').mkdir()
    monkeypatch.setattr(server,'STORE',tmp_path/'sessions')
    def no_model(*args,**kwargs):raise AssertionError('No model call for this stored execution')
    monkeypatch.setattr(explanations,'generate',no_model)
    with TestClient(server.app) as client:
        candidate=client.get('/api/woz-tasks/VERIFY2-M4-A/input').json()
        payload={key:candidate[key] for key in ('input_csv','target_csv')}
        session=client.post('/api/woz-tasks/VERIFY2-M4-A/start',json=payload).json()
        assert session['status']=='ready',session.get('error')
        run=session['run'];sid=session['id']
        response=client.post(f'/api/sessions/{sid}/explanations',json={'run_id':run['id']})
        assert response.status_code==200
        described=response.json()['run']
        assert described['explanation_status']=='ready'
        assert described['explanation_meta']['bundled_replay'] is True
        stage=described['stages'][2]
        assert stage['nl_explanation']['title']=='그룹별 평균과 순위 계산'
        assert len(stage['input']['rows'])==36 and len(stage['table']['rows'])==12
        assert len(described['stages'])==5
        for condition in ('ex','in-situ'):
            shown=client.post(f'/api/sessions/{sid}/condition',json={'condition':condition}).json()['run']
            assert shown['id']==run['id'] and shown['stages']==described['stages']
        changed=copy.deepcopy(described)
        changed['code']+='\n# changed code'
        with pytest.raises(AssertionError,match='No model call'):
            explanations.obtain(changed)
