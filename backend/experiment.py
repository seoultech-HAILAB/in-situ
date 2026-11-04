"""Server-timed, resumable experiments and durable, labelled interaction records.

Browser credentials identify one experiment, never an LLM account. Export is a
local researcher command; the public API cannot list participants or their logs.
Run one application worker (as the existing file-backed session store requires).
"""
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
import sys
from contextvars import ContextVar
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from . import candidates

TASKS = ('PILOT4-T07', 'PILOT4-T01', 'PILOT4-T03')
LEGACY_TASKS = ('PILOT4-T01', 'PILOT4-T03', 'PILOT4-T05')
TUTORIAL_TASK = 'PILOT4-TRAIN'
TASK_SECONDS = 15 * 60
BREAK_SECONDS = 60
VERSION = 'timed-study-v2'
credentials = ContextVar('experiment_credentials', default=None)

# Stable, analysis-facing labels. Generic browser events retain element/context
# details; domain events also include selected Step, run and candidate identities.
LABELS = {
    'study.created': '실험 등록', 'study.resumed': '실험 복원',
    'study.replaced': '과제 순서 변경으로 새 실험 시작',
    'tutorial.started': '튜토리얼 시작', 'tutorial.completed': '튜토리얼 종료',
    'task.preparing': '과제 준비', 'task.started': '과제 시작',
    'task.start_prompt': '과제 시작 안내 열기', 'task.start_confirmed': '과제 시작 버튼 클릭',
    'instructions.open': '과제 안내 열기', 'instructions.close': '과제 안내 닫기',
    'instructions.loaded': '과제 안내 이미지 로드', 'instructions.failed': '과제 안내 이미지 로드 실패',
    'tutorial.instructions_confirmed': '튜토리얼 안내 확인 후 시작',
    'task.finish_prompt': '과제 종료 확인 열기', 'task.finish_cancelled': '과제 종료 취소',
    'task.finish_confirmed': '과제 종료 확인',
    'task.finished': '과제 종료', 'break.started': '휴식 시작',
    'break.completed': '휴식 종료', 'study.completed': '실험 완료',
    'workspace.ready': '작업 화면 준비', 'view.step': 'Step 관찰',
    'view.input': '입력 테이블 관찰', 'view.table': '테이블 전환',
    'view.output': '최종 결과 관찰', 'view.context': '관찰 맥락 변경',
    'transformation.open': '개별 변환 설명 열기',
    'transformation.close': '개별 변환 설명 닫기',
    'explanation.visible': '연산 설명 화면 노출', 'explanation.hidden': '연산 설명 화면 노출 종료',
    'revision.submitted': '자연어 수정 제출', 'revision.approve': '수정 승인 요청',
    'revision.deny': '수정 거부 요청', 'workspace.action_started': '작업 시작',
    'revision.undo': '확정 수정 되돌리기 요청',
    'workspace.action_completed': '작업 완료', 'workspace.action_failed': '작업 실패',
    'ui.click': '클릭', 'ui.input': '입력 내용 변경', 'ui.key': '조작 키 입력',
    'ui.focus': '요소 초점', 'ui.blur': '요소 초점 해제',
    'ui.scroll': '영역 스크롤', 'ui.pointer': '포인터 위치 표본',
    'ui.selection': '텍스트 선택', 'ui.copy': '복사', 'ui.paste': '붙여넣기',
    'ui.resize': '화면 크기 변경', 'ui.panel_resize': '패널 크기 변경',
    'page.enter': '페이지 진입', 'page.hide': '페이지 이탈',
    'page.visibility': '화면 표시 상태 변경', 'page.focus': '브라우저 활성화',
    'page.blur': '브라우저 비활성화', 'network.online': '네트워크 연결',
    'network.offline': '네트워크 끊김', 'page.heartbeat': '활동 상태 표본',
    'client.error': '브라우저 오류', 'client.rejection': '비동기 오류',
    'http.completed': '서버 요청 완료', 'http.failed': '서버 요청 실패',
    'backend.event': '백엔드 처리 기록', 'backend.snapshot': '코드·실행·설명 스냅샷',
    'llm.completed': 'LLM 응답 수신',
}


