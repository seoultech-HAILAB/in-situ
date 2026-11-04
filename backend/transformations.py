"""Source-level transformations, independent of optional cell-provenance replay.

Locations describe syntax. Execution effects are attached separately from
observed operation records. No program is rewritten or evaluated by this module.
"""
import ast
import copy
import hashlib
import json
from .transformation_effects import bind as bind_execution_effects
from .statement_observations import VERSION as OBSERVATIONS_VERSION
from .operation_prose import operation_local_text

VERSION = 'ast-transformations-v3'
METHODS = {
    'assign':'derive', 'astype':'convert', 'to_numeric':'convert', 'to_datetime':'convert',
    'map':'derive', 'apply':'derive', 'applymap':'derive', 'transform':'derive',
    'round':'derive', 'where':'derive', 'mask':'derive', 'clip':'derive', 'rank':'derive', 'cumcount':'derive', 'strftime':'derive',
    'strip':'derive', 'lstrip':'derive', 'rstrip':'derive', 'lower':'derive', 'upper':'derive',
    'title':'derive', 'casefold':'derive', 'split':'derive', 'extract':'derive', 'replace':'derive',
    'fillna':'derive', 'ffill':'derive', 'bfill':'derive', 'cumsum':'derive',
    'groupby':'group', 'resample':'group', 'rolling':'group', 'expanding':'group', 'ewm':'group', 'agg':'aggregate', 'aggregate':'aggregate', 'sum':'aggregate',
    'mean':'aggregate', 'max':'aggregate', 'min':'aggregate', 'count':'aggregate',
    'nunique':'aggregate', 'size':'aggregate', 'pivot':'reshape', 'pivot_table':'reshape',
    'melt':'reshape', 'explode':'reshape', 'unstack':'reshape', 'stack':'reshape',
    'merge':'merge', 'join':'merge', 'concat':'merge', 'drop':'drop',
    'dropna':'filter', 'drop_duplicates':'filter', 'head':'filter', 'tail':'filter',
    'sort_values':'sort', 'sort_index':'sort', 'nlargest':'sort', 'nsmallest':'sort',
    'rename':'rename', 'reset_index':'index', 'set_index':'index',
    'reindex':'reshape', 'DataFrame':'construct', 'get_dummies':'reshape', 'update':'derive', 'insert':'derive', 'pop':'drop',
}


def strings(node, bindings=None):
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)): return [str(node.value)]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)): return [s for n in node.elts for s in strings(n, bindings)]
    if isinstance(node, ast.Name): return (bindings or {}).get(node.id, [])
    return []


def columns(node, bindings=None):
    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Attribute) and node.value.attr in ('loc', 'iloc'):
            return strings(node.slice.elts[1], bindings) if isinstance(node.slice, ast.Tuple) and len(node.slice.elts) == 2 else []
        if isinstance(node.value, ast.Name) and node.value.id == 'tables': return []
        return strings(node.slice, bindings)
    return []


def location(node):
    return dict(start=node.lineno, end=node.end_lineno, start_column=node.col_offset, end_column=node.end_col_offset)


def quoted(values): return ', '.join(f'“{v}”' for v in values)


def object_phrase(value):
    last=value[-1:] or '값'
    ending='을' if '\uac00'<=last<='\ud7a3' and (ord(last)-0xac00)%28 else '를'
    return value+ending


