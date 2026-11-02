"""Register a local review CSV with frozen P0 code, stable numbers and real observations.

No LLM calls or answer-dependent program repairs. Original functions are lifted
only when their straight-line statements can be preserved; otherwise the original
function remains one observable block. Adapted output must match the archive.
"""
import argparse
import ast
import copy
import csv
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.analyze_p0_synth import read_frame
from scripts.build_synth_candidates import frame_csv
from scripts.audit_p0_programs import wrapper
from backend.engine import compare,parse_table,table
from backend.pipeline import prepare,assemble
from backend.isolation import isolated_run


def lift(program,count):
    mod=ast.parse(program)
    functions=[n for n in mod.body if isinstance(n,ast.FunctionDef) and n.name=='transform']
    if len(functions)!=1:raise ValueError('Expected transform function')
    fn=functions[0]
    if len(fn.args.args)!=1 or fn.args.defaults or fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg or fn.decorator_list:
        raise ValueError('Unsupported transform signature')
    if any(not isinstance(n,(ast.Import,ast.ImportFrom)) and n is not fn for n in mod.body):
        raise ValueError('Only imports and one transform function can be lifted')
    body=[n for n in fn.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str))]
    if not body or not isinstance(body[-1],ast.Return) or any(not isinstance(n,ast.Assign) for n in body[:-1]):
        raise ValueError('Original function kept intact: not straight-line assignments')
    formal=fn.args.args[0].arg
    reserved={formal,'input_df','tables','pd','np'}
    if any(isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store) and n.id in reserved for s in body for n in ast.walk(s)):
        raise ValueError('Original function kept intact: source/global name shadowing')
    class Bind(ast.NodeTransformer):
        def visit_Subscript(self,node):
            if isinstance(node.value,ast.Name) and node.value.id==formal and isinstance(node.slice,ast.Constant):
                label=node.slice.value
                allowed=[f'table_{i}' for i in range(1,count+1)]
                if label not in allowed:raise ValueError('Unknown table binding')
                i=allowed.index(label)+1
                value=ast.Name(id='input_df',ctx=ast.Load()) if i==1 else ast.Subscript(value=ast.Name(id='tables',ctx=ast.Load()),slice=ast.Constant(f'source_{i}'),ctx=ast.Load())
                return ast.copy_location(value,node)
            return self.generic_visit(node)
        def visit_Name(self,node):
            if isinstance(node.ctx,ast.Load) and node.id==formal:raise ValueError('Dynamic table access requires original function')
            return node
        def visit_Lambda(self,node):
            if any(a.arg in reserved for a in [*node.args.posonlyargs,*node.args.args,*node.args.kwonlyargs]):
                raise ValueError('Scoped source name shadowing')
            return self.generic_visit(node)
    nodes=[];mapping=[]
    for n in mod.body:
        if n is fn:continue
        if isinstance(n,ast.Import) and all((a.name,a.asname) in [('pandas','pd'),('numpy','np')] for a in n.names):continue
        nodes.append(copy.deepcopy(n));mapping.append({'statement_index':len(nodes)-1,'source_start':n.lineno,'source_end':n.end_lineno})
    for source in body:
        n=Bind().visit(copy.deepcopy(source))
        if isinstance(n,ast.Return):n=ast.copy_location(ast.Assign(targets=[ast.Name(id='result',ctx=ast.Store())],value=n.value),source)
        nodes.append(n);mapping.append({'statement_index':len(nodes)-1,'source_start':source.lineno,'source_end':source.end_lineno})
    return ast.unparse(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[]))),mapping


