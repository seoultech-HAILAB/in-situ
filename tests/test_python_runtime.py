"""Dataset-independent native execution and real API path contract tests."""
import json

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend.engine import parse_table, Unsupported
from backend.generation import OpenAIGenerator, Proposal, StepSpec
from backend.isolation import isolated_run
from backend.pipeline import prepare, assemble
from backend.runtime import table


CASES=[
    ("def tidy(x):\n    return str(x).strip().title()\ns1 = input_df.copy()\ns1['name'] = s1['name'].apply(tidy)\nresult = s1.sort_values('name').reset_index(drop=True)", 'name\n bob\n alice'),
    ("s1 = input_df.copy()\nfor c in ['a','b']:\n    if c in s1.columns:\n        s1[c] = s1[c]*2\nresult = s1.iloc[::-1].reset_index(drop=True)", 'a,b\n1,3\n2,4'),
    ("s1 = input_df.copy()\ns1['rolling'] = s1['x'].rolling(2).mean()\nresult = s1", 'x\n1\n3\n5'),
    ("s1 = input_df.copy()\ns1['date'] = pd.to_datetime(s1['date'])\nresult = s1.set_index('date').resample('D').sum(numeric_only=True).reset_index()", 'date,x\n2026-01-01,2\n2026-01-01,3\n2026-01-03,4'),
    ("import numpy as np\ns1 = input_df.copy()\ns1['label'] = np.where(s1['x']>1,'large','small')\nresult = s1", 'x\n1\n2'),
    ("result = pd.get_dummies(input_df,columns=['name'])", 'name,x\nA,1\nB,2'),
    ("result = input_df.assign(label=input_df['x'].map({1:'A',2:'B'}))", 'x\n1\n2'),
    ("s1 = input_df.copy()\ns1.loc[s1['x']<0,'x'] = 0\nresult = s1.assign(running=s1['x'].cumsum())", 'x\n-2\n1\n3'),
    ("result = input_df.loc[input_df['name'].str.contains('^a.+z$',regex=True)].copy()", 'name\nabczz\nxyz'),
    ("def reshape(df):\n    rows = [{'x':v,'square':v*v} for v in df['x']]\n    return pd.DataFrame(rows)\nresult = reshape(input_df)", 'x\n2\n3'),
]


@pytest.mark.parametrize('code,csv',CASES)
def test_general_python_matches_unmodified_native_program(code,csv):
    plan=prepare(code,[{'statement_indices':list(range(len(__import__('ast').parse(code).body))),'output_variable':'result'}],engine='python')
    records=isolated_run(code,csv,engine='python',plan=plan)
    ns={'pd':pd,'np':np,'input_df':parse_table(csv).reset_index(drop=True),'tables':{}}
    exec(code,ns) # Trusted fixtures: independent, unsegmented pandas reference.
    expected=table(ns['result'])
    assert [r['values'] for r in records[-1]['table']['rows']]==[r['values'] for r in expected['rows']]
    assert records[-1]['table']['stats']==expected['stats']
    assert records[-1]['native_verified']


def test_general_steps_actual_inputs_stable_versions_wrong_result_abc_revision(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'STORE',tmp_path)
    client=TestClient(server.app)
    code="def add_tax(df):\n    out = df.copy()\n    out['total'] = out['x'].apply(lambda v: v*2)\n    return out\ns1 = add_tax(input_df)\nresult = s1[['total']].copy()"
    groups=[{'label':'계산','statement_indices':[0,1],'output_variable':'s1'},{'label':'출력','statement_indices':[2],'output_variable':'result'}]
    s=client.post('/api/sessions',json={'input_csv':'x\n2\n3','target_csv':'total\n6\n9'}).json()
    sid=s['id']
    s=client.post(f'/api/sessions/{sid}/research-code',json={'code':code,'steps':groups}).json()
    assert s['status']=='ready' and not s['run']['comparison']['matches']
    before=s['run'];first=before['stages'][1];last=before['stages'][2]
    assert first['trace_level']=='common' and len(first['input']['rows'])==2
    assert not any(refs for cols in first['lineage'].values() for refs in cols.values())
    assert first['id'] in last['depends_on']
    assert s['run']['code']==code
    for condition in ('ex','in-situ'):
        assert client.post(f'/api/sessions/{sid}/condition',json={'condition':condition}).json()['run']==before
    class Model:
        def generate(self,inp,target,req,old,request,context):
            assert context['target_step']['table']==first['table']
            return Proposal(base_run_id=before['id'],changes=[{'action':'replace','step_id':first['id'],'code':first['code'].replace('v*2','v*3')}])
    monkeypatch.setattr(server,'generator',Model())
    s=client.post(f'/api/sessions/{sid}/generate',json={'request':'세 배로 계산','scope':'step','base_run_id':before['id'],'context':{'step_id':first['id']}}).json()
    assert s['status']=='ready' and s['run']['comparison']['matches']
    after=s['run'];assert after['stages'][1]['id']==first['id'] and after['stages'][2]['id']==last['id']
    assert after['stages'][1]['diff']['code_changed'] and after['stages'][2]['diff']['output_changed']
    assert not after['stages'][2]['diff']['code_changed']
    assert not after['stages'][2]['diff']['comparison_available']
    exported=client.get(f'/api/sessions/{sid}/export').json()
    replay=client.post('/api/replay',json={'session':exported,'run_index':1}).json()
    assert replay['run']['comparison']['matches']
    broken=code.replace("result = s1[['total']].copy()","result = s1[['missing']].copy()")
    failed=client.post(f'/api/sessions/{sid}/research-code',json={'code':broken,'steps':groups}).json()
    assert failed['status']=='failed' and failed['run']['id']==after['id']
    assert len(failed['error']['partial_stages'])==2
    assert failed['error']['failure']['exception_type']=='KeyError'
    assert client.post(f'/api/sessions/{sid}/confirm').status_code==422
    restored=client.post(f'/api/sessions/{sid}/undo').json()
    assert restored['error'] is None
    exported=client.get(f'/api/sessions/{sid}/export').json()
    assert exported['failed_attempts'][-1]['candidate_code']==broken
    assert len(exported['failed_attempts'][-1]['partial_stages'])==2


