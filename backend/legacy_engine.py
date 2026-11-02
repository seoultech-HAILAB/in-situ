"""CSV validation and ordered target comparison; no execution backend."""
import csv
import io
import math
import pandas as pd


class Unsupported(ValueError):
    pass


def parse_table(text):
    if not text.strip() or len(text.encode('utf-8')) > 1_000_000:
        raise ValueError('비어 있거나 1 MB를 넘는 표입니다.')
    text = text.lstrip('\ufeff')
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=',\t;')
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if r]
    headers = rows[0]
    if any(not h.strip() for h in headers) or len(set(headers)) != len(headers):
        raise ValueError('열 이름은 비어 있지 않고 중복되지 않아야 합니다.')
    if any(len(r) != len(headers) for r in rows[1:]):
        raise ValueError('모든 행의 셀 개수가 열 이름의 개수와 같아야 합니다.')
    if len(rows) > 501 or len(headers) > 32:
        raise ValueError('표는 데이터 0–500행, 1–32열을 지원합니다.')
    frame = pd.read_csv(io.StringIO(text), sep=dialect.delimiter, keep_default_na=False, na_values=[''])
    frame.index = [f'r{i + 1:04d}' for i in range(len(frame))]
    return frame


def compare(output, target):
    same_columns = output['columns'] == target['columns']
    differences = []
    for i in range(max(len(output['rows']), len(target['rows']))):
        a = output['rows'][i]['values'] if i < len(output['rows']) else {}
        b = target['rows'][i]['values'] if i < len(target['rows']) else {}
        for c in dict.fromkeys(output['columns'] + target['columns']):
            av, bv = a.get(c), b.get(c)
            eq = (c in a and c in b and (av == bv or (isinstance(av, (int, float)) and isinstance(bv, (int, float)) and math.isclose(av, bv, rel_tol=1e-9, abs_tol=1e-9))))
            if not eq:
                differences.append({'row': i + 1, 'column': c, 'actual': av, 'expected': bv})
    return {'matches': same_columns and not differences and len(output['rows']) == len(target['rows']),
            'same_columns': same_columns, 'differences': differences,
            'policy': '현재 입력의 기대 출력과 행·열 순서를 포함해 비교합니다. 수치 오차 1e−9.'}
