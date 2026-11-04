from copy import deepcopy

import pytest

from backend import candidates, observed_changes
from backend.engine import parse_table
from backend.pipeline import prepare, assemble
from backend.python_runtime import run as native_run
from backend.transformations import annotate_run
from backend.operation_prose import operation_local_text


@pytest.fixture(scope='module')
def selected():
    result={}
    for tid in ('PILOT4-T07','PILOT4-T01','PILOT4-T03'):
        task=candidates.load(tid)
        plan=prepare(task['initial_code'],task['steps'],engine='python')
        records=native_run(task['initial_code'],parse_table(task['input_csv']),{k:parse_table(v) for k,v in task.get('sources',{}).items()},plan)
        stages,ops=assemble(records,plan)
        result[tid]=annotate_run(dict(id=tid,code_version=1,code=task['initial_code'],pipeline=plan,stages=stages,operations=ops))
    return result


def lines(contract,column,kind):
    event=next(e for e in contract['changes'] if e['column']==column and e['kind']==kind)
    candidates={c['id']:c for c in contract['candidates']}
    return {candidates[cid]['code_location']['start'] for cid in event['candidate_ids']}


def test_t07_numeric_creation_has_specific_fallback_and_exact_source(selected):
    run=selected['PILOT4-T07']
    contract=observed_changes.contracts(run)[0]
    assert lines(contract,'Conference_ID','added')=={8}
    assignment=next(t for t in run['stages'][1]['transformations'] if t['method']=='assignment' and t['output_columns']==['Conference_ID'])
    text=assignment['description']['text']
    assert 'value' in text and '숫자' in text and '결측' in text
    assert '결과을' not in text and '코드에 지정된 계산 결과' not in text
    assert not operation_local_text('코드에 지정된 계산 결과을 “Conference_ID” 열에 저장합니다.',assignment,{'Conference_ID','value'})


def test_t07_transpose_columns_keep_origin_through_later_filter(selected):
    run=selected['PILOT4-T07'];contract=observed_changes.contracts(run)[1]
    for event in contract['changes']:
        assert event['axis']=='column'
        assert lines(contract,event['column'],event['kind'])=={12}
    assert lines(observed_changes.contracts(run)[2],'staff_id','added')=={21}
    final=observed_changes.contracts(run)[3]
    for event in final['changes']:
        if event['axis']=='column':assert lines(final,event['column'],event['kind'])=={31}


def test_t03_revenue_aggregation_changes_column_without_fabricating_row_pairs(selected):
    run=selected['PILOT4-T03'];stage=run['stages'][4]
    contract=observed_changes.contracts(run)[3]
    assert lines(contract,'Revenue','changed')=={30}
    event=next(e for e in contract['changes'] if e['column']=='Revenue')
    assert event['effect']['columns']['changed']==['Revenue']
    assert not any(event['effect']['cells'].values())
    assert not any(event['effect']['rows'].values())
    assert not stage.get('row_correspondence_complete')


def test_all_selected_changes_have_relevant_executed_candidates_and_stable_ids(selected):
    for run in selected.values():
        assert len(run['stages'])==5
        before=deepcopy([stage['table'] for stage in run['stages']])
        links=[]
        for contract in observed_changes.contracts(run):
            for event in contract['changes']:
                assert event['candidate_ids'],(run['id'],contract['step_no'],event['column'],event['kind'])
                links.append({'step_no':contract['step_no'],'change_id':event['id'],'status':'linked',
                    'operations':[{'candidate_id':cid,'text':'선택한 값이나 표 구조를 처리합니다.'} for cid in event['candidate_ids']]})
        observed_changes.apply(run,links)
        expected={t['id']:t['code'] for stage in run['stages'][1:] for t in stage['transformations'] if t['method']=='observed_change'}
        annotate_run(run)
        assert {t['id']:t['code'] for stage in run['stages'][1:] for t in stage['transformations'] if t['method']=='observed_change'}==expected
        assert [stage['table'] for stage in run['stages']]==before
