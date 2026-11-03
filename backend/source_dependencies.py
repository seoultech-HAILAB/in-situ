"""Conservative, source-only backward slicing for transformation explanations.

Definitions are read-only context. They never replace the selected expression
or establish runtime cell lineage. No code or data is evaluated here.
"""
import ast
import hashlib
import json
from dataclasses import dataclass, field

VERSION = 'source-dependencies-v1'


def position(node): return node.lineno, node.col_offset


def span(node):
    return {'start':node.lineno,'end':node.end_lineno,'start_column':node.col_offset,'end_column':node.end_col_offset}


def root_name(node):
    while isinstance(node,(ast.Subscript,ast.Attribute)):node=node.value
    return node.id if isinstance(node,ast.Name) else None


def literal(node):
    return node.value if isinstance(node,ast.Constant) else None


@dataclass
class Value:
    kind:str='scalar'
    tables:set=field(default_factory=set)
    originals:list=field(default_factory=list)
    definitions:list=field(default_factory=list)
    operations:list=field(default_factory=list)
    unresolved:set=field(default_factory=set)


def merge(*values):
    out=Value()
    for value in values:
        out.tables.update(value.tables);out.unresolved.update(value.unresolved)
        for attr in ('originals','definitions','operations'):
            for item in getattr(value,attr):
                if item not in getattr(out,attr):getattr(out,attr).append(item)
    return out


