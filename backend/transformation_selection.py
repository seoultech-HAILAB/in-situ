"""Keep explanation dependencies read-only when revising one selected operation."""
import ast
import copy
from .transformations import annotate_run


def selected_transformation(run,context):
    tid=context.get('transformation_id')
    if tid is None:return None
    if not run or not isinstance(tid,str):raise ValueError('현재 실행의 연산을 선택하세요.')
    if context.get('execution_version',run['id'])!=run['id']:raise ValueError('선택한 연산의 실행 버전이 바뀌었습니다.')
    view=annotate_run({**run,'stages':[dict(s) for s in run['stages']]})
    stage=next((s for s in view['stages'] if s['id']==context.get('step_id')),None)
    item=next((t for t in (stage or {}).get('transformations',[]) if t['id']==tid and t.get('contributes_to_output') is not False),None)
    if item is None:raise ValueError('선택한 연산이 현재 Step에 없습니다. 다시 선택하세요.')
    return {'id':item['id'],'step_id':stage['id'],'execution_version':run['id'],'code_version':run['code_version'],
            'code':item['code'],'code_location':item['code_location'],'output_columns':item['output_columns'],
            'syntax_only':item['syntax_only']}


def validate_selected_edit(code,previous,selection,scope):
    if selection is None or scope!='step':return
    old=ast.parse(previous['code']);new=ast.parse(code);loc=selection['code_location']
    found=None
    def visit(node,path):
        nonlocal found
        if all(getattr(node,attr,None)==loc[key] for attr,key in (('lineno','start'),('end_lineno','end'),('col_offset','start_column'),('end_col_offset','end_column'))):found=path
        for key,value in ast.iter_fields(node):
            if isinstance(value,ast.AST):visit(value,path+[(key,None)])
            elif isinstance(value,list):
                for i,child in enumerate(value):
                    if isinstance(child,ast.AST):visit(child,path+[(key,i)])
    visit(old,[])
    if not found:raise ValueError('현재 연산의 원본 코드 위치를 확인하지 못했습니다.')
    def mask(tree):
        tree=copy.deepcopy(tree);node=tree
        try:
            for field,index in found[:-1]:node=getattr(node,field) if index is None else getattr(node,field)[index]
            field,index=found[-1]
            if index is None:setattr(node,field,ast.Constant(value='selected-operation'))
            else:getattr(node,field)[index]=ast.Constant(value='selected-operation')
            return ast.dump(tree,include_attributes=False)
        except (AttributeError,IndexError,TypeError):return None
    if mask(old)!=mask(new):
        raise ValueError('현재 선택한 연산 밖의 코드가 변경되었습니다. 더 넓은 수정이 필요하면 자연어 요청에 명시하세요.')