def readable(node):
    if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Attribute) and node.value.attr=='str':
        position=getattr(node.slice,'value',None)
        label='첫 번째 항목' if position==0 else f'{position+1}번째 항목' if isinstance(position,int) and position>=0 else '지정한 위치의 항목'
        return f'{readable(node.value.value)}에서 {label}을 선택한 값'
    if isinstance(node,ast.Call):
        method=node.func.attr if isinstance(node.func,ast.Attribute) else node.func.id if isinstance(node.func,ast.Name) else ''
        source=node.args[0] if method in ('to_numeric','to_datetime','round','set','sorted') and node.args else node.func.value if isinstance(node.func,ast.Attribute) else None
        if isinstance(source,ast.Attribute) and source.attr=='str':source=source.value
        fields=[field for field in columns(source) if not field.isdecimal()]
        subject=quoted(fields)+' 값' if fields else '선택한 값'
        if method=='to_numeric':
            coerce=any(k.arg=='errors' and isinstance(k.value,ast.Constant) and k.value.value=='coerce' for k in node.keywords)
            return f'{object_phrase(subject)} 숫자로 변환'+('하고 변환할 수 없는 값을 결측값으로 처리한 결과' if coerce else '한 결과')
        if method=='to_datetime':return f'{object_phrase(subject)} 날짜·시간으로 변환한 결과'
        if method=='astype':
            dtype=str(getattr(node.args[0],'id',getattr(node.args[0],'value','지정한 형식'))) if node.args else '지정한 형식'
            dtype={'int':'정수','float':'실수','str':'문자열','bool':'참·거짓'}.get(dtype,dtype)
            return f'{object_phrase(readable(source))} {dtype}로 변환한 결과'
        words={'strip':'양끝 공백을 제거한 결과','lstrip':'왼쪽 공백을 제거한 결과','rstrip':'오른쪽 공백을 제거한 결과',
               'upper':'대문자로 바꾼 결과','lower':'소문자로 바꾼 결과','title':'단어 첫 글자를 대문자로 바꾼 결과','casefold':'대소문자 구분 없이 비교할 수 있는 형태로 바꾼 결과'}
        if method in words:return f'{object_phrase(subject)} {words[method]}'
        if method=='copy':return '선택한 표를 복사한 결과'
        if method=='set':return '선택한 값의 중복을 제거한 집합'
        if method=='split':
            separator=ast.unparse(node.args[0]) if node.args else '공백'
            return f'{object_phrase(subject)} {separator} 기준으로 나눈 결과'
        if method=='round' and node.args:
            digits=ast.unparse(node.args[1]) if len(node.args)>1 else '0'
            return f'{object_phrase(readable(node.args[0]))} 소수점 {digits}자리로 반올림한 결과'
    cols = columns(node)
    if cols: return quoted(cols) + ' 값'
    if isinstance(node, ast.Constant): return str(node.value)
    if isinstance(node, ast.Name): return '현재 값' if node.id in ('v','x','value','s') else f'“{node.id}” 값'
    if isinstance(node, ast.BinOp):
        left, right = readable(node.left), readable(node.right)
        phrases={ast.Add:f'{left}에 {right}을 더한 값', ast.Sub:f'{left}에서 {right}을 뺀 값', ast.Mult:f'{left}에 {right}을 곱한 값', ast.Div:f'{left}을 {right}로 나눈 값', ast.FloorDiv:f'{left}을 {right}로 나눈 몫', ast.Mod:f'{left}을 {right}로 나눈 나머지', ast.Pow:f'{left}의 {right}제곱'}
        return phrases.get(type(node.op),'코드의 계산 결과')
    if isinstance(node, ast.IfExp): return f'{condition_text(node.test)}이면 {readable(node.body)}, 아니면 {readable(node.orelse)}'
    return '선택한 계산식의 결과'


def condition_text(node):
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left = quoted(columns(node.left)) or ast.unparse(node.left)
        right = ast.unparse(node.comparators[0])
        phrases = {ast.Gt:'보다 큰', ast.GtE:'이상인', ast.Lt:'보다 작은', ast.LtE:'이하인', ast.Eq:'과 같은', ast.NotEq:'과 다른'}
        return f'{left} 값이 {right}{phrases.get(type(node.ops[0]), "과 비교되는")} 행'
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.BitAnd, ast.BitOr)):
        return f'{condition_text(node.left)} {"동시에" if isinstance(node.op, ast.BitAnd) else "또는"} {condition_text(node.right)}'
    return '아래 코드의 조건에 해당하는 행'


