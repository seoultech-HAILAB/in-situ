"""Resolve comment selections against the current observed execution, not client values."""


def resolve_review_target(run, context, scope):
    target = context.get('review_target')
    if target is None:
        return None
    if not isinstance(target, dict) or target.get('kind') not in ('step', 'row', 'column', 'cell', 'rows', 'columns', 'cells'):
        raise ValueError('수정 댓글의 선택 종류가 올바르지 않습니다.')
    sid = target.get('step_id')
    stage = next((s for s in run['stages'] if s['id'] == sid), None)
    if stage is None or sid != context.get('step_id'):
        raise ValueError('수정 댓글의 Step이 현재 실행과 일치하지 않습니다.')
    if stage['kind'] == 'input' and scope != 'pipeline':
        raise ValueError('입력 표 선택은 전체 파이프라인 범위로 요청하세요.')
    operation_id = target.get('operation_id')
    observed = stage
    if operation_id is not None:
        observed = next((op for op in stage.get('operations', []) if op['id'] == operation_id), None)
        if observed is None:
            raise ValueError('선택한 연산이 현재 Step에 속하지 않습니다.')
    removed = target.get('removed', False)
    if not isinstance(removed, bool):
        raise ValueError('제외 행 선택 표시가 올바르지 않습니다.')
    role=target.get('table_role','output')
    if role not in ('input','output'):
        raise ValueError('선택한 표의 위치가 올바르지 않습니다.')
    input_ref=target.get('input_ref')
    if role=='input':
        if removed:raise ValueError('변환 전 표와 제외 행을 동시에 선택할 수 없습니다.')
        source=next((item for item in observed.get('inputs',[]) if item['ref']==input_ref),None)
        if source is None:raise ValueError('선택한 입력 표가 현재 Step의 실제 입력과 일치하지 않습니다.')
        data=source['table']
    else:
        if input_ref is not None:raise ValueError('출력 표 선택에 입력 참조를 지정할 수 없습니다.')
        data = observed.get('removed') if removed else observed['table']
    if data is None:
        raise ValueError('선택한 관찰 표가 없습니다.')
    kind = target['kind']
    exact=target.get('cells')
    if exact is not None:
        if kind!='cells' or not isinstance(exact,list) or not exact or len(exact)>len(data['rows'])*len(data['columns']):
            raise ValueError('선택한 개별 셀 목록이 올바르지 않습니다.')
        if any(key in target for key in ('row_ids','columns','row_id','column')):
            raise ValueError('개별 셀 목록과 직사각형 범위를 함께 지정할 수 없습니다.')
        valid_rows={row['id'] for row in data['rows']};valid_columns=set(data['columns']);pairs=set()
        for point in exact:
            if not isinstance(point,dict) or not isinstance(point.get('row_id'),str) or not isinstance(point.get('column'),str):
                raise ValueError('선택한 개별 셀 좌표가 올바르지 않습니다.')
            pair=(point['row_id'],point['column'])
            if pair in pairs or pair[0] not in valid_rows or pair[1] not in valid_columns:
                raise ValueError('선택한 개별 셀이 현재 관찰 표에 없거나 중복됩니다.')
            pairs.add(pair)
        row_map={row['id']:row for row in data['rows']}
        chosen_rows={row for row,column in pairs};chosen_columns={column for row,column in pairs}
        cells=[{'row_id':row['id'],'column':column} for row in data['rows'] for column in data['columns'] if (row['id'],column) in pairs]
        normalized={'kind':'cells','step_id':sid,'removed':removed,'cells':cells}
        if role=='input':normalized.update(table_role='input',input_ref=input_ref)
        if operation_id is not None:normalized['operation_id']=operation_id
        return {'target':normalized,'execution_version':run['id'],'code_version':run['code_version'],
                'stage_label':stage['label'],'operation_label':observed['label'],
                'table_shape':{'rows':len(data['rows']),'columns':len(data['columns'])},
                'selected_data':{'columns':[c for c in data['columns'] if c in chosen_columns],
                    'rows':[{'id':row['id'],'values':{c:row['values'][c] for c in data['columns'] if (row['id'],c) in pairs}} for row in data['rows'] if row['id'] in chosen_rows],
                    'cells':[{**point,'value':row_map[point['row_id']]['values'][point['column']]} for point in cells]}}
    column = target.get('column') if kind in ('column', 'cell') else None
    row_id = target.get('row_id') if kind in ('row', 'cell') else None
    if kind in ('column', 'cell') and (not isinstance(column, str) or column not in data['columns']):
        raise ValueError('선택한 열이 현재 관찰 표에 없습니다.')
    if kind in ('row', 'cell') and (not isinstance(row_id, str) or not any(r['id'] == row_id for r in data['rows'])):
        raise ValueError('선택한 행이 현재 관찰 표에 없습니다.')
    normalized = {'kind': kind, 'step_id': sid, 'removed': removed}
    if role=='input':normalized.update(table_role='input',input_ref=input_ref)
    if operation_id is not None: normalized['operation_id'] = operation_id
    if column is not None: normalized['column'] = column
    if row_id is not None: normalized['row_id'] = row_id
    columns = [column] if column is not None else data['columns']
    rows = [r for r in data['rows'] if row_id is None or r['id'] == row_id]
    if kind in ('rows', 'cells'):
        ids = target.get('row_ids')
        if not isinstance(ids, list) or not ids or any(not isinstance(r, str) for r in ids):
            raise ValueError('선택한 행 범위가 올바르지 않습니다.')
        valid_ids = {r['id'] for r in data['rows']}
        if len(ids) != len(set(ids)) or any(r not in valid_ids for r in ids):
            raise ValueError('선택한 행 범위가 현재 관찰 표에 없습니다.')
        rows = [r for r in data['rows'] if r['id'] in set(ids)]
        normalized['row_ids'] = [r['id'] for r in rows]
    if kind in ('columns', 'cells'):
        requested = target.get('columns')
        if not isinstance(requested, list) or not requested or any(not isinstance(c, str) for c in requested):
            raise ValueError('선택한 열 범위가 올바르지 않습니다.')
        if len(requested) != len(set(requested)) or any(c not in data['columns'] for c in requested):
            raise ValueError('선택한 열 범위가 현재 관찰 표에 없습니다.')
        columns = [c for c in data['columns'] if c in requested]
        normalized['columns'] = columns
    selected_data = None if kind == 'step' else {
        'columns': columns,
        'rows': [{'id': r['id'], 'values': {c: r['values'][c] for c in columns}} for r in rows],
    }
    return {'target': normalized, 'execution_version': run['id'], 'code_version': run['code_version'],
            'stage_label': stage['label'], 'operation_label': observed['label'],
            'table_shape': {'rows': len(data['rows']), 'columns': len(data['columns'])},
            'selected_data': selected_data}
