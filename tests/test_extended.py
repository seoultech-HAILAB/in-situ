import ast
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend.engine import Unsupported, parse_table, run
from backend.generation import Proposal
from backend.pipeline import prepare, assemble, patch, validate_scope
from backend.isolation import isolated_run


def execute(code,csv,sources=None,groups=None,previous=None):
    records=run(code,parse_table(csv),{k:parse_table(v) for k,v in (sources or {}).items()})
    plan=prepare(code,groups,previous)
    stages,ops=assemble(records,plan,previous)
    return {'id':'run-test','code':code,'pipeline':plan,'stages':stages,'operations':ops}


def native(code,csv,sources=None):
    ns={'input_df':parse_table(csv).reset_index(drop=True),'pd':pd,'tables':{k:parse_table(v).reset_index(drop=True) for k,v in (sources or {}).items()}}
    # Trusted fixtures only. Production execution does not eval or exec.
    exec(code,ns)
    return ns['result']


CASES=[
    ("result = input_df.rename(columns={'a':'number'}).drop(columns=['b']).astype({'number':'float64'}).sort_values(['number'])", 'a,b\n2,X\n1,Y'),
    ("s1 = input_df.fillna({'a':0})\ns2 = s1.drop_duplicates(subset=['a'],keep='last')\nresult = s2.dropna(subset=['b'])", 'a,b\n,yes\n2,no\n2,no\n3,'),
    ("s1 = input_df.assign(clean=input_df['name'].str.strip().str.upper(),n=pd.to_numeric(input_df['n'],errors='coerce'))\nresult = s1.assign(n2=s1['n'].fillna(s1['n'].mean()))", 'name,n\n aa ,2\n bb ,bad\n aa ,4'),
    ("s1 = input_df.assign(date=pd.to_datetime(input_df['date'],errors='coerce'))\nresult = s1.assign(year=s1['date'].dt.year,month=s1['date'].dt.strftime('%Y-%m'))", 'date\n2025-01-02\n2026-02-03'),
    ("result = input_df.loc[input_df['name'].str.contains('ab',regex=False,na=False)].copy()", 'name\nabc\nxyz\nzab'),
    ("result = input_df.replace({'name':{'old':'new'}})", 'name,x\nold,1\nother,2'),
    ("result = input_df.melt(id_vars=['id'],value_vars=['a','b'],var_name='metric',value_name='value',ignore_index=True)", 'id,a,b\nX,1,2\nY,3,4'),
    ("s1 = input_df.assign(tags=input_df['tags'].str.split('|',regex=False))\nresult = s1.explode('tags',ignore_index=True)", 'id,tags\n1,a|b\n2,c'),
    ("result = input_df.pivot(index='id',columns='metric',values='value').reset_index()", 'id,metric,value\nX,a,1\nX,b,2\nY,a,3'),
    ("result = input_df.pivot_table(index='id',columns='metric',values='value',aggfunc='sum').reset_index()", 'id,metric,value\nX,a,1\nX,a,2\nX,b,3'),
    ("result = input_df.transpose()", 'a,b\n1,2\n3,4'),
    ("s1 = input_df.loc[input_df['a'] > 1].copy()\nresult = s1.reset_index(drop=True)", 'a\n1\n2\n3'),
]


@pytest.mark.parametrize('code,csv',CASES)
def test_extended_matches_native_pandas(code,csv):
    result=execute(code,csv)
    out=result['stages'][-1]['table']
    from backend.runtime import table
    expected=table(native(code,csv))
    assert out['columns']==expected['columns']
    assert [r['values'] for r in out['rows']]==[r['values'] for r in expected['rows']]


@pytest.mark.parametrize('how',['inner','left','right','outer'])
def test_merge_sources_suffixes_nulls_duplicates_and_keys(how):
    csv='id,name,x\n1,L,10\n2,M,20\n2,N,30\n,Null,40'
    sources={'lookup':'id,name,y\n1,R,9\n2,S,8\n2,T,7\n3,U,6\n,Nil,5'}
    code=f"result = input_df.merge(tables['lookup'],how='{how}',on=['id'],suffixes=('_left','_right'))"
    result=execute(code,csv,sources)
    from backend.runtime import table
    assert [r['values'] for r in result['stages'][-1]['table']['rows']]==[r['values'] for r in table(native(code,csv,sources))['rows']]
    stage=result['stages'][-1]
    assert len(set(r['id'] for r in stage['table']['rows']))==len(stage['table']['rows'])
    match=next(r for r in stage['table']['rows'] if r['values']['name_left']=='L')
    assert stage['lineage'][match['id']]['y']==[{'row_id':'lookup:r0001','column':'y','table_id':'lookup'}]
    assert {r['column'] for r in stage['contexts'][match['id']]['y']['key_sources']}=={'id'}
    assert stage['trace_level']=='detailed'


