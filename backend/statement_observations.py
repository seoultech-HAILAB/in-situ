"""Observe native statement boundaries without changing the executed program.

Only verified pandas selection/replay carries row identity. Matching cell values
or coincidentally equal indexes of unrelated frames never establishes identity.
"""
import ast
import copy
import json

import pandas as pd

from .python_provenance import ProvenanceInterpreter
from .runtime import Frame, Value, digest, table

VERSION='native-statements-v3'
MUTATORS={'drop','dropna','drop_duplicates','sort_values','sort_index','reset_index','set_index','rename',
          'pop','insert','update','resize','reindex','set_axis'}


def location(node):
    return {'start':node.lineno,'end':node.end_lineno,'start_column':node.col_offset,'end_column':node.end_col_offset}


def frames(env):
    return {**{k:v for k,v in env.items() if isinstance(v,pd.DataFrame)},
            **{f'tables:{k}':v for k,v in env.get('tables',{}).items() if isinstance(v,pd.DataFrame)}}


def snapshot(env, names):
    live=frames(env)
    chosen={k:v for k,v in live.items() if k in names or k.startswith('tables:') and 'tables' in names}
    objects={id(v) for v in chosen.values()}
    chosen.update({k:v for k,v in live.items() if id(v) in objects})
    scalars={}
    for k in names:
        value=env.get(k)
        if isinstance(value,pd.Series):scalars[k]=Value(value.copy(deep=True),{}, {},set(),'관찰한 조건 값',False)
        elif value is None or isinstance(value,(str,int,float,bool,list,tuple,dict,set)):
            scalars[k]=copy.deepcopy(value)
    size=sum(int(v.memory_usage(deep=True).sum()) for v in chosen.values())
    size+=sum(int(v.data.memory_usage(deep=True)) for v in scalars.values() if isinstance(v,Value))
    return {'frames':{k:v.copy(deep=True) for k,v in chosen.items()},
            'objects':{k:id(v) for k,v in chosen.items()},'scalars':scalars,'bytes':size}


def pure(node, helpers):
    for part in ast.walk(node):
        if isinstance(part,ast.NamedExpr):return False
        if isinstance(part,ast.Call):
            if isinstance(part.func,ast.Name) and part.func.id in helpers:return False
            if isinstance(part.func,ast.Attribute) and part.func.attr in MUTATORS:return False
            if any(k.arg=='inplace' for k in part.keywords):return False
    return True


def column_writes(node, aliases, helpers):
    found=False
    if not pure(node,helpers):return False
    for part in ast.walk(node):
        if isinstance(part,(ast.Assign,ast.AnnAssign,ast.AugAssign,ast.Delete)):
            targets=part.targets if isinstance(part,(ast.Assign,ast.Delete)) else [part.target]
            for target in targets:
                if isinstance(target,ast.Name):
                    if target.id in aliases:return False
                elif isinstance(target,ast.Subscript) and isinstance(target.value,ast.Name) and target.value.id in aliases:found=True
                else:return False
    return found


def selection_source(node,before,helpers):
    value=getattr(node,'value',None)
    if isinstance(value,ast.Call) and isinstance(value.func,ast.Attribute) and value.func.attr in {
        'head','tail','take','filter','select_dtypes','nlargest','nsmallest'}:
        source=value.func.value
        return source.id if isinstance(source,ast.Name) and source.id in before['frames'] else None
    if not isinstance(value,ast.Subscript) or not pure(value,helpers):return None
    source=value.value
    if isinstance(source,ast.Attribute) and source.attr in ('loc','iloc'):source=source.value
    return source.id if isinstance(source,ast.Name) and source.id in before['frames'] else None


