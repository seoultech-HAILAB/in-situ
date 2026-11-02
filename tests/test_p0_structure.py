import ast

import pandas as pd
import pytest

from scripts.audit_p0_programs import wrapper,replay
from scripts.structure_p0_program import structure,groups_from_observations
from backend.pipeline import prepare,assemble
from backend.isolation import isolated_run
from backend.engine import compare


def test_original_function_and_observed_steps_produce_same_unrepaired_result():
    original='''import pandas as pd
def transform(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    df = tables['table_1']
    mask = (df['x'] > 2) | (df['y'] > 3)
    return df.loc[mask, ['name']].reset_index(drop=True)
'''
    inp='x,y,name\n1,1,a\n3,1,b\n1,4,c\n3,4,d'
    _,raw=replay(wrapper(original,1),[inp])
    code,mapping=structure(original,1)
    assert 'def transform' not in code and len(mapping)==len(ast.parse(code).body)
    plan=prepare(code,engine='python')
    records=isolated_run(code,inp,engine='python',plan=plan)
    groups=groups_from_observations(code,records)
    assert len(groups)==2
    _,observed=replay(code,[inp],groups)
    assert compare(observed[-1]['table'],raw[-1]['table'])['matches']
    assert len(observed[-1]['table']['rows'])==3
    assert all(s['trace_level']=='detailed' for s in observed[1:])
    assert mapping[1]['source_start']<=4<=mapping[1]['source_end']


def test_reassigned_dataframes_are_renamed_without_changing_filter_or_sort():
    source='''import pandas as pd
def transform(tables):
    df = tables['table_1'].copy()
    df = df.dropna(subset=['x'])
    df = df.sort_values('x',ascending=False,kind='stable')
    return df[['name']].reset_index(drop=True)
'''
    inp='x,name\n2,a\n1,b\n,c\n3,d'
    _,raw=replay(wrapper(source,1),[inp])
    code,_=structure(source,1)
    records=isolated_run(code,inp,engine='python',plan=prepare(code,engine='python'))
    groups=groups_from_observations(code,records)
    _,observed=replay(code,[inp],groups)
    assert len(groups)==3
    assert compare(observed[-1]['table'],raw[-1]['table'])['matches']
    assert all(s['trace_level']=='detailed' for s in observed[1:])


@pytest.mark.parametrize('body',[
    "if len(tables):\n        return tables['table_1']\n    return tables['table_1']",
    "df = tables['table_1']\n    df['x'] = 1\n    return df",
    "df = tables.get('table_1')\n    return df",
    "df = tables['table_1']\n    df = df.dropna(inplace=True)\n    return df",
])
def test_unsupported_function_shapes_are_rejected_instead_of_silently_rewritten(body):
    with pytest.raises(ValueError):
        structure('def transform(tables):\n    '+body,1)