def test_concat_and_left_right_on():
    r=execute("result = pd.concat([input_df,tables['other']],ignore_index=True)",'id,v\n1,A',{'other':'id,v\n2,B'})
    assert r['stages'][-1]['lineage']['c1:other:r0001']['v'][0]['table_id']=='other'
    r=execute("result = input_df.merge(tables['other'],how='left',left_on=['id'],right_on=['key'])",'id,v\n1,A',{'other':'key,w\n1,B'})
    assert r['stages'][-1]['table']['rows'][0]['values']['w']=='B'


def test_unknown_lineage_never_reconstructed_downstream():
    r=execute("s1 = input_df.pivot(index='id',columns='metric',values='value').reset_index()\nresult = s1.assign(doubled=s1['a']*2)",'id,metric,value\nX,a,1\nY,a,2')
    for stage in r['stages'][1:]:
        assert stage['trace_level']=='common'
        assert all(not refs for cols in stage['lineage'].values() for refs in cols.values())
    with pytest.raises(Unsupported): run("result = input_df.apply('sum')",parse_table('a\n1'))


def test_join_common_and_melt_explode_precise_dependencies():
    r=execute("result = input_df.join(tables['other'],lsuffix='_l',rsuffix='_r')",'x\n1\n2',{'other':'x\n3\n4'})
    assert r['stages'][-1]['trace_level']=='common'
    assert all(not refs for cols in r['stages'][-1]['lineage'].values() for refs in cols.values())
    melted=execute("result = input_df.melt(id_vars=['id'],value_vars=['a','b'],ignore_index=True)",'id,a,b\nX,1,2')
    stage=melted['stages'][-1]
    b=next(row for row in stage['table']['rows'] if row['values']['variable']=='b')
    assert stage['lineage'][b['id']]['value']==[{'row_id':'r0001','column':'b'}]
    assert stage['lineage'][b['id']]['variable']==[]
    exploded=execute("s1 = input_df.assign(tags=input_df['tags'].str.split('|',regex=False))\nresult = s1.explode('tags',ignore_index=True)",'tags\na|b')
    assert len(exploded['stages'][-1]['table']['rows'])==2
    assert all(cols['tags']==[{'row_id':'r0001','column':'tags'}] for cols in exploded['stages'][-1]['lineage'].values())


def test_chains_split_and_multi_statement_semantic_group_validated():
    code="s1 = input_df.rename(columns={'a':'x'}).astype({'x':'float64'})\nresult = s1.sort_values(['x'])"
    r=execute(code,'a\n2\n1',groups=[{'statement_indices':[0,1],'label':'정규화'}])
    assert len(r['stages'])==2 and len(r['operations'])==3
    assert r['operations'][0]['operation_expression']=="input_df.rename(columns={'a':'x'})"
    assert r['operations'][1]['expression_location']['end_column']>r['operations'][0]['expression_location']['end_column']
    assert r['stages'][1]['kind']=='composite'
    assert r['stages'][1]['code']==code
    with pytest.raises(Unsupported): prepare(code,[{'statement_indices':[0]}])
    with pytest.raises(Unsupported): prepare(code,[{'statement_indices':[0,0,1]}])


def test_step_identity_insertion_scope_and_stale_patch():
    old=execute("s1 = input_df.loc[input_df['a'] > 1].copy()\nresult = s1.assign(b=s1['a']*2)",'a\n1\n2')
    first,last=old['pipeline']['steps']
    changes=[{'action':'insert_after','step_id':first['id'],'code':"s2 = s1.rename(columns={'a':'a'})"}]
    plan=patch(old,changes,old['id'],'step',first['id'])
    assert plan['steps'][0]['id']==first['id'] and plan['steps'][-1]['id']==last['id']
    assert plan['steps'][1]['id'] not in (first['id'],last['id'])
    validate_scope(plan,old,'step',first['id'])
    with pytest.raises(Unsupported):patch(old,changes,'old-version')
    with pytest.raises(Unsupported):patch(old,[{'action':'delete','step_id':last['id']}],old['id'],'step',first['id'])