class Observations:
    def __init__(self,code,spec,identities):
        self.code=code;self.spec=spec;self.identities=dict(identities);self.origins={};self.records=[];self.serial=0
        self.failures=[]
        self.helpers={n.name for n in ast.parse(code).body if isinstance(n,ast.FunctionDef)}

    def observe(self,node,index,before,after,executed_lines):
        before_ids={key:list(ids) for key,ids in self.identities.items()}
        try:
            self._observe(node,index,before,after,executed_lines)
        except Exception as exc:
            self.failures.append({'statement_index':index,'code_location':location(node),'error':str(exc)[:200]})
            for name,df in after['frames'].items():
                self.identities[name]=['obs'+digest([self.spec['id'],index,name,j]) for j in range(len(df))]
                self.origins[name]={r:[] for r in self.identities[name]}
        # The actual assignment is an independently observed operation, even
        # when a nested Series call has no detailed tracing adapter.
        try:self.assignment(node,index,before,after,before_ids,executed_lines)
        except Exception as exc:
            self.failures.append({'statement_index':index,'code_location':location(node),'error':str(exc)[:200]})

    def _observe(self,node,index,before,after,executed_lines):
        prior=before['frames'];following=after['frames']
        for name,df in prior.items():
            if name not in self.identities or len(self.identities[name])!=len(df):
                self.identities[name]=['obs'+digest([self.spec['id'],index,name,j]) for j in range(len(df))]
            self.origins.setdefault(name,{r:[r] for r in self.identities[name]})
        changed=[name for name,df in following.items() if name not in prior or not df.equals(prior[name])]
        stored={n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
        outputs=changed or [name for name in following if name in stored]
        if not outputs:return
        interpreter=ProvenanceInterpreter(pd.DataFrame())
        interpreter.code=self.code;interpreter.env.update(before['scalars'])
        for name,df in prior.items():
            ids=self.identities[name]
            frame=Frame(df.copy(deep=True),list(ids),{r:{str(c):[] for c in df} for r in ids},
                        copy.deepcopy(self.origins[name]),'observed-input:'+name,False)
            interpreter.frames[frame.node]=frame
            if name.startswith('tables:'):interpreter.roots[name[7:]]=frame
            else:interpreter.env[name]=frame
        try:
            interpreter.statement(node,index)
            for name in outputs:
                frame=interpreter.roots.get(name[7:]) if name.startswith('tables:') else interpreter.env.get(name)
                if not isinstance(frame,Frame):raise ValueError('unobserved output')
                pd.testing.assert_frame_equal(frame.data,following[name],check_exact=True)
            for operation in interpreter.ops:
                operation.update(row_identity_verified=operation['kind'] in {
                    'filter','select','derive','drop','rename','sort_values','astype','fillna','replace',
                    'dropna','drop_duplicates','reset_index','copy','head','tail'},
                    observation_scope='expression',executed_lines=sorted(executed_lines))
                self.append(operation)
            for name in outputs:
                frame=interpreter.roots.get(name[7:]) if name.startswith('tables:') else interpreter.env.get(name)
                self.identities[name]=list(frame.ids)
                self.origins[name]=copy.deepcopy(frame.rows)
            return
        except Exception:
            # Native execution already succeeded; an optional replay limitation
            # affects attribution only, never the result or success status.
            pass
        for name in outputs:
            df=following[name]
            source=selection_source(node,before,self.helpers)
            if not source:
                aliases={key for key,obj in before['objects'].items() if obj==after['objects'].get(name)}
                source=next((key for key in aliases if column_writes(node,aliases,self.helpers)),None)
            identity=False
            if source:
                old=prior[source]
                subset=old.index.is_unique and df.index.is_unique and df.index.isin(old.index).all()
                same_object=before['objects'][source]==after['objects'][name]
                if subset and (not same_object or old.index.equals(df.index)):
                    ids=[self.identities[source][old.index.get_loc(ix)] for ix in df.index];identity=True
            if not identity:ids=['obs'+digest([self.spec['id'],index,name,j]) for j in range(len(df))]
            origins={r:list(self.origins[source].get(r,[])) for r in ids} if identity else {r:[] for r in ids}
            if not source:
                loads={n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)}
                source=next((key for key in prior if key in loads),None)
            if source:
                old=prior[source];old_ids=self.identities[source]
                value=getattr(node,'value',None)
                operation={'kind':'observed','table':table(df,ids),'input':table(old,old_ids),
                    'code':ast.get_source_segment(self.code,node),'code_location':location(node),
                    'expression_location':location(value) if value is not None and hasattr(value,'lineno') else None,
                    'statement_index':index,'output_variable':name,'row_identity_verified':identity,
                    'trace_level':'common','observation_scope':'statement','executed_lines':sorted(executed_lines)}
                self.append(operation)
            self.identities[name]=ids
            self.origins[name]=origins

    def assignment(self,node,index,before,after,before_ids,executed_lines):
        if isinstance(node,ast.For):
            return self.loop_assignments(node,index,before,after,before_ids,executed_lines)
        if not isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign)):return
        target=node.targets[0] if isinstance(node,ast.Assign) and len(node.targets)==1 else getattr(node,'target',None)
        if not isinstance(target,ast.Subscript) or not isinstance(target.value,ast.Name):return
        name=target.value.id
        if name not in before['frames'] or name not in after['frames']:return
        column=target.slice.value if isinstance(target.slice,ast.Constant) else before['scalars'].get(target.slice.id) if isinstance(target.slice,ast.Name) else None
        if not isinstance(column,(str,int)):return
        prior,following=before['frames'][name],after['frames'][name]
        old_ids=before_ids.get(name,self.identities.get(name,[]));new_ids=self.identities.get(name,[])
        if len(old_ids)!=len(prior) or len(new_ids)!=len(following):return
        self.append({'kind':'assignment','table':table(following,new_ids),'input':table(prior,old_ids),
            'code':ast.get_source_segment(self.code,node),'code_location':location(node),'expression_location':location(node),
            'statement_index':index,'output_variable':name,'written_columns':[str(column)],
            'row_identity_verified':prior.index.equals(following.index) and old_ids==new_ids,
            'trace_level':'common','observation_scope':'assignment','executed_lines':sorted(executed_lines)})

    def loop_assignments(self,node,index,before,after,before_ids,executed_lines):
        if not isinstance(node.target,ast.Name):return
        try:values=ast.literal_eval(node.iter)
        except (ValueError,TypeError):values=before['scalars'].get(node.iter.id) if isinstance(node.iter,ast.Name) else None
        if not isinstance(values,(list,tuple)) or not all(isinstance(value,(str,int)) for value in values):return
        def resolve(expr,value):
            if isinstance(expr,ast.Constant):return expr.value
            if isinstance(expr,ast.Name):return value if expr.id==node.target.id else before['scalars'].get(expr.id)
            if isinstance(expr,ast.BinOp) and isinstance(expr.op,ast.Add):
                left,right=resolve(expr.left,value),resolve(expr.right,value)
                if isinstance(left,str) and isinstance(right,str):return left+right
            return None
        writes=[]
        for statement in ast.walk(node):
            if not isinstance(statement,ast.Assign) or len(statement.targets)!=1 or statement.lineno not in executed_lines:continue
            target=statement.targets[0]
            if not isinstance(target,ast.Subscript) or not isinstance(target.value,ast.Name):continue
            name=target.value.id
            if name not in before['frames'] or name not in after['frames']:continue
            aliases={key for key,obj in before['objects'].items() if obj==after['objects'].get(name)}
            if not column_writes(node,aliases,self.helpers):continue
            columns={str(column) for value in values if isinstance(column:=resolve(target.slice,value),(str,int))}
            if columns:writes.append((statement,name,columns))
        for statement,name,columns in writes:
            unique=[c for c in columns if sum(other_name==name and c in other_columns for _,other_name,other_columns in writes)==1]
            prior,following=before['frames'][name],after['frames'][name]
            old_ids=before_ids.get(name,[]);new_ids=self.identities.get(name,[])
            if not unique or len(old_ids)!=len(prior) or len(new_ids)!=len(following):continue
            self.append({'kind':'assignment','table':table(following,new_ids),'input':table(prior,old_ids),
                'code':ast.get_source_segment(self.code,statement),'code_location':location(statement),'expression_location':location(statement),
                'statement_index':index,'output_variable':name,'written_columns':sorted(unique),
                'row_identity_verified':prior.index.equals(following.index) and old_ids==new_ids,
                'trace_level':'common','observation_scope':'assignment-block','executed_lines':sorted(executed_lines)})

    def append(self,operation):
        def display(value):
            if isinstance(value,(pd.Period,pd.Interval)):return str(value)
            raise TypeError('Intermediate observation is not displayable')
        operation=json.loads(json.dumps(operation,ensure_ascii=False,allow_nan=False,default=display))
        self.serial+=1
        operation['id']=self.spec['id']+'/observed-'+str(self.serial)
        self.records.append(operation)

    def finish(self,last,output_name,step_inputs,complete=True):
        last['operation_observations']=self.records
        last['execution_observations_version']=VERSION
        if self.failures:last['execution_observation_failures']=self.failures
        if not complete:
            last['execution_observations_limited']=True
            return
        if output_name not in self.identities:return
        ids=self.identities[output_name]
        if len(ids)!=len(last['table']['rows']):return
        aliases={token:row['id'] for token,row in zip(ids,last['table']['rows'])}
        if len(aliases)!=len(ids):return
        last['observation_row_aliases']=aliases
        origins=self.origins.get(output_name,{})
        if any(not origins.get(row_id) for row_id in ids):return
        correspondence=None;best=-1
        for item in step_inputs:
            initial={row['id'] for row in item['table']['rows']}
            matches={token:[source for source in origins.get(token,[]) if source in initial] for token in ids}
            if any(len(values)>1 for values in matches.values()):continue
            mapped=[values[0] for values in matches.values() if values]
            if len(set(mapped))!=len(mapped):continue
            if len(mapped)>best:
                best=len(mapped)
                correspondence={aliases[token]:values[0] for token,values in matches.items() if values}
        if correspondence is None:return
        aliases.update({before:after for after,before in correspondence.items()})
        last['row_correspondence']=correspondence
        last['row_correspondence_complete']=True
        last['observation_row_aliases']=aliases
