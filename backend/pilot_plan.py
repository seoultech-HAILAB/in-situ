"""Two active conditions; historical three-condition plans remain archived."""
VERSION='pilot-two-condition-v4'
PREVIOUS_VERSIONS={VERSION}
EXCLUDED_TASK_NUMBERS={5,6,12}
EXCLUDED_TASK_IDS={f'R500-{number:03}' for number in EXCLUDED_TASK_NUMBERS}
TASK_NUMBERS=[number for number in range(1,17) if number not in EXCLUDED_TASK_NUMBERS]
CONDITIONS=('ex','in-situ')
PARTICIPANTS={'P01':(0,0),'P02':(1,4),'P03':(2,8)}


def allocations(pid):
    if pid not in PARTICIPANTS:return []
    condition_offset,order_offset=PARTICIPANTS[pid]
    order=TASK_NUMBERS[order_offset:]+TASK_NUMBERS[:order_offset]
    tasks=[(number,CONDITIONS[(TASK_NUMBERS.index(number)+condition_offset)%2]) for number in order]
    return [{'id':f'{VERSION}:{pid}:R500-{number:03}:{condition}','plan_version':VERSION,'order':position,
             'task_id':f'R500-{number:03}','condition':condition,'review_number':number,
             'phase':'two-condition-screening'}
            for position,(number,condition) in enumerate(tasks,1)]


def progress(pid,sessions,available_task_ids=None):
    plan=allocations(pid)
    if available_task_ids is not None:plan=[item for item in plan if item['task_id'] in available_task_ids]
    by_id={}
    for s in sorted(sessions,key=lambda s:s['created_at']):
        assignment=s.get('assignment',{})
        if s.get('participant_id')==pid and assignment.get('plan_version') in PREVIOUS_VERSIONS:
            # Preserve actual task/condition identity across removed positions;
            # a completed old position 6 must never complete its replacement.
            by_id[(s['task_id'],s['condition'])]=s
    completed=0;current=None;session_id=None;entries=[]
    for item in plan:
        session=by_id.get((item['task_id'],item['condition']))
        if session and session.get('feedbacks'):
            completed+=1;status='completed'
        elif current is None:
            current=item;session_id=session['id'] if session else None;status='current'
        else:status='locked'
        entries.append({**item,'status':status})
    return {'plan_version':VERSION,'participant_id':pid,'total':len(plan),'completed':completed,
            'current':current,'session_id':session_id,'assignments':entries}
