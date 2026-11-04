"""Bind source expressions to observed operation changes, never inferred lineage."""
import ast

PRESERVING = {'filter','derive','select','drop','rename','sort_values','astype','fillna',
              'dropna','drop_duplicates','replace','reset_index','copy','head','tail'}
KINDS = ('added','changed','removed')


def effects(operation):
    before, after = operation.get('input'), operation.get('table')
    if not before or not after:
        return None
    correspondence=operation.get('row_correspondence',{})
    complete=operation.get('row_correspondence_complete',False)
    identity = complete or operation.get('row_identity_verified',False) or operation.get('trace_level') in ('detailed','partial') and operation.get('kind') in PRESERVING
    result = {'operation_id':operation.get('id'), 'operation_kind':operation.get('kind'),
              'code_location':operation.get('code_location'), 'expression_location':operation.get('expression_location'),
              'row_identity':identity, 'columns':{k:[] for k in KINDS},
              'rows':{k:[] for k in (*KINDS,'reordered')}, 'cells':{k:{} for k in KINDS}}
    old = {r['id']:r for r in before['rows']}
    new = {r['id']:r for r in after['rows']}
    source_id=lambda r:correspondence.get(r) if complete else r
    surviving={source_id(r):r for r in new if source_id(r) in old} if identity else {}
    old_cols, new_cols = before['columns'], after['columns']
    result['columns']['added'] = [c for c in new_cols if c not in old_cols]
    result['columns']['removed'] = [c for c in old_cols if c not in new_cols]
    common_cols = [c for c in new_cols if c in old_cols]
    old_order = [c for c in old_cols if c in new_cols]
    new_order = [c for c in new_cols if c in old_cols]
    retyped = {c for c in common_cols if before['stats']['fields'].get(c,{}).get('dtype') != after['stats']['fields'].get(c,{}).get('dtype')}
    changed = retyped | {c for i,c in enumerate(new_order) if old_order[i] != c}
    # A verified aggregation changes an entire column vector even without
    # one-to-one row identity. Do not invent changed cell/row pairs for it.
    changed.update(c for c in operation.get('schema_origins',{}).get('changed',{}) if c in common_cols)

    def cell(kind, column, row_id):
        result['cells'][kind].setdefault(column, []).append(row_id)

    # A removed/added field is observable even when row correspondence is unknown.
    for c in result['columns']['added']:
        for row_id in new: cell('added',c,row_id)
    for c in result['columns']['removed']:
        for row_id in old: cell('removed',c,surviving.get(row_id,row_id))
    if identity:
        result['rows']['added'] = [r for r in new if source_id(r) not in old]
        result['rows']['removed'] = [r for r in old if r not in surviving]
        old_survivors = [r for r in old if r in surviving]
        new_survivors = [r for r in new if source_id(r) in old]
        result['rows']['reordered'] = [r for i,r in enumerate(new_survivors) if old_survivors[i] != source_id(r)]
        for row_id in result['rows']['added']:
            for c in common_cols: cell('added',c,row_id)
        for row_id in result['rows']['removed']:
            for c in common_cols: cell('removed',c,row_id)
        for row_id in new_survivors:
            a, b = old[source_id(row_id)]['values'], new[row_id]['values']
            row_changed = row_id in result['rows']['reordered']
            for c in common_cols:
                if c not in a and c in b: kind = 'added'
                elif c in a and (c not in b or a[c] is not None and b[c] is None): kind = 'removed'
                elif a.get(c) != b.get(c) or c in retyped: kind = 'changed'
                else: continue
                cell(kind,c,row_id); changed.add(c); row_changed = True
            if row_changed: result['rows']['changed'].append(row_id)
    result['columns']['changed'] = [c for c in common_cols if c in changed]
    return result


def contains(outer, inner):
    if not outer or not inner: return False
    return (outer['start'],outer.get('start_column',0)) <= (inner['start'],inner.get('start_column',0)) and (
        inner['end'],inner.get('end_column',10**9)) <= (outer['end'],outer.get('end_column',10**9))


