"""Identify verified working copies without changing executable code or history."""
import ast


def _reference(node):
    return isinstance(node,ast.Name) or (
        isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name)
        and node.value.id=='tables' and isinstance(node.slice,ast.Constant)
        and isinstance(node.slice.value,str))


def is_working_copy(stage):
    if stage.get('kind')=='input':return False
    try:statements=ast.parse(stage['code']).body
    except (SyntaxError,KeyError,TypeError):return False
    if not statements:return False
    for statement in statements:
        if not isinstance(statement,ast.Assign) or len(statement.targets)!=1 or not isinstance(statement.targets[0],ast.Name):return False
        value=statement.value
        if isinstance(value,ast.Call):
            if not isinstance(value.func,ast.Attribute) or value.func.attr!='copy' or not _reference(value.func.value):return False
            if any(not isinstance(arg,ast.Constant) or not isinstance(arg.value,bool) for arg in value.args):return False
            if any(arg.arg!='deep' or not isinstance(arg.value,ast.Constant) or not isinstance(arg.value.value,bool) for arg in value.keywords):return False
        elif not _reference(value):return False
    operations=stage.get('operations')
    if operations:return all(is_working_copy(op) for op in operations)
    return stage.get('kind')=='copy' and stage.get('input') is not None and stage['input']==stage.get('table')


def present_run(run):
    if run is None:return None
    def mark(stage):
        result={**stage,'review_hidden':is_working_copy(stage)}
        if 'operations' in stage:result['operations']=[mark(op) for op in stage['operations']]
        return result
    return {**run,'stages':[mark(stage) for stage in run['stages']],
            'operations':[mark(op) for op in run.get('operations',[])]}
