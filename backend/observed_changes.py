"""Executed differences are authoritative; the model may only select local code.

No model-supplied row, column, effect or source coordinate is accepted. Candidate
IDs name executed statements; verified statement effects narrow the choice when
available. Otherwise a model association is explicitly a candidate, not lineage.
"""
import ast
from copy import deepcopy
import hashlib
import json

from .transformation_effects import effects, contains
from .statement_observations import location
from .operation_prose import operation_local_text
from .construction_observations import construction_bindings, compatible_fallback, key as node_key

VERSION='observed-change-links-v2'


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def comparison_input(stage):
    tables=[table for table in [stage.get('input'),*[item['table'] for item in stage.get('inputs',[])]] if table]
    ids=set(stage.get('row_correspondence',{}).values()) if stage.get('row_correspondence_complete') else {r['id'] for r in stage['table']['rows']}
    def score(table):return (sum(row['id'] in ids for row in table['rows']),sum(c in stage['table']['columns'] for c in table['columns']))
    return max(tables,key=score) if tables else None


def sample_value(value):
    if isinstance(value,str) and len(value)>160:return value[:160]+'…'
    if isinstance(value,list):return [sample_value(v) for v in value[:8]]
    return value


def table_context(table,relevant):
    if not table:return None
    columns=table['columns']
    return {'columns':columns,'row_count':len(table['rows']),
        'dtypes':{c:table['stats']['fields'].get(c,{}).get('dtype') for c in columns},
        'sample':[{'row':i+1,'values':{c:sample_value(row['values'].get(c)) for c in [c for c in columns if c in relevant][:12]}} for i,row in enumerate(table['rows'][:4])],
        'sampled':len(table['rows'])>4 or len(columns)>12}


def blank(observed):
    return {**observed,'columns':{k:[] for k in ('added','changed','removed')},
        'cells':{k:{} for k in ('added','changed','removed')},
        'rows':{k:[] for k in ('added','changed','removed','reordered')}}


def tokens(effect):
    return ({('column',kind,column) for kind,columns in effect['columns'].items() for column in columns}
        | {('cell',kind,column,row) for kind,columns in effect['cells'].items() for column,rows in columns.items() for row in rows}
        | {('row',kind,row) for kind,rows in effect['rows'].items() for row in rows})


def remap(effect,aliases):
    effect=deepcopy(effect)
    for kind,rows in effect['rows'].items():effect['rows'][kind]=[aliases.get(r,r) for r in rows]
    for columns in effect['cells'].values():
        for c,rows in columns.items():columns[c]=[aliases.get(r,r) for r in rows]
    return effect


def intersect(event,evidence):
    result=blank(event)
    for kind in result['columns']:
        result['columns'][kind]=[c for c in event['columns'][kind] if c in evidence['columns'][kind]]
        result['cells'][kind]={c:[r for r in rows if r in evidence['cells'][kind].get(c,[])]
            for c,rows in event['cells'][kind].items()}
    for kind in result['rows']:result['rows'][kind]=[r for r in event['rows'][kind] if r in evidence['rows'][kind]]
    return result


