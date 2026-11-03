"""Capability-based pandas execution. No eval/exec or arbitrary Python access.

Adapters record observed operations. Unverified reshape lineage is explicitly
unknown and remains unknown downstream, even when execution succeeds.
"""
import ast
import hashlib
import json
import math
import operator
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from .legacy_engine import Unsupported

CAPABILITIES = {k: 'detailed' for k in ('filter','select','copy','derive','aggregate','sort_values','rename','drop','astype','fillna','dropna','drop_duplicates','replace','merge','concat','melt','explode')}
CAPABILITIES.update(reset_index='partial',join='common',pivot='common',pivot_table='common',transpose='common')
LABELS = dict(filter='행 필터',select='열 선택',copy='복사',derive='계산·변환 열',aggregate='그룹 집계',sort_values='정렬',rename='열 이름 변경',drop='열 삭제',astype='타입 변환',fillna='결측 대체',dropna='결측 행 제거',drop_duplicates='중복 제거',replace='값 치환',reset_index='인덱스 정리',merge='테이블 병합',join='인덱스 조인',concat='행 결합',melt='긴 형식 변환',explode='목록 펼치기',pivot='피벗',pivot_table='피벗 집계',transpose='전치')


def clean(v):
    if isinstance(v,dict): return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple,np.ndarray)): return [clean(x) for x in v]
    if v is None or pd.isna(v): return None
    if isinstance(v,(pd.Timestamp,pd.Timedelta)): return v.isoformat()
    if hasattr(v,'item'): v=v.item()
    if isinstance(v,float) and not math.isfinite(v): return None
    return v


