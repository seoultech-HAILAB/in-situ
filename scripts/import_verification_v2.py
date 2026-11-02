"""Import the reviewed v2 pool privately, with no model calls or overwrites."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import candidates
from backend.engine import parse_table
from backend.pipeline import prepare


def import_pool(source,include_superseded=False):
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8-sig'))
    successor=ROOT/'output/natural_hard_audit_20261102/active_manifest.json'
    if not include_superseded and source.resolve()==(ROOT/'output/verification_task_selection_v2_20261102').resolve() and successor.exists():
        retired=set(json.loads(successor.read_text(encoding='utf-8'))['replacement_map'])
        manifest=[item for item in manifest if item['id'] not in retired]
    pending=[]
    for item in manifest:
        file=source/'cases'/item['id']/'candidate.json'
        raw=file.read_bytes();data=json.loads(raw.decode('utf-8-sig'))
        if hashlib.sha256(raw).hexdigest()!=item['candidate_sha256']:raise ValueError('Candidate hash mismatch: '+item['id'])
        if data['id']!=item['id'] or data.get('participant_enabled') is not False or data.get('selected_for_study') is not False:
            raise ValueError('Expected private, unselected candidate: '+item['id'])
        if data['researcher_notes']['fault_steps']!=item['fault_steps']:raise ValueError('Fault key mismatch')
        plan=prepare(data['initial_code'],data['steps'],engine='python')
        prepare(data['reference_code'],data['reference_steps'],engine='python')
        if len(plan['steps'])!=item['steps']:raise ValueError('Semantic Step count mismatch')
        for csv in [data['input_csv'],data['target_csv'],*data.get('sources',{}).values()]:parse_table(csv)
        existing=candidates.directory()/(data['id']+'.json')
        if existing.exists():
            saved=candidates.load(data['id'])
            normalized={**data,'enabled':True,'participant_enabled':False,'provenance':{
                'initial_origin':'stored_code','original_task_id':data['id'],'actual_luna_program':None,**data.get('provenance',{})}}
            if any(saved.get(key)!=value for key,value in normalized.items()):raise ValueError('Existing task differs; refusing overwrite: '+data['id'])
        pending.append((item,data,existing.exists()))
    result=[]
    for item,data,exists in pending:
        if not exists:candidates.register(data)
        result.append({'id':data['id'],'action':'unchanged' if exists else 'registered',
                       'source_sha256':item['candidate_sha256'],'participant_enabled':False,
                       'selected_for_study':False,'steps':item['steps']})
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=ROOT/'output/verification_task_selection_v2_20261102')
    parser.add_argument('--include-superseded',action='store_true',help='Explicitly restore retired composite Hard candidates')
    opts=parser.parse_args()
    report={'source':str(opts.source.resolve()),'initial_model_calls':0,'candidates':import_pool(opts.source,opts.include_superseded)}
    destination=ROOT/'.local/pilot/verification-v2-import.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'imported_or_verified':len(report['candidates']),'report':str(destination)},ensure_ascii=True))
