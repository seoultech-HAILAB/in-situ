"""Semantic review steps, code coverage, stable identity, scoped revisions."""
import ast
import copy
import uuid
from .runtime import digest
from .legacy_engine import Unsupported


def canonical(code):
    return ast.dump(ast.parse(code),include_attributes=False)


def prepare(code, groups=None, previous=None, engine=None):
    tree=ast.parse(code)
    engine=engine or (previous or {}).get('pipeline',{}).get('engine','capability')
    if not tree.body: raise Unsupported('빈 파이프라인입니다.')
    old=(previous or {}).get('pipeline',{}).get('steps',[])
    if not groups and old:
        previous_tree=ast.parse(previous['code'])
        variables=lambda t:[s.targets[0].id if isinstance(s,ast.Assign) and isinstance(s.targets[0],ast.Name) else None for s in t.body]
        if variables(previous_tree)==variables(tree):
            groups=[{'id':s['id'],'statement_indices':s['statement_indices'],'label':s.get('intent_label',''),'output_variable':s.get('output_variable')} for s in old]
    specs=groups or [{'statement_indices':[i]} for i in range(len(tree.body))]
    covered=[];steps=[];used=set()
    for spec in specs:
        if hasattr(spec,'model_dump'): spec=spec.model_dump()
        indices=spec.get('statement_indices',[])
        if not indices or indices!=list(range(indices[0],indices[-1]+1)):
            raise Unsupported('검수 Step은 연속된 문장 범위를 가져야 합니다.')
        if any(not isinstance(i,int) or i<0 or i>=len(tree.body) for i in indices): raise Unsupported('Step 코드 위치가 유효하지 않습니다.')
        covered+=indices
        statements=[tree.body[i] for i in indices]
        if engine=='capability' and any(not isinstance(s,ast.Assign) or len(s.targets)!=1 or not isinstance(s.targets[0],ast.Name) for s in statements): raise Unsupported('Step은 DataFrame 할당문으로 구성해야 합니다.')
        block='\n'.join(ast.get_source_segment(code,s) for s in statements)
        variables=[s.targets[0].id for s in statements if isinstance(s,ast.Assign) and isinstance(s.targets[0],ast.Name)]
        output=spec.get('output_variable') or (variables[-1] if variables else None)
        explicit=spec.get('id')
        match=next((s for s in old if s['id']==explicit),None) if explicit else None
        if explicit and not match and explicit!='new': raise Unsupported('기존 Step ID를 임의로 만들 수 없습니다.')
        if not match:
            match=next((s for s in old if s['id'] not in used and canonical(s['code'])==canonical(block)),None)
        if not match:
            candidates=[s for s in old if s['id'] not in used and output and s.get('output_variable')==output]
            match=candidates[0] if len(candidates)==1 else None
        sid=match['id'] if match else 'step-'+uuid.uuid4().hex[:12]
        if sid in used: raise Unsupported('Step ID가 중복되었습니다.')
        used.add(sid)
        changed=not match or canonical(match['code'])!=canonical(block)
        steps.append({'id':sid,'revision':(match['revision']+int(changed)) if match else 1,
                      'code':block,'statement_indices':indices,'output_variable':output,'output_explicit':bool(spec.get('output_variable')),
                      'intent_label':spec.get('label',''),'code_location':{'start':statements[0].lineno,'end':statements[-1].end_lineno}})
    if covered!=list(range(len(tree.body))): raise Unsupported('Step 정보는 전체 코드를 순서대로, 중복·누락 없이 포함해야 합니다.')
    return {'steps':steps,'code':code,'schema_version':3 if engine=='python' else 2,'engine':engine,'grouping_source':'provided' if groups else 'syntax_fallback'}


def patch(previous,changes,base_run_id,scope='pipeline',target=None):
    if base_run_id!=previous['id']: raise Unsupported('기준 실행 버전이 달라 수정 응답을 적용하지 않았습니다.')
    steps=copy.deepcopy(previous['pipeline']['steps']);original={s['id']:s for s in steps}
    if not changes: raise Unsupported('수정할 변경 집합이 없습니다.')
    for item in changes:
        if hasattr(item,'model_dump'): item=item.model_dump()
        action=item['action'];sid=item['step_id']
        if sid not in original: raise Unsupported('수정 대상 Step이 존재하지 않습니다.')
        if scope=='step' and sid!=target: raise Unsupported('선택 Step 밖의 코드 변경입니다. 필요한 구조 변경은 전체 파이프라인 범위를 선택하세요.')
        pos=next((i for i,s in enumerate(steps) if s['id']==sid),None)
        if pos is None: raise Unsupported('이미 삭제된 Step을 다시 수정할 수 없습니다.')
        if action=='delete': steps.pop(pos)
        elif action=='replace': steps[pos].update(code=item['code'],intent_label=item.get('label',''))
        elif action=='insert_after':
            steps.insert(pos+1,{'id':None,'code':item['code'],'intent_label':item.get('label','')})
        else: raise Unsupported('지원하지 않는 수정 action입니다.')
    if not steps: raise Unsupported('모든 Step을 삭제할 수 없습니다.')
    blocks=[];specs=[];offset=0
    for s in steps:
        n=len(ast.parse(s['code']).body)
        blocks.append(s['code']);specs.append({'id':s['id'],'statement_indices':list(range(offset,offset+n)),'label':s.get('intent_label',''),'output_variable':s.get('output_variable')});offset+=n
    return prepare('\n'.join(blocks),specs,previous)


