const {readFileSync,existsSync}=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const {spawnSync}=require('node:child_process');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const ts=require('typescript'),cache={};
function load(name){
  const file=path.resolve(name);if(cache[file])return cache[file];
  const out={};cache[file]=out;
  const localRequire=name=>name.startsWith('.')?load(path.resolve(path.dirname(file),name)+(existsSync(path.resolve(path.dirname(file),name)+'.tsx')?'.tsx':'.ts')):require(name);
  new Function('require','exports',ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText)(localRequire,out);
  return out;
}
const {ReviewWorkspace}=load('src/ReviewWorkspace.tsx');
const {reviewGroups}=load('src/reviewGroups.ts');
const {ColumnOriginDetails}=load('src/ColumnOrigin.tsx');
const runtime=spawnSync(process.env.TRACE_TEST_PYTHON || (existsSync('.venv/Scripts/python.exe')?'.venv/Scripts/python.exe':'python'),['-c',
  "import json;from backend.pipeline import prepare,assemble;from backend.python_runtime import run;from backend.engine import parse_table;from backend.prototype import INPUT;code=\"work=input_df.loc[input_df['status'].eq('done')].copy()\\nwork['total']=work['quantity']*work['unit_price']\\nresult=work.groupby('region',as_index=False)['total'].sum()\";plan=prepare(code,engine='python');print(json.dumps(assemble(run(code,parse_table(INPUT),{},plan),plan)[0]))"
],{encoding:'utf8',timeout:20000});
assert.equal(runtime.status,0,runtime.stderr);
const steps=JSON.parse(runtime.stdout).slice(1),selected=steps.at(-1);
test('composite Step uses its executed column operation for the cell creation explanation',()=>{
  const operation=steps.find(step=>step.params.formulas?.total);
  assert.ok(operation);
  const grouped={...operation,params:{},column_explanations:{},operations:[{
    ...operation,column_explanations:{total:'quantity와 unit_price를 곱해 계산'},
  }]};
  const html=renderToStaticMarkup(React.createElement(ColumnOriginDetails,{stage:grouped,column:'total'}));
  assert.ok(html.includes('quantity · unit_price'));
  assert.ok(html.includes('quantity와 unit_price를 곱해 계산'));
  assert.ok(!html.includes('확인되지 않았습니다'));
});
function render(condition){return renderToStaticMarkup(React.createElement(ReviewWorkspace,{
  condition,steps,selected,busy:false,explanation:'지역별 매출을 합산합니다.',title:()=> '지역별 집계',onSelect:()=>{},onCondition:()=>{},canSwitch:true,version:1,
  before:React.createElement('table',{'data-before':'actual-input'}),after:React.createElement('table',{'data-after':'actual-result'}),
  input:React.createElement('span',null,'전체 입력'),target:React.createElement('span',null,'전체 목표'),
  footer:React.createElement('form',null,React.createElement('textarea',{'aria-label':'자연어 수정 요청'}),React.createElement('button',null,'수정 요청'))}));}
test('both conditions share navigation and explanation, with a footer form only in Ex-situ',()=>{
  for(const condition of ['ex','in-situ']){
    const html=render(condition);assert.equal((html.match(/<textarea/g)||[]).length,condition==='ex'?1:0);
    assert.equal((html.match(/aria-current="step"/g)||[]).length,1);
    assert.equal((html.match(/aria-pressed=/g)||[]).length,2);
    assert.ok(html.includes('지역별 매출을 합산합니다.')&&html.includes('data-after="actual-result"'));
    assert.ok(html.includes('>Input<')&&html.includes('>Target<'));
    assert.ok(!/조건 [ABC]|B2|다음 순서/.test(html));
  }
});
test('Ex-situ shows code and only intermediate output; In-situ shows actual before/after without code',()=>{
  const ex=render('ex'),ins=render('in-situ');
  assert.ok(ex.includes('읽기 전용 Python 코드')&&!ex.includes('data-before='));
  assert.ok(ins.includes('data-before=')&&!ins.includes('python-code')&&!ins.includes('groupby'));
  assert.ok(!ins.includes('정오 판정이 아닙니다')&&!ins.includes('셀을 클릭해 선택하고'));
});
test('real executed aggregation colors only the recorded members and aggregate cells',()=>{
  const groups=reviewGroups(selected);assert.equal(groups.groups.length,2);
  assert.equal(Object.keys(groups.inputRows).length,4);assert.equal(Object.keys(groups.outputCells).length,2);
  assert.equal(new Set(Object.values(groups.inputRows)).size,2);
  const unknown=structuredClone(selected);unknown.trace_level='common';assert.deepEqual(reviewGroups(unknown).groups,[]);
  const invalid=structuredClone(selected);Object.values(invalid.contexts)[0].total.member_rows=['invented'];
  assert.deepEqual(reviewGroups(invalid).groups,[]);
});