def operation_name(nodes):
    calls=[n for s in nodes for n in ast.walk(s) if isinstance(n,ast.Call)]
    names={n.func.attr if isinstance(n.func,ast.Attribute) else n.func.id if isinstance(n.func,ast.Name) else '' for n in calls}
    if names & {'merge','join'}:return '집계·연결' if names & {'groupby','agg','sum','size','count'} else '테이블 연결'
    if names & {'groupby','agg','mean','sum','size','count','len','max','min'}:return '그룹 집계' if 'groupby' in names else '집계 결과 구성'
    if 'sort_values' in names:return '정렬'
    if 'drop_duplicates' in names:return '중복 정리'
    if 'dropna' in names:return '결측 행 정리'
    if 'fillna' in names:return '결측값 처리'
    if 'split' in names:return '문자열 분리'
    if names & {'to_numeric','astype','to_datetime'}:return '타입·열 값 변환'
    if names & {'strip','upper','lower','replace','extract'}:return '문자열 정리'
    if names & {'rename','drop'}:return '열 정리'
    last=nodes[-1]
    if isinstance(last,ast.Assign) and isinstance(last.targets[0],ast.Subscript):return '열 계산·정리'
    if any(isinstance(n,ast.Subscript) and isinstance(n.value,ast.Attribute) and n.value.attr in ('loc','iloc') for n in ast.walk(last)):return '행·열 선택'
    if any(isinstance(n,ast.Subscript) and isinstance(n.slice,(ast.List,ast.Tuple)) for n in ast.walk(last)):return '열 정리'
    return '결과 구성'


def observable_groups(code,records):
    nodes=ast.parse(code).body
    last={r['statement_index']:r for r in records[1:]}
    groups=[];start=0
    for i,node in enumerate(nodes):
        record=last.get(i)
        if not record or not isinstance(node,ast.Assign):continue
        variable=record.get('output_variable')
        target=node.targets[0]
        if isinstance(target,ast.Name) and target.id!=variable:continue  # Series/scalar setup stays with its consumer.
        value=node.value
        trivial=isinstance(value,ast.Name) or isinstance(value,ast.Subscript) and isinstance(value.value,ast.Name) and value.value.id=='tables'
        trivial=trivial or isinstance(value,ast.Call) and isinstance(value.func,ast.Attribute) and value.func.attr=='copy' and isinstance(value.func.value,ast.Name)
        if trivial:continue
        group_nodes=nodes[start:i+1]
        groups.append({'statement_indices':list(range(start,i+1)),'output_variable':variable,'label':operation_name(group_nodes)})
        start=i+1
    if not groups:return [{'statement_indices':list(range(len(nodes))),'output_variable':'result','label':'결과 구성'}]
    groups[-1]['statement_indices'].extend(range(start,len(nodes)))
    groups[-1]['output_variable']='result'
    return groups


def execute(code,inputs,groups=None):
    plan=prepare(code,groups,engine='python')
    records=isolated_run(code,inputs[0],{f'source_{i}':v for i,v in enumerate(inputs[1:],2)},engine='python',plan=plan)
    return records,assemble(records,plan)[0]