def equal_location(a,b):
    return bool(a and b) and all(a.get(k)==b.get(k) for k in ('start','end','start_column','end_column'))


def compatible(item, operation):
    kind = operation.get('kind')
    if kind=='construction':return item['method'] in ('DataFrame','concat','from_records','from_dict','array','pivot','pivot_table','melt')
    if kind=='assignment':return item['method']=='assignment'
    if item['method']=='assignment':return False
    if kind=='observed':return True
    if item['kind']=='derive': return kind in ('derive','fillna','replace','ffill','bfill','round','clip','where','mask')
    if item['kind']=='convert': return kind in ('derive','astype')
    if item['kind']=='sort': return kind in ('sort_values','sort_index')
    if item['kind']=='filter': return kind in ('filter','dropna','drop_duplicates','head','tail')
    if item['kind']=='aggregate': return kind=='aggregate'
    if item['kind']=='merge': return kind in ('merge','join','concat')
    if item['kind']=='reshape': return kind in ('melt','explode','pivot','pivot_table','transpose','reset_index')
    if item['kind']=='index': return kind in ('reset_index','set_index')
    return item['kind']==kind


def restrict(observed, columns, row_changes):
    result={**observed,
            'columns':{k:[c for c in observed['columns'][k] if columns is None or c in columns] for k in KINDS},
            'rows':{k:list(ids) for k,ids in observed['rows'].items()},
            'cells':{k:{c:list(ids) for c,ids in observed['cells'][k].items() if columns is None or c in columns} for k in KINDS}}
    if not row_changes:
        result['rows']={k:[] for k in (*KINDS,'reordered')}
        # A row header can reflect a verified value change in this expression.
        if result['row_identity']:
            changed={r for values in result['cells'].values() for column,ids in values.items()
                     if column not in observed['columns']['added'] and column not in observed['columns']['removed'] for r in ids}
            result['rows']['changed']=[r for r in observed['rows']['changed'] if r in changed]
    return result


def covers_write(item, operation, tree):
    """An assign record is the final value, not each nested Series call."""
    index=operation.get('statement_index')
    if not isinstance(index,int) or not 0<=index<len(tree.body): return False
    statement=tree.body[index]
    calls=[n for n in ast.walk(statement) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
           and n.func.attr=='assign' and equal_location(
               {'start':n.lineno,'end':n.end_lineno,'start_column':n.col_offset,'end_column':n.end_col_offset},operation.get('expression_location'))]
    values=[kw.value for call in calls for kw in call.keywords if kw.arg in item['output_columns']]
    if not values and isinstance(statement,(ast.Assign,ast.AnnAssign)):values=[statement.value]
    return bool(values) and all(contains(item['code_location'],
        {'start':value.lineno,'end':value.end_lineno,'start_column':value.col_offset,'end_column':value.end_col_offset}) for value in values)


