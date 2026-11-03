"""Native Python execution with observed Step boundaries and optional verified tracing.

No dataset-specific transformation rules. Run only in the isolated worker. AST
checks and the audit hook are defense in depth, not an adversarial-code sandbox.
"""
import ast
import builtins
import copy
import importlib
import io
import os
from pathlib import Path
import sys
import sysconfig
from contextlib import redirect_stdout

import numpy as np
import pandas as pd

from .runtime import Frame, Interpreter, Unsupported, clean, digest, run as traced_run, table
from .python_provenance import ProvenanceInterpreter
from .statement_observations import Observations, SchemaObservations, snapshot as observation_snapshot, VERSION as OBSERVATIONS_VERSION
from .table_call_observations import TableCallObservations, VERSION as TABLE_CALLS_VERSION

MODULES=('pandas','numpy','math','re','datetime','statistics','collections','itertools','functools')
# datetime's native strftime/strptime call __import__ for these trusted helpers.
# AST validation still rejects user-written imports outside MODULES.
DATETIME_INTERNAL_IMPORTS={'time','_strptime'}
FORBIDDEN={'open','exec','eval','compile','globals','locals','vars','getattr','setattr','delattr',
           'breakpoint','input','help','exit','quit','__import__'}
ATTRS={'os','sys','subprocess','ctypes','builtins','importlib','system','popen','load_library',
       'eval','query','read_pickle','to_pickle','read_sql','to_sql','read_html','read_xml'}


class PythonFailure(Unsupported):
    def __init__(self,message,records=None,failure=None):
        super().__init__(message)
        self.records=records or []
        self.failure=failure or {}


def validate(code):
    if len(code)>30000: raise Unsupported('코드 길이 제한 초과')
    tree=ast.parse(code)
    if not any(isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load) and n.id in ('input_df','tables') for n in ast.walk(tree)):
        raise Unsupported('변환 코드가 제공된 입력을 참조하지 않습니다. Target 상수 출력은 허용하지 않습니다.')
    if not tree.body or len(tree.body)>40 or len(list(ast.walk(tree)))>5000:
        raise Unsupported('코드 문장/구문 제한 초과')
    for node in ast.walk(tree):
        if isinstance(node,(ast.ClassDef,ast.AsyncFunctionDef,ast.Await,ast.Yield,ast.YieldFrom,ast.Global,ast.Nonlocal)):
            raise Unsupported('클래스·비동기·generator·global/nonlocal은 실행 범위 밖입니다.')
        if isinstance(node,ast.Name) and (node.id.startswith('__') or node.id in FORBIDDEN):
            raise Unsupported('동적 코드 실행·반사·직접 입출력은 허용하지 않습니다.')
        if isinstance(node,ast.Attribute) and (node.attr.startswith('_') or node.attr in ATTRS):
            raise Unsupported('시스템 접근·반사 속성은 허용하지 않습니다.')
        if isinstance(node,ast.Import) and any(x.name not in MODULES for x in node.names):
            raise Unsupported('허용 라이브러리: '+', '.join(MODULES))
        if isinstance(node,ast.ImportFrom) and (node.level or node.module not in MODULES or any(x.name=='*' or x.name.startswith('_') or x.name in FORBIDDEN|ATTRS for x in node.names)):
            raise Unsupported('허용된 라이브러리의 명시적 import만 사용할 수 있습니다.')
        if isinstance(node,(ast.FunctionDef,ast.Lambda)):
            if isinstance(node,ast.FunctionDef) and (node.decorator_list or node.name.startswith('__')):
                raise Unsupported('decorator는 실행 범위 밖입니다.')
    return tree


def install_audit():
    """Worker only: block writes, user-file reads, networking and process launch."""
    roots=[Path(sys.base_prefix).resolve(),Path(sysconfig.get_path('purelib')).resolve()]
    # Resolve lazy imports before sealing execution; library resource reads remain allowed.
    for name in MODULES: importlib.import_module(name)
    def audit(event,args):
        if event=='open':
            filename,mode,flags=args
            if not isinstance(filename,(str,bytes,os.PathLike)): raise PermissionError('파일 핸들 접근 차단')
            resolved=Path(os.fsdecode(filename)).resolve()
            write=bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            if write or not any(resolved.is_relative_to(root) for root in roots):
                raise PermissionError('실행 코드는 파일을 읽거나 쓸 수 없습니다. 제공된 DataFrame을 사용하세요.')
        if event.startswith(('socket.','subprocess.','ctypes.','os.exec','os.spawn')) or event in ('os.system','os.fork','os.remove','os.rename','os.mkdir','os.rmdir','os.chdir','os.putenv'):
            raise PermissionError('파일 변경·네트워크·프로세스 접근 차단')
    sys.addaudithook(audit)