def validate_scope(plan,previous,scope,target):
    if scope!='step': return
    old={s['id']:s for s in previous['pipeline']['steps']};new={s['id']:s for s in plan['steps']}
    for sid,step in old.items():
        if sid!=target and (sid not in new or canonical(step['code'])!=canonical(new[sid]['code'])):
            raise Unsupported('선택 Step 밖 코드가 변경되었습니다. 전체 파이프라인 범위를 사용하세요.')
    # Insertions are allowed next to the selected step; arbitrary reordering isn't.
    old_order=[s['id'] for s in previous['pipeline']['steps'] if s['id']!=target]
    new_order=[s['id'] for s in plan['steps'] if s['id'] in old and s['id']!=target]
    if old_order!=new_order: raise Unsupported('선택 Step 밖 순서가 변경되었습니다.')
    for i,s in enumerate(plan['steps']):
        if s['id'] not in old and not ((i and plan['steps'][i-1]['id']==target) or (i+1<len(plan['steps']) and plan['steps'][i+1]['id']==target)):
            raise Unsupported('새 Step은 선택 Step 인접 위치에만 삽입할 수 있습니다.')


def assemble(records,plan,previous=None):
    root=records[0];ops=records[1:];mapping={};owners={}
    for step in plan['steps']:
        members=[o for o in ops if o['statement_index'] in step['statement_indices']]
        if not members: raise Unsupported('코드와 Step 실행 기록이 일치하지 않습니다.')
        for j,o in enumerate(members):
            owners[o['id']]=step['id'];mapping[o['id']]=f'{step["id"]}/operation-{j+1}'
    for o in ops:
        o['id']=mapping[o['id']]
        o['depends_on']=[mapping.get(x,x) for x in o['depends_on']]
        o['input_refs']=[mapping.get(x,x) for x in o['input_refs']];o['output_ref']=o['id']
        for inp in o['inputs']: inp['ref']=mapping.get(inp['ref'],inp['ref'])
        for cols in o['parents'].values():
            for refs in cols.values():
                for ref in refs: ref['step_id']=mapping.get(ref['step_id'],ref['step_id'])
    stages=[root];old={s['id']:s for s in (previous or {}).get('stages',[])}
    for i,step in enumerate(plan['steps']):
        members=[o for o in ops if o['statement_index'] in step['statement_indices']]
        first,last=members[0],members[-1];stage=copy.deepcopy(last)
        if plan.get('engine')=='python':
            step['observed_output_variable']=last.get('output_variable')
            if not step.get('output_explicit'):step['output_variable']=last.get('output_variable')
        stage.update(id=step['id'],order=i+1,revision=step['revision'],operations=members,code=step['code'],code_location=step['code_location'],
                     input=first['input'],input_refs=first['input_refs'],output_ref=last['id'],intent_label=step['intent_label'])
        internal={o['id'] for o in members}
        deps=list(dict.fromkeys(x for o in members for x in o['depends_on'] if x not in internal))
        external_inputs={(item['ref'],item.get('variable')):item for op in members for item in op['inputs'] if item['ref'] not in internal}
        stage['inputs']=list(external_inputs.values())
        stage['input_refs']=list(dict.fromkeys(x['ref'] for x in external_inputs.values()))
        stage['depends_on']=list(dict.fromkeys(next((s['id'] for s in plan['steps'] if x.startswith(s['id']+'/')),x) for x in deps))
        step.update(depends_on=stage['depends_on'],input_refs=stage['input_refs'],output_ref=stage['output_ref'],operation_ids=[o['id'] for o in members])
        meaningful=[o for o in members if o['kind']!='copy'] or members
        if len(meaningful)==1:
            primary=meaningful[0]
            stage.update(kind=primary['kind'],label=primary['label'],summary=primary['summary'],params=primary['params'],removed=primary['removed'],contexts=primary['contexts'],removed_lineage=primary.get('removed_lineage',{}))
        else:
            stage.update(kind='composite',label=' · '.join(dict.fromkeys(o['label'] for o in members)),
                         summary=' '.join(o['summary'] for o in members),params={},removed=None,
                         trace_level='detailed' if all(o['trace_level']=='detailed' for o in members) else 'common')
        if last.get('observation_only'):
            stage.update(kind='setup',label=last['label'],summary=last['summary'],params={},removed=None,contexts={})
        if stage['trace_level']=='common' and any(refs for cols in stage['lineage'].values() for refs in cols.values()):
            stage.update(trace_level='partial',trace_reason='일부 셀의 원본 출처만 확인되었습니다. 나머지 출처는 미확인입니다.')
        stage['related_columns']=list(dict.fromkeys(c for o in members for c in o['related_columns']))
        path_keys={s['id']:s.get('path_fingerprint') for s in stages}
        stage['path_fingerprint']=digest([canonical(step['code']),[(d,path_keys.get(d,d)) for d in stage['depends_on']]])
        stage['changes']={'rows':len(last['table']['rows'])-len(first['input']['rows']),
                          'added_columns':[c for c in last['table']['columns'] if c not in first['input']['columns']],
                          'removed_columns':[c for c in first['input']['columns'] if c not in last['table']['columns']]}
        prior=old.get(stage['id'])
        stage['diff']={'added':prior is None,'code_changed':prior is None or canonical(prior['code'])!=canonical(stage['code']),
                       'output_changed':prior is None or digest(prior['table'])!=digest(stage['table']),
                       'provenance_changed':prior is None or prior.get('path_fingerprint')!=stage['path_fingerprint'] or digest({'lineage':prior['lineage'],'contexts':prior.get('contexts',{}),'rows':prior['row_sources']})!=digest({'lineage':stage['lineage'],'contexts':stage.get('contexts',{}),'rows':stage['row_sources']}),
                       'comparison_available':stage['trace_level']=='detailed' and (prior or stage).get('trace_level','detailed')=='detailed'}
        stages.append(stage)
    return stages,ops