def stage_contract(run,stage,step_no,tree):
    before=comparison_input(stage)
    if not before:return None
    operation={**stage,'input':before}
    # Composite common Steps use only explicit correspondence, never matching
    # indexes or equal values. Detailed preserving pipelines retain their IDs.
    preserving={'filter','derive','select','drop','rename','sort_values','astype','fillna','dropna','drop_duplicates','replace','reset_index','copy','head','tail'}
    members=stage.get('operations') or [stage]
    if not stage.get('row_correspondence_complete'):
        operation['row_identity_verified']=stage.get('trace_level') in ('detailed','partial') and all(op['kind'] in preserving for op in members)
        operation['trace_level']='common'
    observed=effects(operation)
    if not observed:return None
    net=[]
    added_removed=set(observed['rows']['added']+observed['rows']['removed'])
    for kind in ('added','changed','removed'):
        for column in dict.fromkeys(observed['columns'][kind]+list(observed['cells'][kind])):
            rows=observed['cells'][kind].get(column,[])
            is_column=column in observed['columns'][kind]
            if not is_column:rows=[r for r in rows if r not in added_removed]
            if not is_column and not rows:continue
            event=blank(observed)
            event['columns'][kind]=[column] if is_column else []
            if rows:event['cells'][kind][column]=rows
            if column not in observed['columns']['added']+observed['columns']['removed']:
                event['rows']['changed']=[r for r in rows if r in observed['rows']['changed'] and r not in observed['rows']['reordered']]
            net.append({'axis':'column' if is_column else 'cells','kind':kind,'column':column,'effect':event})
    for kind in ('added','removed','reordered'):
        rows=observed['rows'][kind]
        if not rows:continue
        event=blank(observed)
        event['rows'][kind]=rows
        if kind=='reordered':event['rows']['changed']=rows
        else:event['cells'][kind]={c:[r for r in values if r in rows] for c,values in observed['cells'][kind].items()}
        net.append({'axis':'rows','kind':kind,'column':None,'effect':event})
    observations=[*stage.get('operations',[]),*stage.get('operation_observations',[])]
    executed={line for op in [*observations,*stage.get('executed_statements',[])] for line in op.get('executed_lines',[])}
    spec=next((spec for spec in run.get('pipeline',{}).get('steps',[]) if spec['id']==stage['id']),None)
    indices=spec['statement_indices'] if spec else [i for i,node in enumerate(tree.body) if contains(stage.get('code_location'),location(node))]
    source_items=[item for item in stage.get('transformations',[]) if item.get('method')!='observed_change']
    contributing={item['statement_index'] for item in source_items if item.get('contributes_to_output') is not False}
    unrelated={item['statement_index'] for item in source_items if item.get('contributes_to_output') is False}-contributing
    construction=construction_bindings([(index,tree.body[index]) for index in indices],observations,executed,contributing)
    construction_producers=set().union(*(positions for fields in construction.values() for positions in fields.values()))
    candidates=[]
    candidate_nodes={}
    for index in indices:
        for node in ast.walk(tree.body[index]):
            if not isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign,ast.Delete,ast.Expr)):continue
            if index in unrelated and node_key(node) not in construction_producers:continue
            loc=location(node)
            if executed and node.lineno not in executed:continue
            if not executed and not any(contains(loc,op.get('expression_location') or op.get('code_location')) for op in observations):continue
            snippet=ast.get_source_segment(run['code'],node)
            candidate={'id':f's{step_no}-code-{len(candidates)+1}','code':snippet,'code_location':loc,'statement_index':index,'evidence':[]}
            for op in observations:
                if not contains(loc,op.get('expression_location') or op.get('code_location')):continue
                effect=effects(op)
                if not effect:continue
                if op.get('kind')=='assignment':
                    written=set(op.get('written_columns',[]))
                    effect['columns']={k:[c for c in values if c in written] for k,values in effect['columns'].items()}
                    effect['cells']={k:{c:values for c,values in cols.items() if c in written} for k,cols in effect['cells'].items()}
                    effect['rows']={k:[] for k in effect['rows']}
                candidate['evidence'].append(remap(effect,stage.get('observation_row_aliases',{}) if op.get('observation_scope') else {}))
            candidates.append(candidate)
            candidate_nodes[candidate['id']]=node
    # Row IDs are local execution identifiers. The model sees numbered examples;
    # effects retain IDs only on the server and are rebuilt when applying links.
    old={r['id']:(i+1,r) for i,r in enumerate(before['rows'])}
    new={r['id']:(i+1,r) for i,r in enumerate(stage['table']['rows'])}
    inverse=stage.get('row_correspondence',{})
    for number,event in enumerate(net,1):
        event['id']=f's{step_no}-change-{number}'
        event['candidate_effects']={}
        for candidate in candidates:
            evidence=candidate['evidence']
            if event['kind']=='reordered':evidence=[e for e in evidence if e.get('operation_kind') in ('sort_values','sort_index')]
            matching=[intersect(event['effect'],effect) for effect in evidence]
            matching=[effect for effect in matching if tokens(effect)]
            if matching:event['candidate_effects'][candidate['id']]=matching
        # A real schema write to the observed output is stronger than a broad
        # Step association. Dynamic loop column names are runtime values here.
        if not event['candidate_effects'] and event['column']:
            for candidate in candidates:
                site=candidate['code_location']
                writes=[write for write in stage.get('statement_schema_effects',[])
                        if write['code_location']==site and write['output_variable'] in stage.get('output_bindings',[])
                        and event['column'] in write.get(event['kind'],[])]
                if writes:event['candidate_effects'][candidate['id']]=[deepcopy(event['effect'])]
        origins=stage.get('schema_origins',{}).get(event['kind'],{}).get(event['column'],[]) if event['axis']=='column' and event['kind'] in ('added','changed','removed') else []
        origin_candidates=[candidate for candidate in candidates if candidate['code_location'] in origins]
        if origin_candidates:
            event['candidate_effects']={candidate['id']:[deepcopy(event['effect'])] for candidate in origin_candidates}
        # Constructor field positions identify local calculations, even when
        # the calculation itself produces a scalar rather than a DataFrame.
        producers=set().union(*(fields[event['column']] for fields in construction.values() if event['column'] in fields)) if event['kind']=='added' else set()
        bound=[candidate for candidate in candidates if node_key(candidate_nodes[candidate['id']]) in producers]
        if bound:
            event['candidate_effects']={candidate['id']:[deepcopy(event['effect'])] for candidate in bound}
            event['candidate_ids']=list(event['candidate_effects'])
            event['code_evidence']='executed-construction'
        else:
            event['candidate_ids']=list(event['candidate_effects']) or [candidate['id'] for candidate in candidates
                if compatible_fallback(candidate_nodes[candidate['id']],event,construction)]
            event['code_evidence']='executed-effect' if event['candidate_effects'] else 'executed-step-only'
        ids=list(dict.fromkeys([r for rows in event['effect']['rows'].values() for r in rows]+[r for cols in event['effect']['cells'].values() for rows in cols.values() for r in rows]))
        examples=[]
        for row_id in ids[:4]:
            a=old.get(inverse.get(row_id,row_id));b=new.get(row_id)
            if not observed['row_identity']:
                if event['kind']=='removed':b=None
                else:a=None
            cols=[event['column']] if event['column'] else stage['table']['columns'][:8]
            examples.append({'before_row':a[0] if a else None,'after_row':b[0] if b else None,
                'before':{c:sample_value(a[1]['values'][c]) for c in cols if a and c in a[1]['values']},
                'after':{c:sample_value(b[1]['values'][c]) for c in cols if b and c in b[1]['values']}})
        event['examples']=examples
        event['affected_rows']=len(set(ids))
    relevant={event['column'] for event in net if event['column']}
    relevant.update(node.value for index in indices for node in ast.walk(tree.body[index]) if isinstance(node,ast.Constant) and isinstance(node.value,str))
    return {'step_no':step_no,'row_correspondence_known':observed['row_identity'],
        'before':table_context(before,relevant),'after':table_context(stage['table'],relevant),
        'candidates':candidates,'changes':net}


