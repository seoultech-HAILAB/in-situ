"""Audit restored P0 artifacts; replay only compact completed incorrect programs in the app worker."""
import argparse
import ast
import collections
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.analyze_p0_synth import read_frame
from scripts.build_synth_candidates import frame_csv
from backend.engine import parse_table,table,compare
from backend.pipeline import prepare,assemble
from backend.isolation import isolated_run


def wrapper(program,table_count):
    mapping=["'table_1': input_df"]+[f"'table_{i}': tables['source_{i}']" for i in range(2,table_count+1)]
    return program.rstrip()+'\n\nresult = transform({'+', '.join(mapping)+'})\n'


def replay(program,inputs,groups=None):
    inp=inputs[0];sources={f'source_{i}':value for i,value in enumerate(inputs[1:],2)}
    if groups is None:
        groups=[{'statement_indices':list(range(len(ast.parse(program).body))),'output_variable':'result','label':'원본 프로그램 실행'}]
    plan=prepare(program,groups,engine='python')
    stages,ops=assemble(isolated_run(program,inp,sources,engine='python',plan=plan),plan)
    return plan,stages


def audit(inventory,run_root,out):
    rows=json.loads((run_root/'results.json').read_text(encoding='utf-8'))
    metadata={r['task_id']:r for r in json.loads(inventory.read_text(encoding='utf-8'))}
    results=[];schema_only_prompts=0;first20_prompts=0
    for original in rows:
        tid=original['task_id'];r=metadata[tid]
        assert original['condition']=='P0' and original['matched']==r['p0_recorded_matches']
        folder=run_root/'runs'/tid/str(original['seed'])/'P0'
        prompt=json.loads((folder/'prompt.json').read_text(encoding='utf-8'))
        system='\n'.join(p['content'] for p in prompt if p['role']=='system')
        user='\n'.join(p['content'] for p in prompt if p['role']=='user')
        schema_only_prompts+=('Target schema:' in user and 'No target values.' in user)
        first20_prompts+=('first 20 rows' in system and 'tables_first20_csv' in user)
        source=folder/'program.py'
        result={'task_id':tid,'cohort':original['cohort'],'original_status':original['status'],
            'original_completed':original['workflow_completed'],'original_matched':original['matched'],
            'original_model_calls':original['model_calls'],'program_available':source.exists(),
            'program_path':str(source),'compact':r.get('compact',False),
            'structural_exclusions':r.get('structural_exclusions',[])}
        if source.exists():result['program_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
        if not (original['workflow_completed'] and not original['matched'] and r.get('compact') and not r.get('structural_exclusions')):
            result['replay_status']='not_selected_for_replay';results.append(result);continue
        try:
            data_folder=Path(r['manifest']).parent
            inputs=[frame_csv(read_frame(data_folder/f)) for f in r['inputs']]
            target_csv=frame_csv(read_frame(data_folder/r['target']))
            program=source.read_text(encoding='utf-8-sig')
            code=wrapper(program,len(inputs))
            _,stages=replay(code,inputs)
            saved=json.loads((folder/'output_table.json').read_text(encoding='utf-8'))['data']
            saved_table=table(pd.DataFrame(saved['data'],columns=list(map(str,saved['columns']))))
            same_saved=compare(stages[-1]['table'],saved_table)['matches']
            matches_target=compare(stages[-1]['table'],table(parse_table(target_csv)))['matches']
            result.update(replay_status='completed',same_as_archived_output=same_saved,
                current_target_match=matches_target,output_rows=len(stages[-1]['table']['rows']),
                target_rows=len(parse_table(target_csv)),csv_roundtrip_verified=True)
        except Exception as exc:
            result.update(replay_status='unavailable_in_current_app',replay_error=str(exc)[:1200])
        results.append(result)
        print(json.dumps({k:result.get(k) for k in ('task_id','replay_status','same_as_archived_output','current_target_match','replay_error')}),flush=True)
    summary={'technical_tasks':len(rows),'original_completed':sum(r['workflow_completed'] for r in rows),
        'original_correct':sum(r['matched'] for r in rows),
        'original_completed_incorrect':sum(r['workflow_completed'] and not r['matched'] for r in rows),
        'original_failed':sum(not r['workflow_completed'] for r in rows),
        'model_call_counts':dict(collections.Counter(r['model_calls'] for r in rows)),
        'programs_available':sum(r['program_available'] for r in results),
        'replay_counts':dict(collections.Counter(r['replay_status'] for r in results)),
        'replays_matching_saved_output':sum(r.get('same_as_archived_output',False) for r in results),
        'replayed_and_still_incorrect':sum(r.get('same_as_archived_output',False) and not r.get('current_target_match',True) for r in results),
        'new_model_calls':0,'original_prompt_target':'schema_only_no_target_values',
        'schema_only_prompts_verified':schema_only_prompts,'first20_prompts_verified':first20_prompts,
        'original_prompt_input':'first20_and_full_metadata; full_frames_at_execution'}
    out.mkdir(parents=True,exist_ok=True)
    (out/'original_program_audit.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'original_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inventory',type=Path,required=True)
    p.add_argument('--run-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();audit(a.inventory,a.run_root,a.out)
