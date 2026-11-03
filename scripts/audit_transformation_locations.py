"""Audit AST transformation coverage without executing code or calling a model."""
import ast
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.pipeline import prepare


def audit():
    tasks=[]
    for file in sorted((ROOT/'tasks/candidates').glob('*.json')):
        candidate=json.loads(file.read_text(encoding='utf-8-sig'))
        if 'initial_code' not in candidate:continue
        plan=prepare(candidate['initial_code'],candidate['steps'],engine='python')
        steps=[]
        for step in plan['steps']:
            items=step['transformations']
            steps.append({'lines':step['code_location'],'transformations':len(items),
                          'locations':[t['code_location'] for t in items]})
        tasks.append({'task':candidate['id'],'steps':steps})
    return {'tasks':len(tasks),'steps':sum(len(t['steps']) for t in tasks),
            'transformations':sum(s['transformations'] for t in tasks for s in t['steps']),
            'steps_with_individual_locations':sum(s['transformations']>0 for t in tasks for s in t['steps']),
            'details':tasks}


if __name__=='__main__':
    result=audit()
    if '--json' in sys.argv: print(json.dumps(result,ensure_ascii=False,indent=2))
    else: print(json.dumps({k:v for k,v in result.items() if k!='details'}))
