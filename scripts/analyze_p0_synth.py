"""Read-only inventory of P0 cohort and manifested Synth tables; never run archived code."""
import argparse
import collections
import csv
import hashlib
import io
import json
import pickle
from pathlib import Path

import pandas as pd

ALLOWED = {
    ('pandas.core.frame','DataFrame'), ('pandas','DataFrame'), ('pandas.core.internals.managers','BlockManager'),
    ('pandas._libs.internals','_unpickle_block'), ('numpy._core.multiarray','_reconstruct'),
    ('numpy.core.multiarray','_reconstruct'), ('numpy','ndarray'), ('numpy','dtype'),
    ('builtins','slice'), ('pandas.core.indexes.base','_new_Index'),
    ('pandas.core.indexes.base','Index'), ('pandas.core.indexes.range','RangeIndex'),
    ('pandas','Index'), ('pandas','RangeIndex'),
    ('numpy._core.numeric','_frombuffer'), ('numpy.core.numeric','_frombuffer'),
    ('pandas._libs.missing','NA'),
}


class DataReader(pickle.Unpickler):
    def find_class(self,module,name):
        if (module,name) not in ALLOWED:
            raise pickle.UnpicklingError(f'Unsupported data constructor: {module}.{name}')
        return super().find_class(module,name)


def read_frame(file):
    if file.stat().st_size>20_000_000:
        raise ValueError('Data artifact exceeds 20 MB')
    frame=DataReader(io.BytesIO(file.read_bytes())).load()
    if not isinstance(frame,pd.DataFrame):
        raise ValueError('Expected DataFrame')
    return frame


def shape(frame):
    nested=any(isinstance(v,(list,tuple,dict,set)) for row in frame.itertuples(index=False,name=None) for v in row)
    duplicates=None if nested else int(frame.duplicated().sum())
    return {'rows':len(frame),'columns':len(frame.columns),'labels':list(map(str,frame.columns)),
        'duplicate_labels':not frame.columns.is_unique or len(set(map(str,frame.columns)))!=len(frame.columns),
        'missing_cells':int(frame.isna().sum().sum()),'duplicate_rows':duplicates,'nested_values':nested,
        'dtypes':list(map(str,frame.dtypes))}


def inventory(data_root,matrix,out,p0_root=None):
    cohort=list(csv.DictReader(matrix.open(encoding='utf-8-sig')))
    original_records={}
    if p0_root:
        for summary in p0_root.glob('*/results.json'):
            for record in json.loads(summary.read_text(encoding='utf-8-sig')):
                original_records[record['task_id']] = (summary.parent,record)
    selected={r['task_id']:r for r in cohort}
    records={}
    for file in data_root.glob('nl2sql-*/**/benchmark.jsonl'):
        for line in file.read_text(encoding='utf-8-sig').splitlines():
            task=json.loads(line)
            if task['task_id'] in selected:
                if task['task_id'] in records:
                    raise ValueError('Ambiguous task ID across manifests: '+task['task_id'])
                records[task['task_id']]=(file,task)
    output=[]
    for key,row in selected.items():
        r={'task_id':key,'cohort':row['cohort'],'p0_recorded_matches':row['P0_success']=='True',
           'p0_code_available':False,'p0_execution_status':'unverified_original_artifact_missing'}
        if key in original_records:
            source_folder,original=original_records[key]
            assert original['matched']==r['p0_recorded_matches'] and original['model_calls']==1
            r.update(p0_code_available=(source_folder/'runs'/key/str(original['seed'])/'P0/program.py').exists(),
                p0_execution_status=original['status'],p0_workflow_completed=original['workflow_completed'],
                p0_model_calls=original['model_calls'])
        if key not in records:
            r['load_error']='Missing manifested task';output.append(r);continue
        manifest,task=records[key]
        r.update(description=task.get('question',''),sql=task.get('sql',''),dataset=manifest.parent.parent.name,
            manifest=str(manifest),manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
            inputs=task['input_table'],target=task['target_table'],operations=task.get('tol_ops',[]),
            cleaning_operations=task.get('dc_ops',[]),sql_operations=task.get('sql2op_op_lis',[]))
        try:
            r['input_profiles']=[shape(read_frame(manifest.parent/f)) for f in task['input_table']]
            r['target_profile']=shape(read_frame(manifest.parent/task['target_table']))
            reasons=[]
            if len(r['input_profiles'])>5:reasons.append('too_many_sources')
            for p in r['input_profiles']+[r['target_profile']]:
                if p['duplicate_labels']:reasons.append('duplicate_column_labels')
                if p['nested_values']:reasons.append('nested_values_not_lossless_in_csv')
                if p['rows']>500 or p['columns']>32:reasons.append('input_or_target_size_limit')
                if not p['columns']:reasons.append('no_columns')
            r['structural_exclusions']=sorted(set(reasons))
            r['compact']=all(p['rows']<=20 and p['columns']<=8 for p in r['input_profiles']) and r['target_profile']['rows']<=12 and r['target_profile']['columns']<=8
        except Exception as exc:r['load_error']=str(exc)
        output.append(r)
    technical=[r for r in output if r['cohort']!='development']
    summary={'cohort_total':len(output),'development':len(output)-len(technical),'technical':len(technical),
        'technical_p0_recorded_correct':sum(r['p0_recorded_matches'] for r in technical),
        'technical_p0_recorded_incorrect':sum(not r['p0_recorded_matches'] for r in technical),
        'all_p0_code_available':all(r['p0_code_available'] for r in technical),
        'technical_p0_code_available':sum(r['p0_code_available'] for r in technical),
        'technical_p0_status_counts':dict(collections.Counter(r['p0_execution_status'] for r in technical)),
        'inventory_executes_programs':False,'new_model_calls':0,
        'technical_tables_loaded':sum('load_error' not in r for r in technical),
        'technical_structurally_eligible':sum('load_error' not in r and not r['structural_exclusions'] for r in technical),
        'technical_compact':sum(r.get('compact',False) and not r.get('structural_exclusions') for r in technical),
        'technical_compact_recorded_incorrect':sum(r.get('compact',False) and not r.get('structural_exclusions') and not r['p0_recorded_matches'] for r in technical),
        'datasets':dict(collections.Counter(r.get('dataset') for r in technical)),
        'input_count_distribution':dict(collections.Counter(len(r.get('inputs',[])) for r in technical)),
        'reference_operation_counts':dict(collections.Counter(op.split('(',1)[0] for r in technical for op in r.get('operations',[]))),
        'technical_exclusion_reasons':dict(collections.Counter(x for r in technical for x in r.get('structural_exclusions',[]))),
        'technical_load_errors':dict(collections.Counter(r['load_error'] for r in technical if 'load_error' in r))}
    out.mkdir(parents=True,exist_ok=True)
    (out/'inventory.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--p0-matrix',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--p0-root',type=Path)
    args=parser.parse_args()
    inventory(args.data_root,args.p0_matrix,args.out,args.p0_root)
