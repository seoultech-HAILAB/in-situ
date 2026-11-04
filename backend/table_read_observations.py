"""Snapshot source-table reads at their actual executed subscription instruction.

The tables dictionary and program stay unchanged. Do not evaluate an expression,
replay a statement, or infer a read from the whole Step's conservative inputs.
"""
import ast
import dis

import pandas as pd

from .runtime import table
from .statement_observations import location
from .table_call_observations import call_key


class TableReadObservations:
    def __init__(self, code, step_id):
        self.code=code;self.step_id=step_id;self.records=[];self.pending={};self.positions={};self.bytes=0;self.limited=False
        self.sites={call_key(node):node for node in ast.walk(ast.parse(code))
                    if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name) and isinstance(node.ctx,ast.Load)}

    def observe(self, frame, event, statement_index):
        if frame.f_code.co_filename!='<trace-program>':return
        if event=='call':
            frame.f_trace_opcodes=True
            return
        identity=id(frame)
        if event in ('exception','return'):
            self.pending.pop(identity,None)
            return
        if event!='opcode':return
        completed=self.pending.pop(identity,None)
        if completed:self.records.append(completed)
        opname=dis.opname[frame.f_code.co_code[frame.f_lasti]]
        if opname not in ('BINARY_SUBSCR','BINARY_OP'):return
        positions=self.positions.get(frame.f_code)
        if positions is None:
            positions=self.positions[frame.f_code]=list(frame.f_code.co_positions())
        node=self.sites.get(positions[frame.f_lasti//2])
        if node is None:return
        source=frame.f_locals.get(node.value.id)
        if not isinstance(source,dict) or source is not frame.f_globals.get('tables'):return
        key=node.slice.value if isinstance(node.slice,ast.Constant) else frame.f_locals.get(node.slice.id) if isinstance(node.slice,ast.Name) else None
        if not isinstance(key,str):return
        value=source.get(key)
        if not isinstance(value,pd.DataFrame):return
        if len(self.records)>=128 or self.bytes>16_000_000:
            self.limited=True;return
        self.bytes+=int(value.memory_usage(deep=True).sum())
        if self.bytes>16_000_000:
            self.limited=True;return
        self.pending[identity]={'name':key,'statement_index':statement_index,
            'code':ast.get_source_segment(self.code,node),'code_location':location(node),
            'table':table(value,[f'source-read:{self.step_id}:{key}:{i}' for i in range(len(value))])}