def test_code_output_and_provenance_changes_are_distinct():
    csv='id,k,q,value\nA,X,1,10\nB,X,2,10'
    old=execute("s1 = input_df.loc[input_df['q'] == 1].copy()\nresult = s1.groupby(['k'],as_index=False,dropna=False).agg(total=('value','sum'))",csv)
    new=execute(old['code'].replace("['q'] == 1","['q'] == 2"),csv,previous=old)
    assert old['stages'][2]['id']==new['stages'][2]['id']
    diff=new['stages'][2]['diff']
    assert diff['code_changed'] is False and diff['output_changed'] is False and diff['provenance_changed'] is True
    assert new['stages'][2]['row_sources']!=old['stages'][2]['row_sources']


def test_global_structural_patch_rewires_and_failed_schema_does_not_execute():
    old=execute("s1 = input_df.assign(b=input_df['a']*2)\nresult = s1[['b']].copy()",'a\n2')
    first,last=old['pipeline']['steps']
    changes=[{'action':'insert_after','step_id':first['id'],'code':"s2 = s1.rename(columns={'b':'value'})"},
             {'action':'replace','step_id':last['id'],'code':"result = s2[['value']].copy()"}]
    plan=patch(old,changes,old['id'],'pipeline')
    records=run(plan['code'],parse_table('a\n2'))
    stages,ops=assemble(records,plan,old)
    assert stages[-1]['table']['columns']==['value']
    assert stages[-1]['id']==last['id']
    assert stages[-1]['table']['rows'][0]['values']['value']==4
    bad=patch(old,[{'action':'delete','step_id':first['id']}],old['id'],'pipeline')
    with pytest.raises(Unsupported):run(bad['code'],parse_table('a\n2'))


def test_observed_statistics_do_not_merge_missing_and_literal_nan():
    from backend.runtime import table
    df=pd.DataFrame({'x':[float('nan'),'nan']})
    assert table(df)['stats']['duplicates']==0
    assert table(pd.DataFrame({'integer':[3], 'fraction':[1.5]}))['rows'][0]['values']['integer']==3
    with pytest.raises(Unsupported): table(pd.DataFrame({'unsafe':[-9_007_199_254_740_992]}))


def test_cross_table_scalar_dependencies_include_only_used_nonmissing_contributors():
    r=execute("s1 = tables['other'].assign(v=tables['other']['v']*2)\nresult = input_df.assign(n=input_df['n'].fillna(s1['v'].mean()))",
              'id,n\nA,2\nB,',{'other':'id,v\nX,3\nY,\nZ,5'})
    last=r['stages'][-1]
    assert r['stages'][1]['id'] in last['depends_on']
    assert len(last['inputs'])==2
    assert last['table']['rows'][1]['values']['n']==8
    assert {x['row_id'] for x in last['lineage']['r0002']['n']}=={'r0002','other:r0001','other:r0003'}
    assert {x['row_id'] for x in last['lineage']['r0001']['n']}=={'r0001'}
    empty=execute("s1 = tables['other'].loc[tables['other']['v'] > 99].copy()\nresult = input_df.assign(n=input_df['n'].fillna(s1['v'].mean()))",
                  'id,n\nA,2',{'other':'v\n3'})
    assert empty['stages'][1]['id'] in empty['stages'][-1]['depends_on']
    assert any(not item['table']['rows'] for item in empty['stages'][-1]['inputs'])


def test_sort_ties_follow_actual_pandas_defaults_and_regex_requires_explicit_literal_mode():
    csv='key,order\n'+'\n'.join(f'{i%3},{i}' for i in range(30))
    code="result = input_df.sort_values('key')"
    from backend.runtime import table
    actual=execute(code,csv)['stages'][-1]['table']
    assert [r['values'] for r in actual['rows']]==[r['values'] for r in table(native(code,csv))['rows']]
    with pytest.raises(Unsupported): execute("result = input_df.assign(x=input_df['x'].str.split('.*'))",'x\na.b')


