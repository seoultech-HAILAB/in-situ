import ast
from copy import deepcopy

from backend.engine import parse_table
from backend.pipeline import prepare,assemble
from backend.python_runtime import run as native_run
from backend.transformations import annotate_run


SOURCES={'rates':'key,rate\na,2\nb,3','unused':'key,note\na,unused'}


def execute(code,groups=None):
    groups=groups or [{'statement_indices':list(range(len(ast.parse(code).body))),'output_variable':'result'}]
    plan=prepare(code,groups,engine='python')
    stages,ops=assemble(native_run(code,parse_table('key,x\na,10\nb,20'),{k:parse_table(v) for k,v in SOURCES.items()},plan),plan)
    return annotate_run(dict(id='run',code_version=1,code=code,pipeline=plan,stages=stages,operations=ops))


def test_shows_only_current_join_input_with_its_actual_cleaned_values():
    run=execute("main = input_df.copy()\nlookup = tables['rates'].copy()\nunused = tables['unused'].copy()\nlookup['rate'] = lookup['rate'] * 2\nresult = main.merge(lookup, on='key', how='left')")
    stage=run['stages'][1];items=stage['direct_tables']
    assert len(items)==1 and items[0]['name']=='lookup'
    assert [row['values']['rate'] for row in items[0]['table']['rows']]==[4,6]
    assert 'key' in items[0]['uses'][0]['text'] and '행을 유지' in items[0]['uses'][0]['text']
    assert items[0]['uses'][0]['line']==5
    snapshot=deepcopy(stage['table']);annotate_run(run)
    assert stage['table']==snapshot and stage['direct_tables']==items


def test_later_steps_do_not_repeat_a_previously_joined_source_table():
    code="lookup = tables['rates'].copy()\nmerged = input_df.merge(lookup, on='key', how='left')\nresult = merged.sort_values('x')"
    run=execute(code,[{'statement_indices':[0,1],'output_variable':'merged'},{'statement_indices':[2],'output_variable':'result'}])
    assert len(run['stages'][1]['direct_tables'])==1
    assert run['stages'][2]['direct_tables']==[]


def test_unused_side_branch_and_unexecuted_join_do_not_get_cards():
    run=execute("unused = input_df.merge(tables['rates'], on='key')\nif False:\n    unused = input_df.merge(tables['unused'], on='key')\nresult = input_df.copy()")
    assert run['stages'][1]['direct_tables']==[]


def test_precomputed_scalar_influence_does_not_count_as_direct_table_use():
    code="rates = tables['rates'].copy()\nfactor = rates['rate'].mean()\nresult = input_df.copy()\nresult['scaled'] = result['x'] * factor"
    run=execute(code,[{'statement_indices':[0,1],'output_variable':'rates'},{'statement_indices':[2,3],'output_variable':'result'}])
    assert run['stages'][2]['direct_tables']==[]


def test_direct_read_of_existing_lookup_frame_counts_as_use_in_calculation():
    code="rates = tables['rates'].copy()\nresult = input_df.copy()\nresult['scaled'] = result['x'] * rates['rate']"
    run=execute(code,[{'statement_indices':[0],'output_variable':'rates'},{'statement_indices':[1,2],'output_variable':'result'}])
    assert len(run['stages'][2]['direct_tables'])==1
    assert run['stages'][2]['direct_tables'][0]['name']=='rates'
    assert '결과 열 계산' in run['stages'][2]['direct_tables'][0]['uses'][0]['text']


def test_conservative_whole_step_input_lists_never_prove_table_use():
    run=execute("result = input_df.copy()\nresult['x'] = result['x'].map(lambda value: value * 2)")
    stage=run['stages'][1]
    assert stage['trace_level']=='common'
    stage['operation_observations']=[]
    stage['operations'][0]['inputs'].append({'ref':'source:rates','variable':'rates','table':stage['table']})
    annotate_run(run)
    assert stage['direct_tables']==[]


def test_concat_shows_each_additional_input_once_with_direction():
    run=execute("extra = tables['rates'][['key']]\nmain = input_df[['key']]\nresult = pd.concat([main, extra], ignore_index=True)")
    assert len(run['stages'][1]['direct_tables'])==1
    assert run['stages'][1]['direct_tables'][0]['name']=='extra'
    assert '행' in run['stages'][1]['direct_tables'][0]['uses'][0]['text']


def test_native_loop_merges_keep_each_actual_operand_snapshot():
    code="result = input_df[['key']].copy()\nfor field in ['rate', 'double']:\n    lookup = tables['rates'].rename(columns={'rate': field})\n    result = result.merge(lookup, on='key', how='left')"
    run=execute(code);stage=run['stages'][1]
    assert [item['table']['columns'] for item in stage['direct_tables']]==[['key','rate'],['key','double']]
    assert all(item['uses'][0]['line']==4 for item in stage['direct_tables'])
    assert all(item['name']=='lookup' for item in stage['direct_tables'])
    assert len(stage['direct_table_calls'])==2
    assert run['direct_table_observations_version']=='native-table-calls-v2'


