"""Auxiliary tables consumed by an executed operation in this Step only.

Do not walk source lineage, parent Steps or conservative dependency lists.
Unknown/common records cannot establish an actual multi-table use.
"""
import ast
import hashlib
import json


def expression(run,op):
    loc=op.get('expression_location') or op.get('code_location')
    if not loc:return None
    nodes=[n for n in ast.walk(ast.parse(run['code'])) if hasattr(n,'lineno') and n.lineno==loc['start'] and n.end_lineno==loc['end']]
    exact=[n for n in nodes if n.col_offset==loc.get('start_column') and n.end_col_offset==loc.get('end_column')]
    return next((n for n in exact if isinstance(n,ast.Call)),None) or (exact[0] if exact else next((n for n in nodes if isinstance(n,ast.Call)),None) or (nodes[0] if nodes else None))


def input_name(item,fallback):
    ref=item.get('ref','')
    if ref.startswith('observed-input:tables:'):return ref[len('observed-input:tables:'):]
    return item.get('variable') or (ref.split(':',1)[1] if ref.startswith(('observed-input:','source:')) else fallback)


def label(node,fallback):
    if isinstance(node,ast.Name):return node.id
    if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name) and node.value.id=='tables' and isinstance(node.slice,ast.Constant):return str(node.slice.value)
    if isinstance(node,(ast.Call,ast.Attribute,ast.Subscript)):
        return label(node.func.value if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) else getattr(node,'value',None),fallback)
    return fallback


def description(op,node):
    params=op.get('params',{});arguments=params.get('arguments',{})
    if op['kind'] in ('merge','join'):
        keys=params.get('keys') or arguments.get('on') or arguments.get('right_on') or []
        if isinstance(keys,str):keys=[keys]
        basis=', '.join(f'“{key}”' for key in keys)+' 열' if keys else '행 인덱스'
        how=params.get('how') or arguments.get('how') or ('left' if op['kind']=='join' else 'inner')
        rule={'left':'기존 표의 행을 유지하며 연결합니다.','inner':'양쪽에 일치하는 행을 연결합니다.',
              'right':'이 표의 행을 유지하며 연결합니다.','outer':'양쪽의 모든 행을 포함해 연결합니다.',
              'cross':'양쪽 행의 모든 조합을 만듭니다.'}.get(how,'다른 입력 표와 연결합니다.')
        return ('이 표를 사용해 '+rule) if how=='cross' else basis+'을 기준으로 이 표의 정보를 '+rule
    if op['kind']=='concat':
        axis=next((kw.value for kw in node.keywords if kw.arg=='axis'),None) if isinstance(node,ast.Call) else None
        if isinstance(axis,ast.Constant) and axis.value in (1,'columns'):return '행 인덱스를 맞춰 이 표의 열을 옆으로 이어 붙입니다.'
        if axis is None or isinstance(axis,ast.Constant) and axis.value in (0,'index'):return '이 표의 행을 다른 입력 표의 행과 이어 붙입니다.'
        return '이 표를 다른 입력 표와 이어 붙여 결과를 구성합니다.'
    if op['kind']=='filter':return '이 표에서 읽은 값을 현재 Step의 행 선택 조건에 사용합니다.'
    return '이 표에서 읽은 값을 현재 Step의 결과 열 계산에 사용합니다.'


def collect(run,stage):
    result=[];seen=set()
    operations=stage.get('operations',[])
    by_id={op['id']:op for op in operations}
    live=set();pending=[stage.get('output_ref')]
    while pending:
        ref=pending.pop()
        if ref in live or ref not in by_id:continue
        live.add(ref)
        pending.extend(item['ref'] for item in by_id[ref].get('inputs',[]))
    contributing={item['statement_index'] for item in stage.get('transformations',[]) if item.get('contributes_to_output') is not False and item.get('method')!='observed_change'}
    external_refs={item['ref'] for item in stage.get('inputs',[])}
    external_names={item.get('variable') for item in stage.get('inputs',[])}
    # Scope only: whether a frame variable existed before this Step. This does
    # not follow its origin or propagate tables from earlier transformations.
    earlier=[node for node in ast.parse(run['code']).body if node.end_lineno<(stage.get('code_location') or {}).get('start',0)]
    external_names.update(n.id for node in earlier for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store))
    records=[op for op in operations if op['id'] in live]
    records.extend(op for op in stage.get('operation_observations',[]) if op.get('statement_index') in contributing)
    for op in records:
        if any(op.get(key) is not None and op[key]!=run.get(key) for key in ('execution_version','code_version')):continue
        inputs=op.get('inputs',[])
        # These records are produced by successful, native-verified detailed
        # replay. A whole-Step Python input list is only a conservative guess.
        if len(inputs)<2 or op['kind'] not in ('merge','join','concat','derive','filter'):continue
        node=expression(run,op)
        names={n.id for n in ast.walk(node) if isinstance(n,ast.Name)} if node else set()
        source_keys={str(n.slice.value) for n in ast.walk(node) if isinstance(n,ast.Subscript) and isinstance(n.value,ast.Name) and n.value.id=='tables' and isinstance(n.slice,ast.Constant)} if node else set()
        for index,item in enumerate(inputs[1:],1):
            name=input_name(item,f'보조 표 {index}')
            if op['kind'] in ('derive','filter') and name not in names and name not in source_keys:
                # Value.nodes may refer to a scalar/Series prepared in a prior
                # Step. Without a direct frame reference it is propagated only.
                continue
            if op['kind'] in ('derive','filter') and not (
                name in external_names or f'tables:{name}' in external_names or item.get('ref') in external_refs
                or item.get('ref','').startswith('source:') or name=='input_df' and 'input' in external_refs
            ):continue  # A temporary split/working table inside this Step is not an additional input table.
            operand=None
            if isinstance(node,ast.Call):
                if op['kind'] in ('merge','join'):
                    if isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id in ('pd','pandas'):
                        operand=node.args[index] if len(node.args)>index else next((kw.value for kw in node.keywords if kw.arg=='right'),None)
                    else:operand=node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg in ('right','other')),None)
                elif op['kind']=='concat' and node.args and isinstance(node.args[0],(ast.List,ast.Tuple)) and len(node.args[0].elts)>index:operand=node.args[0].elts[index]
            name=label(operand,name)
            signature=json.dumps([name,item['table']],ensure_ascii=False,sort_keys=True)
            identity=hashlib.sha256(signature.encode()).hexdigest()[:16]
            usage={'text':description(op,node),'line':(op.get('expression_location') or op.get('code_location') or {}).get('start')}
            if identity in seen:
                existing=next(entry for entry in result if entry['id']==identity)
                if usage not in existing['uses']:existing['uses'].append(usage)
                continue
            seen.add(identity)
            result.append({'id':identity,'name':name,'table':item['table'],'uses':[usage]})
    return result


def annotate(run):
    for stage in run.get('stages',[])[1:]:stage['direct_tables']=collect(run,stage)
