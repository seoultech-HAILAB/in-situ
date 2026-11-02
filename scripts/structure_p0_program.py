"""Observation-only restructuring for a restricted straight-line transform function.

No column names, values, predicates, cleaning rules or expected answers are supplied.
Callers MUST differentially verify the result against the unmodified program.
"""
import ast
import copy
from collections import Counter


def structure(program,table_count):
    module=ast.parse(program)
    entries=[n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='transform']
    if len(entries)!=1:raise ValueError('Expected one transform entry')
    entry=entries[0]
    if len(entry.args.args)!=1 or entry.args.vararg or entry.args.kwarg or entry.args.defaults or entry.args.kwonlyargs or entry.decorator_list:
        raise ValueError('Unsupported entry signature')
    if any(not isinstance(n,(ast.Import,ast.ImportFrom,ast.FunctionDef)) or isinstance(n,ast.FunctionDef) and n is not entry for n in module.body):
        raise ValueError('Only imports and one entry function can be lifted')
    body=copy.deepcopy(entry.body)
    body=[n for n in body if not isinstance(n,ast.Expr) or not isinstance(n.value,ast.Constant) or not isinstance(n.value.value,str)]
    if not body or not isinstance(body[-1],ast.Return) or any(not isinstance(n,(ast.Assign,ast.Return)) for n in body):
        raise ValueError('Only straight-line assignments followed by one return can be lifted')
    if any(isinstance(n,ast.Return) for n in body[:-1]):raise ValueError('Early return is unsupported')
    if any(isinstance(n,(ast.Lambda,ast.ListComp,ast.DictComp,ast.SetComp,ast.GeneratorExp,ast.NamedExpr)) for s in body for n in ast.walk(s)):
        raise ValueError('Scoped expressions require original-function observation')
    if any(isinstance(n,ast.Assign) and (len(n.targets)!=1 or not isinstance(n.targets[0],ast.Name)) for n in body):
        raise ValueError('In-place column or tuple assignment requires original-function observation')
    if any(isinstance(n,ast.keyword) and n.arg=='inplace' and isinstance(n.value,ast.Constant) and n.value.value is True for s in body for n in ast.walk(s)):
        raise ValueError('In-place operations cannot be safely renamed')

    # Move a single-use boolean temporary into its immediately following consumer.
    uses=Counter(n.id for s in body for n in ast.walk(s) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load))
    i=0
    while i<len(body)-1:
        s=body[i]
        if isinstance(s,ast.Assign) and isinstance(s.value,(ast.BinOp,ast.BoolOp,ast.Compare,ast.UnaryOp)):
            name=s.targets[0].id
            if uses[name]==1 and any(isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load) and n.id==name for n in ast.walk(body[i+1])):
                class Inline(ast.NodeTransformer):
                    def visit_Name(self,node):
                        return copy.deepcopy(s.value) if isinstance(node.ctx,ast.Load) and node.id==name else node
                body[i+1]=Inline().visit(body[i+1]);body.pop(i);continue
        i+=1

    formal=entry.args.args[0].arg
    renamed={};counts=Counter();emitted=[];mapping=[]
    used={n.id for n in ast.walk(module) if isinstance(n,ast.Name)}
    def fresh(base):
        while True:
            counts[base]+=1;name=f'p0_{base}_{counts[base]}'
            if name not in used:used.add(name);return name
    def emit(name,value,source):
        node=ast.copy_location(ast.Assign(targets=[ast.Name(id=name,ctx=ast.Store())],value=value),source)
        emitted.append(node)
        starts=[n.lineno for n in ast.walk(source) if hasattr(n,'lineno')]
        ends=[getattr(n,'end_lineno',n.lineno) for n in ast.walk(source) if hasattr(n,'lineno')]
        mapping.append({'statement_index':len(emitted)-1,'source_start':min(starts),'source_end':max(ends)})
        return ast.Name(id=name,ctx=ast.Load())
    class Bind(ast.NodeTransformer):
        def visit_Subscript(self,node):
            if isinstance(node.value,ast.Name) and node.value.id==formal and isinstance(node.slice,ast.Constant):
                label=node.slice.value
                if label not in [f'table_{i}' for i in range(1,table_count+1)]:raise ValueError('Unknown source binding')
                i=int(label.split('_')[1])
                return ast.Name(id='input_df',ctx=ast.Load()) if i==1 else ast.Subscript(value=ast.Name(id='tables',ctx=ast.Load()),slice=ast.Constant(f'source_{i}'),ctx=ast.Load())
            return self.generic_visit(node)
        def visit_Name(self,node):
            if isinstance(node.ctx,ast.Load) and node.id==formal:
                raise ValueError('Dynamic tables access requires original-function observation')
            if isinstance(node.ctx,ast.Load) and node.id in renamed:return ast.copy_location(ast.Name(id=renamed[node.id],ctx=ast.Load()),node)
            return node

    def expression(node):
        if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Attribute) and node.value.attr=='loc' and isinstance(node.slice,ast.Tuple) and len(node.slice.elts)==2:
            rows,columns=node.slice.elts
            if isinstance(columns,ast.List) and all(isinstance(x,ast.Constant) and isinstance(x.value,str) for x in columns.elts):
                selected=ast.Subscript(value=node.value,slice=rows,ctx=ast.Load())
                name=emit(fresh('rows'),selected,node)
                return ast.copy_location(ast.Subscript(value=name,slice=columns,ctx=ast.Load()),node)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
            receiver=node.func.value
            if isinstance(receiver,(ast.Call,ast.Subscript)):
                receiver=expression(receiver)
                # Keep groupby().aggregate as one expression; GroupBy isn't a table.
                is_group=isinstance(receiver,ast.Call) and isinstance(receiver.func,ast.Attribute) and receiver.func.attr=='groupby'
                if not is_group:
                    receiver=emit(fresh('view'),receiver,node.func.value)
                node.func.value=receiver
        return node

    # Canonical pd/np aliases already exist in the worker. Other imports are preserved.
    for n in module.body:
        if isinstance(n,(ast.Import,ast.ImportFrom)):
            canonical=isinstance(n,ast.Import) and all((x.name,x.asname) in [('pandas','pd'),('numpy','np')] for x in n.names)
            if not canonical:
                emitted.append(copy.deepcopy(n));mapping.append({'statement_index':len(emitted)-1,'source_start':n.lineno,'source_end':n.end_lineno})
    for s in body:
        value=Bind().visit(copy.deepcopy(s.value))
        value=expression(value)
        if isinstance(s,ast.Return):
            emit('result',value,s)
        else:
            original=s.targets[0].id;name=fresh(original);emit(name,value,s);renamed[original]=name
    tree=ast.fix_missing_locations(ast.Module(body=emitted,type_ignores=[]))
    return ast.unparse(tree),mapping


