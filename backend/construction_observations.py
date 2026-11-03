"""Local, executed container-to-column bindings, without upstream explanations.

The native constructor output proves its schema. Literal row positions connect
that schema to calculations executed in this Step. This does not establish row
identity, replay user code, or include previous Step/variable definitions in prose.
"""
import ast


def key(node):
    return (node.lineno, node.col_offset)


def literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def definitions_before(statements, name, before):
    definitions = [(owner, node) for owner, node in statements
                   if isinstance(node, ast.Assign) and node.lineno < before.lineno
                   and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    latest = max((owner for owner, _ in definitions), default=None)
    return {key(node) for owner, node in definitions if owner == latest}


def dictionary_value_producers(data, statements):
    """Resolve executed dict writes used by an items() comprehension locally."""
    aliases = {}
    for generator in data.generators:
        call = generator.iter
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == 'items'
                and isinstance(call.func.value, ast.Name) and isinstance(generator.target, (ast.Tuple, ast.List))
                and len(generator.target.elts) == 2 and isinstance(generator.target.elts[1], ast.Name)):
            continue
        source = call.func.value.id
        root, depth = aliases.get(source, (source, 0))
        aliases[generator.target.elts[1].id] = (root, depth + 1)
    result = {}
    for name, (root, depth) in aliases.items():
        producers = set()
        for _, statement in statements:
            if not isinstance(statement, ast.Assign):
                continue
            for target in statement.targets:
                count = 0
                while isinstance(target, ast.Subscript):
                    count += 1; target = target.value
                if count != depth or not isinstance(target, ast.Name) or target.id != root:
                    continue
                value = statement.value
                if isinstance(value, ast.Name):
                    producers.update(definitions_before(statements, value.id, statement))
                else:
                    producers.add(key(statement))
        if producers:
            result[name] = producers
    return result


def construction_bindings(nodes, observations, executed, contributing):
    statements = [(index, node) for index, root in nodes for node in ast.walk(root)
                  if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr)) and node.lineno in executed]
    bindings = {}
    for record in observations:
        if record.get('kind') != 'construction' or record.get('statement_index') not in contributing:
            continue
        loc = record['code_location']
        constructor = next((node for _, node in statements if key(node) == (loc['start'], loc['start_column'])), None)
        call = getattr(constructor, 'value', None)
        if not isinstance(call, ast.Call):
            continue
        columns = record['table']['columns']
        fields = {column: {key(constructor)} for column in columns}
        # A literal DataFrame schema + literal append positions is an explicit
        # column binding. Other container shapes retain the constructor itself.
        if isinstance(call.func, ast.Attribute) and call.func.attr == 'DataFrame':
            declared = next((literal(k.value) for k in call.keywords if k.arg == 'columns'), None)
            data = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == 'data'), None)
            if declared == columns and isinstance(data, ast.Name):
                appends = [(index, node) for index, node in statements if isinstance(node, ast.Expr)
                           and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                           and node.value.func.attr == 'append' and isinstance(node.value.func.value, ast.Name)
                           and node.value.func.value.id == data.id and node.lineno < constructor.lineno
                           and len(node.value.args) == 1 and isinstance(node.value.args[0], (ast.List, ast.Tuple))
                           and len(node.value.args[0].elts) == len(columns)]
                for position, column in enumerate(columns):
                    producers = set()
                    for index, append in appends:
                        value = append.value.args[0].elts[position]
                        while isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in ('str', 'float', 'int', 'bool') and len(value.args) == 1:
                            value = value.args[0]
                        if isinstance(value, ast.Name):
                            producers.update(definitions_before(statements, value.id, append))
                        elif isinstance(value, (ast.BinOp, ast.Compare, ast.IfExp, ast.UnaryOp)):
                            producers.add(key(append))
                    if producers:
                        fields[column] = producers
            elif declared == columns and isinstance(data, ast.ListComp) and isinstance(data.elt, (ast.List, ast.Tuple)) and len(data.elt.elts) == len(columns):
                producers = dictionary_value_producers(data, statements)
                for column, value in zip(columns, data.elt.elts):
                    if isinstance(value, ast.Name) and value.id in producers:
                        fields[column] = producers[value.id]
        bindings[key(constructor)] = fields
    return bindings


def compatible_fallback(node, event, construction):
    """Only locally relevant executed code; an empty match stays unresolved."""
    column, kind = event['column'], event['kind']
    if key(node) in construction:
        fields = construction[key(node)]
        return column in fields if kind == 'added' else column not in fields if kind == 'removed' else False
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Subscript) and literal(target.slice) == column for target in targets):
            return kind in ('added', 'changed')
        if any(isinstance(target, ast.Attribute) and target.attr == 'columns' for target in targets):
            fields = literal(getattr(node, 'value', None))
            if isinstance(fields, (list, tuple)):
                return column in fields if kind == 'added' else column not in fields if kind == 'removed' else False
    value = getattr(node, 'value', None)
    if kind == 'removed' and isinstance(value, ast.Subscript):
        fields = literal(value.slice)
        return isinstance(fields, (list, tuple)) and column not in fields
    for call in (n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
        if kind == 'reordered' and call.func.attr.startswith('sort'):
            return True
        if kind == 'removed' and call.func.attr == 'drop':
            fields = next((literal(k.value) for k in call.keywords if k.arg == 'columns'), None)
            if fields is not None and column in ([fields] if isinstance(fields, str) else fields):
                return True
    return False