class Enrollment(BaseModel):
    condition: Literal['in-situ', 'ex']
    environment: dict = Field(default_factory=dict)
    previous_experiment_id: str | None = Field(default=None,max_length=80)


class Action(BaseModel):
    action: Literal['prepare_tutorial', 'prepare', 'begin', 'finish', 'next', 'resume']
    expected_phase: str | None = None
    expected_index: int | None = None


class ClientEvent(BaseModel):
    id: uuid.UUID
    label: str = Field(max_length=80)
    client_at: str = Field(max_length=80)
    sequence: int = Field(ge=0)
    page_id: str = Field(max_length=80)
    data: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)


class EventBatch(BaseModel):
    events: list[ClientEvent] = Field(max_length=250)


def folder(server):
    result = server.STORE.parent / 'experiments'
    result.mkdir(parents=True, exist_ok=True)
    return result


def state_path(server, eid):
    try:
        uuid.UUID(eid)
    except (ValueError, TypeError):
        raise HTTPException(404, '실험을 찾을 수 없습니다.')
    return folder(server) / f'{eid}.json'


def load(server, eid):
    try:
        return json.loads(state_path(server, eid).read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise HTTPException(404, '실험을 찾을 수 없습니다.')


def save(server, state):
    dest = state_path(server, state['id'])
    temp = dest.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    temp.replace(dest)


def verify(state, token):
    digest = hashlib.sha256((token or '').encode()).hexdigest()
    if not hmac.compare_digest(state['token_hash'], digest):
        raise HTTPException(403, '이 실험의 접속 정보가 필요합니다.')


def sequence(state):
    # Old records without a frozen sequence retain their original task labels.
    return tuple(state.get('task_order') or (TASKS if state.get('protocol_version')==VERSION else LEGACY_TASKS))


def record(server, state, label, data=None, **extra):
    entry = dict(id=str(uuid.uuid4()), label=label, action_label=LABELS.get(label, label),
                 server_at=server.now(), experiment_id=state['id'],
                 participant_id=state['participant_id'], condition=state['condition'],
                 protocol_version=state.get('protocol_version','timed-study-v1'), phase=state['phase'],
                 task_index=state['task_index'], task_number=None if state['phase']=='tutorial' else state['task_index'] + 1,
                 task_id=TUTORIAL_TASK if state['phase']=='tutorial' else sequence(state)[state['task_index']], session_id=state.get('session_id'),
                 data=data or {})
    entry.update(extra)
    with sqlite3.connect(folder(server) / 'events.sqlite3', timeout=30) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS events (experiment_id TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(experiment_id,id))')
        db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?)',
                   (state['id'], entry['id'], json.dumps(entry, ensure_ascii=False, allow_nan=False)))


def public(server, state):
    return {**{k: v for k, v in state.items() if k != 'token_hash'},
            'server_now': time.time(), 'task_seconds': TASK_SECONDS,
            'break_seconds': BREAK_SECONDS,
            'current_protocol_version':VERSION,'task_order':list(sequence(state)),
            'tutorial_task': candidates.study_summary(candidates.load(TUTORIAL_TASK)),
            'tasks': [{'id': tid, **candidates.study_summary(candidates.load(tid))} for tid in sequence(state)]}


def finish(server, state, reason):
    sid = state.get('session_id')
    snapshot = None
    if sid:
        with server.lock(sid):
            session = server.read(sid)
            run = server.current(session)
            snapshot = {'run_id': run['id'] if run else None, 'code_version': run['code_version'] if run else None,
                        'pending_revision_id': (session.get('pending_revision') or {}).get('id')}
    ended = time.time()
    state.setdefault('completed_tasks', []).append({
        'task_id': sequence(state)[state['task_index']], 'task_number': state['task_index'] + 1,
        'session_id': sid, 'started_at': state.get('started_at'),
        'ended_at': min(ended, state.get('deadline') or ended), 'detected_at': ended,
        'reason': reason, 'final_snapshot': snapshot,
    })
    record(server, state, 'task.finished', state['completed_tasks'][-1])
    if state['task_index'] == len(sequence(state)) - 1:
        state.update(phase='complete', deadline=None)
        record(server, state, 'study.completed')
    else:
        # The break starts when the participant actually reaches it, even if
        # the task expired while their browser was closed/offline.
        state.update(phase='break', break_started_at=ended, deadline=ended + BREAK_SECONDS)
        record(server, state, 'break.started', {'seconds': BREAK_SECONDS})
    save(server, state)