def description(method, kind, node, targets):
    subject = quoted(targets) + ' 값을 ' if targets else '선택한 데이터를 '
    args = node.args if isinstance(node, ast.Call) else []
    kws = {k.arg:k.value for k in node.keywords} if isinstance(node, ast.Call) else {}
    first = ast.unparse(args[0]) if args else ''
    if method == 'filter': return condition_text(node.slice.elts[0] if isinstance(node.slice, ast.Tuple) else node.slice) + '을 남기고 나머지 행을 제외합니다.'
    if method == 'formula':
        value = node.value if isinstance(node, (ast.keyword, ast.Assign, ast.AnnAssign, ast.AugAssign)) else node
        if isinstance(node,ast.AugAssign):value=ast.BinOp(left=node.target,op=node.op,right=node.value)
        return f'{object_phrase(readable(value))} {quoted(targets) or "출력"}에 저장합니다.'
    if method == 'select': return f'{quoted(targets)} 열을 선택합니다.'
    if method == 'selection': return '코드에 지정한 행·열만 선택해 결과에 남깁니다.'
    if method in ('astype', 'to_numeric', 'to_datetime'):
        dtype = {'str':'문자열', 'int':'정수', 'float':'실수', 'bool':'참·거짓', "'str'":'문자열', "'int'":'정수', "'float'":'실수'}.get(first, first or '지정한 자료형')
        if method == 'to_numeric': dtype = '숫자'
        if method == 'to_datetime': dtype = '날짜·시간'
        return subject + f'{dtype} 형식으로 변환합니다.'
    prose = {'strip':'양끝 공백을 제거합니다.', 'lstrip':'왼쪽 공백을 제거합니다.', 'rstrip':'오른쪽 공백을 제거합니다.', 'lower':'소문자로 바꿉니다.', 'upper':'대문자로 바꿉니다.', 'title':'단어 첫 글자를 대문자로 바꿉니다.', 'casefold':'대소문자 구분 없이 비교할 수 있는 형태로 바꿉니다.', 'cumsum':'위에서부터 누적 합계를 계산합니다.'}
    if method in prose: return subject + prose[method]
    if method == 'round': return subject + f'소수점 {first or "0"}자리로 반올림합니다.'
    if method == 'fillna': return subject + f'확인하고 결측값을 {first or ast.unparse(kws.get("value", ast.Constant(None)))}로 채웁니다.'
    if method == 'replace': return subject + f'코드에 지정된 {first or "기존 값"}을 새 값으로 바꿉니다.'
    if method == 'split': return subject + f'{first or "지정된 구분자"} 기준으로 나눕니다.'
    if method == 'drop_duplicates': return f'{quoted(strings(kws.get("subset")) or strings(args[0] if args else None)) or "전체 열"}을 기준으로 중복 행을 제거합니다.'
    if method == 'dropna': return '코드에 지정된 기준에 따라 결측값이 있는 행 또는 열을 제거합니다.'
    if kind == 'sort':
        keys = strings(args[0] if args else kws.get('by'))
        direction = kws.get('ascending', ast.Constant(True))
        directions = direction.elts if isinstance(direction, (ast.List, ast.Tuple)) else [direction]*len(keys)
        order = ', '.join(f'“{key}” {"내림차순" if isinstance(d,ast.Constant) and d.value is False else "오름차순"}' for key,d in zip(keys,directions))
        return f'{order or "인덱스"} 기준으로 정렬합니다.'
    if kind == 'drop': return f'{quoted(targets) or "코드에 지정된 행·열"}을 결과에서 제거합니다.'
    if kind == 'rename': return f'열 이름을 {quoted(targets) or "코드에 지정된 새 이름"}으로 바꿉니다.'
    if kind == 'aggregate':
        value = node.value if isinstance(node, ast.keyword) else args[0] if args else ast.Constant(method)
        terms={'mean':'평균','sum':'합계','max':'최댓값','min':'최솟값','count':'개수','size':'행 수','nunique':'서로 다른 값의 개수','median':'중앙값','first':'첫 번째 값','last':'마지막 값'}
        if isinstance(value,ast.Tuple) and len(value.elts)==2:
            return f'{quoted(strings(value.elts[0]))}의 {terms.get(str(getattr(value.elts[1],"value","")), "집계 값")}를 {quoted(targets)}에 저장합니다.'
        return f'각 그룹의 {terms.get(str(getattr(value,"value",method)), "집계 값")}를 {quoted(targets) or "결과"}에 저장합니다.'
    if kind == 'group': return f'{quoted(strings(args[0] if args else kws.get("by")))} 기준으로 행을 묶습니다.'
    if kind == 'merge':
        keys = strings(kws.get('on')) or strings(kws.get('left_on'))
        how = str(getattr(kws.get('how'), 'value', 'inner' if method == 'merge' else 'left'))
        ways={'inner':'양쪽에 모두 있는 행', 'left':'왼쪽 테이블의 행', 'right':'오른쪽 테이블의 행', 'outer':'양쪽 테이블의 모든 행'}
        if method == 'concat': return f'테이블들을 {"열" if getattr(kws.get("axis"), "value", 0)==1 else "행"} 방향으로 이어 붙입니다.'
        return f'{quoted(keys) or "연결 키"}를 기준으로 {ways.get(how,"지정된 행")}을 남겨 테이블을 연결합니다.'
    if kind == 'index': return '코드에 지정된 기준에 따라 테이블의 인덱스를 정리합니다.'
    if kind == 'reshape': return '코드에 지정된 기준에 따라 행과 열의 구조를 바꿉니다.'
    if method in ('apply', 'map', 'transform', 'applymap'):
        if args and isinstance(args[0],ast.Lambda): return f'{subject}{readable(args[0].body)}으로 변환합니다.'
        return subject + f'{first or "지정된 함수"}의 변환 규칙을 적용해 계산합니다.'
    return f'{quoted(targets) or "출력 데이터"}을 아래 계산식으로 계산합니다.'


