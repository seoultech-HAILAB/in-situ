"""Isolated, single-Step revision previews; only approval commits a full run."""
from copy import deepcopy
import importlib
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .pipeline import prepare, patch, validate_scope
from .transformation_selection import selected_transformation, validate_selected_edit
from .transformations import annotate_run
from .transformation_effects import revision_effects
from . import explanations


class RevisionRequest(BaseModel):
    request: str = Field(min_length=1, max_length=5000)
    base_run_id: str
    context: dict = Field(default_factory=dict)


def public_preview(pending, baseline_run=None):
    if not pending:
        return None
    result = {key: pending[key] for key in
              ('id', 'base_run_id', 'step_id', 'step_number', 'label', 'request', 'status', 'scope', 'error', 'assumptions') if key in pending}
    run = annotate_run(deepcopy(pending['preview_run'])) if pending.get('preview_run') else None
    if run:
        baseline=next((stage for stage in (baseline_run or {}).get('stages',[]) if stage['id']==pending['step_id']),None)
        if baseline:revision_effects(run,baseline)
        location=run['stages'][-1]['code_location']
        result.update(stage=deepcopy(run['stages'][-1]), execution_version=run['id'],
                      step_code='\n'.join(run['code'].splitlines()[location['start']-1:location['end']]),
                      explanation_status=run.get('explanation_status'), explanation_error=run.get('explanation_error'))
    return result


def _pending(server, session, preview_id, statuses):
    pending = session.get('pending_revision')
    if not pending or pending['id'] != preview_id or pending['status'] not in statuses:
        raise HTTPException(409, '이 수정 후보는 더 이상 대기 중이 아닙니다.')
    if server.current(session)['id'] != pending['base_run_id']:
        raise HTTPException(409, '기준 실행이 바뀌었습니다. 후보를 거부하고 다시 요청하세요.')
    return pending


