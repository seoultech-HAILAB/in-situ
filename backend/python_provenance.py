"""Optional pandas provenance replay, verified against independent native execution.

This does not generate or repair programs. Unsupported expressions raise and the
native runner invalidates only affected bindings; no value matching infers origin.
"""
import ast
import copy
from dataclasses import dataclass

import pandas as pd

from .runtime import Interpreter,Frame,Value,Access,Group,Unsupported,raw,union,table,digest,clean


@dataclass
class SelectedGroup(Group):
    column: object=None


def plain(x):
    if isinstance(x,(Value,Frame)):return x.data
    if isinstance(x,dict):return {k:plain(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return type(x)(plain(v) for v in x)
    return x


def origin_namespace(frames):
    return sorted({ref.get('table_id','input') for f in frames for cols in f.lineage.values() for refs in cols.values() for ref in refs})


class ProvenanceInterpreter(Interpreter):
    def record(self,srcs,out,ids,lin,rows,kind,p=None,removed=None,contexts=None,parents=None,complete=None):
        # Selection, ordering and renaming preserve the already observed group
        # context through explicit row IDs/parent columns, never value equality.
        if contexts is None and kind in ('copy','select','filter','sort_values','rename','drop','dropna','drop_duplicates','reset_index'):
            prior={op['id']:op.get('contexts',{}) for op in self.ops};contexts={}
            for rid in ids:
                for col in out:
                    refs=(parents or {}).get(rid,{}).get(str(col),[])
                    if not refs and rid in srcs[0].ids and col in srcs[0].data:
                        refs=[{'step_id':srcs[0].node,'row_id':rid,'column':str(col)}]
                    if len(refs)==1:
                        ref=refs[0];context=prior.get(ref['step_id'],{}).get(ref['row_id'],{}).get(ref['column'])
                        if context:contexts.setdefault(rid,{})[str(col)]=copy.deepcopy(context)
        return super().record(srcs,out,ids,lin,rows,kind,p,removed,contexts,parents,complete)

    def dtype(self,x):
        if not isinstance(x,dict) and x in (str,int,float,bool,object):return
        return super().dtype(x)

    def bind(self,name,value):
        old=self.env.get(name)
        if isinstance(old,Frame) and isinstance(value,Frame):
            # Assignment to a name rebinds only that name. In-place writes use mutate.
            self.env[name]=value
        else:self.env[name]=value

    def mutate(self,old,new):
        for key,value in list(self.env.items()):
            if value is old:self.env[key]=new
        for key,value in list(self.roots.items()):
            if value is old:self.roots[key]=new

    def statement(self,node,index):
        self.stmt,self.si,self.expr=node,index,getattr(node,'value',node)
        if isinstance(node,(ast.Import,ast.ImportFrom)):return
        if not isinstance(node,ast.Assign) or len(node.targets)!=1:raise Unsupported('이 구문의 상세 추적은 미지원')
        target=node.targets[0];value=self.evaluate(node.value)
        if isinstance(target,ast.Name):self.bind(target.id,value);return
        if isinstance(target,ast.Subscript) and isinstance(target.value,ast.Name):
            f=self.env.get(target.value.id);column=self.evaluate(target.slice)
            if not isinstance(f,Frame) or not isinstance(column,(str,int)) or not isinstance(value,Value):raise Unsupported('열 할당의 출처 미확인')
            result=self.frame(f,'assign',[],{column:value});self.mutate(f,result);return
        if isinstance(target,ast.Attribute) and target.attr=='columns' and isinstance(target.value,ast.Name):
            f=self.env.get(target.value.id)
            if not isinstance(f,Frame) or not isinstance(value,list) or len(value)!=len(f.data.columns):raise Unsupported('열 이름 변경의 대응 미확인')
            out=f.data.copy();out.columns=value
            result=self.rowwise(f,out,'rename',{'columns':list(map(str,value))},dict(zip(value,f.data.columns)))
            self.mutate(f,result);return
        raise Unsupported('이 할당의 상세 추적은 미지원')

    def evaluate(self,n):
        if isinstance(n,ast.Name) and n.id in ('str','int','float','bool','object'):return {'str':str,'int':int,'float':float,'bool':bool,'object':object}[n.id]
        if isinstance(n,ast.Attribute) and n.attr in ('columns','index'):
            obj=self.evaluate(n.value)
            if isinstance(obj,Frame):return list(obj.data.columns) if n.attr=='columns' else obj.data.index
        if isinstance(n,ast.Subscript):
            obj=self.evaluate(n.value) if not (isinstance(n.value,ast.Name) and n.value.id=='tables') else None
            if isinstance(obj,Group):return SelectedGroup(obj.source,obj.args,obj.kw,self.evaluate(n.slice))
            if isinstance(obj,Access) and obj.name=='str':return self.series(obj.source,'get',[self.evaluate(n.slice)],{},'str')
            if isinstance(obj,Access) and obj.name=='loc' and isinstance(n.slice,ast.Tuple) and len(n.slice.elts)==2:
                row,col=n.slice.elts
                filtered=self.evaluate(ast.copy_location(ast.Subscript(value=n.value.value,slice=row,ctx=ast.Load()),n))
                columns=self.evaluate(col);self.expr=n
                if isinstance(columns,list):return self.record([filtered],filtered.data[columns].copy(),filtered.ids,filtered.lineage,filtered.rows,'select',{'columns':list(map(str,columns))})
                return self.col(filtered,columns)
        if isinstance(n,ast.Call):
            if isinstance(n.func,ast.Name) and n.func.id in ('len','int','float'):
                if len(n.args)!=1 or n.keywords:raise Unsupported('미지원 스칼라 호출')
                obj=self.evaluate(n.args[0])
                if n.func.id=='len' and isinstance(obj,Frame):
                    v=Value(len(obj.data),{'*':[]},{'*':[]},set(),'행 수',obj.complete,nodes={obj.node})
                    v.row_members=list(obj.ids);v.row_context={'group_keys':{},'key_sources':[],'member_rows':list(obj.ids),'operation':'size'}
                    return v
                if isinstance(obj,Value):
                    value=copy.copy(obj);value.data={'int':int,'float':float,'len':len}[n.func.id](obj.data);return value
            if isinstance(n.func,ast.Attribute):
                args=[self.evaluate(a) for a in n.args];kw={}
                for k in n.keywords:
                    v=self.evaluate(k.value)
                    if k.arg is None:
                        if not isinstance(v,dict):raise Unsupported('동적 키워드 출처 미확인')
                        kw.update(v)
                    else:kw[k.arg]=v
                m=n.func.attr;self.expr=n
                if isinstance(n.func.value,ast.Name) and n.func.value.id=='pd':
                    if m=='DataFrame':return self.constructor(args,kw)
                    return self.pandas(m,args,kw)
                obj=self.evaluate(n.func.value);self.expr=n
                if isinstance(obj,Group):return self.group_operation(obj,m,args,kw)
                if isinstance(obj,Frame):return self.frame(obj,m,args,kw)
                if isinstance(obj,Value):return self.series(obj,m,args,kw)
                if isinstance(obj,Access) and obj.name in ('str','dt'):return self.series(obj.source,m,args,kw,obj.name)
        return super().evaluate(n)

    def frame(self,f,m,args,kw):
        if m=='groupby':
            self.arguments(m,kw,{'by','as_index','dropna','sort','observed'})
            return Group(f,args,kw)
        if m=='join':
            other=args[0] if args else kw.get('other')
            if isinstance(other,Value) and isinstance(other.data,pd.Series):other=self.series_frame(other)
            return self.join(f,other,{k:v for k,v in kw.items() if k!='other'})
        result=super().frame(f,m,args,kw)
        if m=='assign' and isinstance(result,Frame):
            op=self.ops[-1]
            for column,v in kw.items():
                for ix,r in zip(result.data.index,result.ids):
                    context=getattr(v,'contexts',{}).get(ix,getattr(v,'row_context',None))
                    if context:op['contexts'].setdefault(r,{})[str(column)]=context
            result.rows={r:sorted(set(f.rows.get(r,[])+[ref['row_id'] for refs in result.lineage[r].values() for ref in refs])) for r in result.ids}
            op['row_sources']=result.rows
        return result

    def series(self,v,m,args,kw,access=None):
        if access=='str' and m in ('extract','casefold','split','replace','contains'):
            data=getattr(v.data.str,m)(*plain(args),**plain(kw))
            if isinstance(data,pd.Series):return Value(data,v.refs,v.parents,v.columns,f'{m.upper()}({v.label})',v.complete,nodes=v.nodes)
            sources=[self.frames[node] for node in sorted(v.nodes)];origin=sources[0]
            if not origin.data.index.is_unique or not data.index.isin(origin.data.index).all():raise Unsupported('문자열 결과의 행 대응 미확인')
            ids=[origin.ids[origin.data.index.get_loc(ix)] for ix in data.index]
            lin={r:{str(c):v.refs.get(ix,[]) for c in data} for ix,r in zip(data.index,ids)}
            parents={r:{str(c):v.parents.get(ix,[]) for c in data} for ix,r in zip(data.index,ids)}
            return self.record(sources,data,ids,lin,{r:sorted({x['row_id'] for x in v.refs.get(ix,[])}) for ix,r in zip(data.index,ids)},'derive',{'columns':list(map(str,data.columns)),'formulas':{str(c):{'formula':f'{m.upper()}({v.label})[{c}]','sources':sorted(v.columns)} for c in data}},parents=parents,complete=v.complete)
        comparisons={'eq':ast.Eq,'ne':ast.NotEq,'gt':ast.Gt,'ge':ast.GtE,'lt':ast.Lt,'le':ast.LtE}
        if access is None and m in comparisons and len(args)==1 and not kw:return self.binary(v,args[0],comparisons[m](),True)
        if access is None and m=='map' and len(args)==1:
            mapper=args[0]
            if not isinstance(mapper,(dict,Value)):raise Unsupported('콜백 map의 출처 미확인')
            data=v.data.map(raw(mapper),**kw);refs={};parents={};contexts={}
            for ix,key in v.data.items():
                exists=isinstance(mapper,Value) and key in mapper.data.index
                refs[ix]=union(v.refs.get(ix,[])+(mapper.refs.get(key,[]) if exists else []))
                parents[ix]=v.parents.get(ix,[])+(mapper.parents.get(key,[]) if exists else [])
                if exists and key in getattr(mapper,'contexts',{}):contexts[ix]=mapper.contexts[key]
            result=Value(data,refs,parents,v.columns|(mapper.columns if isinstance(mapper,Value) else set()),f'MAP({v.label})',v.complete and (mapper.complete if isinstance(mapper,Value) else True),nodes=v.nodes|(mapper.nodes if isinstance(mapper,Value) else set()))
            result.contexts=contexts;return result
        if access is None and m in ('rename','drop_duplicates','combine_first'):
            data=getattr(v.data,m)(*plain(args),**plain(kw));refs={};parents={}
            for ix in data.index:
                other=args[0] if m=='combine_first' else None
                selected=other if isinstance(other,Value) and pd.isna(v.data.loc[ix]) else v
                refs[ix]=selected.refs.get(ix,[]);parents[ix]=selected.parents.get(ix,[])
            result=Value(data,refs,parents,v.columns,v.label,v.complete and all(not isinstance(x,Value) or x.complete for x in args),nodes=v.nodes|set().union(*(x.nodes for x in args if isinstance(x,Value))))
        elif access is None and m in ('reset_index','to_frame'):
            f=self.series_frame(v);out=getattr(v.data,m)(*plain(args),**plain(kw));lin={};parents={}
            if not isinstance(out,pd.DataFrame):raise Unsupported('Series 출력 형식 미지원')
            for ix,r in zip(v.data.index,f.ids):
                lin[r]={str(c):getattr(v,'index_refs',{}).get(ix,{}).get(c,v.refs.get(ix,[]) if c not in getattr(v,'index_columns',[]) else []) for c in out}
                parents[r]={str(c):v.parents.get(ix,[]) for c in out}
            return self.record([f],out,f.ids,lin,f.rows,'reset_index',{'columns':list(map(str,out.columns))},parents=parents,complete=v.complete)
        else:result=super().series(v,m,args,kw,access)
        if isinstance(result,Value):
            for attr in ('contexts','index_refs','index_columns','row_members','row_context'):
                if hasattr(v,attr):setattr(result,attr,getattr(v,attr))
        return result

    def group_operation(self,g,m,args,kw):
        if m=='agg':
            if args or not kw:raise Unsupported('이름을 지정한 집계만 상세 추적')
            # The existing aggregate adapter requires explicit output keys; add
            # pandas defaults only to this replay, retaining native group behavior.
            opts={**g.kw,'as_index':False};opts.setdefault('dropna',True)
            return super().aggregate(Group(g.source,g.args,opts),[],kw)
        if m not in ('size','count','sum','mean','min','max') or args:raise Unsupported('미지원 그룹 집계 추적')
        f=g.source;keys=g.args[0] if g.args else g.kw.get('by');keys=[keys] if isinstance(keys,str) else keys
        if not keys or any(key not in f.data for key in keys):raise Unsupported('그룹 키 출처 미확인')
        gb=f.data.groupby(*g.args,**g.kw)
        column=getattr(g,'column',None)
        if column is not None:gb=gb[column]
        data=getattr(gb,m)(**kw)
        returned_frame=isinstance(data,pd.DataFrame)
        observed=data
        if returned_frame:
            if not isinstance(column,str) or column not in data or any(key not in data for key in keys):
                raise Unsupported('이 그룹 출력 형식은 공통 관찰')
            data=data.set_index(keys)[column]
        if not isinstance(data,pd.Series):raise Unsupported('이 그룹 출력 형식은 공통 관찰')
        out=observed if returned_frame else data.to_frame();value_column=str(column) if returned_frame else str(out.columns[0]);ids=[];lin={};rows={};contexts={};index_refs={};parents={}
        for ix in data.index:
            values=ix if isinstance(ix,tuple) else (ix,);mask=pd.Series(True,index=f.data.index)
            for key,value in zip(keys,values):mask &= f.data[key].isna() if pd.isna(value) else f.data[key].eq(value)
            members=[r for r,keep in zip(f.ids,mask) if keep];rid='g'+digest([origin_namespace([f]),keys,clean(ix)]);ids.append(rid)
            keyrefs={key:union([ref for r in members for ref in f.lineage[r].get(str(key),[])]) for key in keys}
            used=members if m=='size' else [r for r,keep,value in zip(f.ids,mask,f.data[column]) if keep and pd.notna(value)]
            refs=union([ref for refs in keyrefs.values() for ref in refs]) if m=='size' else union([ref for r in used for ref in f.lineage[r].get(str(column),[])])
            context={'group_keys':dict(zip(map(str,keys),map(clean,values))),'key_sources':union([ref for refs in keyrefs.values() for ref in refs]),'member_rows':members,'operation':m}
            lin[rid]={value_column:refs};rows[rid]=sorted({root for r in members for root in f.rows[r]});contexts[rid]={value_column:context};index_refs[ix]=keyrefs
            parents[rid]={value_column:[{'step_id':f.node,'row_id':r,'column':str(key)} for r in used for key in (keys if m=='size' else [column])]}
            if returned_frame:
                for key in keys:
                    lin[rid][str(key)]=keyrefs[key]
                    parents[rid][str(key)]=[{'step_id':f.node,'row_id':r,'column':str(key)} for r in members]
        result=self.record([f],out,ids,lin,rows,'aggregate',{'keys':list(map(str,keys)),'aggregations':{value_column:{'column':'*' if m=='size' else str(column),'operation':m}}},contexts=contexts,parents=parents)
        if returned_frame:return result
        v=Value(data,{ix:lin[r][str(out.columns[0])] for ix,r in zip(data.index,ids)},{ix:[{'step_id':result.node,'row_id':r,'column':str(out.columns[0])}] for ix,r in zip(data.index,ids)},set(map(str,keys))|({str(column)} if column is not None else set()),f'{m.upper()}({column or "*"})',f.complete,nodes={result.node})
        v.contexts={ix:contexts[r][str(out.columns[0])] for ix,r in zip(data.index,ids)};v.index_refs=index_refs;v.index_columns=keys
        return v

    def series_frame(self,v):
        out=v.data.to_frame();sources=[self.frames[n] for n in sorted(v.nodes)]
        if not sources:raise Unsupported('Series 입력 출처 미확인')
        ids=['v'+digest([origin_namespace(sources),clean(ix)]) for ix in out.index]
        result=self.record(sources,out,ids,{r:{str(out.columns[0]):v.refs.get(ix,[])} for ix,r in zip(out.index,ids)},
            {r:sorted({x['row_id'] for x in v.refs.get(ix,[])}) for ix,r in zip(out.index,ids)},'select',{'columns':list(map(str,out.columns))},complete=v.complete)
        return result

    def join(self,left,right,kw):
        if not isinstance(right,Frame):raise Unsupported('join 상대 출처 미확인')
        lm,rm='__trace_left__','__trace_right__'
        if any(marker in f.data for f in (left,right) for marker in (lm,rm)):raise Unsupported('추적 예약 열 충돌')
        a,b=left.data.copy(),right.data.copy();a[lm]=left.ids;b[rm]=right.ids
        marked=a.join(b,**kw);out=marked.drop(columns=[lm,rm]);ids=[];lin={};rows={};keys=kw.get('on',[]);keys=[keys] if isinstance(keys,str) else keys
        for _,row in marked.iterrows():
            l=None if pd.isna(row[lm]) else row[lm];r=None if pd.isna(row[rm]) else row[rm];rid='j'+digest([l,r]);ids.append(rid);lin[rid]={}
            rows[rid]=sorted(set((left.rows[l] if l else [])+(right.rows[r] if r else [])))
            for col in out:
                refs=[]
                for f,origin,suffix in ((left,l,kw.get('lsuffix','')),(right,r,kw.get('rsuffix',''))):
                    for old in f.data:
                        displayed=str(old)+suffix if old in left.data and old in right.data else old
                        if displayed==col and origin:refs+=f.lineage[origin].get(str(old),[])
                lin[rid][str(col)]=union(refs)
        return self.record([left,right],out,ids,lin,rows,'join',{'keys':keys,'columns':list(map(str,out.columns)),'how':kw.get('how','left')})

    def constructor(self,args,kw):
        if len(args)!=1 or kw:raise Unsupported('이 생성자 형식의 상세 추적은 미지원')
        data=args[0];out=pd.DataFrame(plain(data));vals=[]
        def collect(x):
            if isinstance(x,Value):vals.append(x)
            elif isinstance(x,dict):
                for v in x.values():collect(v)
            elif isinstance(x,(tuple,list)):
                for v in x:collect(v)
        collect(data)
        nodes=sorted(set().union(*(v.nodes for v in vals)))
        if not nodes:raise Unsupported('생성자의 데이터 출처 미확인')
        sources=[self.frames[n] for n in nodes];ids=['d'+digest([origin_namespace(sources),clean(ix)]) for ix in out.index];lin={};parents={};contexts={};rows={}
        for pos,(ix,r) in enumerate(zip(out.index,ids)):
            lin[r]={};parents[r]={};contexts[r]={};members=[]
            for col in out:
                value=data[col] if isinstance(data,dict) else data[pos][col] if isinstance(data,list) and isinstance(data[pos],dict) else None
                if isinstance(value,list):value=value[pos]
                if isinstance(value,Value):
                    key=ix if isinstance(value.data,pd.Series) else '*';lin[r][str(col)]=value.refs.get(key,[]);parents[r][str(col)]=value.parents.get(key,[])
                    if hasattr(value,'row_context'):contexts[r][str(col)]=value.row_context
                    members+=getattr(value,'row_members',[])
                else:lin[r][str(col)]=[]
            rows[r]=sorted(set(members+[ref['row_id'] for refs in lin[r].values() for ref in refs]))
        return self.record(sources,out,ids,lin,rows,'derive',{'columns':list(map(str,out.columns)),'formulas':{str(c):{'formula':'입력 기반 값 구성','sources':sorted(set().union(*(v.columns for v in vals)))} for c in out}},contexts=contexts,parents=parents,complete=all(v.complete for v in vals))