def advance_clock(server, state):
    if not state.get('superseded_by') and state['phase'] == 'task' and time.time() >= state['deadline']:
        finish(server, state, 'timeout')


def authorize_session(server, session, mutate=False, allow_preparing=False):
    eid = session.get('experiment_id')
    if not eid:
        return
    auth = credentials.get() or {}
    if auth.get('id') != eid:
        raise HTTPException(403, '이 실험의 접속 정보가 필요합니다.')
    state = load(server, eid)
    verify(state, auth.get('token'))
    if mutate and (state.get('superseded_by') or state.get('session_id') != session['id'] or
                   state['phase'] not in (('task', 'tutorial', 'preparing') if allow_preparing else ('task', 'tutorial')) or
                   (state['phase'] == 'task' and time.time() >= state['deadline'])):
        raise HTTPException(409, '이 과제의 작업 시간이 종료되었습니다.')


def snapshot(server, session, reason):
    if not session.get('experiment_id'):
        return
    state = load(server, session['experiment_id'])
    # Retain candidate code/results/explanations even after Deny removes it
    # from the active workspace. Only local researcher exports contain this.
    record(server, state, 'backend.snapshot', {
        'reason': reason, 'run': server.current(session),
        'pending_revision': session.get('pending_revision'),
        'session_id': session['id'],
    })


def llm_record(payload, response, purpose):
    """Record provider identifiers/usage and exact prompts without auth headers."""
    auth = credentials.get() or {}
    if not auth.get('id'):
        return
    server = sys.modules.get('backend.app')
    if server is None:
        return
    state = load(server, auth['id'])
    try:
        body = response.json()
    except ValueError:
        body = {}
    record(server, state, 'llm.completed', {
        'purpose': purpose, 'model': payload.get('model'), 'http_status': response.status_code,
        'response_id': body.get('id'), 'status': body.get('status'), 'usage': body.get('usage'),
        'instructions': payload.get('instructions'), 'input': payload.get('input'),
        'output_text': [part.get('text') for item in body.get('output', []) for part in item.get('content', []) if part.get('type')=='output_text'],
    })


def bind_session(server, state, session):
    session.update(experiment_id=state['id'], participant_id=state['participant_id'], study_mode=state['protocol_version'])
    for entry in session['events']:
        entry.update(participant_id=state['participant_id'], study_mode=state['protocol_version'], task_id=session['task_id'])
        record(server, state, 'backend.event', entry)
    server.save(session)


