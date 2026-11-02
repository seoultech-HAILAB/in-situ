"""A table-only prototype contract, separate from frozen pilot/study tasks."""
from typing import Literal
from pydantic import BaseModel,Field

MODE='prototype-v1'
CONDITIONS={'ex':'ex-situ-review-v2','in-situ':'in-situ-review-v2'}
INPUT='''order_id,region,status,quantity,unit_price
O1,Busan,done,2,10
O2,Seoul,done,3,10
O3,Busan,cancelled,4,10
O4,Seoul,done,1,20
O5,Busan,done,3,20
O6,Seoul,pending,2,30
'''
TARGET='''region,total
Busan,80
Seoul,50
'''


class PrototypeTables(BaseModel):
    model_config={'extra':'forbid'}
    input_csv:str=Field(min_length=1,max_length=1_000_000)
    target_csv:str=Field(min_length=1,max_length=1_000_000)
    sources:dict[str,str]=Field(default_factory=dict,max_length=4)
    condition:Literal['ex','in-situ']='in-situ'
