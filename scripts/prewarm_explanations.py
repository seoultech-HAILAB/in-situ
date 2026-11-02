"""Generate real LLM prose for frozen candidates without creating participant logs."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import backend.app # Server configuration loader; never prints credentials.
from backend import candidates,explanations
from backend.isolation import isolated_run
from backend.pipeline import prepare,assemble


def warm(cid):
    c=candidates.load(cid);plan=prepare(c['initial_code'],c['steps'],engine='python')
    records=isolated_run(plan['code'],c['input_csv'],c.get('sources',{}),engine='python',plan=plan)
    stages,_=assemble(records,plan);run={'code':plan['code'],'stages':stages}
    bundle,cached=explanations.obtain(run)
    result={'task_id':cid,'model':bundle['model'],'cache_hit':cached,'fingerprint':bundle['fingerprint'],
        'steps':bundle['steps'],'usage':bundle.get('usage'),'response_id':bundle.get('response_id')}
    print(json.dumps({'task_id':cid,'steps':len(bundle['steps']),'cache_hit':cached,'model':bundle['model'],
        'example':bundle['steps'][0]},ensure_ascii=True),flush=True)
    return result


def main():
    args=argparse.ArgumentParser();args.add_argument('--task',required=True);opts=args.parse_args()
    ids=[opts.task]
    results=[];errors=[]
    for cid in ids:
        try:results.append(warm(cid))
        except Exception as exc:
            error={'task_id':cid,'error':str(exc)};errors.append(error);print(json.dumps(error,ensure_ascii=True),flush=True)
    output=ROOT/'.local/pilot/explanation-prewarm.json'
    output.write_text(json.dumps({'results':results,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ready':len(results),'failed':len(errors),'actual_model_calls':sum(not r['cache_hit'] for r in results)}),flush=True)
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