def extract(code, indices, tree=None, output_variable=None):
    tree = tree or ast.parse(code)
    helpers = {n.name:n for n in tree.body if isinstance(n, ast.FunctionDef)}
    found = []; bindings = {}; active = set()
    column_lists=set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            literal = strings(node.value)
            if literal: bindings[node.targets[0].id] = literal
            if isinstance(node.value,(ast.List,ast.Tuple)):column_lists.add(node.targets[0].id)

    def emit(node, kind, method, targets, variable, statement, callsite=None):
        loc = location(node); text = ast.get_source_segment(code, node) or ''
        lines = code.splitlines(keepends=True)
        loc['start_character'] = len(lines[loc['start']-1].encode('utf-8')[:loc['start_column']].decode('utf-8'))
        loc['end_character'] = len(lines[loc['end']-1].encode('utf-8')[:loc['end_column']].decode('utf-8'))
        inputs = list(dict.fromkeys(c for n in ast.walk(node) for c in columns(n, bindings)))
        item = {'kind':kind, 'method':method, 'code':text, 'code_location':loc,
                'output_columns':list(dict.fromkeys(targets)), 'input_columns':inputs,
                'output_variable':variable, 'statement_index':statement,
                'row_effect':'remove' if kind == 'filter' or method=='selection' else 'reorder' if kind == 'sort' else 'reshape' if kind in ('aggregate','merge','reshape','construct') else None,
                'description':{'text':description(method, kind, node, targets), 'source':'ast'},
                'syntax_only':True}
        if callsite is not None: item['call_location'] = location(callsite)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            prefix = node.func.value
            item['focus_location'] = {**loc, 'start':prefix.end_lineno, 'start_column':prefix.end_col_offset}
            start, end = item['focus_location']['start']-1, loc['end']-1
            segment = b''.join(line.encode('utf-8') for line in lines[start:end+1])
            end_byte = sum(len(line.encode('utf-8')) for line in lines[start:end]) + loc['end_column']
            item['focus_code'] = segment[prefix.end_col_offset:end_byte].decode('utf-8')
        found.append(item)

    def expression(node, targets, variable, statement, callsite=None):
        begin = len(found)
        if isinstance(node, ast.Call):
            method = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ''
            if isinstance(node.func, ast.Attribute): expression(node.func.value, targets, variable, statement, callsite)
            for arg in node.args: expression(arg, targets, variable, statement, callsite)
            for kw in node.keywords:
                dest = [kw.arg] if method in ('assign', 'agg', 'aggregate') and kw.arg else targets
                kw_begin = len(found); expression(kw.value, dest, variable, statement, callsite)
                if method == 'assign' and kw.arg and len(found) == kw_begin: emit(kw, 'derive', 'formula', dest, variable, statement, callsite)
                if method in ('agg','aggregate') and kw.arg and kw.arg not in ('func','axis','engine','engine_kwargs'):
                    emit(kw, 'aggregate', method, dest, variable, statement, callsite)
            if method in helpers and method not in active:
                active.add(method)
                for body in helpers[method].body: walk(body, statement, targets, variable, node)
                active.remove(method)
            elif method != 'assign' and (method in METHODS or isinstance(node.func,ast.Attribute) and method!='copy') and not (method in ('agg','aggregate') and any(k.arg not in ('func','axis','engine','engine_kwargs') for k in node.keywords)):
                dest = targets
                if method in ('agg','aggregate'):
                    dest = [k.arg for k in node.keywords if k.arg] or targets
                if method == 'drop':
                    opts = {k.arg:k.value for k in node.keywords}; dest = strings(opts.get('columns'), bindings) or targets
                if method == 'pop' and node.args:dest=strings(node.args[0],bindings)
                if method == 'insert' and len(node.args)>1:dest=strings(node.args[1],bindings)
                if method == 'rename':
                    opt = next((k.value for k in node.keywords if k.arg == 'columns'), None)
                    if isinstance(opt, ast.Dict): dest = [s for n in [*opt.keys,*opt.values] for s in strings(n, bindings)]
                emit(node, METHODS.get(method,'call'), method, dest, variable, statement, callsite)
        elif isinstance(node, ast.Subscript):
            expression(node.value, targets, variable, statement, callsite)
            selector = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) else node.slice
            if isinstance(selector, (ast.Compare, ast.BoolOp, ast.BinOp, ast.UnaryOp)) or isinstance(selector, ast.Call):
                emit(node, 'filter', 'filter', [], variable, statement, callsite)
            elif isinstance(selector,ast.Name) and selector.id in column_lists:
                emit(node,'select','select',strings(selector,bindings),variable,statement,callsite)
            elif isinstance(selector,ast.Name) and not strings(selector,bindings) or isinstance(node.value,ast.Attribute) and node.value.attr in ('loc','iloc') and not (
                isinstance(selector,ast.Slice) and selector.lower is None and selector.upper is None and selector.step is None):
                emit(node,'select','selection',[],variable,statement,callsite)
            elif isinstance(node.slice, (ast.List, ast.Tuple)):
                if not (isinstance(node.value,ast.Attribute) and node.value.attr in ('loc','iloc')):
                    emit(node, 'select', 'select', columns(node, bindings), variable, statement, callsite)
            if isinstance(node.value,ast.Attribute) and node.value.attr=='loc' and isinstance(node.slice,ast.Tuple) and len(node.slice.elts)==2 and isinstance(node.slice.elts[1],(ast.List,ast.Tuple)):
                emit(node,'select','select',columns(node,bindings),variable,statement,callsite)
        elif not isinstance(node, (ast.Lambda, ast.FunctionDef)):
            for child in ast.iter_child_nodes(node): expression(child, targets, variable, statement, callsite)
        return len(found) > begin

    def walk(node, statement, inherited=None, inherited_variable=None, callsite=None):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Pass)): return
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            dest = columns(target, bindings) or inherited or []
            variable = next((n.id for n in ast.walk(target) if isinstance(n, ast.Name)), inherited_variable)
            if isinstance(target,ast.Attribute) and target.attr=='columns':
                emit(node,'rename','rename',strings(node.value,bindings),variable,statement,callsite)
                return
            if isinstance(target, ast.Name):
                literal = strings(node.value, bindings)
                if literal: bindings[target.id] = literal
            if not expression(node.value, dest, variable, statement, callsite) and (dest or any(isinstance(n, ast.Subscript) for n in ast.walk(node.value))):
                emit(node, 'derive', 'formula', dest, variable, statement, callsite)
        elif isinstance(node, (ast.For, ast.If, ast.While, ast.With, ast.Try)):
            if isinstance(node, ast.For) and isinstance(node.target, ast.Name): bindings[node.target.id] = strings(node.iter, bindings)
            for body in [*node.body, *getattr(node, 'orelse', []), *getattr(node, 'finalbody', [])]: walk(body, statement, inherited, inherited_variable, callsite)
            for handler in getattr(node, 'handlers', []):
                for body in handler.body: walk(body, statement, inherited, inherited_variable, callsite)
        elif isinstance(node, (ast.Expr, ast.Return)) and node.value:
            expression(node.value, inherited or [], inherited_variable, statement, callsite)
        elif isinstance(node,ast.Delete):
            for target in node.targets:emit(target,'drop','drop',columns(target,bindings),inherited_variable,statement,callsite)

    for i in indices: walk(tree.body[i], i)
    contributing = set(indices)
    if output_variable:
        live = {output_variable}; contributing = set()
        for i in reversed(indices):
            node = tree.body[i]
            writes = set()
            for assignment in ast.walk(node):
                if isinstance(assignment, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    dsts = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
                    for dst in dsts:
                        root = next((n.id for n in ast.walk(dst) if isinstance(n, ast.Name)), None)
                        if root: writes.add(root)
                if isinstance(assignment,ast.Delete):
                    for dst in assignment.targets:
                        root=next((n.id for n in ast.walk(dst) if isinstance(n,ast.Name)),None)
                        if root:writes.add(root)
                if isinstance(assignment,ast.Call) and isinstance(assignment.func,ast.Attribute):
                    mutates=assignment.func.attr in ('update','insert','pop') or any(k.arg=='inplace' and isinstance(k.value,ast.Constant) and k.value.value is True for k in assignment.keywords)
                    if mutates:
                        root=next((n.id for n in ast.walk(assignment.func.value) if isinstance(n,ast.Name)),None)
                        if root:writes.add(root)
            if writes & live:
                contributing.add(i)
                if isinstance(node, ast.Assign) and all(isinstance(t,ast.Name) for t in node.targets): live -= {t.id for t in node.targets}
                live.update(n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load))
    unique = []; seen = set()
    for item in found:
        identity = json.dumps([item['code_location'], item['call_location'] if 'call_location' in item else None, item['code'], item['output_columns']], sort_keys=True)
        if identity in seen: continue
        seen.add(identity); item['id'] = 'transform-' + hashlib.sha256(identity.encode()).hexdigest()[:16]
        item['contributes_to_output'] = item['statement_index'] in contributing
        unique.append(item)
    return unique