def test_native_calls_exclude_dead_loop_branches_overwritten_results_and_unchanged_later_steps():
    code="result = input_df.copy()\nfor field in ['rate']:\n    unused = input_df.merge(tables['unused'], on='key')\n    result = result.merge(tables['rates'], on='key', how='left')\n    if False:\n        result = result.merge(tables['unused'], on='key')\nresult = result.sort_values('key')"
    groups=[{'statement_indices':[0,1],'output_variable':'result'},{'statement_indices':[2],'output_variable':'result'}]
    run=execute(code,groups)
    assert [item['name'] for item in run['stages'][1]['direct_tables']]==['rates']
    assert run['stages'][2]['direct_tables']==[]
    overwritten=execute("result = input_df.merge(tables['rates'], on='key')\nresult = input_df.copy()")
    assert overwritten['stages'][1]['direct_tables']==[]
    replaced=execute("result = input_df.merge(tables['rates'], on='key')\nif True:\n    result = input_df.copy()")
    assert replaced['stages'][1]['direct_tables']==[]


def test_distinct_same_line_calls_are_not_cross_connected_and_failed_calls_are_not_displayed():
    code="unused = input_df.merge(tables['unused'], on='key'); result = input_df.merge(tables['rates'], on='key')"
    assert [item['name'] for item in execute(code)['stages'][1]['direct_tables']]==['rates']
    failed=execute("try:\n    result = input_df.merge(tables['rates'], on='missing')\nexcept KeyError:\n    result = input_df.copy()")
    assert failed['stages'][1]['direct_table_calls']==[] and failed['stages'][1]['direct_tables']==[]


def test_concat_does_not_consume_a_generator_twice_or_change_native_result():
    run=execute("frames = (frame for frame in [input_df[['key']], tables['rates'][['key']]])\nresult = pd.concat(frames, ignore_index=True)")
    assert len(run['stages'][1]['table']['rows'])==4


def test_concat_collection_uses_actual_selected_keys_and_readable_operand_names():
    run=execute("parts = {'unused': tables['unused'][['key']], 'main': input_df[['key']], 'rates': tables['rates'][['key']]}\nresult = pd.concat(parts, keys=['main','rates'])")
    items=run['stages'][1]['direct_tables']
    assert [item['name'] for item in items]==["parts['rates']"]
    assert len(items[0]['table']['rows'])==2


def test_replay_ids_do_not_duplicate_plain_auxiliary_cards():
    run=execute("result = input_df.merge(tables['rates'], on='key')")
    stage=run['stages'][1]
    stage['direct_table_calls']=[]
    records=[record for record in stage['operation_observations'] if record['kind']=='merge']
    duplicate=deepcopy(records[0]);duplicate['id']='other-replay'
    for row in duplicate['inputs'][1]['table']['rows']:row['id']='other:'+row['id']
    stage['operation_observations'].append(duplicate)
    annotate_run(run)
    assert len(stage['direct_tables'])==1


def test_single_source_read_is_shown_even_without_a_multi_table_operation():
    run=execute("result = tables['rates'].set_index('key').T")
    stage=run['stages'][1]
    assert [item['name'] for item in stage['direct_tables']]==['rates']
    item=stage['direct_tables'][0]
    assert item['table']['columns']==['key','rate'] and len(item['table']['rows'])==2
    assert item['uses'][0]['line']==1 and '행과 열' in item['uses'][0]['text']
    assert stage['direct_table_reads'][0]['code']=="tables['rates']"


def test_source_reads_require_actual_execution_and_contribution_to_the_output():
    run=execute("unused = tables['unused'].copy()\nresult = tables['unused'].copy() if False else tables['rates'].copy()")
    assert [item['name'] for item in run['stages'][1]['direct_tables']]==['rates']
    assert [item['name'] for item in run['stages'][1]['direct_table_reads']]==['unused','rates']
    overwritten=execute("result = tables['rates'].copy()\nresult = input_df.copy()")
    assert overwritten['stages'][1]['direct_tables']==[]


def test_dynamic_source_key_and_later_scalar_influence_stay_separate():
    code="key = 'rates'\nrates = tables[key].copy()\nfactor = rates['rate'].mean()\nresult = input_df.assign(scaled=input_df['x'] * factor)"
    groups=[{'statement_indices':[0,1,2],'output_variable':'rates'},{'statement_indices':[3],'output_variable':'result'}]
    run=execute(code,groups)
    assert [item['name'] for item in run['stages'][1]['direct_tables']]==['rates']
    assert run['stages'][2]['direct_tables']==[]


def test_source_reads_do_not_duplicate_cleaned_combination_operands():
    code="lookup = tables['rates'].copy()\nlookup['rate'] *= 2\nresult = input_df.merge(lookup, on='key')"
    items=execute(code)['stages'][1]['direct_tables']
    assert [item['name'] for item in items]==['lookup']
    assert [row['values']['rate'] for row in items[0]['table']['rows']]==[4,6]


def test_a_missing_source_and_a_failed_combination_cannot_add_input_cards():
    code="try:\n    result = tables['missing'].copy()\nexcept KeyError:\n    result = input_df.copy()"
    stage=execute(code)['stages'][1]
    assert stage['direct_table_reads']==[] and stage['direct_tables']==[]
    code="try:\n    result = input_df.merge(tables['rates'], on='missing')\nexcept KeyError:\n    result = input_df.copy()"
    stage=execute(code)['stages'][1]
    assert stage['direct_table_reads'] and stage['direct_tables']==[]
