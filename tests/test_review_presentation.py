import copy

import pytest

from backend.review_presentation import is_working_copy,present_run


def operation(code="work = input_df.copy()",kind='copy'):
    table={'columns':['x'],'rows':[{'id':'r1','values':{'x':1}}],'stats':{'rows':1,'columns':1}}
    return {'id':'prepare/operation-1','kind':kind,'code':code,'input':table,'table':copy.deepcopy(table)}


@pytest.mark.parametrize('code',[
    'work = input_df.copy()', 'work = input_df.copy(deep=True)',
    'work = input_df.copy(deep=False)', "work = tables['second'].copy()", 'work = input_df',
])
def test_only_verified_identity_copies_are_hidden(code):
    assert is_working_copy(operation(code))


@pytest.mark.parametrize('code',[
    "work = input_df[['x']].copy()", "work = input_df.sort_values('x').copy()",
    "work = input_df.dropna().copy()", 'work = input_df.assign(x=2).copy()',
    'work = input_df.copy()\nwork["x"] = 2', 'work = other(input_df)',
    'input_df.x = input_df.copy()', 'work = input_df.copy(deep=compute())',
])
def test_transformations_stay_visible_even_when_current_values_coincide(code):
    assert not is_working_copy(operation(code))


def test_copy_requires_unchanged_observed_table_and_does_not_hide_input():
    changed=operation();changed['table']['rows'][0]['values']['x']=2
    assert not is_working_copy(changed)
    assert not is_working_copy(operation(kind='input'))
    assert not is_working_copy(operation(kind='python'))


def test_two_source_preparation_and_embedded_copy_are_marked_without_mutating_execution():
    first=operation()
    second=operation("other = tables['second'].copy()")
    second['id']='prepare/operation-2'
    second['table']['rows'].append({'id':'r2','values':{'x':2}})
    second['input']=copy.deepcopy(second['table'])
    prepare={**first,'id':'prepare','kind':'composite','code':first['code']+'\n'+second['code'],'operations':[first,second]}
    transform={**operation('result = work.assign(x=2)',kind='derive'),'id':'transform','operations':[first,operation('result = work.assign(x=2)',kind='derive')]}
    run={'code':prepare['code']+'\n'+transform['code'],'stages':[prepare,transform],'operations':[first,second]}
    original=copy.deepcopy(run)
    result=present_run(run)
    assert result['stages'][0]['review_hidden']
    assert not result['stages'][1]['review_hidden']
    assert result['stages'][1]['operations'][0]['review_hidden']
    assert not result['stages'][1]['operations'][1]['review_hidden']
    assert result['code']==run['code'] and result['stages'][-1]['table']==run['stages'][-1]['table']
    assert run==original


@pytest.mark.parametrize('condition',['A','B2','C'])
def test_existing_session_views_mark_copies_consistently_for_all_conditions(condition):
    from backend.app import view
    run={'id':'original-execution','code':'work = input_df.copy()',
         'stages':[operation()], 'operations':[operation()]}
    session={'condition':condition,'runs':[run],'cursor':0}
    original=copy.deepcopy(session)
    response=view(session)
    assert response['run']['stages'][0]['review_hidden']
    assert response['runs'][0]['stages'][0]['review_hidden']
    assert response['run']['id']=='original-execution'
    assert response['run']['code']==run['code']
    assert session==original
