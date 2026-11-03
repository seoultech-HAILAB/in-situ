import ast
import copy

from backend.engine import parse_table
from backend.pipeline import prepare, assemble
from backend.python_runtime import run as native_run
from backend.transformations import annotate_run
from backend.transformation_effects import revision_effects


def snapshot(code, csv='x,y\n2,7\n1,8', groups=None, rid='executed'):
    plan=prepare(code,groups or [{'statement_indices':list(range(len(ast.parse(code).body))),'output_variable':'result'}],engine='python')
    stages,operations=assemble(native_run(code,parse_table(csv),{},plan),plan)
    return annotate_run({'id':rid,'code_version':1,'code':code,'pipeline':plan,'stages':stages,'operations':operations})


def test_select_records_excluded_columns_as_removed_and_sort_only_records_reordered_rows():
    run=snapshot("result = input_df[['x']].sort_values('x')")
    select, sort = run['stages'][1]['transformations']
    assert select['method']=='select' and sort['method']=='sort_values'
    assert select['output_columns']==['x'] and select['removed_columns']==['y']
    assert not select['syntax_only'] and not sort['syntax_only']
    selected=select['execution_effects'][0]
    assert selected['columns']=={'added':[],'changed':[],'removed':['y']}
    assert selected['cells']['removed']['y']==['r0001','r0002']
    assert selected['expression_location']=={k:select['code_location'][k] for k in ('start','end','start_column','end_column')}
    assert selected['operation_id'].endswith('/operation-1')
    sorted_effect=sort['execution_effects'][0]
    assert sorted_effect['rows']['reordered']==['r0002','r0001']
    assert sorted_effect['columns']=={'added':[],'changed':[],'removed':[]}
    assert all(not values for values in sorted_effect['cells'].values())


def test_named_assign_outputs_receive_only_their_own_verified_column_and_cell_changes():
    run=snapshot("result = input_df.assign(x=input_df['x'] * 2, z=input_df['y'] + 1)")
    x,z=run['stages'][1]['transformations']
    assert x['execution_effects'][0]['columns']['changed']==['x']
    assert x['execution_effects'][0]['cells']['changed']=={'x':['r0001','r0002']}
    assert x['execution_effects'][0]['columns']['added']==[]
    assert z['execution_effects'][0]['columns']['added']==['z']
    assert z['execution_effects'][0]['cells']['changed']=={}
    assert x['code_location']!=z['code_location']


def test_loc_selection_records_deleted_columns_separately_from_row_filtering():
    run=snapshot("result = input_df.loc[input_df['x'] > 1, ['x']]")
    filtered,selected=run['stages'][1]['transformations']
    assert filtered['kind']=='filter' and selected['kind']=='select'
    assert filtered['removed_columns']==[] and selected['removed_columns']==['y']
    assert filtered['execution_effects'][0]['rows']['removed']==['r0002']
    assert selected['execution_effects'][0]['rows']['removed']==[]
    common=snapshot("result = input_df.loc[:, ['x']]")
    select=common['stages'][1]['transformations'][0]
    assert select['removed_columns']==['y']
    assert select['execution_effects'][0]['rows']['removed']==[]


def test_deleted_rows_belong_to_the_executed_filter_not_other_columns_or_sort():
    run=snapshot("kept = input_df[input_df['x'] > 1]\nresult = kept.assign(z=kept['x'] * 3).sort_values('x')")
    filter_op,derive,sort=run['stages'][1]['transformations']
    assert filter_op['execution_effects'][0]['rows']['removed']==['r0002']
    assert filter_op['execution_effects'][0]['cells']['removed']['y']==['r0002']
    assert derive['execution_effects'][0]['rows']['removed']==[]
    assert derive['execution_effects'][0]['columns']['added']==['z']
    assert sort['execution_effects'][0]['rows']['reordered']==[]


def test_a_no_op_assignment_is_not_a_verified_changed_column():
    run=snapshot("result = input_df.assign(x=input_df['x'])")
    observed=run['stages'][1]['transformations'][0]['execution_effects'][0]
    assert all(not values for values in observed['columns'].values())
    assert all(not values for values in observed['cells'].values())


def test_null_fill_and_clear_record_different_actual_change_types():
    fill=snapshot("result = input_df.fillna({'x': 0})",csv='x,y\n,2\n3,4')
    changed=fill['stages'][1]['transformations'][0]['execution_effects'][0]
    assert changed['columns']['changed']==['x']
    assert changed['cells']['changed']=={'x':['r0001']}
    clear=snapshot("result = input_df.replace({2: None})")
    removed=clear['stages'][1]['transformations'][0]['execution_effects'][0]
    assert removed['cells']['removed']=={'x':['r0001']}
    assert removed['columns']['removed']==[]


def test_composite_common_observation_cannot_prove_unexecuted_or_individual_changes():
    run=snapshot("result = input_df.copy()\nif False:\n    result = result[['x']]\nresult['x'] = result['x'].apply(lambda value: value * 2)")
    assert run['stages'][1]['trace_level']=='common'
    assert all(not item['execution_effects'] for item in run['stages'][1]['transformations'])
    assert all(item['syntax_only'] for item in run['stages'][1]['transformations'])
    assert 'y' in run['stages'][1]['table']['columns']


def test_chained_series_methods_without_individual_observations_do_not_claim_each_others_changes():
    run=snapshot("result = input_df.assign(z=input_df['x'].astype(str).str.strip())")
    assert len(run['stages'][1]['transformations'])==2
    assert all(not item['execution_effects'] for item in run['stages'][1]['transformations'])
    for value in ("result['x'].astype(str).str.strip()", "result['x'].astype(float) * 2"):
        assignment=snapshot("result = input_df.copy()\nresult['x'] = " + value)
        assert all(not item['execution_effects'] for item in assignment['stages'][1]['transformations'])


def test_revision_comparison_is_separate_from_actual_operation_input_changes():
    baseline=snapshot("result = input_df.assign(z=input_df['x'] * 2).sort_values('x')",rid='base')
    candidate=snapshot("result = input_df.assign(z=input_df['x'] * 3).sort_values('x')",rid='candidate')
    before=copy.deepcopy(baseline)
    revision_effects(candidate,baseline['stages'][1])
    derive,sort=candidate['stages'][1]['transformations']
    assert derive['execution_effects'][0]['columns']['added']==['z']
    assert derive['revision_effects'][0]['columns']['changed']==['z']
    assert derive['revision_effects'][0]['columns']['added']==[]
    assert sort['revision_effects'][0]['rows']['changed']==[]
    assert sort['revision_effects'][0]['columns']['changed']==[]
    assert baseline==before
