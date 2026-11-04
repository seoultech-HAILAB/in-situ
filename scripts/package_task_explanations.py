"""Package model explanations for every fixed task; never generate/repair code.

Uses existing cached explanations where possible. Missing explanations call the
configured model with code/Step metadata only, under backend.explanations' policy.
"""
import json
import hashlib
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import app as server  # loads the local, ignored .env
from backend import explanations
from backend.pipeline import prepare,assemble
from backend.isolation import isolated_run


def main():
    manifest_file=ROOT/'tasks/manifest.json'
    manifest=json.loads(manifest_file.read_text(encoding='utf-8'))
    output=ROOT/'tasks/explanations';output.mkdir(exist_ok=True)
    entries=[]
    for source in sorted((ROOT/'tasks/candidates').glob('*.json')):
        c=json.loads(source.read_text(encoding='utf-8-sig'))
        plan=prepare(c['initial_code'],c['steps'],engine='python')
        records=isolated_run(plan['code'],c['input_csv'],c.get('sources',{}),engine='python',plan=plan)
        stages,operations=assemble(records,plan)
        run={'code':plan['code'],'stages':stages,'operations':operations}
        bundle,cached=explanations.obtain(run)
        artifact={key:bundle[key] for key in ('prompt_version','model','generated_at','steps','columns')}
        if 'transformations' in bundle:artifact['transformations']=bundle['transformations']
        if 'transformation_contract' in bundle:artifact['transformation_contract']=bundle['transformation_contract']
        artifact['observation_sha256']=explanations.observation_fingerprint(run)
        file=output/(artifact['observation_sha256']+'.json')
        file.write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        entries.append({'task_id':c['id'],'file':'explanations/'+file.name,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
        print(c['id'], 'cached' if cached else 'model-generated',flush=True)
    manifest['explanations']=entries
    manifest_file.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Packaged explanations:',len(entries))

if __name__=='__main__':main()