def test_metadata_actual_output_validation_and_no_trace_reconstruction():
    code="s1 = input_df.assign(y=input_df['x']*2)\ns2 = s1.assign(z=s1['y'].apply(lambda v:v+1))\nresult = s2[['z']].copy()"
    plan=prepare(code,engine='python')
    records=isolated_run(code,'x\n2',engine='python',plan=plan)
    stages,_=assemble(records,plan)
    assert stages[1]['trace_level']=='detailed'
    assert all(s['trace_level'] in ('common','partial') for s in stages[2:])
    assert not stages[-1]['lineage'][stages[-1]['table']['rows'][0]['id']]['z']
    wrong=prepare(code,[{'statement_indices':[0,1,2],'output_variable':'not_real'}],engine='python')
    with pytest.raises(Unsupported,match='DataFrame'):isolated_run(code,'x\n2',engine='python',plan=wrong)


def test_scalar_setup_records_reference_observation_with_actual_dataframe_name():
    code="factor = 2\ns1 = input_df.assign(y=input_df['x']*factor)\nresult = s1[['y']].copy()"
    plan=prepare(code,engine='python')
    records=isolated_run(code,'x\n3',engine='python',plan=plan)
    stages,_=assemble(records,plan)
    assert stages[1]['kind']=='setup'
    assert plan['steps'][0]['output_variable']=='input_df'
    assert stages[-1]['table']['rows'][0]['values']['y']==6


@pytest.mark.parametrize('code',[
    "import os\nresult = input_df.copy()",
    "result = input_df.__class__(input_df)",
    "result = pd.read_csv('C:/Users/박부성/Documents/ChatGPT/in-situ/README.md')",
    "result = input_df.copy()\nresult.to_csv('escaped.csv')",
    "result = pd.read_csv('https://example.com/data.csv')",
])
def test_python_worker_blocks_io_network_system_and_reflection(code):
    plan=prepare(code,engine='python')
    with pytest.raises(Unsupported):isolated_run(code,'x\n1',engine='python',plan=plan)


def test_native_worker_timeout():
    code="while True:\n    pass\nresult = input_df.copy()"
    with pytest.raises(Unsupported,match='시간 제한'):
        isolated_run(code,'x\n1',engine='python',plan=prepare(code,engine='python'),timeout=.01)


def test_existing_code_annotations_cannot_rewrite_program(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','contract-test-key')
    calls=[]
    code="def transform(df):\n    return df.head(1)\nresult = transform(input_df)"
    def post(self,url,headers,json):
        calls.append(json)
        assert __import__('json').loads(json['input'])['code']==code
        answer={'steps':[{'id':None,'label':'첫 행','statement_indices':[0,1],'output_variable':'result'}],'assumptions':[]}
        return httpx.Response(200,json={'status':'completed','output':[{'content':[{'type':'output_text','text':__import__('json').dumps(answer)}]}]})
    monkeypatch.setattr(httpx.Client,'post',post)
    proposal=OpenAIGenerator().structure(code)
    assert proposal.code==code and len(proposal.steps)==1 and len(calls)==1
    assert prepare(proposal.code,proposal.steps,engine='python')['code']==code
