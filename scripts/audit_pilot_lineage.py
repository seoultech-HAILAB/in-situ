"""Check frozen P0 outputs and provenance references in the isolated worker."""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.engine import parse_table,table,compare
from backend.pipeline import prepare,assemble
from backend.isolation import isolated_run


def main():
    inventory={r['task_id']:r for r in json.loads((ROOT/'.local/task_selection_500/inventory.json').read_text(encoding='utf-8'))}
    results=[]
    for file in sorted((ROOT/'.local/pilot/candidates').glob('R500-*.json')):
        c=json.loads(file.read_text(encoding='utf-8-sig'));plan=prepare(c['initial_code'],c['steps'],engine='python')
        records=isolated_run(plan['code'],c['input_csv'],c.get('sources',{}),engine='python',plan=plan)
        stages,_=assemble(records,plan)
        item=inventory[c['provenance']['original_task_id']]
        saved=json.loads((Path(item['folder'])/'output_table.json').read_text(encoding='utf-8'))['data']
        original=table(pd.DataFrame(saved['data'],columns=saved['columns']))
        if not compare(stages[-1]['table'],original)['matches']:raise ValueError(c['id']+': frozen P0 output changed')
        valid=set()
        for name,text in {'input':c['input_csv'],**c.get('sources',{})}.items():
            df=parse_table(text)
            for ix in df.index:
                for col in df.columns:valid.add((name,str(ix) if name=='input' else name+':'+str(ix),str(col)))
        for op in records:
            for cols in op['lineage'].values():
                for refs in cols.values():
                    for ref in refs:
                        if (ref.get('table_id','input'),ref['row_id'],ref['column']) not in valid:raise ValueError(c['id']+': invalid source reference')
        levels=[s['trace_level'] for s in stages[1:]]
        result={'id':c['id'],'output_preserved':True,'trace_levels':levels,
                'source_cells':sum(bool(refs) for s in stages[1:] for cols in s['lineage'].values() for refs in cols.values()),
                'limitations':[s['trace_reason'] for s in stages[1:] if s.get('trace_reason')]}
        results.append(result)
        c.setdefault('researcher_notes',{})['initial_trace_levels']=levels
        c['researcher_notes']['native_provenance_audit']=result
        temp=file.with_suffix('.tmp');temp.write_text(json.dumps(c,ensure_ascii=False),encoding='utf-8');temp.replace(file)
        print(json.dumps(result,ensure_ascii=True),flush=True)
    (ROOT/'.local/pilot/lineage-audit.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
