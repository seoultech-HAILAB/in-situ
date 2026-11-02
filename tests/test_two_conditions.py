import copy

from backend import pilot_plan
from backend.conditions import normalize


def test_only_two_active_conditions_and_historical_read_aliases():
    assert {normalize(value) for value in ('A','B2','B','C','ex','in-situ')}=={'ex','in-situ'}
    assert normalize('A')==normalize('B2')=='ex'


def test_retired_tasks_leave_no_dangling_assignment_and_do_not_assign_private_replacements():
    state=pilot_plan.progress('P01',[],available_task_ids={'VERIFY2-H1-A','VERIFY2-M1-A'})
    assert state['total']==0 and state['current'] is None and state['assignments']==[]


def test_new_pilot_plan_uses_two_conditions_without_relabeling_old_completions():
    assert pilot_plan.CONDITIONS==('ex','in-situ')
    for pid in pilot_plan.PARTICIPANTS:
        plan=pilot_plan.allocations(pid)
        assert len(plan)==13 and all(item['review_number'] not in {5,6,12} for item in plan)
        assert abs(sum(item['condition']=='ex' for item in plan)-sum(item['condition']=='in-situ' for item in plan))<=1
        legacy={'id':'historic','task_id':plan[0]['task_id'],'condition':'ex','created_at':'2026-10-30',
                'participant_id':pid,'assignment':{'plan_version':'pilot-balanced-v3'},'feedbacks':[{}]}
        original=copy.deepcopy(legacy)
        assert pilot_plan.progress(pid,[legacy])['completed']==0 and legacy==original
    for number in pilot_plan.TASK_NUMBERS:
        assert {entry['condition'] for pid in pilot_plan.PARTICIPANTS for entry in pilot_plan.allocations(pid) if entry['review_number']==number}=={'ex','in-situ'}
