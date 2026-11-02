const {readFileSync,existsSync}=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const ts=require('typescript'),cache={};
function load(name){
  const filename=path.resolve(name);if(cache[filename])return cache[filename];
  const exports={};cache[filename]=exports;
  const localRequire=name=>name.startsWith('.')?load(path.resolve(path.dirname(filename),name)+(existsSync(path.resolve(path.dirname(filename),name)+'.tsx')?'.tsx':'.ts')):require(name);
  new Function('require','exports',ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText)(localRequire,exports);
  return exports;
}
const {ReviewWorkspace}=load('src/ReviewWorkspace.tsx');
const {InitialStepJudgment}=load('src/InitialStepJudgment.tsx');
const {reviewGroups}=load('src/reviewGroups.ts');
const {tableChanges}=load('src/tableChanges.ts');
const fixturesPath='.local/woz-v2-validation/ui-fixtures.json';
test('executed 8/9-Step Hard retains every navigation item and full selected code in Ex; common trace invents no lineage', {skip:!existsSync(fixturesPath)},()=>{
  const fixtures=JSON.parse(readFileSync(fixturesPath,'utf8'));assert.equal(fixtures.length,2);
  for(const fixture of fixtures){
    const steps=fixture.run.stages.slice(1);assert.ok([8,9].includes(steps.length));
    for(const selected of steps)for(const condition of ['ex','in-situ']){
      const html=renderToStaticMarkup(React.createElement(ReviewWorkspace,{condition,steps,selected,busy:false,
        explanation:'현재 실행 코드의 설명',title:step=>step.intent_label||step.label,onSelect(){},onCondition(){},canSwitch:true,version:1,
        before:React.createElement('table',{'data-test':'input'}),after:React.createElement('table',{'data-test':'output'}),input:null,target:null,footer:null}));
      const nav=html.match(/<nav[^>]*>[\s\S]*?<\/nav>/)[0];
      assert.equal((nav.match(/<button/g)||[]).length,steps.length);
      assert.equal((nav.match(/aria-current="step"/g)||[]).length,1);
      assert.ok(nav.includes('>'+steps.length+'</span>'));
      assert.equal(html.includes('읽기 전용 Python 코드'),condition==='ex');
      if(condition==='ex'){
        const code=html.match(/<code>([\s\S]*?)<\/code>/)[1].replace(/<[^>]+>/g,'').replace(/&#x27;/g,"'").replace(/&quot;/g,'"').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
        assert.equal(code,selected.code);
      }
      assert.equal(html.includes('data-test="input"'),condition==='in-situ');
      assert.deepEqual(reviewGroups(selected).groups,[]);
      const delta=tableChanges(selected);if(delta){assert.equal(delta.rowIdentity,false);assert.equal(delta.changedCells.size,0);assert.equal(delta.removedRows.length,0);}
    }
    const html=renderToStaticMarkup(React.createElement(InitialStepJudgment,{session:{review_baseline:fixture.baseline,run:fixture.run,condition:'ex',id:'preview'},api(){},busy:false}));
    assert.ok(html.includes('오류 없음')&&html.includes('판단 어려움'));
    assert.ok(!html.includes('fault_steps')&&!html.includes('정답')&&!html.includes('오류 2개'));
    const multi=renderToStaticMarkup(React.createElement(InitialStepJudgment,{session:{review_baseline:fixture.baseline,run:fixture.run,condition:'ex',id:'preview',initial_step_judgments:[{condition:'ex',answer:'steps',step_ids:[steps[0].id,steps[2].id]}]},api(){},busy:false}));
    assert.equal((multi.match(/type="checkbox"/g)||[]).length,steps.length);
    assert.equal((multi.match(/type="checkbox" checked=""/g)||[]).length,2);
  }
});