def annotate_run(run):
    """Also upgrade persisted runs from their own code, never another version's."""
    code = run.get('code', '')
    try: tree = ast.parse(code)
    except SyntaxError: return run
    code_hash=hashlib.sha256(code.encode()).hexdigest()
    all_columns={str(column) for stage in run.get('stages',[]) for node in [stage,*stage.get('operations',[])]
                 for observed in (node.get('input'),node.get('table')) if observed for column in observed['columns']}
    current=(run.get('transformations_version')==VERSION and run.get('transformations_code_hash')==code_hash)
    if not current:
        # Invalidate persisted prose from the previous explanation policy.
        for key in ('explanation_status','explanation_error','explanation_meta'):run.pop(key,None)
        run['operations']=[{k:v for k,v in op.items() if k not in ('nl_explanation','column_explanations')} for op in run.get('operations',[])]
        if run.get('pipeline'):
            run['pipeline']={**run['pipeline'],'steps':[
                {**spec,'transformations':extract(code,spec['statement_indices'],tree,
                    output_variable=spec.get('observed_output_variable') or spec.get('output_variable'))}
                for spec in run['pipeline'].get('steps',[])]}
    plan = run.get('pipeline', {}).get('steps', [])
    for stage in run.get('stages', [])[1:]:
        stage.pop('observed_change_status',None)
        spec = next((s for s in plan if s['id'] == stage['id']), None)
        if spec: indices = spec['statement_indices']
        else:
            loc = stage.get('code_location') or {}
            indices = [i for i,n in enumerate(tree.body) if loc.get('start', 0) <= n.lineno <= loc.get('end', -1)]
        output = stage.get('output_variable') or (spec or {}).get('observed_output_variable') or (spec or {}).get('output_variable')
        fresh = extract(code, indices, tree, output_variable=output)
        for observation in stage.get('operation_observations',[]):
            if observation.get('kind')!='assignment':continue
            loc=observation['code_location'];snippet=observation['code'];written=observation['written_columns']
            existing=next((item for item in fresh if item['code']==snippet and item['code_location']['start']==loc['start'] and item['code_location']['start_column']==loc['start_column']),None)
            if existing:
                existing['method']='assignment'
                existing['output_columns']=written
                continue
            value=next((node.value for node in ast.walk(tree) if isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign)) and node.lineno==loc['start'] and node.col_offset==loc['start_column']),None)
            target=quoted(written)
            if isinstance(value,ast.Call) and isinstance(value.func,ast.Attribute) and value.func.attr=='strip':
                text=f'선택한 값의 양끝 공백을 제거해 {target} 열에 저장합니다.'
            else:text=f'{object_phrase(readable(value))} {target} 열에 저장합니다.'
            contributing=any(item['statement_index']==observation['statement_index'] and item.get('contributes_to_output') is not False for item in fresh)
            fresh.append({'id':'transform-assignment-'+hashlib.sha256(json.dumps([loc,snippet,written],sort_keys=True).encode()).hexdigest()[:16],
                'kind':'derive','method':'assignment','code':snippet,'code_location':loc,'output_columns':written,'input_columns':[],
                'output_variable':observation['output_variable'],'statement_index':observation['statement_index'],
                'row_effect':None,'description':{'text':text,'source':'ast'},'syntax_only':False,'contributes_to_output':contributing})
        if not current:
            stage.pop('nl_explanation',None);stage.pop('column_explanations',None)
            stage['operations']=[{k:v for k,v in op.items() if k not in ('nl_explanation','column_explanations')} for op in stage.get('operations',[])]
        fresh=bind_execution_effects(fresh,stage,tree)
        old = {t['id']:t for t in stage.get('transformations', [])} if current else {}
        for item in fresh:
            item['ast_description']=item['description']['text']
            prior = old.get(item['id'])
            if prior and prior.get('code') == item['code'] and prior.get('execution_version') == run.get('id') and prior.get('code_version') == run.get('code_version') and operation_local_text(prior['description']['text'],item,all_columns):
                item['description'] = copy.deepcopy(prior['description'])
            item['execution_version'] = run.get('id'); item['code_version'] = run.get('code_version')
        stage['transformations'] = fresh; stage['transformations_version'] = VERSION
    run['transformations_version'] = VERSION
    run['transformations_code_hash'] = code_hash
    if run.get('pipeline',{}).get('engine')=='capability' or all(stage.get('execution_observations_version')==OBSERVATIONS_VERSION for stage in run.get('stages',[])[1:]):
        run['execution_observations_version']=OBSERVATIONS_VERSION
    from .observed_changes import restore
    restore(run)
    # Display the complete containing statement in both conditions, while
    # preserving the operation's original coordinates for attribution/editing.
    statements=[node for node in ast.walk(tree) if isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign,ast.Expr,ast.Delete,ast.Return))]
    for stage in run.get('stages',[])[1:]:
        for item in stage.get('transformations',[]):
            loc=item.get('code_location') or {}
            start=(loc.get('start',0),loc.get('start_column',0))
            end=(loc.get('end',0),loc.get('end_column',10**9))
            matches=[node for node in statements if (node.lineno,node.col_offset)<=start and (node.end_lineno,node.end_col_offset)>=end]
            statement=min(matches,key=lambda node:(node.end_lineno-node.lineno,node.end_col_offset-node.col_offset),default=None)
            if statement is not None:
                item['statement_code']=ast.get_source_segment(code,statement)
                item['statement_location']={'start':statement.lineno,'end':statement.end_lineno,'start_column':statement.col_offset,'end_column':statement.end_col_offset}
    from .direct_tables import annotate as annotate_direct_tables
    annotate_direct_tables(run)
    return run


def targets(run):
    run = {**run, 'stages':[dict(stage) for stage in run.get('stages', [])]}
    annotate_run(run)
    return [{'step_no':i, 'transformation_no':j, **{k:t[k] for k in ('kind','code','code_location','output_columns','input_columns')}}
            for i,s in enumerate(run.get('stages', [])[1:], 1) for j,t in enumerate([t for t in s.get('transformations', []) if t.get('method')!='observed_change'], 1)]
