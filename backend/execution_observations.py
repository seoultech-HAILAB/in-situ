"""Upgrade saved executions with statement observations, without replacing runs."""
from copy import deepcopy
import importlib

from fastapi import HTTPException
from pydantic import BaseModel

from .pipeline import assemble
from .statement_observations import VERSION


class ObservationRequest(BaseModel):
    run_id: str


def install(app):
    server=importlib.import_module('backend.app')

    @app.post('/api/sessions/{sid}/execution-observations')
    def refresh(sid: str, body: ObservationRequest):
        with server.lock(sid):
            session=server.read(sid);run=server.current(session)
            if not run or run['id']!=body.run_id:raise HTTPException(409,'실행 버전이 바뀌었습니다.')
            if run.get('execution_observations_version')==VERSION:return server.view(session)
            snapshot=deepcopy(run);inputs=session['input_csv'];sources=session.get('sources_csv',{})
        try:
            plan=deepcopy(snapshot['pipeline'])
            records=server.isolated_run(snapshot['code'],inputs,sources,engine=plan['engine'],plan=plan)
            stages,_=assemble(records,plan)
            old={stage['id']:stage for stage in snapshot['stages']}
            if set(old)!={stage['id'] for stage in stages}:raise ValueError('Step 경계가 기존 실행과 다릅니다.')
            if any(stage['table']!=old[stage['id']]['table'] or stage.get('input')!=old[stage['id']].get('input') for stage in stages):
                raise ValueError('재관찰 결과가 저장된 실행과 달라 기존 결과를 유지합니다. 코드를 다시 실행해주세요.')
            failure=None
        except Exception as exc:
            stages=[];failure=str(exc)[:500]
        with server.lock(sid):
            session=server.read(sid);run=server.current(session)
            if not run or run['id']!=body.run_id:raise HTTPException(409,'관찰 중 실행 버전이 바뀌었습니다.')
            keys=('operation_observations','row_correspondence','row_correspondence_complete',
                  'observation_row_aliases','execution_observations_version')
            if failure:
                run.update(execution_observations_version='unavailable-v3',execution_observations_error=failure)
            else:
                by_id={stage['id']:stage for stage in stages}
                for stage in run['stages'][1:]:
                    fresh=by_id[stage['id']]
                    for key in keys:
                        if key in fresh:stage[key]=deepcopy(fresh[key])
                        else:stage.pop(key,None)
                run['execution_observations_version']=VERSION
                run.pop('execution_observations_error',None)
                server.annotate_run(run)
            server.event(session,'execution_observations_refreshed',{'run_id':body.run_id,'error':failure})
            server.save(session)
            return server.view(session)