def test_scoped_api_revision_context_accumulation_and_failure_atomicity(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'STORE',tmp_path)
    class Model:
        calls=[]
        bad=False
        def generate(self,inp,target,req,previous_code,request,context):
            self.calls.append(context)
            if not previous_code:return Proposal(code="s1 = input_df.loc[input_df['q'] > 2].copy()\nresult = s1.assign(v=s1['q']*2)",assumptions=[])
            sid=context['target_step']['id']
            if self.bad:sid=context['pipeline']['steps'][-1]['id']
            return Proposal(base_run_id=context['base_run_id'],changes=[{'action':'replace','step_id':sid,'code':"s1 = input_df.loc[input_df['q'] >= 2].copy()"}],assumptions=[])
    model=Model();monkeypatch.setattr(server,'generator',model)
    client=TestClient(server.app)
    s=client.post('/api/sessions',json={'input_csv':'q\n1\n2\n3','target_csv':'q,v\n2,4\n3,6','requirements':'누적 원요구'}).json();sid=s['id']
    s=client.post(f'/api/sessions/{sid}/generate',json={}).json();rid=s['run']['id'];step=s['run']['stages'][1]['id']
    s=client.post(f'/api/sessions/{sid}/generate',json={'request':'2도 포함','scope':'step','base_run_id':rid,'context':{'step_id':step,'selection':{'row':'r0002','column':'q'}}}).json()
    assert s['status']=='ready' and s['run']['comparison']['matches']
    assert s['run']['stages'][1]['id']==step and s['run']['stages'][1]['revision']==2
    ctx=model.calls[-1]
    assert ctx['target_step']['input']['rows'] and ctx['target_step']['table']['rows']
    assert ctx['cumulative_requirements']==['누적 원요구']
    assert s['run']['cumulative_requirements']==['누적 원요구','2도 포함']
    assert client.post(f'/api/sessions/{sid}/generate',json={'request':'stale','base_run_id':rid}).status_code==409
    good=s['run']['id'];model.bad=True
    s=client.post(f'/api/sessions/{sid}/generate',json={'request':'선택 밖 수정','scope':'step','context':{'step_id':step}}).json()
    assert s['status']=='failed' and s['run']['id']==good
    assert client.post(f'/api/sessions/{sid}/confirm').status_code==422


def test_isolation_capabilities_timeout_and_limits():
    records=isolated_run("result = input_df.rename(columns={'a':'b'})",'a\n1')
    assert records[-1]['table']['columns']==['b']
    for code in ["import os\nresult = input_df.copy()","result = pd.read_csv('secret')","result = input_df.__class__()","result = pd.DataFrame({'a':[1]})"]:
        with pytest.raises(Unsupported): isolated_run(code,'a\n1')
    with pytest.raises(Unsupported):isolated_run("result = input_df.copy()",'a\n1',timeout=0.001)


def test_extended_demo_ac_preserves_same_trace_and_replay(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'STORE',tmp_path)
    client=TestClient(server.app)
    s=client.post('/api/demo/wrangling',json={}).json()
    assert s['run']['comparison']['matches']
    assert len(s['run']['stages'])==7 and len(s['run']['operations'])>6
    assert s['run']['stages'][-1]['trace_level']=='common'
    sid=s['id'];trace=s['run']
    for condition in ('ex','in-situ'):
        other=client.post(f'/api/sessions/{sid}/condition',json={'condition':condition}).json()
        assert other['run']==trace
    exported=client.get(f'/api/sessions/{sid}/export').json()
    target=trace['stages'][-2]['id']
    revised=client.post(f'/api/sessions/{sid}/generate',json={'request':'평균으로 계산','scope':'step','base_run_id':trace['id'],'context':{'step_id':target}}).json()
    assert revised['status']=='ready'
    assert [s['id'] for s in revised['run']['stages']]==[s['id'] for s in trace['stages']]
    assert revised['run']['stages'][-2]['diff']['code_changed']
    replay=client.post('/api/replay',json={'session':exported,'condition':'C'}).json()
    assert replay['run']['comparison']['matches']
    assert [len(s['operations']) for s in replay['run']['stages'][1:]]==[len(s['operations']) for s in trace['stages'][1:]]