def namespace(frame,sources):
    allowed=('abs','all','any','bool','dict','enumerate','filter','float','int','isinstance','issubclass',
             'len','list','map','max','min','next','print','range','reversed','round','set','slice',
             'sorted','str','sum','tuple','type','zip','Exception','ValueError','TypeError','KeyError',
             'AssertionError','ZeroDivisionError')
    safe={k:getattr(builtins,k) for k in allowed}
    def importer(name,globals=None,locals=None,fromlist=(),level=0):
        if name not in MODULES and name not in DATETIME_INTERNAL_IMPORTS or level: raise ImportError('허용되지 않은 import')
        return importlib.import_module(name)
    safe['__import__']=importer
    return {'__builtins__':safe,'__name__':'trace_program','pd':pd,'np':np,
            'input_df':frame.reset_index(drop=True).copy(deep=True),
            'tables':{k:v.reset_index(drop=True).copy(deep=True) for k,v in sources.items()}}


def frames(env):
    return {**{k:v for k,v in env.items() if isinstance(v,pd.DataFrame)},
            **{f'tables:{k}':v for k,v in env.get('tables',{}).items() if isinstance(v,pd.DataFrame)}}


def checked(df,ids):
    if len(df)>2000 or len(df.columns)>64 or df.memory_usage(deep=True).sum()>16_000_000:
        raise Unsupported('관찰 결과 2000행·64열·16 MB 제한 초과')
    value=table(df,ids)
    # Fail at the exact boundary when a cell cannot be faithfully serialized.
    import json
    json.dumps(value,ensure_ascii=False,allow_nan=False)
    return value


def same(a,b):
    try:
        pd.testing.assert_frame_equal(a,b,check_exact=True)
        return True
    except (AssertionError,TypeError,ValueError): return False