def groups_from_observations(code,records):
    """Group scalar/alias setup with observed DataFrame transformations."""
    tree=ast.parse(code)
    last={r['statement_index']:r for r in records[1:]}
    groups=[];start=0
    for i,node in enumerate(tree.body):
        if not isinstance(node,ast.Assign) or not isinstance(node.targets[0],ast.Name):continue
        name=node.targets[0].id;r=last.get(i)
        if not r or r.get('output_variable')!=name:continue
        value=node.value
        alias=isinstance(value,ast.Name) or isinstance(value,ast.Subscript) and isinstance(value.value,ast.Name) and value.value.id=='tables'
        copy_only=isinstance(value,ast.Call) and isinstance(value.func,ast.Attribute) and value.func.attr=='copy' and isinstance(value.func.value,ast.Name)
        reset_only=isinstance(value,ast.Call) and isinstance(value.func,ast.Attribute) and value.func.attr=='reset_index' and isinstance(value.func.value,ast.Name) and any(k.arg=='drop' and isinstance(k.value,ast.Constant) and k.value.value is True for k in value.keywords)
        if alias or copy_only or reset_only:continue
        groups.append({'statement_indices':list(range(start,i+1)),'output_variable':name,'label':f'관찰 단계 {len(groups)+1}'})
        start=i+1
    if not groups:return [{'statement_indices':list(range(len(tree.body))),'output_variable':'result','label':'프로그램 관찰'}]
    if start<len(tree.body):groups[-1]['statement_indices'].extend(range(start,len(tree.body)))
    groups[-1]['output_variable']='result'
    return groups