def install(app):
    server = importlib.import_module('backend.app')

    @app.post('/api/sessions/{sid}/revision-preview')
    def propose(sid: str, body: RevisionRequest):
        with server.lock(sid):
            session = server.read(sid)
            base = server.current(session)
            if not base or base['id'] != body.base_run_id:
                raise HTTPException(409, '기준 실행 버전이 달라졌습니다. 최신 실행을 다시 열어주세요.')
            if session.get('pending_revision'):
                raise HTTPException(409, '대기 중인 후보를 먼저 승인하거나 거부하세요.')
            target_id = body.context.get('step_id')
            target = next((stage for stage in base['stages'][1:] if stage['id'] == target_id), None)
            if not target or not body.request.strip():
                raise HTTPException(422, '현재 관찰 중인 Step과 수정 요청이 필요합니다.')
            try:
                selected = selected_transformation(base, body.context)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            pending = dict(id=str(uuid.uuid4()), base_run_id=base['id'], step_id=target_id,
                           step_number=target['order'], label=f"Step {target['order']}a",
                           request=body.request.strip(), status='generating')
            session['pending_revision'] = pending
            server.event(session, 'revision_preview_requested', public_preview(pending))
            server.save(session)
            snapshot = deepcopy(session)
        # Model/worker calls deliberately happen outside the session lock.
        # Confirmed runs, downloads and table navigation remain available.
        try:
            context = {**body.context, 'scope': 'auto', 'base_run_id': base['id'],
                       'pipeline': base['pipeline'], 'target_step': target,
                       'selected_transformation': selected,
                       'cumulative_requirements': base.get('cumulative_requirements', []),
                       'source_tables': snapshot.get('sources_csv', {}),
                       'approval_workflow': 'Preview ONLY target_step. Infer revision_scope from the request and selected transformation. Preserve target Step identity; replace it rather than deleting it.'}
            if base['mode'] == 'demo':
                proposal = server.revise_demo(base['code'], body.request)
                mode = 'demo'
            else:
                proposal = server.generator.generate(snapshot['input_csv'], snapshot['target_csv'], snapshot['requirements'],
                                                     base['code'], body.request, context)
                mode = 'api'
            plan = (patch(base, proposal.changes, proposal.base_run_id, 'pipeline', target_id)
                    if proposal.changes else prepare(proposal.code, proposal.steps or None, base,
                                                     engine=snapshot.get('execution_engine', 'capability')))
            outside = any(stage['id'] != target_id and
                          next((old['code'] for old in base['pipeline']['steps'] if old['id'] == stage['id']), None) != stage['code']
                          for stage in plan['steps']) or any(old['id'] != target_id and not any(st['id'] == old['id'] for st in plan['steps']) for old in base['pipeline']['steps'])
            scope = getattr(proposal, 'revision_scope', None) or ('pipeline' if outside else 'transformation' if selected else 'step')
            validate_scope(plan, base, 'pipeline' if scope == 'pipeline' else 'step', target_id)
            if scope == 'transformation':
                validate_selected_edit(plan['code'], base, selected, 'step')
            index = next((i for i, stage in enumerate(plan['steps']) if stage['id'] == target_id), None)
            if index is None:
                raise ValueError('현재 Step의 후보가 필요합니다. 해당 Step을 삭제하지 말고 수정해주세요.')
            prefix = deepcopy(plan)
            prefix.update(steps=prefix['steps'][:index + 1], preview_only=True)
            preview_run = server.execute(snapshot, plan['code'], proposal.assumptions, mode, body.request, prepared=prefix)
            # Retain only this Step in the review snapshot. Upstream code is still
            # available to AST source-definition analysis; no downstream is run.
            preview_run['stages'] = [preview_run['stages'][0], preview_run['stages'][-1]]
            preview_run['operations'] = preview_run['stages'][-1].get('operations', [])
            preview_run.pop('comparison', None)
            ready = dict(pending, status='ready', scope=scope, plan=plan, mode=mode,
                         assumptions=proposal.assumptions, preview_run=preview_run)
        except Exception as exc:
            ready = dict(pending, status='failed', error=str(exc)[:2000])
        with server.lock(sid):
            session = server.read(sid)
            _pending(server, session, pending['id'], ('generating',))
            session['pending_revision'] = ready
            server.event(session, 'revision_preview_ready' if ready['status'] == 'ready' else 'revision_preview_failed',
                         {'preview_id': pending['id'], 'step_id': target_id, 'error': ready.get('error')})
            server.save(session)
            return server.view(session)

    @app.post('/api/sessions/{sid}/revision-preview/{preview_id}/approve')
    def approve(sid: str, preview_id: str):
        with server.lock(sid):
            session = server.read(sid)
            pending = _pending(server, session, preview_id, ('ready',))
            pending['status'] = 'approving'
            pending.pop('error', None)
            server.save(session)
            snapshot = deepcopy(session)
        try:
            # Execute the complete pipeline before committing anything. A later
            # failure leaves the confirmed code and every original result intact.
            run = server.execute(snapshot, pending['plan']['code'], pending['assumptions'], pending['mode'],
                                 pending['request'], prepared=deepcopy(pending['plan']))
        except Exception as exc:
            with server.lock(sid):
                session = server.read(sid)
                active = _pending(server, session, preview_id, ('approving',))
                active.update(status='ready', error=f'전체 파이프라인 실행 실패: {str(exc)[:1500]}')
                server.save(session)
                return server.view(session)
        with server.lock(sid):
            session = server.read(sid)
            _pending(server, session, preview_id, ('approving',))
            session['runs'].append(run)
            session.update(cursor=len(session['runs']) - 1, status='ready', error=None, confirmed=None, pending_revision=None)
            server.event(session, 'revision_approved', {'preview_id': preview_id, 'step_id': pending['step_id']})
            server.save(session)
            return server.view(session)

    @app.post('/api/sessions/{sid}/revision-preview/{preview_id}/deny')
    def deny(sid: str, preview_id: str):
        with server.lock(sid):
            session = server.read(sid)
            _pending(server, session, preview_id, ('ready', 'failed'))
            session['pending_revision'] = None
            server.event(session, 'revision_denied', {'preview_id': preview_id})
            server.save(session)
            return server.view(session)

    @app.post('/api/sessions/{sid}/revision-preview/{preview_id}/explanations')
    def describe(sid: str, preview_id: str):
        with server.lock(sid):
            session = server.read(sid)
            pending = _pending(server, session, preview_id, ('ready',))
            snapshot = deepcopy(pending['preview_run'])
        try:
            bundle, cached = explanations.obtain(snapshot, require_transformations=True)
            explanations.attach(snapshot, bundle, cached)
        except Exception as exc:
            snapshot.update(explanation_status='failed', explanation_error=str(exc)[:500])
        with server.lock(sid):
            session = server.read(sid)
            pending = _pending(server, session, preview_id, ('ready',))
            pending['preview_run'] = snapshot
            server.save(session)
            return server.view(session)