def run(code,frame,sources,plan):
    tree=validate(code);env=namespace(frame,sources)
    tracer=ProvenanceInterpreter(frame.copy(deep=True),{k:v.copy(deep=True) for k,v in sources.items()})
    tracer.code=code
    root=traced_run('result = input_df.copy()',frame.copy(deep=True))[0]
    records=[root];owners={'input_df':'input',**{f'tables:{k}':f'source:{k}' for k in sources}}
    identities={'input_df':tracer.roots['input'].ids,**{f'tables:{k}':tracer.roots[k].ids for k in sources}}
    helper_names={n.name:{x.id for x in ast.walk(n) if isinstance(x,ast.Name) and isinstance(x.ctx,ast.Load)} for n in tree.body if isinstance(n,ast.FunctionDef)}
    for spec in plan['steps']:
        indices=spec['statement_indices'];nodes=[tree.body[i] for i in indices]
        before=frames(env)
        # Input discovery is conservative static code dependency, never asserted as cell lineage.
        loaded={n.id for s in nodes for n in ast.walk(s) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)}
        todo=list(loaded);seen=set()
        while todo:
            name=todo.pop()
            if name in seen: continue
            seen.add(name)
            for x in helper_names.get(name,set()):
                if x not in loaded:loaded.add(x);todo.append(x)
        names=[k for k in before if k in loaded or k.startswith('tables:') and 'tables' in loaded]
        reference_names=list(names)
        inputs=[{'ref':owners.get(k,'input'),'variable':k,'table':checked(before[k],identities[k])} for k in names]
        previous={k:v.copy(deep=True) for k,v in before.items()}
        observations=Observations(code,spec,identities)
        statement_snapshots=[]
        executed_statements=[]
        schemas=SchemaObservations(list(zip(indices,nodes)))
        table_calls=TableCallObservations(code,spec['id'])
        observation_bytes=0;complete_observations=True
        try:
            output=io.StringIO()
            with redirect_stdout(output):
                for statement_index,node in zip(indices,nodes):
                    observed_names={n.id for n in ast.walk(node) if isinstance(n,ast.Name)}
                    for helper in list(observed_names):observed_names.update(helper_names.get(helper,set()))
                    observed_before=None
                    if complete_observations:
                        try:observed_before=observation_snapshot(env,observed_names)
                        except Exception:complete_observations=False
                    executed_lines=set()
                    old_trace=sys.gettrace()
                    def record_line(frame,event,arg):
                        try:table_calls.observe(frame,event,arg,statement_index)
                        except Exception:table_calls.limited=True
                        if frame.f_code.co_filename=='<trace-program>':
                            if event=='line':executed_lines.add(frame.f_lineno)
                            try:schemas.trace(frame,event)
                            except Exception:pass
                        return record_line
                    try:
                        sys.settrace(record_line)
                        exec(compile(ast.Module(body=[node],type_ignores=[]),'<trace-program>','exec'),env,env)
                    finally:sys.settrace(old_trace)
                    # Independent of snapshot/replay support and memory limits.
                    executed_statements.append({'statement_index':statement_index,
                        'code_location':{'start':node.lineno,'end':node.end_lineno,'start_column':node.col_offset,'end_column':node.end_col_offset},
                        'executed_lines':sorted(executed_lines)})
                    if complete_observations:
                        try:
                            observed_after=observation_snapshot(env,observed_names)
                            observation_bytes+=observed_before['bytes']+observed_after['bytes']
                            if observation_bytes>16_000_000:complete_observations=False
                            else:statement_snapshots.append((node,statement_index,observed_before,observed_after,executed_lines))
                        except Exception:complete_observations=False
            after=frames(env);name=spec.get('output_variable')
            observation_only=False
            if spec.get('output_explicit') and name not in after:
                raise Unsupported(f'Step 출력 {name!r}이 실제 DataFrame이 아닙니다.')
            if name not in after:
                changed=[k for k,v in after.items() if k not in previous or not same(v,previous[k])]
                observation_only=not changed
                name=changed[-1] if changed else names[-1] if names else 'input_df'
            actual=after[name]
            constructed_input=not inputs and not observation_only
            if not inputs:
                inputs=[{'ref':owners.get(name,'input') if observation_only else 'constructed',
                         'variable':name if observation_only else None,
                         'table':checked(before[name],identities[name]) if observation_only else checked(pd.DataFrame(),[])}]
            ids=['p'+digest([spec['id'],clean(ix),j]) for j,ix in enumerate(actual.index)]
            observed=checked(actual,ids)
            detailed=None;trace_error=None
            try:
                clone=copy.deepcopy(tracer);start=len(clone.ops)
                for i,node in zip(indices,nodes):
                    begin=len(clone.ops);clone.statement(node,i)
                    for op in clone.ops[begin:]:op['output_variable']=name
                f=clone.roots.get(name[7:]) if name.startswith('tables:') else clone.env.get(name)
                if not isinstance(f,Frame) or not same(f.data,actual):raise Unsupported('native/상세 어댑터 출력 불일치')
                if len(clone.ops)==start or clone.ops[-1]['id']!=f.node:
                    observed_frame=clone.rowwise(f,f.data.copy(),'copy');clone.mutate(f,observed_frame);f=observed_frame
                    clone.ops[-1]['output_variable']=name
                for key,value in after.items():
                    traced=clone.roots.get(key[7:]) if key.startswith('tables:') else clone.env.get(key)
                    if isinstance(traced,Frame) and not same(traced.data,value):raise Unsupported('native/상세 어댑터 중간 변수 불일치')
                from .runtime import Value
                for key,value in clone.env.items():
                    if isinstance(value,Value) and key in env:
                        if isinstance(value.data,pd.Series):pd.testing.assert_series_equal(value.data,env[key],check_exact=True)
                        elif clean(value.data)!=clean(env[key]):raise Unsupported('native/상세 어댑터 스칼라 불일치')
                detailed=clone.ops[start:];tracer=clone
            except Exception as exc:
                # A tracing limitation never converts successful native code into failure.
                trace_error=str(exc)[:500]
            if detailed:
                for op in detailed:
                    if op['trace_level']=='common' and any(refs for cols in op['lineage'].values() for refs in cols.values()):
                        op.update(trace_level='partial',trace_reason='일부 셀의 원본 출처만 확인되었습니다. 나머지 출처는 미확인입니다.')
                records.extend(detailed);last=detailed[-1];ids=last['table']['rows'];ids=[r['id'] for r in ids]
                if observation_only and last['kind']=='copy':
                    last.update(kind='setup',observation_only=True,label='실행 준비 · 표 유지',summary='설정 값을 준비하고 입력 표를 유지합니다.')
            else:
                node_id=f'op-{len(records)}'
                last={'id':node_id,'order':len(records),'kind':'setup' if observation_only else 'python','label':'실행 준비 · 표 유지' if observation_only else 'Python 변환',
                      'summary':f'코드를 실행한 실제 관찰 결과는 {len(actual)}행·{len(actual.columns)}열입니다.',
                      'table':observed,'input':inputs[0]['table'],'inputs':inputs,
                      'input_refs':list(dict.fromkeys(x['ref'] for x in inputs)),
                      'depends_on':list(dict.fromkeys(owners[k] for k in reference_names)),'output_ref':node_id,
                      'params':{'output_variable':name,'dependency_kind':'conservative_code_reference'},'lineage':{r:{str(c):[] for c in actual} for r in ids},
                      'row_sources':{r:[] for r in ids},'parents':{},'contexts':{},'removed':None,
                      'related_columns':[], 'trace_level':'common','trace_reason':'실행은 완료했습니다. 이 구문의 원본 셀 출처는 미확인입니다.',
                      'trace_diagnostic':trace_error,
                      'code':spec['code'],'code_location':spec['code_location'],'statement_index':indices[-1],
                      'operation_expression':spec['code'],'output_variable':name,
                      'changes':{'rows':len(actual)-len(inputs[0]['table']['rows']),'added_columns':[str(c) for c in actual if str(c) not in inputs[0]['table']['columns']],
                                 'removed_columns':[c for c in inputs[0]['table']['columns'] if c not in list(map(str,actual.columns))]}}
                records.append(last)
                tracer.ops.append(last)
                # Preserve independently verified bindings; invalidate written
                # helpers and changed frames without inferring origin from values.
                written={n.id for node in nodes for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
                for key in written:tracer.env.pop(key,None)
            last['stdout']=output.getvalue()[:10000]
            last['executed_statements']=executed_statements
            last['direct_table_calls']=table_calls.records
            last['direct_table_observations_version']=TABLE_CALLS_VERSION
            if table_calls.limited:last['direct_table_observations_limited']=True
            last['statement_schema_effects']=list(schemas.records.values())
            last['schema_origins']=schemas.for_frame(actual)
            last['output_bindings']=[key for key,value in after.items() if value is actual]
            last['comparison_input_kind']='constructed' if constructed_input else 'observed'
            try:
                for observation in statement_snapshots:observations.observe(*observation)
                observations.finish(last,name,inputs,complete_observations)
            except Exception:
                last['operation_observations']=observations.records
                last['execution_observations_version']=OBSERVATIONS_VERSION
                last['execution_observations_limited']=True
            last['execution_backend']='native-python';last['native_verified']=True
            spec['observed_output_variable']=name
            for key,df in after.items():
                changed=key not in previous or not same(df,previous[key])
                if key==name or changed:
                    own_ids=ids if same(df,actual) else ['p'+digest([spec['id'],key,clean(ix),j]) for j,ix in enumerate(df.index)]
                    checked(df,own_ids);owners[key]=last['id'];identities[key]=own_ids
                    known=tracer.roots.get(key[7:]) if key.startswith('tables:') else tracer.env.get(key)
                    if not isinstance(known,Frame) or not same(known.data,df):
                        observation_node=last['id'] if key==name else last['id']+'/binding-'+digest(key)
                        unknown=Frame(df.copy(deep=True),own_ids,{r:{str(c):[] for c in df} for r in own_ids},{r:[] for r in own_ids},observation_node,False)
                        tracer.frames[observation_node]=unknown
                        if key.startswith('tables:'):tracer.roots[key[7:]]=unknown
                        else:tracer.env[key]=unknown
                elif key not in identities:
                    identities[key]=['p'+digest([key,clean(ix),j]) for j,ix in enumerate(df.index)]
            if len(records)>81:raise Unsupported('실행 기록 수 제한 초과')
        except Exception as exc:
            import traceback
            failure={'step_id':spec['id'],'statement_indices':indices,'code_location':spec['code_location'],
                     'exception_type':type(exc).__name__,'message':str(exc)[:2000],
                     'traceback':traceback.format_exc(limit=6)[-4000:]}
            raise PythonFailure(f'Step {spec["id"]} 실행 실패: {exc}',records,failure) from exc
    if plan.get('preview_only'):return records
    if not isinstance(env.get('result'),pd.DataFrame):raise PythonFailure('최종 result DataFrame이 없습니다.',records)
    if plan['steps'][-1].get('observed_output_variable')!='result':
        raise PythonFailure('마지막 Step 출력은 실제 result여야 합니다.',records)
    return records