def digest(v):
    return hashlib.sha256(json.dumps(clean(v),ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]


def union(refs):
    found={(x.get('table_id','input'),x['row_id'],x['column']):x for x in refs}
    return [found[k] for k in sorted(found)]


def table(df,ids=None):
    if isinstance(df.columns,pd.MultiIndex): raise Unsupported('MultiIndex 열은 미지원입니다. 단일 values 열을 사용하세요.')
    cols=[str(c) for c in df.columns]
    if len(set(cols))!=len(cols): raise Unsupported('중복되거나 표시 이름이 충돌하는 열은 미지원입니다.')
    ids=ids if ids is not None else [str(x) for x in df.index]
    if np.isinf(df.select_dtypes(include='number').to_numpy(dtype=float,na_value=np.nan)).any(): raise Unsupported('계산에서 무한대가 발생했습니다.')
    for c in df.select_dtypes(include='integer'):
        if ((df[c]>9_007_199_254_740_991)|(df[c]<-9_007_199_254_740_991)).any(): raise Unsupported('브라우저 정수 정밀도 범위를 초과했습니다.')
    try:
        duplicates=int(df.duplicated().sum())
    except TypeError:
        duplicates=int(pd.Series([json.dumps(clean(row),sort_keys=True) for row in df.to_dict('records')]).duplicated().sum())
    return {'columns':cols,'rows':[{'id':ids[i],'values':{str(c):clean(df[c].iloc[i]) for c in df}} for i in range(len(df))],
        'stats':{'rows':len(df),'columns':len(cols),'duplicates':duplicates,
                 'fields':{str(c):{'dtype':str(df[c].dtype),'missing':int(df[c].isna().sum()),'min':clean(df[c].min()) if pd.api.types.is_numeric_dtype(df[c]) else None,'max':clean(df[c].max()) if pd.api.types.is_numeric_dtype(df[c]) else None} for c in df}}}


@dataclass
class Frame:
    data: pd.DataFrame
    ids: list
    lineage: dict
    rows: dict
    node: str
    complete: bool=True


@dataclass
class Value:
    data: object
    refs: dict
    parents: dict
    columns: set
    label: str
    complete: bool=True
    tests: list=field(default_factory=list)
    nodes: set=field(default_factory=set)


@dataclass
class Access:
    source: object
    name: str


@dataclass
class Group:
    source: Frame
    args: list
    kw: dict


def raw(x): return x.data if isinstance(x,Value) else x
BIN={ast.Add:(operator.add,'+'),ast.Sub:(operator.sub,'−'),ast.Mult:(operator.mul,'×'),ast.Div:(operator.truediv,'÷'),ast.Mod:(operator.mod,'%'),ast.BitAnd:(operator.and_,'∧'),ast.BitOr:(operator.or_,'∨')}
CMP={ast.Eq:(operator.eq,'='),ast.NotEq:(operator.ne,'≠'),ast.Gt:(operator.gt,'>'),ast.GtE:(operator.ge,'≥'),ast.Lt:(operator.lt,'<'),ast.LtE:(operator.le,'≤')}
SERIES={'astype':{'dtype','errors'},'fillna':{'value','limit'},'round':{'decimals'},'isin':{'values'},'isna':set(),'notna':set(),'between':{'left','right','inclusive'},'replace':{'to_replace','value','regex'},'clip':{'lower','upper'},'sum':set(),'mean':set(),'min':set(),'max':set(),'count':set()}
STR={'strip':{'to_strip'},'lstrip':{'to_strip'},'rstrip':{'to_strip'},'lower':set(),'upper':set(),'title':set(),'replace':{'pat','repl','n','regex','case'},'contains':{'pat','case','regex','na'},'startswith':{'pat','na'},'endswith':{'pat','na'},'len':set(),'slice':{'start','stop','step'},'split':{'pat','n','expand','regex'},'get':{'i'}}
METHODS={'copy':set(),'assign':None,'sort_values':{'by','ascending','na_position','kind'},'rename':{'columns','errors'},'drop':{'columns','errors'},'astype':{'dtype','errors'},'fillna':{'value','limit'},'dropna':{'axis','how','thresh','subset'},'drop_duplicates':{'subset','keep'},'replace':{'to_replace','value','regex'},'reset_index':{'drop','names'},'merge':{'right','how','on','left_on','right_on','suffixes','validate','sort'},'join':{'other','on','how','lsuffix','rsuffix','sort','validate'},'melt':{'id_vars','value_vars','var_name','value_name','ignore_index'},'explode':{'column','ignore_index'},'pivot':{'index','columns','values'},'pivot_table':{'values','index','columns','aggfunc','fill_value','dropna','observed','sort'},'transpose':set()}


class Interpreter:
    def __init__(self,frame,sources=None):
        self.ops=[];self.code='';self.stmt=None;self.si=0;self.start=time.monotonic();self.env={};self.roots={}
        for name,df in {'input':frame,**(sources or {})}.items():
            ids=[str(r) if name=='input' else f'{name}:{r}' for r in df.index]
            lin={r:{str(c):[{'row_id':r,'column':str(c),**({'table_id':name} if name!='input' else {})}] for c in df} for r in ids}
            self.roots[name]=Frame(df.reset_index(drop=True),ids,lin,{r:[r] for r in ids},'input' if name=='input' else f'source:{name}')
        self.env['input_df']=self.roots['input']
        self.frames={f.node:f for f in self.roots.values()}

    def check(self,df):
        if len(self.ops)>=80 or time.monotonic()-self.start>12: raise Unsupported('연산 수 또는 실행 시간 제한 초과')
        if len(df)>2000 or len(df.columns)>64 or df.memory_usage(deep=True).sum()>16_000_000: raise Unsupported('실행 결과의 행·열·메모리 제한 초과')
        if not df.index.is_unique: raise Unsupported('중복 인덱스는 미지원입니다. ignore_index=True를 사용하세요.')
        table(df)

    def record(self,srcs,out,ids,lin,rows,kind,p=None,removed=None,contexts=None,parents=None,complete=None):
        self.check(out);p=p or {};node=f'op-{len(self.ops)+1}';before=srcs[0]
        if len(ids)!=len(out) or len(set(ids))!=len(ids): raise Unsupported('출력 행 식별자가 유일하지 않습니다.')
        complete=all(x.complete for x in srcs) if complete is None else complete
        lin={r:{str(c):lin.get(r,{}).get(str(c),[]) for c in out} for r in ids}
        f=Frame(out,ids,lin,rows,node,complete)
        summary=f'{LABELS[kind]} 연산을 적용하여 {len(before.data)}행·{len(before.data.columns)}열에서 {len(out)}행·{len(out.columns)}열이 되었습니다.'
        if kind=='filter': summary=f'{p["condition"]} 조건이 참인 {p["kept"]}행을 유지합니다. {p["removed"]}행은 제외됩니다.'
        if kind=='derive': summary=' · '.join(f'{c} = {x["formula"]}' for c,x in p['formulas'].items())+'를 계산합니다.'
        if kind=='aggregate': summary=', '.join(p['keys'])+'별로 '+', '.join(f'{c} = {v["operation"].upper()}({v["column"]})' for c,v in p['aggregations'].items())+'를 계산합니다.'
        if p.get('arguments'): summary+=' 적용 인자: '+json.dumps(p['arguments'],ensure_ascii=False)+'.'
        self.ops.append({'id':node,'order':len(self.ops)+1,'kind':kind,'label':LABELS[kind],'summary':summary,'table':table(out,ids),
            'input':table(before.data,before.ids),'inputs':[{'ref':x.node,'table':table(x.data,x.ids)} for x in srcs],
            'input_refs':[x.node for x in srcs],'output_ref':node,'depends_on':[x.node for x in srcs],
            'params':p,'lineage':lin,'row_sources':rows,'parents':parents or {},'contexts':contexts or {},'removed':removed,
            'related_columns':list(dict.fromkeys(p.get('columns',[])+p.get('keys',[])+list(p.get('formulas',{})))),
            'trace_level':'detailed' if complete else 'common','trace_reason':None if complete else '셀 계보 미지원 또는 이전 공통 추적 단계에서 출처가 끊겼습니다.',
            'code':ast.get_source_segment(self.code,self.stmt),'code_location':{'start':self.stmt.lineno,'end':self.stmt.end_lineno},'statement_index':self.si,
            'operation_expression':ast.get_source_segment(self.code,self.expr),
            'expression_location':{'start':self.expr.lineno,'end':self.expr.end_lineno,'start_column':self.expr.col_offset,'end_column':self.expr.end_col_offset},
            'changes':{'rows':len(out)-len(before.data),'added_columns':[str(c) for c in out if c not in before.data],'removed_columns':[str(c) for c in before.data if c not in out]}})
        if removed:
            self.ops[-1]['removed_lineage']={r['id']:before.lineage.get(r['id'],{}) for r in removed['rows']}
        self.frames[node]=f
        return f

    def col(self,f,c):
        if not isinstance(c,(str,int)) or c not in f.data: raise Unsupported(f'존재하지 않는 열: {c}')
        return Value(f.data[c],{ix:f.lineage[r].get(str(c),[]) for ix,r in zip(f.data.index,f.ids)},
            {ix:[{'step_id':f.node,'row_id':r,'column':str(c)}] for ix,r in zip(f.data.index,f.ids)},{str(c)},str(c),f.complete,nodes={f.node})

    def label(self,x): return x.label if isinstance(x,Value) else f'“{x}”' if isinstance(x,str) else str(x)

    def binary(self,a,b,op,comparison=False):
        av,bv=raw(a),raw(b);vals=[v for v in (a,b) if isinstance(v,Value)]
        if not vals: raise Unsupported('계산에는 입력 열 참조가 필요합니다.')
        if isinstance(av,pd.Series) and isinstance(bv,pd.Series) and not av.index.equals(bv.index): raise Unsupported('다른 인덱스 Series의 산술은 미지원입니다.')
        if not comparison and isinstance(op,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Mod)):
            if any(not (pd.api.types.is_numeric_dtype(v) if isinstance(v,pd.Series) else isinstance(v,(int,float))) for v in (av,bv)): raise Unsupported('산술은 수치형 값만 지원합니다.')
        fn,sym=(CMP if comparison else BIN)[type(op)];data=fn(av,bv);indexes=data.index if isinstance(data,pd.Series) else ['*']
        refs={i:union([r for v in vals for r in v.refs.get(i,v.refs.get('*',[]))]) for i in indexes}
        parents={i:[p for v in vals for p in v.parents.get(i,v.parents.get('*',[]))] for i in indexes}
        label=f'{self.label(a)} {sym} {self.label(b)}';label=label if comparison else '('+label+')'
        tests=[t for v in vals for t in v.tests]+([(label,data)] if comparison else [])
        return Value(data,refs,parents,set().union(*(v.columns for v in vals)),label,all(v.complete for v in vals),tests,nodes=set().union(*(v.nodes for v in vals)))

    def evaluate(self,n):
        if isinstance(n,ast.Constant):
            v=n.value
            if not isinstance(v,(str,int,float,bool,type(None))) or isinstance(v,str) and len(v)>1000: raise Unsupported('미지원 상수')
            if isinstance(v,(int,float)) and (not math.isfinite(v) or abs(v)>1e12): raise Unsupported('상수 범위 초과')
            return v
        if isinstance(n,ast.Name) and n.id in self.env: return self.env[n.id]
        if isinstance(n,(ast.List,ast.Tuple)) and len(n.elts)<=500:
            vals=[self.evaluate(x) for x in n.elts];return tuple(vals) if isinstance(n,ast.Tuple) else vals
        if isinstance(n,ast.Dict) and len(n.keys)<=64 and all(k is not None for k in n.keys): return {self.evaluate(k):self.evaluate(v) for k,v in zip(n.keys,n.values)}
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.Invert,ast.USub)):
            v=self.evaluate(n.operand)
            if isinstance(v,Value): return Value(~v.data if isinstance(n.op,ast.Invert) else -v.data,v.refs,v.parents,v.columns,('¬' if isinstance(n.op,ast.Invert) else '−')+v.label,v.complete,v.tests,nodes=v.nodes)
            if isinstance(n.op,ast.USub) and isinstance(v,(int,float)): return -v
        if isinstance(n,ast.BinOp) and type(n.op) in BIN: return self.binary(self.evaluate(n.left),self.evaluate(n.right),n.op)
        if isinstance(n,ast.Compare) and len(n.ops)==1 and type(n.ops[0]) in CMP: return self.binary(self.evaluate(n.left),self.evaluate(n.comparators[0]),n.ops[0],True)
        if isinstance(n,ast.Subscript):
            if isinstance(n.value,ast.Name) and n.value.id=='tables':
                name=self.evaluate(n.slice)
                if name not in self.roots or name=='input': raise Unsupported('등록되지 않은 추가 입력 표')
                return self.roots[name]
            obj=self.evaluate(n.value);key=self.evaluate(n.slice)
            self.expr=n
            if isinstance(obj,Access) and obj.name=='loc': obj=obj.source
            if isinstance(obj,Frame):
                if isinstance(key,Value):
                    mask=key.data
                    if not isinstance(mask,pd.Series) or not pd.api.types.is_bool_dtype(mask) or not mask.index.equals(obj.data.index): raise Unsupported('같은 입력의 불리언 Series 필터가 필요합니다.')
                    mask=mask.fillna(False);ids=[r for r,k in zip(obj.ids,mask) if k];gone=[r for r,k in zip(obj.ids,mask) if not k]
                    p={'condition':key.label,'columns':sorted(key.columns),'kept':len(ids),'removed':len(gone),'decision_sources':{r:key.refs.get(ix,[]) for ix,r in zip(obj.data.index,obj.ids)},'decisions':{r:{'kept':bool(mask.loc[ix]),'tests':[{'label':t,'passed':clean(v.loc[ix]) if isinstance(v,pd.Series) else clean(v)} for t,v in key.tests]} for ix,r in zip(obj.data.index,obj.ids)}}
                    dependencies=list(dict.fromkeys([obj.node]+sorted(key.nodes)))
                    return self.record([self.frames[n] for n in dependencies],obj.data.loc[mask].copy(),ids,obj.lineage,{r:obj.rows[r] for r in ids},'filter',p,table(obj.data.loc[~mask],gone),complete=obj.complete and key.complete)
                if isinstance(key,list) and key: return self.record([obj],obj.data[key].copy(),obj.ids,obj.lineage,obj.rows,'select',{'columns':list(map(str,key))})
                return self.col(obj,key)
        if isinstance(n,ast.Attribute) and not n.attr.startswith('_'):
            obj=self.evaluate(n.value)
            self.expr=n
            if isinstance(obj,Frame) and n.attr=='loc': return Access(obj,'loc')
            if isinstance(obj,Frame) and n.attr=='T': return self.common([obj],obj.data.T,'transpose',{})
            if isinstance(obj,Value) and n.attr in ('str','dt'): return Access(obj,n.attr)
            if isinstance(obj,Access) and obj.name=='dt' and n.attr in ('year','month','day','dayofweek','quarter','hour'):
                v=obj.source;return Value(getattr(v.data.dt,n.attr),v.refs,v.parents,v.columns,f'{n.attr.upper()}({v.label})',v.complete,nodes=v.nodes)
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute):
            if any(k.arg is None for k in n.keywords): raise Unsupported('가변 키워드 인자는 미지원입니다.')
            args=[self.evaluate(a) for a in n.args];kw={k.arg:self.evaluate(k.value) for k in n.keywords};method=n.func.attr
            if isinstance(n.func.value,ast.Name) and n.func.value.id=='pd':
                self.expr=n
                return self.pandas(method,args,kw)
            obj=self.evaluate(n.func.value)
            self.expr=n
            if isinstance(obj,Frame): return self.frame(obj,method,args,kw)
            if isinstance(obj,Group) and method=='agg': return self.aggregate(obj,args,kw)
            if isinstance(obj,Value): return self.series(obj,method,args,kw)
            if isinstance(obj,Access) and obj.name in ('str','dt'): return self.series(obj.source,method,args,kw,obj.name)
        raise Unsupported('실행 미지원 구문입니다. 허용된 pandas 연산·상수·열 참조만 사용하세요.')

    def arguments(self,method,kw,allowed):
        if allowed is not None and set(kw)-allowed: raise Unsupported(f'{method}: 미지원 인자 {sorted(set(kw)-allowed)}')

    def dtype(self,x):
        allowed={'str','string','int64','int32','Int64','Int32','float64','float32','Float64','boolean','bool','category'}
        if any(v not in allowed for v in (x.values() if isinstance(x,dict) else [x])): raise Unsupported('미지원 dtype입니다.')

    def series(self,v,m,args,kw,access=None):
        allowed=STR if access=='str' else {'strftime':{'date_format'},'floor':{'freq'},'ceil':{'freq'}} if access=='dt' else SERIES
        if m not in allowed: raise Unsupported(f'Series 실행 미지원: {access or ""}.{m}')
        self.arguments(m,kw,allowed[m]);aa=[raw(x) for x in args];kk={k:raw(x) for k,x in kw.items()}
        if access=='str' and m in ('contains','replace','split') and kk.get('regex') is not False: raise Unsupported('패턴 처리에는 regex=False를 명시하세요.')
        if m=='replace' and access is None and kk.get('regex',False): raise Unsupported('정규식 치환 미지원')
        if m=='astype': self.dtype(aa[0] if aa else kk.get('dtype'))
        if m=='split' and kk.get('expand',False): raise Unsupported('split(expand=True) 미지원. 목록 Series와 explode를 사용하세요.')
        data=getattr(getattr(v.data,access) if access else v.data,m)(*aa,**kk)
        if not isinstance(data,pd.Series):
            if m in ('sum','mean','min','max','count'):
                contributors=list(v.data.index[v.data.notna()])
                return Value(data,{'*':union([r for ix in contributors for r in v.refs.get(ix,[])])},
                             {'*':[p for ix in contributors for p in v.parents.get(ix,[])]},v.columns,f'{m.upper()}({v.label})',v.complete,nodes=v.nodes)
            raise Unsupported('미지원 Series 출력 형식')
        extra=[x for x in args+list(kw.values()) if isinstance(x,Value)]
        refs={ix:union(v.refs.get(ix,[])+[r for x in extra if m!='fillna' or pd.isna(v.data.loc[ix]) for r in x.refs.get(ix,x.refs.get('*',[]))]) for ix in data.index}
        parents={ix:v.parents.get(ix,[])+[p for x in extra if m!='fillna' or pd.isna(v.data.loc[ix]) for p in x.parents.get(ix,x.parents.get('*',[]))] for ix in data.index}
        label=f'{m.upper()}({v.label}'+(', '+', '.join(self.label(x) for x in args) if args else '')+('; '+', '.join(f'{k}={self.label(x)}' for k,x in kw.items()) if kw else '')+')'
        tests=list(v.tests)+([(label,data)] if m in ('isin','isna','notna','between','contains','startswith','endswith') else [])
        return Value(data,refs,parents,v.columns|set().union(*(x.columns for x in extra)),label,v.complete and all(x.complete for x in extra),tests,nodes=v.nodes|set().union(*(x.nodes for x in extra)))

    def pandas(self,m,args,kw):
        if m in ('to_numeric','to_datetime') and len(args)==1 and isinstance(args[0],Value):
            v=args[0];self.arguments(m,kw,{'errors','downcast'} if m=='to_numeric' else {'errors','format','dayfirst','yearfirst','utc','unit','origin'})
            data=getattr(pd,m)(v.data,**kw)
            label=f'{m.upper()}({v.label}'+('; '+', '.join(f'{k}={self.label(x)}' for k,x in kw.items()) if kw else '')+')'
            return Value(data,v.refs,v.parents,v.columns,label,v.complete,nodes=v.nodes)
        if m=='merge' and args and isinstance(args[0],Frame): return self.frame(args[0],'merge',args[1:],kw)
        if m=='concat' and len(args)==1 and isinstance(args[0],list) and args[0] and all(isinstance(x,Frame) for x in args[0]):
            self.arguments(m,kw,{'ignore_index','axis','join','sort'})
            if kw.get('axis',0)!=0 or kw.get('ignore_index') is not True: raise Unsupported('concat은 axis=0, ignore_index=True만 지원합니다.')
            frames=args[0];out=pd.concat([f.data for f in frames],**kw);ids=[];lin={};rows={}
            for j,f in enumerate(frames):
                for r in f.ids:
                    rid=f'c{j}:{r}';ids.append(rid);lin[rid]=f.lineage[r];rows[rid]=f.rows[r]
            return self.record(frames,out,ids,lin,rows,'concat',{'columns':list(map(str,out.columns))})
        raise Unsupported(f'pd.{m} 실행 미지원. 생성자·파일·네트워크 접근은 금지됩니다.')

    def rowwise(self,f,out,kind,p=None,rename=None):
        indexes=f.data.index.get_indexer(out.index)
        if any(i<0 for i in indexes): raise Unsupported('행 대응 확인 불가')
        ids=[f.ids[i] for i in indexes];rename=rename or {}
        lin={r:{str(c):f.lineage[r].get(str(rename.get(c,c)),[]) for c in out} for r in ids}
        parents={r:{str(c):[{'step_id':f.node,'row_id':r,'column':str(rename.get(c,c))}] for c in out if rename.get(c,c) in f.data} for r in ids}
        gone=[i for i,r in enumerate(f.ids) if r not in ids]
        removed=table(f.data.iloc[gone],[f.ids[i] for i in gone]) if gone else None
        return self.record([f],out,ids,lin,{r:f.rows[r] for r in ids},kind,p,removed,parents=parents)

    def frame(self,f,m,args,kw):
        if m=='groupby':
            self.arguments(m,kw,{'by','as_index','dropna','sort','observed'})
            if kw.get('as_index') is not False or kw.get('dropna') is not False: raise Unsupported('groupby에 as_index=False, dropna=False를 지정하세요.')
            return Group(f,args,kw)
        if m not in METHODS: raise Unsupported(f'DataFrame 실행 미지원: {m}')
        self.arguments(m,kw,METHODS[m])
        if m=='assign':
            if args or not kw or any(not isinstance(v,Value) or not isinstance(v.data,pd.Series) for v in kw.values()): raise Unsupported('계산 열은 입력에 의존하는 Series이어야 합니다.')
            if any(not v.data.index.equals(f.data.index) for v in kw.values()): raise Unsupported('계산 Series와 입력 행 불일치')
            out=f.data.assign(**{k:v.data for k,v in kw.items()});lin={r:dict(c) for r,c in f.lineage.items()};parents={};forms={}
            for c,v in kw.items():
                forms[c]={'formula':v.label,'sources':sorted(v.columns)}
                for ix,r in zip(f.data.index,f.ids): lin[r][c]=v.refs.get(ix,[]);parents.setdefault(r,{})[c]=v.parents.get(ix,[])
            nodes=list(dict.fromkeys([f.node]+sorted(set().union(*(v.nodes for v in kw.values())))))
            result=self.record([self.frames[n] for n in nodes],out,f.ids,lin,f.rows,'derive',{'formulas':forms,'columns':list(kw)},parents=parents,complete=f.complete and all(v.complete for v in kw.values()))
            self.ops[-1]['depends_on']=list(dict.fromkeys(self.ops[-1]['depends_on']+[p['step_id'] for v in kw.values() for ps in v.parents.values() for p in ps]))
            return result
        if m in ('merge','join'): return self.merge(f,m,args,kw)
        if m=='melt': return self.melt(f,args,kw)
        if m=='explode': return self.explode(f,args,kw)
        if m in ('pivot','pivot_table','transpose'):
            if m=='pivot_table' and kw.get('aggfunc','mean') not in ('sum','mean','min','max','count','size','first','last'): raise Unsupported('미지원 pivot 집계')
            return self.common([f],getattr(f.data,m)(*args,**kw),m,{'columns':list(map(str,f.data.columns)),'arguments':clean({'args':args,**kw})})
        if any(isinstance(x,(Value,Frame,Access)) for x in args+list(kw.values())): raise Unsupported('이 연산에는 리터럴 인자만 허용됩니다.')
        if m=='astype': self.dtype(args[0] if args else kw.get('dtype'))
        if m=='drop' and (args or not kw.get('columns')): raise Unsupported('drop은 columns=... 열 삭제만 지원합니다.')
        if m=='rename' and (args or not isinstance(kw.get('columns'),dict)): raise Unsupported('rename은 columns={...}만 지원합니다.')
        if m=='dropna' and kw.get('axis',0)!=0: raise Unsupported('dropna는 행 제거만 지원합니다.')
        if m=='replace' and kw.get('regex',False): raise Unsupported('정규식 치환 미지원')
        out=getattr(f.data,m)(*args,**kw)
        selected=kw.get('columns') if m in ('rename','drop') else kw.get('subset') if m in ('dropna','drop_duplicates') else (args[0] if args else kw.get('by')) if m=='sort_values' else (args[0] if args else kw.get('dtype')) if m=='astype' else None
        selected=list(selected) if isinstance(selected,dict) else [selected] if isinstance(selected,str) else selected
        p={'columns':list(map(str,selected or f.data.columns)), 'arguments':clean({'args':args,**kw})}
        if m=='reset_index':
            lin={r:{str(c):f.lineage[r].get(str(c),[]) for c in out} for r in f.ids}
            return self.record([f],out,f.ids,lin,f.rows,m,p,complete=f.complete and kw.get('drop',False))
        rename={new:old for old,new in kw.get('columns',{}).items()} if m=='rename' else None
        return self.rowwise(f,out,m,p,rename)

    def aggregate(self,g,args,kw):
        allowed=('sum','mean','min','max','count','size','first','last','nunique')
        if args or not kw or any(not isinstance(v,tuple) or len(v)!=2 or v[1] not in allowed for v in kw.values()): raise Unsupported('이름=(열, 집계명) 집계만 지원합니다.')
        f=g.source;opts=dict(g.kw);keys=g.args[0] if g.args else opts.pop('by',None);keys=[keys] if isinstance(keys,str) else keys
        if not isinstance(keys,list) or not keys or any(k not in f.data for k in keys) or any(k in kw for k in keys): raise Unsupported('그룹 키/출력 열을 확인하세요.')
        out=f.data.groupby(keys,**opts).agg(**kw);ids=[];lin={};rows={};contexts={};parents={}
        for pos in range(len(out)):
            row={c:out[c].iloc[pos] for c in out}
            mask=pd.Series(True,index=f.data.index)
            for k in keys: mask &= f.data[k].isna() if pd.isna(row[k]) else f.data[k].eq(row[k])
            members=[r for r,b in zip(f.ids,mask) if b];rid='g'+digest([clean(row[k]) for k in keys]);ids.append(rid);lin[rid]={};contexts[rid]={};parents[rid]={}
            rows[rid]=sorted({x for r in members for x in f.rows[r]});keyrefs=union([x for r in members for k in keys for x in f.lineage[r][str(k)]])
            for c in out:
                col=c if c in keys else kw[c][0];op='key' if c in keys else kw[c][1]
                contrib=[r for ix,r in zip(f.data.index,f.ids) if r in members and (op in ('key','size') or pd.notna(f.data.loc[ix,col]))]
                if op=='first': contrib=contrib[:1]
                if op=='last': contrib=contrib[-1:]
                lin[rid][str(c)]=union([x for r in contrib for x in f.lineage[r][str(col)]])
                contexts[rid][str(c)]={'group_keys':{str(k):clean(row[k]) for k in keys},'key_sources':keyrefs,'member_rows':members,'operation':op}
                parents[rid][str(c)]=[{'step_id':f.node,'row_id':r,'column':str(col)} for r in contrib]
        return self.record([f],out,ids,lin,rows,'aggregate',{'keys':list(map(str,keys)),'aggregations':{c:{'column':v[0],'operation':v[1]} for c,v in kw.items()}},contexts=contexts,parents=parents)

    def merge(self,left,m,args,kw):
        kw=dict(kw);right=args[0] if args else kw.pop('right' if m=='merge' else 'other',None)
        if not isinstance(right,Frame) or len(args)>1: raise Unsupported('병합 상대는 등록 입력에서 유도된 DataFrame이어야 합니다.')
        if len(left.data)*len(right.data)>1_000_000: raise Unsupported('병합 후보 조합 제한 초과')
        if m=='join': return self.common([left,right],left.data.join(right.data,**kw),'join',{'columns':list(map(str,left.data.columns)),'arguments':clean(kw)})
        if kw.get('how','inner') not in ('inner','left','right','outer'): raise Unsupported('merge는 inner/left/right/outer만 지원합니다.')
        a,b=left.data.copy(),right.data.copy();lm,rm='__trace_left__','__trace_right__'
        if any(x in f for x in (lm,rm) for f in (a,b)): raise Unsupported('예약된 내부 열 이름')
        a[lm]=left.ids;b[rm]=right.ids;keys=kw.get('on')
        if keys is None and 'left_on' not in kw:
            keys=[c for c in left.data if c in right.data]
            if not keys: raise Unsupported('병합 키를 지정하세요.')
            kw['on']=keys
        on=[keys] if isinstance(keys,str) else (keys or []);lk=kw.get('left_on',on);rk=kw.get('right_on',on);lk=[lk] if isinstance(lk,str) else lk;rk=[rk] if isinstance(rk,str) else rk
        out=a.merge(b,**kw);suffixes=kw.get('suffixes',('_x','_y'));overlap=(set(left.data)&set(right.data))-set(on)
        if not isinstance(suffixes,(list,tuple)) or len(suffixes)!=2 or any(not isinstance(x,str) for x in suffixes): raise Unsupported('suffixes에는 문자열 2개를 사용하세요.')
        ids=[];lin={};rows={};contexts={}
        for _,row in out.iterrows():
            l=None if pd.isna(row[lm]) else row[lm];r=None if pd.isna(row[rm]) else row[rm];rid='j'+digest([l,r]);ids.append(rid);lin[rid]={}
            rows[rid]=sorted(set((left.rows[l] if l else [])+(right.rows[r] if r else [])))
            for c in [c for c in out if c not in (lm,rm)]:
                rr=[]
                for f,source,suffix in ((left,l,suffixes[0]),(right,r,suffixes[1])):
                    for old in f.data:
                        if (str(old)+suffix if old in overlap else old)==c and source: rr+=f.lineage[source][str(old)]
                lin[rid][str(c)]=union(rr)
            keyrefs=union(([x for k in lk for x in left.lineage[l][str(k)]] if l else [])+([x for k in rk for x in right.lineage[r][str(k)]] if r else []))
            contexts[rid]={str(c):{'group_keys':{str(k):clean(row[k]) for k in on},'key_sources':keyrefs,'member_rows':[x for x in (l,r) if x],'operation':'merge'} for c in out if c not in (lm,rm)}
        out=out.drop(columns=[lm,rm])
        return self.record([left,right],out,ids,lin,rows,'merge',{'keys':list(map(str,on or lk)),'columns':list(map(str,out.columns)),'how':kw.get('how','inner'),'arguments':clean(kw)},contexts=contexts)

    def melt(self,f,args,kw):
        if args or kw.get('ignore_index',True) is not True: raise Unsupported('melt은 키워드 인자와 ignore_index=True를 사용하세요.')
        kw=dict(kw);iv=kw.get('id_vars',[]);iv=[iv] if isinstance(iv,str) else iv;vv=kw.get('value_vars',[c for c in f.data if c not in iv]);vv=[vv] if isinstance(vv,str) else vv
        marker='__trace_row__'
        if marker in f.data: raise Unsupported('예약 열 이름')
        work=f.data.copy();work[marker]=f.ids;kw.update(id_vars=iv+[marker],value_vars=vv);out=work.melt(**kw);var=kw.get('var_name','variable');val=kw.get('value_name','value');ids=[];lin={};rows={}
        for _,row in out.iterrows():
            origin=row[marker];rid='m'+digest([origin,clean(row[var])]);ids.append(rid);lin[rid]={str(c):f.lineage[origin][str(c)] for c in iv};lin[rid][str(val)]=f.lineage[origin][str(row[var])];lin[rid][str(var)]=[];rows[rid]=f.rows[origin]
        return self.record([f],out.drop(columns=[marker]),ids,lin,rows,'melt',{'keys':list(map(str,iv)),'columns':list(map(str,vv)),'generated_labels':[str(var)],'arguments':{'id_vars':iv,'value_vars':vv,'var_name':var,'value_name':val}})

    def explode(self,f,args,kw):
        if kw.get('ignore_index') is not True: raise Unsupported('explode에는 ignore_index=True가 필요합니다.')
        col=args[0] if args else kw.get('column')
        if isinstance(col,list): raise Unsupported('단일 열 explode만 지원합니다.')
        marker='__trace_row__';work=f.data.copy()
        if marker in work: raise Unsupported('예약 열 이름')
        work[marker]=f.ids;out=work.explode(*args,**kw);ids=[];lin={};rows={};counts={}
        for _,row in out.iterrows():
            origin=row[marker];n=counts.get(origin,0);counts[origin]=n+1;rid=f'e{origin}:{n}';ids.append(rid);lin[rid]=f.lineage[origin];rows[rid]=f.rows[origin]
        return self.record([f],out.drop(columns=[marker]),ids,lin,rows,'explode',{'columns':[str(col)]})

    def common(self,srcs,out,kind,p):
        ids=['u'+digest([kind,clean(ix)]) for ix in out.index]
        return self.record(srcs,out,ids,{}, {r:[] for r in ids},kind,p,complete=False)

    def run(self,code,plan=None):
        if len(code)>30000: raise Unsupported('코드 길이 제한 초과')
        self.code=code;tree=ast.parse(code)
        if not tree.body or len(tree.body)>40 or len(list(ast.walk(tree)))>5000: raise Unsupported('구문 수 제한 초과')
        names=set(self.env)
        statements=tree.body
        if plan and plan.get('preview_only'):
            statements=statements[:max(i for step in plan['steps'] for i in step['statement_indices'])+1]
        for i,stmt in enumerate(statements):
            self.stmt,self.si=stmt,i
            if not isinstance(stmt,ast.Assign) or len(stmt.targets)!=1 or not isinstance(stmt.targets[0],ast.Name): raise Unsupported('직선형 DataFrame 할당문만 지원합니다. import/함수/루프/콜백/직접 셀 변경은 금지됩니다.')
            name=stmt.targets[0].id
            if name in names or name.startswith('_') or name in ('target','target_df','pd','tables'): raise Unsupported('중복되지 않는 새 변수명을 사용하세요.')
            self.expr=stmt.value
            start=len(self.ops);f=self.evaluate(stmt.value)
            if not isinstance(f,Frame): raise Unsupported('각 할당은 DataFrame이어야 합니다.')
            if len(self.ops)==start: f=self.rowwise(f,f.data.copy(),'copy')
            for op in self.ops[start:]: op['output_variable']=name
            self.env[name]=f;names.add(name)
        if not (plan and plan.get('preview_only')) and tree.body[-1].targets[0].id!='result': raise Unsupported('마지막 출력 변수는 result이어야 합니다.')
        return self.ops


def run(code,frame,sources=None,plan=None):
    worker=Interpreter(frame,sources);ops=worker.run(code,plan);f=worker.roots['input']
    root={'id':'input','order':0,'kind':'input','label':'입력','summary':'원본 데이터를 불러옵니다.','table':table(f.data,f.ids),'input':None,'params':{},'lineage':f.lineage,'row_sources':f.rows,'removed':None,'code':'','code_location':None,'trace_level':'detailed'}
    return [root]+ops