def register(server):
    app = server.app

    @app.post('/api/experiments')
    def enroll(body: Enrollment):
        if len(json.dumps(body.environment)) > 16000:
            raise HTTPException(422, '환경 정보가 너무 큽니다.')
        token = secrets.token_urlsafe(32)
        previous=None
        if body.previous_experiment_id:
            auth=credentials.get() or {}
            if auth.get('id')!=body.previous_experiment_id:
                raise HTTPException(403,'이전 실험의 접속 정보가 필요합니다.')
            previous=load(server,body.previous_experiment_id)
            verify(previous,auth.get('token'))
        state = dict(id=str(uuid.uuid4()), participant_id='P-' + secrets.token_hex(6),
                     token_hash=hashlib.sha256(token.encode()).hexdigest(),
                     condition=body.condition, phase='tutorial', task_index=0,
                     session_id=None, tutorial_session_id=None, deadline=None,
                     created_at=server.now(), protocol_version=VERSION, task_order=list(TASKS), environment=body.environment)
        if previous:state['previous_experiment_id']=previous['id']
        save(server, state)
        record(server, state, 'study.created', {'environment': body.environment})
        if previous:
            with server.lock('experiment:'+previous['id']):
                previous=load(server,previous['id'])
                previous['superseded_by']=state['id']
                previous['task_order']=list(sequence(previous))
                record(server,previous,'study.replaced',{'new_experiment_id':state['id'],'new_task_order':list(TASKS)})
                save(server,previous)
        return {**public(server, state), 'token': token}

    def authenticated(request, eid):
        state = load(server, eid)
        verify(state, request.headers.get('x-study-token'))
        return state

    @app.get('/api/experiments/{eid}')
    def get_state(eid: str, request: Request):
        with server.lock('experiment:' + eid):
            state = authenticated(request, eid)
            advance_clock(server, state)
            return public(server, state)

    @app.post('/api/experiments/{eid}/action')
    def action(eid: str, body: Action, request: Request):
        with server.lock('experiment:' + eid):
            state = authenticated(request, eid)
            if state.get('superseded_by') and body.action!='resume':
                raise HTTPException(409,'과제 순서가 변경되었습니다. 새 실험으로 시작하세요.')
            advance_clock(server, state)
            if body.expected_phase is not None and (body.expected_phase != state['phase'] or body.expected_index != state['task_index']):
                return public(server, state)  # Idempotent retry or a second tab.
            phase = state['phase']
            if body.action == 'resume':
                record(server, state, 'study.resumed')
            elif body.action == 'prepare_tutorial' and phase == 'tutorial':
                old_sid = state.get('session_id')
                existing = server.read(old_sid) if old_sid else None
                if not existing or existing['task_id'] != TUTORIAL_TASK:
                    registered = server.start_study(TUTORIAL_TASK, server.StudyStart(condition=state['condition']), preview=True, woz=True)
                    s = server.read(registered['id'])
                    if s['status'] != 'ready':
                        raise HTTPException(422, '튜토리얼 실행에 실패했습니다. 다시 시도하세요.')
                    if old_sid:
                        state.setdefault('previous_tutorial_session_ids', []).append(old_sid)
                    state.update(session_id=s['id'], tutorial_session_id=s['id'])
                    bind_session(server, state, s)
                    record(server, state, 'tutorial.started', {'task_id': TUTORIAL_TASK, 'replaced_session_id': old_sid})
            elif body.action == 'prepare' and phase in ('tutorial', 'ready'):
                if phase == 'tutorial':
                    record(server, state, 'tutorial.completed')
                # Task preparation is deliberately outside the timed interval.
                prepared = server.start_study(sequence(state)[state['task_index']], server.StudyStart(condition=state['condition']), preview=True, woz=True)
                s = server.read(prepared['id'])
                if s['status'] != 'ready':
                    raise HTTPException(422, '과제 실행에 실패했습니다. 다시 시도하세요.')
                state.update(phase='preparing', session_id=s['id'], deadline=None)
                bind_session(server, state, s)
                record(server, state, 'task.preparing')
            elif body.action == 'begin' and phase == 'preparing':
                started=time.time()
                state.update(phase='task', started_at=started, deadline=started + TASK_SECONDS)
                record(server, state, 'task.started', {'started_at':started,'deadline': state['deadline']})
            elif body.action == 'finish' and phase == 'task':
                finish(server, state, 'participant')
            elif body.action == 'next' and phase == 'break':
                ended = time.time()
                record(server, state, 'break.completed', {
                    'skipped': ended < state['deadline'],
                    'elapsed_seconds': max(0, ended - state.get('break_started_at', state['deadline'] - BREAK_SECONDS)),
                    'remaining_seconds': max(0, state['deadline'] - ended),
                })
                state.update(phase='ready', task_index=state['task_index'] + 1, session_id=None, deadline=None)
            else:
                raise HTTPException(409, '현재 단계에서 수행할 수 없는 요청입니다.')
            save(server, state)
            return public(server, state)

    @app.post('/api/experiments/{eid}/events')
    def events(eid: str, body: EventBatch, request: Request):
        state = authenticated(request, eid)
        for item in body.events:
            if item.label not in LABELS or len(json.dumps(item.model_dump(mode='json'), ensure_ascii=False).encode()) > 45000:
                raise HTTPException(422, '올바르지 않은 로그입니다.')
        for item in body.events:
            values = item.model_dump(mode='json')
            record(server, state, values.pop('label'), values.pop('data'), **values)
        return {'ok': True, 'accepted': [str(e.id) for e in body.events]}