class SourceDependencies:
    def __init__(self,code,tree=None,describe=None):
        self.code=code;self.tree=tree or ast.parse(code)
        self.describe=describe
        self.parents={child:node for node in ast.walk(self.tree) for child in ast.iter_child_nodes(node)}
        self.nodes={tuple(span(n).values()):n for n in ast.walk(self.tree) if hasattr(n,'end_lineno') and n.end_lineno is not None}
        self.definitions=[];self.active=set();self.call_bindings={};self.call_limit=None
        self.helpers={n.name:n for n in self.tree.body if isinstance(n,ast.FunctionDef)}
        def scan(nodes,scope=None,conditional=False):
            for node in nodes:
                if isinstance(node,ast.FunctionDef):scan(node.body,node)
                elif isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign)):
                    for target in node.targets if isinstance(node,ast.Assign) else [node.target]:
                        if isinstance(target,ast.Name):key=('name',target.id)
                        elif isinstance(target,ast.Subscript) and isinstance(literal(target.slice),(str,int)):key=('column',root_name(target),str(literal(target.slice)))
                        else:continue
                        self.definitions.append({'key':key,'node':node,'scope':scope,'conditional':conditional})
                elif isinstance(node,(ast.If,ast.For,ast.While,ast.With,ast.Try)):
                    for body in ('body','orelse','finalbody'):
                        scan(getattr(node,body,[]),scope,True)
                    for handler in getattr(node,'handlers',[]):scan(handler.body,scope,True)
        scan(self.tree.body)

    def scope(self,node):
        while node in self.parents:
            node=self.parents[node]
            if isinstance(node,ast.FunctionDef):return node
        return None

    def statement(self,node):
        while node in self.parents and not isinstance(node,ast.stmt):node=self.parents[node]
        return node

    def find(self,key,scope,before):
        matches=[d for d in self.definitions if d['key']==key and d['scope'] is scope and position(d['node'])<before]
        return max(matches,key=lambda d:position(d['node']),default=None)

    def reference(self,definition,value):
        node=definition['node']
        entry={'symbol':definition['key'][1] if definition['key'][0]=='name' else f"{definition['key'][1]}[{definition['key'][2]!r}]",
               'code':ast.get_source_segment(self.code,node),'code_location':span(node),'read_only':True}
        if entry not in value.definitions:value.definitions.append(entry)
        if definition['conditional']:value.unresolved.add(entry['symbol']+' (조건부 정의)')
        return value

    def definition(self,definition):
        node=definition['node'];token=(id(node),definition['key'])
        if token in self.active:return Value(unresolved={definition['key'][1]})
        self.active.add(token)
        try:
            result=self.resolve(node.value,definition['scope'],position(node))
            if isinstance(node,ast.AugAssign):
                result=merge(self.resolve(node.target,definition['scope'],position(node)),result)
                result.operations.append('앞선 값에 현재 계산을 적용합니다.')
            return self.reference(definition,result)
        finally:self.active.remove(token)

    def resolve(self,node,scope,before):
        if node is None:return Value()
        if isinstance(node,(ast.Assign,ast.AnnAssign,ast.keyword)):
            return self.resolve(node.value,scope,before)
        if isinstance(node,ast.AugAssign):
            return merge(self.resolve(node.target,scope,before),self.resolve(node.value,scope,before))
        if isinstance(node,ast.Name):
            if node.id=='input_df':return Value(kind='frame',tables={'input_df'})
            found=self.find(('name',node.id),scope,before)
            if found:return self.definition(found)
            if scope is not None:
                binding=self.call_bindings.get((id(scope),node.id))
                if binding:return self.resolve(*binding)
                local=any(d['scope'] is scope and d['key']==('name',node.id) for d in self.definitions)
                if local or node.id in {a.arg for a in scope.args.args}:return Value(unresolved={node.id})
                found=self.find(('name',node.id),None,self.call_limit or before)
                if found:return self.definition(found)
            if node.id in ('pd','np','str','int','float','bool','None','True','False','tables','math','re'):return Value()
            if node.id in self.helpers:
                helper=self.helpers[node.id]
                value=Value(unresolved={node.id+' (함수 내부 경로)'})
                return self.reference({'key':('name',node.id),'node':helper,'conditional':False},value)
            return Value(unresolved={node.id})
        if isinstance(node,ast.Subscript):
            if isinstance(node.value,ast.Name) and node.value.id=='tables' and isinstance(literal(node.slice),str):
                return Value(kind='frame',tables={f"tables[{literal(node.slice)!r}]"})
            name=root_name(node.value);column=literal(node.slice)
            if name and isinstance(column,(str,int)):
                changed=self.find(('column',name,str(column)),scope,before)
                binding=self.find(('name',name),scope,before)
                if changed and (binding is None or position(changed['node'])>position(binding['node'])):
                    resolved=self.definition(changed)
                    if binding:
                        out=merge(self.definition(binding),resolved);out.kind=resolved.kind;return out
                    return resolved
                if binding:
                    source=binding['node'].value;parent=None;original_column=column
                    if isinstance(source,ast.Name):parent=source
                    elif isinstance(source,ast.Subscript) and isinstance(source.slice,(ast.List,ast.Tuple)):
                        if column in [literal(c) for c in source.slice.elts]:parent=source.value
                    elif isinstance(source,ast.Call) and isinstance(source.func,ast.Attribute):
                        if source.func.attr in ('copy','rename','assign'):parent=source.func.value
                        if source.func.attr=='assign':
                            kw=next((k for k in source.keywords if k.arg==str(column)),None)
                            if kw:
                                resolved=self.resolve(kw.value,binding['scope'],position(binding['node']))
                                return self.reference(binding,resolved)
                        if source.func.attr=='rename':
                            mapping=next((k.value for k in source.keywords if k.arg=='columns'),None)
                            if isinstance(mapping,ast.Dict):
                                original_column=next((literal(k) for k,v in zip(mapping.keys,mapping.values) if literal(v)==column),column)
                    if parent is not None:
                        selected=ast.Subscript(value=parent,slice=ast.Constant(original_column),ctx=ast.Load())
                        resolved=self.resolve(selected,binding['scope'],position(binding['node']))
                        return self.reference(binding,resolved)
            base=self.resolve(node.value,scope,before)
            if base.kind=='parts' and isinstance(column,int):
                base.operations.append(f'{ {0:"첫 번째",1:"두 번째",2:"세 번째"}.get(column,str(column+1)+"번째") } 분할 부분을 선택합니다.')
                base.kind='series';return base
            if base.kind=='frame' and isinstance(column,(str,int)):
                base.originals.extend((table,str(column)) for table in sorted(base.tables) if (table,str(column)) not in base.originals)
                base.kind='series';return base
            if base.kind=='frame' and isinstance(node.slice,(ast.List,ast.Tuple)):
                base.originals.extend((table,str(literal(c))) for table in sorted(base.tables) for c in node.slice.elts if literal(c) is not None and (table,str(literal(c))) not in base.originals)
                return base
            return base
        if isinstance(node,ast.Attribute):
            base=self.resolve(node.value,scope,before)
            if base.kind=='frame' and node.attr not in ('str','dt','columns','index','loc','iloc'):
                base.originals.extend((table,node.attr) for table in sorted(base.tables) if (table,node.attr) not in base.originals)
                base.kind='series'
            return base
        if isinstance(node,ast.Call):
            method=node.func.attr if isinstance(node.func,ast.Attribute) else node.func.id if isinstance(node.func,ast.Name) else ''
            if isinstance(node.func,ast.Name) and method in self.helpers:
                helper=self.helpers[method];token=('helper',id(helper))
                ref={'key':('name',method),'node':helper,'conditional':False}
                returns=[r for r in ast.walk(helper) if isinstance(r,ast.Return)]
                if token in self.active or len(returns)!=1 or returns[0] not in helper.body or position(helper)>=(self.call_limit or before):
                    return self.reference(ref,Value(unresolved={method+' (반환 경로)'}))
                previous_bindings=self.call_bindings.copy();previous_limit=self.call_limit
                self.active.add(token)
                try:
                    for parameter,arg in zip(helper.args.args,node.args):self.call_bindings[(id(helper),parameter.arg)]=(arg,scope,before)
                    for kw in node.keywords:
                        if kw.arg:self.call_bindings[(id(helper),kw.arg)]=(kw.value,scope,before)
                    self.call_limit=self.call_limit or before
                    resolved=self.resolve(returns[0].value,helper,position(returns[0]))
                    return self.reference(ref,resolved)
                finally:
                    self.call_bindings=previous_bindings;self.call_limit=previous_limit;self.active.remove(token)
            base=self.resolve(node.func.value,scope,before) if isinstance(node.func,ast.Attribute) else Value()
            args=[self.resolve(arg,scope,before) for arg in node.args if not isinstance(arg,ast.Lambda)]
            args += [self.resolve(kw.value,scope,before) for kw in node.keywords if not isinstance(kw.value,ast.Lambda)]
            value=merge(base,*args);value.kind=base.kind if base.kind!='scalar' else next((arg.kind for arg in args if arg.kind!='scalar'),'scalar')
            if method=='copy':return value
            if method=='split':
                sep=literal(node.args[0]) if node.args else next((literal(k.value) for k in node.keywords if k.arg=='pat'),None)
                count=next((literal(k.value) for k in node.keywords if k.arg=='n'),None)
                value.operations.append(f'{repr(sep) if sep is not None else "공백"}을 기준으로'+(f' 최대 {count}회' if isinstance(count,int) and count>0 else '')+' 나눕니다.')
                value.kind='parts'
            elif method in ('strip','lstrip','rstrip'):
                chars=literal(node.args[0]) if node.args else None
                value.operations.append(f'{ {"strip":"양끝","lstrip":"왼쪽","rstrip":"오른쪽"}[method] }의 {repr(chars) if chars is not None else "공백"}을 제거합니다.')
            elif method in ('astype','to_numeric','to_datetime'):
                dtype=ast.unparse(node.args[0]) if node.args else ''
                dtype={'str':'문자열','int':'정수','float':'실수'}.get(dtype,dtype or '지정한 자료형')
                if method=='to_numeric':dtype='숫자'
                if method=='to_datetime':dtype='날짜·시간'
                value.operations.append(f'{dtype} 형식으로 변환합니다.')
            elif method in ('lower','upper','title','casefold'):
                value.operations.append({'lower':'소문자로 바꿉니다.','upper':'대문자로 바꿉니다.','title':'단어의 첫 글자를 대문자로 바꿉니다.','casefold':'대소문자를 구분하지 않는 형태로 바꿉니다.'}[method])
            elif method=='get' and base.kind=='parts' and node.args and isinstance(literal(node.args[0]),int):
                part=literal(node.args[0]);value.operations.append(f'{ {0:"첫 번째",1:"두 번째",2:"세 번째"}.get(part,str(part+1)+"번째") } 분할 부분을 선택합니다.')
                value.kind='series'
            elif self.describe:
                value.operations.append(self.describe(method,node))
            return value
        if isinstance(node,ast.Lambda):return Value()
        return merge(*(self.resolve(child,scope,before) for child in ast.iter_child_nodes(node)))

    def context(self,item):
        loc=item['code_location'];key=tuple(loc[k] for k in ('start','end','start_column','end_column'))
        node=self.nodes.get(key)
        if node is None:return {'version':VERSION,'original_columns':[],'definitions':[],'complete':False,'unresolved':['코드 위치'],'text':item['description']['text']}
        self.call_bindings={};self.call_limit=None
        call_loc=item.get('call_location')
        if call_loc:
            call=self.nodes.get(tuple(call_loc[k] for k in ('start','end','start_column','end_column')))
            helper=self.scope(node)
            if isinstance(call,ast.Call) and helper:
                limit=position(self.statement(call));self.call_limit=limit
                for param,arg in zip(helper.args.args,call.args):self.call_bindings[(id(helper),param.arg)]=(arg,self.scope(call),limit)
                for kw in call.keywords:
                    if kw.arg:self.call_bindings[(id(helper),kw.arg)]=(kw.value,self.scope(call),limit)
        value=self.resolve(node,self.scope(node),position(self.statement(node)))
        definitions=sorted(value.definitions,key=lambda d:(d['code_location']['start'],d['code_location']['start_column']))
        # A definition surrounding the selected expression is the edit target,
        # not an upstream reference. Do not relabel it as read-only context.
        definitions=[d for d in definitions if not ((d['code_location']['start'],d['code_location']['start_column']) <= (loc['start'],loc['start_column']) and (d['code_location']['end'],d['code_location']['end_column']) >= (loc['end'],loc['end_column']))]
        origins=[{'table':table,'column':column} for table,column in value.originals]
        steps=list(dict.fromkeys(value.operations))
        text=('원본 '+', '.join(f'“{x["column"]}” 열' for x in origins)+'에서 시작합니다. ') if origins else ''
        text+=' '.join(steps)
        if not steps:text+=item['description']['text']
        if item['output_columns']:text+=' 이 결과로 '+', '.join(f'“{c}”' for c in item['output_columns'])+' 열을 만듭니다.'
        result={'version':VERSION,'original_columns':origins,'definitions':definitions,'operations':steps,'complete':bool(origins) and not value.unresolved,'unresolved':sorted(value.unresolved),'text':text}
        result['fingerprint']=hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        return result
