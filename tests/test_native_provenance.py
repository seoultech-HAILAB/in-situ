import pandas as pd
from backend.engine import parse_table
from backend.pipeline import prepare,assemble
from backend.python_runtime import run


def observed(code,csv,sources=None,groups=None):
    plan=prepare(code,groups,engine='python')
    stages,ops=assemble(run(code,parse_table(csv),{k:parse_table(v) for k,v in (sources or {}).items()},plan),plan)
    return stages,ops


def test_mutation_aliases_filter_and_string_parts_have_actual_sources():
    code="df = input_df.copy()\nalias = df\ndf['clean'] = df['text'].astype(str).str.strip()\ndf = df.loc[df['x'].gt(1)].copy()\nparts = df['clean'].str.split('-',expand=True)\ndf['left'] = parts[0]\nresult = df[['left']].reset_index(drop=True)"
    stages,_=observed(code,'text,x\n A-B ,1\n C-D ,2')
    assert all(s['trace_level']=='detailed' for s in stages)
    refs=stages[-1]['lineage'][stages[-1]['table']['rows'][0]['id']]['left']
    assert refs==[{'row_id':'r0002','column':'text'}]
    assert stages[4]['removed']['rows'][0]['values']['x']==1


def test_default_groupby_named_aggregation_and_map_counts_include_real_members():
    code="df = input_df.copy()\ndf['n'] = pd.to_numeric(df['n'],errors='coerce')\ncounts = tables['orders'].groupby('id').size()\ndf['count'] = df['id'].map(counts).fillna(0).astype(int)\nresult = df.groupby('kind',as_index=False).agg(total=('count','sum'))\nresult = result[['kind','total']].reset_index(drop=True)"
    stages,_=observed(code,'id,kind,n\n1,A,10\n2,A,20\n3,B,30',{'orders':'id\n1\n1\n2'})
    assert all(s['trace_level']=='detailed' for s in stages)
    row=stages[-1]['table']['rows'][0]
    assert row['values']['total']==3
    refs=stages[-1]['lineage'][row['id']]['total']
    assert stages[-1]['contexts'][row['id']]['total']['group_keys']=={'kind':'A'}
    assert {(r.get('table_id','input'),r['row_id'],r['column']) for r in refs if r.get('table_id')=='orders'}=={('orders','orders:r0001','id'),('orders','orders:r0002','id'),('orders','orders:r0003','id')}


def test_untraced_branch_does_not_destroy_independent_provenance_and_no_value_matching():
    code="bad = input_df.assign(y=input_df['x'].apply(lambda v:v*2))\nresult = input_df[['x']].copy()"
    stages,_=observed(code,'x\n2\n3')
    assert stages[1]['trace_level']=='common'
    assert not any(refs for cols in stages[1]['lineage'].values() for refs in cols.values())
    assert stages[2]['trace_level']=='detailed'
    assert stages[2]['lineage']['r0001']['x']==[{'row_id':'r0001','column':'x'}]
    changed="df = input_df.copy()\ndf['y'] = df['x'].apply(lambda v:v)\nresult = df[['y']].copy()"
    stages,_=observed(changed,'x\n2\n3')
    assert not any(refs for cols in stages[-1]['lineage'].values() for refs in cols.values())


def test_row_count_tracks_cardinality_without_inventing_cell_value_sources():
    stages,_=observed("result = pd.DataFrame({'count(*)':[len(input_df)]})\nresult = result[['count(*)']].copy()",'x\n1\n2')
    stage=stages[-1];rid=stage['table']['rows'][0]['id']
    assert stage['table']['rows'][0]['values']['count(*)']==2
    assert stage['lineage'][rid]['count(*)']==[]
    assert stage['contexts'][rid]['count(*)']['member_rows']==['r0001','r0002']