def bind(items, stage, tree):
    for item in items:
        item['execution_effects']=[]
        item['removed_columns']=[]
    for operation in [*stage.get('operations',[]),*stage.get('operation_observations',[])]:
        if any(operation.get(key) and stage.get(key) and operation[key]!=stage[key] for key in ('execution_version','code_version')):continue
        observed=effects(operation)
        if not observed or operation.get('kind') in ('copy','setup'): continue
        expr=operation.get('expression_location')
        exact=[item for item in items if equal_location(item['code_location'],expr) and compatible(item,operation)]
        if operation.get('kind')=='derive':exact=[]
        candidates=exact
        if not candidates and expr:
            # Named assign/aggregate outputs share one DataFrame record. Attach
            # that record only to a unique expression for each written column.
            candidates=[item for item in items if compatible(item,operation) and
                        item.get('statement_index')==operation.get('statement_index') and
                        (contains(expr,item['code_location']) or contains(item['code_location'],expr))]
        if not candidates and not expr:
            # Common Python records only prove one straight-line statement;
            # grouped blocks, helper bodies and unobserved branches stay unbound.
            loc=operation.get('code_location')
            nodes=[node for node in tree.body if node.lineno==(loc or {}).get('start') and node.end_lineno==(loc or {}).get('end')]
            if len(nodes)==1 and isinstance(nodes[0],(ast.Assign,ast.AnnAssign,ast.Expr)) and not any(
                isinstance(n,(ast.IfExp,ast.BoolOp,ast.Lambda)) for n in ast.walk(nodes[0])):
                value=getattr(nodes[0],'value',None)
                value_loc={'start':value.lineno,'end':value.end_lineno,'start_column':value.col_offset,'end_column':value.end_col_offset} if value is not None else None
                candidates=[item for item in items if not item.get('call_location') and contains(loc,item['code_location']) and contains(item['code_location'],value_loc)]
        for item in candidates:
            if operation.get('kind')=='derive' and not covers_write(item,operation,tree):continue
            columns=None
            if not exact:
                own=item.get('output_columns',[])
                if item['kind']=='select' and len(candidates)==1:
                    columns=None
                elif not own:
                    if len(candidates)!=1: continue
                else:
                    columns={c for c in own if sum(c in other.get('output_columns',[]) for other in candidates)==1}
                    if not columns: continue
            selected=restrict(observed,columns,bool(exact) or len(candidates)==1 and item['row_effect'] in ('remove','reorder'))
            if operation.get('kind')=='assignment':
                selected=restrict(observed,set(operation.get('written_columns',[])),False)
            elif operation.get('kind')=='observed' and item['kind']=='filter':
                selected=restrict(observed,set(),True)
                selected['cells']['removed']={c:[r for r in ids if r in observed['rows']['removed']] for c,ids in observed['cells']['removed'].items()}
            elif operation.get('kind')=='observed' and item['method']=='select':
                selected=restrict(observed,set(observed['columns']['removed'])|set(observed['columns']['added'])|set(observed['columns']['changed']),False)
                selected['rows']={k:[] for k in (*KINDS,'reordered')}
            aliases=stage.get('observation_row_aliases',{}) if operation.get('observation_scope') else {}
            for values in (selected['rows'],):
                for kind,ids in values.items():values[kind]=[aliases.get(r,r) for r in ids]
            for columns in selected['cells'].values():
                for column,ids in columns.items():columns[column]=[aliases.get(r,r) for r in ids]
            item['execution_effects'].append(selected)
            item['removed_columns']=list(dict.fromkeys(item['removed_columns']+selected['columns']['removed']))
    bind_step_removals(items,stage)
    for item in items:item['syntax_only']=not bool(item['execution_effects'])
    return items


def bind_step_removals(items,stage):
    """Search every executed statement in this Step for unmatched removals."""
    aliases=stage.get('observation_row_aliases',{})
    for operation in stage.get('operation_observations',[]):
        observed=effects(operation)
        if not observed:continue
        line_set=set(operation.get('executed_lines',[]))
        candidates=[item for item in items if item.get('contributes_to_output') is not False and
            item['statement_index']==operation.get('statement_index') and item['code_location']['start'] in line_set]
        def attach(item,selected,ambiguous):
            selected['attribution']='step-search-candidate' if ambiguous else 'executed-statement'
            for kind,ids in selected['rows'].items():selected['rows'][kind]=[aliases.get(r,r) for r in ids]
            for columns in selected['cells'].values():
                for column,ids in columns.items():columns[column]=[aliases.get(r,r) for r in ids]
            item['execution_effects'].append(selected)
            item['removed_columns']=list(dict.fromkeys(item['removed_columns']+selected['columns']['removed']))
        for column in observed['columns']['removed']:
            if any(column in binding['columns']['removed'] for item in items for binding in item['execution_effects']):continue
            matching=[item for item in candidates if item['kind'] in ('select','drop','rename','reshape','call') and
                (item['kind']!='select' or column not in item['output_columns'])]
            for item in matching:
                selected=restrict(observed,{column},False)
                selected['columns']['added']=[];selected['columns']['changed']=[]
                selected['cells']['added']={};selected['cells']['changed']={}
                selected['rows']={k:[] for k in (*KINDS,'reordered')}
                attach(item,selected,len(matching)>1)
        removed=observed['rows']['removed']
        if not removed:continue
        claimed={r for item in items for binding in item['execution_effects'] for r in binding['rows']['removed']}
        missing=[r for r in removed if aliases.get(r,r) not in claimed]
        if not missing:continue
        matching=[item for item in candidates if item['row_effect']=='remove' or item['method']=='selection']
        for item in matching:
            selected=restrict(observed,set(),True)
            selected['rows']={k:(list(missing) if k=='removed' else []) for k in (*KINDS,'reordered')}
            selected['cells']['removed']={c:[r for r in ids if r in missing] for c,ids in observed['cells']['removed'].items()}
            attach(item,selected,len(matching)>1)


