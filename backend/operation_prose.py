"""Check operation prose against the displayed local code, without upstream tracing."""
import ast
import re


def operation_local_text(text,transform,columns):
    """A description cannot borrow named fields/actions from other operations."""
    code=transform['code']
    if re.search(r'코드에\s*지정(?:된|한)\s*계산\s*결과|계산 결과을',text):return False
    allowed=set(transform.get('output_columns',[])+transform.get('input_columns',[])+transform.get('removed_columns',[]))
    try:tree=ast.parse(code)
    except SyntaxError:tree=None
    code_columns={node.value for node in ast.walk(tree) if isinstance(node,ast.Constant) and isinstance(node.value,str)} if tree else set()
    allowed.update(code_columns)
    latin=sorted({column for column in columns if re.search(r'[A-Za-z]',column)},key=lambda column:(-len(column),column))
    if latin:
        names=r'(?<![A-Za-z0-9_])(?:'+'|'.join(re.escape(column) for column in latin)+r')(?![A-Za-z0-9_])'
        if any(match.group() not in allowed for match in re.finditer(names,text)):return False
    for column in columns:
        if column in allowed or column in latin:continue
        if re.search(r'[“\"\x27`]'+re.escape(column)+r'[”\"\x27`]|'+re.escape(column)+r'\s*(?:열|컬럼)',text):return False
    if tree is None:return True
    calls={node.func.attr if isinstance(node.func,ast.Attribute) else node.func.id if isinstance(node.func,ast.Name) else ''
           for node in ast.walk(tree) if isinstance(node,ast.Call)}
    if re.search(r'분할|분리|나눈|나눠|쉼표',text) and not any('split' in name or 'partition' in name or name=='extract' for name in calls) and not any(isinstance(node,(ast.Div,ast.FloorDiv)) for node in ast.walk(tree)):
        return False
    if '정렬' in text and not any('sort' in name or name in ('nlargest','nsmallest') for name in calls):return False
    return True