def build(csv_path,inventory_path,destination,state_dir):
    inventory={r['task_id']:r for r in json.loads(inventory_path.read_text(encoding='utf-8-sig'))}
    with csv_path.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
    destination.mkdir(parents=True,exist_ok=True);state_dir.mkdir(parents=True,exist_ok=True)
    index_file=state_dir/'numbers.json'
    numbers=json.loads(index_file.read_text()) if index_file.exists() else {}
    reports=[]
    for row in rows:
        tid=row['task_id']
        if tid not in numbers:numbers[tid]=max(numbers.values(),default=0)+1
        number=numbers[tid];cid=f'R500-{number:03d}';file=destination/(cid+'.json')
        try:
            if file.exists():
                old=json.loads(file.read_text(encoding='utf-8'))
                if old.get('provenance',{}).get('original_task_id')!=tid:raise ValueError('Existing task number belongs to another source')
                reports.append({'number':number,'id':cid,'task_id':tid,'status':'existing','steps':len(old['steps'])});continue
            item=inventory[tid];base=Path(item['manifest']).parent;folder=Path(item['folder'])
            source_bytes=(folder/'program.py').read_bytes();original=source_bytes.decode('utf-8-sig')
            if ast.dump(ast.parse(original))!=ast.dump(ast.parse(item['code'])):raise ValueError('Original code differs from local inventory')
            frames=[read_frame(base/name) for name in item['inputs']]
            target=read_frame(base/item['target']);inputs=[frame_csv(df) for df in frames];target_csv=frame_csv(target)
            for df,csv_text in zip([*frames,target],[*inputs,target_csv]):
                if not compare(table(df),table(parse_table(csv_text)))['matches']:raise ValueError('CSV conversion changes original values')
            _,unchanged=execute(wrapper(original,len(inputs)),inputs)
            saved=json.loads((folder/'output_table.json').read_text(encoding='utf-8-sig'))['data']
            archived=table(pd.DataFrame(saved['data'],columns=list(map(str,saved['columns']))))
            if not compare(unchanged[-1]['table'],archived)['matches']:raise ValueError('Unchanged original output differs from archive')
            adaptation='original_function';mapping=[]
            try:code,mapping=lift(original,len(inputs));adaptation='straight_line_lift'
            except ValueError:code=wrapper(original,len(inputs))
            if adaptation=='straight_line_lift':
                probe,_=execute(code,inputs)
                groups=observable_groups(code,probe)
            else:groups=[{'statement_indices':list(range(len(ast.parse(code).body))),'output_variable':'result','label':'변환 결과 구성'}]
            _,stages=execute(code,inputs,groups)
            if not compare(stages[-1]['table'],archived)['matches']:raise ValueError('Observed code output differs from archived original')
            reference=state_dir.parent/'evidence'/f'{tid}_multiple_errors_reference.py'
            payload={'id':cid,'review_number':number,'title':row['과제요약'],'description':item['question'],
                'participant_title':row['과제요약'],'participant_description':item['question'],
                'enabled':True,'participant_enabled':True,'input_csv':inputs[0],
                'sources':{f'source_{i}':v for i,v in enumerate(inputs[1:],2)},'target_csv':target_csv,
                'initial_code':code,'steps':groups,'original_program':original,
                'provenance':{'initial_origin':'luna_p0_observed','original_task_id':tid,'actual_luna_program':True,
                    'source_csv':str(csv_path),'cohort':'additional500-multiple-errors-v3',
                    'original_program_sha256':hashlib.sha256(source_bytes).hexdigest(),'same_as_archived_output':True,
                    'display_code_is_original_bytes':False,'observational_adaptation':adaptation,'adaptation_source_map':mapping,
                    'model_calls_in_original_run':item.get('model_calls'),'new_model_calls':0},
                'researcher_notes':{'review_csv':row,'proposed_steps_uninstrumented':row.get('제안_Step수'),
                    'description_requires_review':True,'description_review_notes':row.get('과제설명_확인사항',''),
                    'initial_trace_levels':[s['trace_level'] for s in stages[1:]],'actual_step_count':len(groups)}}
            # Researcher references are separate, intact programs, not applied to the initial code.
            if reference.exists():
                ref=reference.read_text(encoding='utf-8-sig');payload['reference_code']=wrapper(ref,len(inputs))
                payload['reference_steps']=[{'statement_indices':list(range(len(ast.parse(payload['reference_code']).body))),
                    'output_variable':'result','label':'연구자 참조 실행'}]
            file.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
            reports.append({'number':number,'id':cid,'task_id':tid,'status':'registered','steps':len(groups),
                'proposed_steps':row.get('제안_Step수'),'trace_levels':[s['trace_level'] for s in stages[1:]]})
        except Exception as exc:reports.append({'number':number,'id':cid,'task_id':tid,'status':'blocked','error':str(exc)[:1000]})
        print(json.dumps(reports[-1],ensure_ascii=True),flush=True)
        index_file.write_text(json.dumps(numbers,indent=2),encoding='utf-8')
    index_file.write_text(json.dumps(numbers,indent=2),encoding='utf-8')
    (state_dir/'registration.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    report_path=csv_path.with_name('TRACE_task_server_numbers_v3.csv')
    with report_path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['과제번호','서버과제ID',*rows[0].keys(),'서버등록상태','실제관찰Step수'])
        writer.writeheader()
        for row,report in zip(rows,reports):writer.writerow({'과제번호':f"{report['number']:02d}",'서버과제ID':report['id'],**row,
            '서버등록상태':report['status'],'실제관찰Step수':report.get('steps','')})
    print(json.dumps({'registered':sum(r['status']!='blocked' for r in reports),'blocked':sum(r['status']=='blocked' for r in reports),'mapping':str(report_path)},ensure_ascii=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--csv',type=Path,required=True)
    parser.add_argument('--inventory',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--state',type=Path,required=True);args=parser.parse_args()
    build(args.csv,args.inventory,args.out,args.state)