def revision_effects(run, baseline):
    """Compare two executed Step outputs, separately from normal operation input."""
    stage=run['stages'][-1]
    comparable=all(op.get('trace_level') in ('detailed','partial') and op.get('kind') in PRESERVING
                   for st in (baseline,stage) for op in (st.get('operations') or [st]))
    operation={'id':'revision:'+run['id'], 'kind':'derive', 'input':baseline['table'], 'table':stage['table'],
               'trace_level':'detailed' if comparable else 'common', 'code_location':stage.get('code_location')}
    base_map={value:key for key,value in baseline.get('row_correspondence',{}).items()}
    if baseline.get('row_correspondence_complete') and stage.get('row_correspondence_complete'):
        correspondence={output:base_map[source] for output,source in stage['row_correspondence'].items() if source in base_map}
        stage.update(revision_row_correspondence=correspondence,revision_row_correspondence_complete=True)
        operation.update(row_correspondence=correspondence,row_correspondence_complete=True)
    observed=effects(operation)
    items=[item for item in stage.get('transformations',[]) if item.get('contributes_to_output') is not False]
    for item in items:
        item['revision_effects']=[]
        bindings=item.get('execution_effects',[])
        owned={c for binding in bindings for values in (binding['columns'],binding['cells']) for group in values.values() for c in group}
        columns={c for c in owned if sum(any(c in group for b in other.get('execution_effects',[]) for values in (b['columns'],b['cells']) for group in values.values()) for other in items)==1}
        if item['method']=='observed_change':columns=set(item['output_columns'])
        row_changes=bool(bindings) and (item['kind'] in ('sort','filter') or item['method']=='selection')
        if columns or row_changes:
            selected=restrict(observed,columns,row_changes)
            if item['kind']=='sort':
                selected['rows']={k:(observed['rows']['reordered'] if k in ('changed','reordered') else []) for k in (*KINDS,'reordered')}
            elif item['kind']=='filter' or item['method']=='selection':
                selected['rows']['changed']=[]; selected['rows']['reordered']=[]
                removed={r for binding in bindings for r in binding['rows']['removed']}
                removed={base_map.get(r,r) for r in removed}
                selected['rows']['removed']=[r for r in observed['rows']['removed'] if r in removed]
                prior=[old for old in baseline.get('transformations',[]) if old['method']==item['method'] and
                       old['code_location']['start']==item['code_location']['start'] and old['code_location']['start_column']==item['code_location']['start_column']]
                old_removed={r for old in prior for binding in old.get('execution_effects',[]) for r in binding['rows']['removed']}
                inverse={source:output for output,source in stage.get('row_correspondence',{}).items()}
                restored={inverse.get(r,r) for r in old_removed}
                selected['rows']['added']=[r for r in observed['rows']['added'] if r in restored]
                for kind in ('added','removed'):
                    selected['cells'][kind]={c:[r for r in ids if r in selected['rows'][kind]] for c,ids in observed['cells'][kind].items()}
            item['revision_effects'].append(selected)
    return run