def contracts(run):
    tree=ast.parse(run['code'])
    return [contract for i,stage in enumerate(run['stages'][1:],1) if (contract:=stage_contract(run,stage,i,tree))]


def public_contracts(run):
    return [{'step_no':item['step_no'],'row_correspondence_known':item['row_correspondence_known'],
        'before':item['before'],'after':item['after'],
        'code_candidates':[{k:c[k] for k in ('id','code','code_location')} for c in item['candidates']],
        'changes':[{k:e[k] for k in ('id','axis','kind','column','candidate_ids','code_evidence','affected_rows','examples')} for e in item['changes']]}
        for item in contracts(run)]


def contract_hash(run):
    # The model sees bounded examples, but persisted links are invalidated by
    # any changed observation, including a row outside those examples.
    return digest({'code':run['code'],'public':public_contracts(run),
        'tables':[(comparison_input(stage),stage['table']) for stage in run['stages'][1:]]})


def validate(run,links,required=True):
    items=contracts(run)
    expected={(item['step_no'],event['id']):(item,event) for item in items for event in item['changes']}
    actual=[(link['step_no'],link['change_id']) for link in links]
    if len(set(actual))!=len(actual) or (required and set(actual)!=set(expected)) or any(key not in expected for key in actual):
        raise ValueError('관찰된 변화와 LLM 코드 대응 목록이 일치하지 않습니다.')
    for link in links:
        item,event=expected[(link['step_no'],link['change_id'])]
        selections=link['operations'];ids=[operation['candidate_id'] for operation in selections]
        if len(ids)!=len(set(ids)) or any(cid not in event['candidate_ids'] for cid in ids):raise ValueError('해당 변화의 실행 코드 후보 밖을 선택했습니다.')
        if link['status'] not in ('linked','ambiguous','unresolved') or (link['status']=='unresolved')!=(not bool(ids)):raise ValueError('변화의 코드 대응 상태가 올바르지 않습니다.')
        if any(not isinstance(operation['text'],str) or not 1<=len(operation['text'])<=700 for operation in selections):raise ValueError('변화 설명이 비어 있거나 너무 깁니다.')
    return items


