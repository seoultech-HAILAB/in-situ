import ast
import io

import pandas as pd
import pytest

from backend.engine import Unsupported, compare, parse_table, run as raw_run, table

def run(code, frame):
    return [s for s in raw_run(code, frame) if s["kind"] != "copy"]
from backend.generator import DEMO_INPUT, DEMO_TARGET, demo_code


def test_actual_wrong_filter_is_not_idealized():
    stages = run(demo_code(False), parse_table(DEMO_INPUT))
    f = stages[1]
    assert f['params']['condition'] == '(status = “완료” ∧ quantity > 2)'
    assert f['params']['decisions']['r0001']['kept'] is False
    assert f['params']['decisions']['r0001']['tests'][-1]['passed'] is False
    assert {r['id'] for r in f['removed']['rows']} == {'r0001', 'r0003', 'r0004', 'r0005', 'r0008'}
    assert not compare(stages[-1]['table'], table(parse_table(DEMO_TARGET)))['matches']
    assert compare(run(demo_code(True), parse_table(DEMO_INPUT))[-1]['table'], table(parse_table(DEMO_TARGET)))['matches']


def test_calculated_cell_and_aggregate_context():
    stages = run(demo_code(True), parse_table(DEMO_INPUT))
    assert stages[2]['lineage']['r0001']['amount'] == [
        {'row_id': 'r0001', 'column': 'price'}, {'row_id': 'r0001', 'column': 'quantity'}]
    agg = stages[3]
    seoul = next(r for r in agg['table']['rows'] if r['values']['region'] == '서울')
    assert seoul['values']['total'] == 70000
    assert set(agg['row_sources'][seoul['id']]) == {'r0001', 'r0002', 'r0007'}
    ctx = agg['contexts'][seoul['id']]['total']
    assert ctx['group_keys'] == {'region': '서울'}
    assert {r['column'] for r in ctx['key_sources']} == {'region'}
    assert len(agg['lineage'][seoul['id']]['total']) == 6
    assert stages[2]['parents']['r0001']['amount'][0]['step_id'] .startswith('op-')


def test_matches_native_pandas_on_changed_input():
    frame = parse_table(DEMO_INPUT.replace('3,10000', '7,12000'))
    code = demo_code(True)
    # The production interpreter never uses exec. This test compares to native Python/pandas.
    namespace = {'input_df': frame.copy()}
    exec(compile(ast.parse(code), '<trusted-test-fixture>', 'exec'), {}, namespace)
    assert table(namespace['result'].set_axis(run(code, frame)[-1]['table']['rows'][i]['id'] for i in range(len(namespace['result']))))['rows'] == run(code, frame)[-1]['table']['rows']


def test_missing_groups_count_size_and_empty_filter():
    frame = parse_table('key,value\nA,1\nA,\n,4\n')
    stages = run("result = input_df.groupby(['key'], as_index=False, dropna=False).agg(n=('value', 'count'), rows=('value', 'size'), total=('value', 'sum'))", frame)
    a = stages[-1]['table']['rows'][0]
    assert a['values'] == {'key': 'A', 'n': 1, 'rows': 2, 'total': 1}
    assert len(stages[-1]['lineage'][a['id']]['n']) == 1
    assert len(stages[-1]['lineage'][a['id']]['rows']) == 2
    assert stages[-1]['table']['rows'][1]['values']['key'] is None
    empty = run("result = input_df.loc[input_df['value'] > 50].copy()", frame)
    assert empty[-1]['table']['rows'] == []
    assert empty[-1]['params']['removed'] == 3


def test_identity_survives_sort_and_duplicate_rows():
    frame = parse_table('x,y\n2,a\n1,b\n2,a\n')
    st = run("s1 = input_df.sort_values(['x'], ascending=True)\nresult = s1.loc[s1['x'] >= 2].copy()", frame)
    assert [r['id'] for r in st[-1]['table']['rows']] == ['r0001', 'r0003']
    assert st[-1]['lineage']['r0003']['x'] == [{'row_id': 'r0003', 'column': 'x'}]
    assert st[0]['table']['stats']['duplicates'] == 1


@pytest.mark.parametrize('code', [
    "import os\nresult = input_df.copy()", "result = __import__('os').system('whoami')",
    "result = target_df.copy()", "result = input_df.head()", "result = input_df.assign(x=123)",
    "result = input_df.loc[True].copy()", "result = input_df.query('quantity > 2')",
    "result = input_df.groupby(['region']).agg(total=('price', 'sum'))",
    "result = input_df.assign(x=input_df['price'].map(str))",
    "result = input_df.assign(x=input_df['price'] ** 10000000)",
    "result = input_df.loc[input_df['price'].__class__].copy()",
])
def test_unsupported_code_is_rejected(code):
    with pytest.raises((Unsupported, ValueError, TypeError)):
        run(code, parse_table(DEMO_INPUT))


def test_paste_validation_and_comparison():
    assert parse_table('a\tb\n1\t2\n').columns.tolist() == ['a', 'b']
    assert parse_table('\ufeffa,b\n1,\n').isna().sum()['b'] == 1
    for text in ['a,a\n1,2', 'a,b\n1,2,3', 'a,b\n1', 'a,\n1,2']:
        with pytest.raises(ValueError):
            parse_table(text)
    assert not compare(table(parse_table('a,b\n1,2')), table(parse_table('b,a\n2,1')))['matches']
    assert compare(table(parse_table('a\n1.0000000001')), table(parse_table('a\n1')))['matches']
    assert len(parse_table('a,b\n')) == 0


def test_string_expansion_and_nonfinite_results_are_rejected():
    with pytest.raises(Unsupported):
        run("result = input_df.assign(x=input_df['region'] * 999999999)", parse_table(DEMO_INPUT))
    with pytest.raises(Unsupported):
        run("result = input_df.assign(x=input_df['quantity'] / 0)", parse_table(DEMO_INPUT))
