"""Snapshot actual pandas table-combination operands, including loop iterations.

Observe the original native calls; never evaluate/replay an expression or consume
an iterator to discover its inputs. This metadata is for plain input cards only.
"""
import ast
import json

import pandas as pd

from .runtime import table, clean
from .statement_observations import location

VERSION = 'native-table-calls-v2'


def call_key(node):
    return (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)


def contributing_expressions(nodes, output, executed=None, kinds=(ast.Call,)):
    """Local backward slice down to assignments inside a loop/branch."""
    selected = set()

    def names(node):
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}

    def use(node):
        selected.update(call_key(n) for n in ast.walk(node) if isinstance(n, kinds))
        return names(node)

    def block(statements, live):
        live = set(live)
        for node in reversed(statements):
            if executed is not None and node.lineno not in executed:
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                roots = {n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name)}
                if roots & live:
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        live -= {target.id for target in targets if isinstance(target, ast.Name)}
                    live.update(use(node))
            elif isinstance(node, (ast.For, ast.While)):
                before = set(live)
                while True:
                    expanded = before | block(node.body, before) | block(node.orelse, before)
                    if expanded == before:
                        break
                    before = expanded
                if before != live or any(call_key(n) in selected for n in ast.walk(node) if isinstance(n, ast.Call)):
                    before.update(use(node.iter if isinstance(node, ast.For) else node.test))
                live = before
            elif isinstance(node, ast.If):
                body = executed is None or any(n.lineno in executed for n in node.body)
                otherwise = executed is None or any(n.lineno in executed for n in node.orelse)
                if body and not otherwise:
                    before = block(node.body, live)
                elif otherwise and not body:
                    before = block(node.orelse, live)
                else:
                    before = block(node.body, live) | block(node.orelse, live)
                if before != live:
                    before.update(use(node.test))
                live = before
            elif isinstance(node, ast.Try):
                live = block(node.finalbody, live)
                live = block(node.body, live) | block(node.orelse, live) | set().union(*(block(h.body, live) for h in node.handlers))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                root = call.func.value if isinstance(call.func, ast.Attribute) else None
                mutates = isinstance(root, ast.Name) and root.id in live and (call.func.attr in ('append', 'extend', 'update', 'insert')
                    or any(kw.arg == 'inplace' and isinstance(kw.value, ast.Constant) and kw.value.value is True for kw in call.keywords))
                if mutates:
                    live.update(use(node))
        return live

    block(nodes, {output} if output else set())
    return selected


def contributing_calls(nodes, output, executed=None):
    return contributing_expressions(nodes, output, executed)


class TableCallObservations:
    def __init__(self, code, step_id):
        self.code = code; self.step_id = step_id
        self.kinds = {pd.DataFrame.merge.__code__: 'merge', pd.merge.__code__: 'merge',
                      pd.DataFrame.join.__code__: 'join', pd.concat.__code__: 'concat'}
        self.calls = {call_key(n): n for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Call)}
        self.positions = {}; self.pending = {}; self.records = []; self.bytes = 0; self.limited = False

    def observe(self, frame, event, result, statement_index):
        if event not in ('call', 'return') or frame.f_code not in self.kinds:
            return
        if event == 'return':
            record = self.pending.pop(id(frame), None)
            if record and isinstance(result, pd.DataFrame):
                self.records.append(record)
            return
        caller = frame.f_back
        if not caller or caller.f_code.co_filename != '<trace-program>':
            return  # Internal pandas calls are part of the same native operation.
        if len(self.records) >= 128 or self.bytes > 16_000_000:
            self.limited = True; return
        positions = self.positions.get(caller.f_code)
        if positions is None:
            positions = self.positions[caller.f_code] = list(caller.f_code.co_positions())
        position = positions[caller.f_lasti // 2]
        node = self.calls.get(position)
        if node is None:
            return  # Never guess between different calls on the same line.
        values = frame.f_locals; kind = self.kinds[frame.f_code]
        selectors=None
        if kind == 'concat':
            operands = values.get('objs')
            if isinstance(operands, dict):
                keys=values.get('keys')
                if keys is None:keys=list(operands)
                if not isinstance(keys,(list,tuple,pd.Index)):
                    return
                selectors=list(keys)
                operands = [operands[key] for key in keys]
            if not isinstance(operands, (list, tuple)):
                return  # Do not consume a generator or user iterator.
        else:
            left = values.get('self', values.get('left'))
            right = values.get('right') if kind == 'merge' else values.get('other')
            operands = [left, *(right if isinstance(right, (list, tuple)) else [right])]
        if len(operands) < 2 or not all(isinstance(value, (pd.DataFrame, pd.Series)) for value in operands):
            return
        inputs = []
        for index, value in enumerate(operands):
            data = value.to_frame() if isinstance(value, pd.Series) else value
            self.bytes += int(data.memory_usage(deep=True).sum())
            if self.bytes > 16_000_000:
                self.limited = True; return
            inputs.append({'ref': f'native-call:{self.step_id}:{len(self.records)}:{index}',
                           'table': table(data, [f'operand:{index}:{i}' for i in range(len(data))])})
            if kind=='concat':inputs[-1]['operand_key']=clean(selectors[index] if selectors is not None else index)
        arguments = {key: values[key] for key in ('how', 'on', 'left_on', 'right_on', 'left_index', 'right_index', 'axis') if key in values}
        record = dict(id=f'{self.step_id}/table-call-{len(self.records)}', kind=kind, statement_index=statement_index,
                      code=ast.get_source_segment(self.code, node), code_location=location(node), expression_location=location(node),
                      params={'how': arguments.get('how'), 'keys': arguments.get('on') or arguments.get('left_on'), 'arguments': arguments}, inputs=inputs)
        # Copy only display data; a tracing failure never changes execution.
        self.pending[id(frame)] = json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False,
            default=lambda value: str(value) if isinstance(value, (pd.Period, pd.Interval)) else value))