def prose_issues(run,links):
    items=validate(run,links)
    all_columns={c for item in items for side in ('before','after') for c in item[side]['columns']}
    issues=[]
    for link in links:
        item=next(item for item in items if item['step_no']==link['step_no'])
        event=next(event for event in item['changes'] if event['id']==link['change_id'])
        for selection in link['operations']:
            candidate=next(c for c in item['candidates'] if c['id']==selection['candidate_id'])
            local={'code':candidate['code'],'output_columns':[event['column']] if event['column'] else [],'removed_columns':event['effect']['columns']['removed']}
            if operation_local_text(selection['text'],local,all_columns):continue
            allowed=set(local['output_columns']+local['removed_columns'])
            allowed.update(n.value for n in ast.walk(ast.parse(candidate['code'])) if isinstance(n,ast.Constant) and isinstance(n.value,str))
            issues.append({'key':f"{link['step_no']}/{link['change_id']}/{selection['candidate_id']}",
                'code':candidate['code'],'column':event['column'],'change':event['kind'],
                'forbidden_columns':sorted(all_columns-allowed),'text':selection['text']})
    return issues


def apply(run,links,required=True):
    items=validate(run,links,required)
    all_columns={c for item in items for side in ('before','after') for c in item[side]['columns']}
    for stage in run['stages'][1:]:
        stage['transformations']=[t for t in stage.get('transformations',[]) if t.get('method')!='observed_change']
        stage['observed_change_status']=[]
    for link in links:
        item=next(item for item in items if item['step_no']==link['step_no'])
        event=next(event for event in item['changes'] if event['id']==link['change_id'])
        stage=run['stages'][link['step_no']]
        accepted=0
        for selection in link['operations']:
            candidate=next(c for c in item['candidates'] if c['id']==selection['candidate_id'])
            local={'code':candidate['code'],'output_columns':[event['column']] if event['column'] else [],'removed_columns':event['effect']['columns']['removed']}
            if not operation_local_text(selection['text'],local,all_columns):continue
            accepted+=1
            bindings=deepcopy(event['candidate_effects'].get(candidate['id']) or [event['effect']])
            uncertain=link['status']=='ambiguous' or event['code_evidence']=='executed-step-only'
            for binding in bindings:binding['attribution']='llm-step-candidate' if uncertain else 'llm-executed-effect'
            column=event['column']
            stage['transformations'].append({'id':'observed-'+digest([event['id'],candidate['id']])[:20],
                'kind':'sort' if event['kind']=='reordered' else 'filter' if event['axis']=='rows' else 'derive',
                'method':'observed_change','code':candidate['code'],'code_location':candidate['code_location'],
                'statement_index':candidate['statement_index'],'output_columns':[column] if column else [],'input_columns':[],
                'removed_columns':event['effect']['columns']['removed'],'row_effect':'reorder' if event['kind']=='reordered' else 'remove' if event['axis']=='rows' and event['kind']=='removed' else None,
                'description':{'text':selection['text'],'source':'llm'},'execution_effects':bindings,
                'execution_version':run['id'],'code_version':run['code_version'],'syntax_only':False,'contributes_to_output':True,
                'mapping_status':'candidate' if uncertain else 'matched','observed_change_id':event['id']})
        stage['observed_change_status'].append({'change_id':event['id'],'status':link['status'] if accepted else 'unresolved',
            'axis':event['axis'],'kind':event['kind'],'column':event['column']})
    run['observed_change_links']={'version':VERSION,'execution_version':run['id'],'code_version':run['code_version'],
        'contract_hash':contract_hash(run),'links':deepcopy(links)}


def restore(run):
    saved=run.get('observed_change_links')
    if not saved:return
    if (saved.get('version')!=VERSION or saved.get('execution_version')!=run.get('id') or saved.get('code_version')!=run.get('code_version')
            or saved.get('contract_hash')!=contract_hash(run)):
        run.pop('observed_change_links',None)
        return
    try:apply(run,saved['links'])
    except (ValueError,KeyError,TypeError):run.pop('observed_change_links',None)
