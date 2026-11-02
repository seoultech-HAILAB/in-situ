"""Pilot feedback and exports. Self reports do not label task correctness."""
import csv
import io
from typing import Literal
from uuid import UUID

from pydantic import BaseModel,Field,field_validator
from .conditions import normalize


class Feedback(BaseModel):
    submission_id: UUID
    execution_version: str | None=None
    condition: str

    @field_validator('condition')
    @classmethod
    def active_condition(cls,value):return normalize(value)

    task_clarity: int | None=Field(default=None,ge=1,le=5)
    navigation_ease: int | None=Field(default=None,ge=1,le=5)
    change_understanding: int | None=Field(default=None,ge=1,le=5)
    outcome: Literal['revised','found_not_revised','uncertain','blocked','task_issue','time_limit']
    issue_types:list[Literal['ambiguous_requirement','insufficient_input','target_inconsistent','ui_problem','revision_problem','other']]=Field(default_factory=list,max_length=6)
    comments: str=Field(default='',max_length=3000)


def session_summary(s):
    events=s.get('events',[])
    runs=s.get('runs',[])
    r=runs[s['cursor']] if s.get('cursor',-1)>=0 else None
    feedbacks=s.get('feedbacks',[])
    feedback=feedbacks[-1] if feedbacks else {}
    reviews=[e for e in events if e['event']=='review_started']
    actors={e.get('actor_id') for e in events if e.get('actor_id')}
    return {'participant_id':s.get('participant_id'),'session_id':s['id'],
        'task_id':s['task_id'],'review_number':s.get('task_display',{}).get('review_number'),
        'title':s.get('task_display',{}).get('title',s['task_id']),
        'condition':s['condition'],'condition_changed':any(e['event']=='condition_changed' for e in events),
        'assignment_id':s.get('assignment',{}).get('id'),'plan_version':s.get('assignment',{}).get('plan_version'),
        'mixed_actors':bool(actors-{s.get('creator_id')}),'started_at':s['created_at'],
        'review_started_at':reviews[0]['timestamp'] if reviews else None,
        'status':s['status'],'confirmed':bool(s.get('confirmed')),
        'execution_version':r['id'] if r else None,
        'revision_requests':sum(e['event']=='revision_requested' for e in events),
        'revision_executions':sum(e['event']=='revision_execution_completed' for e in events),
        'revision_failures':sum(e['event'] in ('revision_failed','revision_execution_failed') for e in events),
        'undo_count':sum(e['event']=='undo' for e in events),'event_count':len(events),
        'last_event_id':events[-1]['id'] if events else None,
        'feedback_count':len(feedbacks),'last_feedback_at':feedback.get('at'),
        'feedback_execution_version':feedback.get('execution_version'),
        'issue_types':feedback.get('issue_types',[]),
        **{key:feedback.get(key) for key in ('task_clarity','navigation_ease','change_understanding','outcome','comments')}}


def csv_text(rows,columns=None):
    out=io.StringIO()
    columns=columns or (list(rows[0]) if rows else ['participant_id','task_id','condition','session_id'])
    writer=csv.DictWriter(out,fieldnames=columns,extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        # Keep raw text in JSONL; prevent spreadsheet formula evaluation in CSV.
        writer.writerow({k: "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for k,v in row.items()})
    return '\ufeff'+out.getvalue()
