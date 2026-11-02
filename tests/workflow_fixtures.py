"""Generate synthetic UI observations directly, without a server or saved logs."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.pipeline import prepare,assemble
from backend.python_runtime import run
from backend.engine import parse_table
from backend.generator import DEMO_INPUT,demo_code

csv=(ROOT/'examples/long-workflow.csv').read_text(encoding='utf-8')
code=(ROOT/'examples/long-workflow.py').read_text(encoding='utf-8')
eight='\n'.join(line for line in code.splitlines() if line and not line.startswith('#'))
six='\n'.join(eight.splitlines()[:5]+["result = s5.sort_values(['amount'], ascending=False, kind='stable')"])
programs={
 'short2':"s1 = input_df.fillna({'quantity': 0})\nresult = s1[['order_id', 'quantity']]",
 'short3':demo_code(),'long6':six,'long8':eight,
 'common':"s1 = input_df.assign(quantity=input_df['quantity'].apply(lambda v: 0 if pd.isna(v) else v * 2))\nresult = s1[['order_id','quantity']]",
}
result={}
for name,program in programs.items():
 plan=prepare(program,engine='python')
 stages,_=assemble(run(program,parse_table(DEMO_INPUT if name=='short3' else csv),{},plan),plan)
 result[name]={'run':{'stages':stages}}
print(json.dumps(result))
