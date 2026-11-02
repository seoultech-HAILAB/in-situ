"""Verify the real model with an authored synthetic fixture, outside pilot logs."""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUTPUT=ROOT/'.local/prototype-validation'
OUTPUT.mkdir(parents=True,exist_ok=True)
os.environ['TRACE_DATA_DIR']=str(OUTPUT/'sessions')
os.environ.pop('TRACE_ACCESS_FILE',None)

import httpx
from fastapi.testclient import TestClient
import backend.app as server
from backend import prototype


def main():
    # .env is already loaded by the app. Use only local ASGI and the configured
    # model endpoint. This verification never reads existing user/pilot sessions.
    os.environ.pop('TRACE_ACCESS_FILE',None)
    client=TestClient(server.app)
    calls=[];original=httpx.Client.post
    def tracked(self,url,*args,**kwargs):
        response=original(self,url,*args,**kwargs)
        if str(url).endswith('/responses'):
            body=response.json()
            calls.append({'model':kwargs.get('json',{}).get('model'),'response_id':body.get('id'),
                          'status':body.get('status'),'usage':body.get('usage'),'http_status':response.status_code})
        return response
    httpx.Client.post=tracked
    try:
        result=client.post('/api/prototype/sessions',json={'input_csv':prototype.INPUT,'target_csv':prototype.TARGET,'condition':'in-situ'})
        result.raise_for_status();s=result.json();sid=s['id']
        first=client.post(f'/api/sessions/{sid}/generate',json={}).json()
        if first['status']!='ready':raise RuntimeError(first.get('error'))
        before=first['run'];assert len(calls)==1 and before['mode']=='api'
        assert before['pipeline']['grouping_source']=='provided'
        described=client.post(f'/api/sessions/{sid}/explanations',json={'run_id':before['id']}).json()
        if described['run'].get('explanation_status')!='ready':raise RuntimeError(described['run'].get('explanation_error'))
        before=described['run'];count=len(calls)
        for condition in ('ex','in-situ'):
            switched=client.post(f'/api/sessions/{sid}/condition',json={'condition':condition}).json()
            assert switched['run']==before and len(calls)==count
        last=before['stages'][-1]
        revision=client.post(f'/api/sessions/{sid}/generate',json={
            'request':'최종 결과의 region을 내림차순으로 정렬해 주세요. 다른 필터와 계산은 그대로 유지해 주세요.',
            'scope':'step','base_run_id':before['id'],'context':{'step_id':last['id']}}).json()
        if revision['status']!='ready':raise RuntimeError(revision.get('error'))
        after=revision['run'];assert after['id']!=before['id']
        final=after['stages'][-1]['table']
        assert [row['values']['region'] for row in final['rows']]==sorted([row['values']['region'] for row in before['stages'][-1]['table']['rows']],reverse=True)
        described=client.post(f'/api/sessions/{sid}/explanations',json={'run_id':after['id']}).json()
        assert described['run'].get('explanation_status')=='ready'
        assert client.post(f'/api/sessions/{sid}/undo',json={}).json()['run']['id']==before['id']
        report={'fixture':'authored-synthetic-orders','selected_for_study':False,'session_id':sid,
            'model':os.getenv('OPENAI_MODEL'),'initial_run_id':before['id'],'revised_run_id':after['id'],
            'generated_steps':len(before['stages'])-1,'trace_levels':[s['trace_level'] for s in before['stages'][1:]],
            'initial_target_matches_researcher_only':before.get('comparison',{}).get('matches'),
            'revision_target_matches_researcher_only':after.get('comparison',{}).get('matches'),
            'same_execution_across_conditions':True,'revision_reexecuted':True,'undo_restored':True,
            'api_calls':calls,'generated_code':before['code'],'initial_steps':before['pipeline']['steps'],
            'revision_code':after['code'],'initial_natural_language':[s['nl_explanation'] for s in before['stages'][1:]]}
        (OUTPUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k not in ('generated_code','initial_steps','revision_code','initial_natural_language','api_calls')},ensure_ascii=True))
        print(json.dumps({'actual_api_calls':len(calls),'all_completed':all(call['status']=='completed' for call in calls)}))
    finally:httpx.Client.post=original


if __name__=='__main__':main()
