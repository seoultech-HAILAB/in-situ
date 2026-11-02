"""Exercise the v2 WoZ routes in disposable sessions; never calls a model."""
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import backend.app as server
from backend import candidates
from backend.generation import Proposal
from backend.pipeline import prepare
from fastapi.testclient import TestClient


def main():
    os.environ.pop('TRACE_ACCESS_FILE',None)
    source=ROOT/'output/verification_task_selection_v2_20261102'
    expected={item['id']:item for item in json.loads((source/'manifest.json').read_text(encoding='utf-8-sig'))}
    report={'model_calls':0,'revision_model':'deterministic test double, not live LLM',
            'cases':[],'runtime_executions':0,'ui_fixtures':[]}
    class NoInitialModel:
        def generate(self,*args):raise AssertionError('Initial model call forbidden')
    with tempfile.TemporaryDirectory(prefix='trace-woz-v2-') as folder:
        server.STORE=Path(folder)
        with TestClient(server.app) as client:
            catalog=client.get('/api/woz-tasks').json()
            assert set(expected)<=set(item['id'] for item in catalog)
            assert not set(expected)&set(item['id'] for item in client.get('/api/study-tasks').json())
            for cid,manifest in expected.items():
                server.generator=NoInitialModel()
                candidate=candidates.load(cid)
                assert candidate['participant_enabled'] is False and candidate['selected_for_study'] is False
                fields=client.get(f'/api/woz-tasks/{cid}/input').json()
                assert not any(key in fields for key in ('description','participant_description','fault_steps','reference_code','initial_code'))
                response=client.post(f'/api/woz-tasks/{cid}/start',json={key:fields[key] for key in ('input_csv','target_csv')})
                assert response.status_code==200,response.text
                session=response.json();assert session['status']=='ready',session.get('error')
                run=session['run'];report['runtime_executions']+=1
                assert run['code']==candidate['initial_code'] and len(run['stages'])-1==manifest['steps']
                assert run['comparison']['matches']==manifest['initial_target_match']
                assert run['pipeline']['grouping_source']=='provided'
                assert run['pipeline']['steps'][0]['statement_indices']==candidate['steps'][0]['statement_indices']
                sid=session['id'];baseline=session['review_baseline']
                assert [step['id'] for step in baseline['steps']]==[step['id'] for step in run['stages'][1:]]
                for condition in ('ex','in-situ'):
                    switched=client.post(f'/api/sessions/{sid}/condition',json={'condition':condition},headers={'X-Trace-View':'participant'}).json()
                    assert switched['run']['id']==run['id'] and switched['run']['code']==run['code']
                    assert 'comparison' not in switched['run'] and 'task_provenance' not in switched
                    assert 'judgment_evaluations' not in switched
                result={'id':cid,'steps':manifest['steps'],'snapshot_sha256':session['task_provenance']['snapshot_sha256'],
                        'initial_matches':run['comparison']['matches'],'trace_levels':[step['trace_level'] for step in run['stages'][1:]],
                        'shared_run_in_both_conditions':True,'partial_repairs':[]}
                if cid in ('VERIFY2-H1-A','VERIFY2-H2-A'):
                    report['ui_fixtures'].append({'id':cid,'run':run,'baseline':baseline})
                if manifest['level']=='hard':
                    for selected in ([manifest['fault_steps'][0]],manifest['fault_steps']):
                        payload={'submission_id':str(uuid.uuid4()),'initial_run_id':run['id'],'execution_version':run['id'],
                                 'condition':'in-situ','answer':'steps','step_ids':[baseline['steps'][index-1]['id'] for index in selected]}
                        submitted=client.post(f'/api/sessions/{sid}/initial-step-judgment',json=payload)
                        assert submitted.status_code==200 and 'exact_step_set' not in submitted.text
                        evaluation=server.read(sid)['judgment_evaluations'][-1]
                        assert evaluation['exact_step_set']==(len(selected)==2)
                    result['multiple_step_response_verified']=True
                    reference=prepare(candidate['reference_code'],candidate['reference_steps'],engine='python')
                    faults=manifest['fault_steps']
                    for repaired in ([faults[0]],[faults[1]],faults):
                        class RepairModel:
                            def generate(self,inp,target,requirements,previous_code,request,context):
                                assert requirements==''
                                return Proposal(base_run_id=context['base_run_id'],changes=[{
                                    'action':'replace','step_id':baseline['steps'][index-1]['id'],
                                    'label':candidate['steps'][index-1]['label'],
                                    'code':reference['steps'][index-1]['code']} for index in repaired])
                        server.generator=RepairModel()
                        revision=client.post(f'/api/sessions/{sid}/generate',json={'request':'검수한 변환을 수정해 주세요.',
                            'scope':'step' if len(repaired)==1 else 'pipeline','base_run_id':run['id'],
                            'context':{'step_id':baseline['steps'][repaired[0]-1]['id']}}).json()
                        assert revision['status']=='ready',revision.get('error')
                        report['runtime_executions']+=1
                        assert revision['run']['comparison']['matches']==(len(repaired)==2)
                        assert revision['review_baseline']==baseline
                        result['partial_repairs'].append({'repaired_initial_steps':list(repaired),
                            'target_match':revision['run']['comparison']['matches'],
                            'changed_code_steps':[index for index,step in enumerate(revision['run']['stages'][1:],1) if step['diff'].get('code_changed')],
                            'changed_output_steps':[index for index,step in enumerate(revision['run']['stages'][1:],1) if step['diff'].get('output_changed')]})
                        restored=client.post(f'/api/sessions/{sid}/undo',json={}).json()
                        assert restored['run']['id']==run['id']
                report['cases'].append(result)
                print(json.dumps({'id':cid,'passed':True,'steps':manifest['steps']}),flush=True)
    destination=ROOT/'.local/woz-v2-validation';destination.mkdir(parents=True,exist_ok=True)
    fixtures=report.pop('ui_fixtures')
    (destination/'ui-fixtures.json').write_text(json.dumps(fixtures,ensure_ascii=False),encoding='utf-8')
    (destination/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'cases':len(report['cases']),'runtime_executions':report['runtime_executions'],'model_calls':0}))


if __name__=='__main__':main()
