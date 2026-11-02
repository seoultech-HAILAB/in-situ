"""Create fresh localhost-only UI fixtures; never generate or modify code with an LLM."""
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / '.local' / 'workflow-validation'
DEST.mkdir(parents=True, exist_ok=True)


def post(path, data):
    req = urllib.request.Request('http://127.0.0.1:8000/api' + path,
        data=json.dumps(data).encode(), headers={'Content-Type': 'application/json', 'X-Trace-View': 'researcher'})
    with urllib.request.urlopen(req) as response:
        return json.load(response)


def main():
    code = (ROOT / 'examples/long-workflow.py').read_text(encoding='utf-8')
    csv = (ROOT / 'examples/long-workflow.csv').read_text(encoding='utf-8')
    eight = '\n'.join(line for line in code.splitlines() if line and not line.startswith('#'))
    six = '\n'.join(eight.splitlines()[:5] + ["result = s5.sort_values(['amount'], ascending=False, kind='stable')"])
    fixtures = {
        'short2': "s1 = input_df.fillna({'quantity': 0})\nresult = s1[['order_id', 'quantity']]",
        'long6': six, 'long8': eight,
        'common': "s1 = input_df.assign(quantity=input_df['quantity'].apply(lambda v: 0 if pd.isna(v) else v * 2))\nresult = s1[['order_id','quantity']]",
    }
    index = {}
    for name, program in fixtures.items():
        session = post('/sessions', {'input_csv': csv, 'target_csv': 'area,total\nBusan,71000\nSeoul,57000\nDaegu,57000',
            'task_id': f'ui-validation-{name}', 'condition': 'C', 'execution_engine': 'python',
            'requirements': 'UI 검증용 합성 데이터. 실제 실행의 단계별 변화를 확인하세요.'})
        result = post(f"/sessions/{session['id']}/research-code", {'code': program, 'execution_engine': 'python'})
        assert result['status'] == 'ready', result.get('error')
        (DEST / f'{name}.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        index[name] = {'session': session['id'], 'steps': len(result['run']['stages']) - 1}
    demo = post('/demo', {'condition': 'C'})
    (DEST / 'short3.json').write_text(json.dumps(demo, ensure_ascii=False), encoding='utf-8')
    index['short3'] = {'session': demo['id'], 'steps': len(demo['run']['stages']) - 1}
    (DEST / 'index.json').write_text(json.dumps(index, indent=2), encoding='utf-8')
    print(json.dumps(index))


if __name__ == '__main__':
    main()
