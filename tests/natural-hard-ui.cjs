const {readFileSync,existsSync}=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const ts=require('typescript'),cache={};
function load(name){
  const file=path.resolve(name);if(cache[file])return cache[file];const exports={};cache[file]=exports;
  const localRequire=name=>name.startsWith('.')?load(path.resolve(path.dirname(file),name)+(existsSync(path.resolve(path.dirname(file),name)+'.tsx')?'.tsx':'.ts')):require(name);
  new Function('require','exports',ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText)(localRequire,exports);
  return exports;
}
test('natural Hard keeps real 3/4 semantic Steps, identical navigation, and researcher-only source descriptions',{skip:!existsSync('output/natural_hard_audit_20261102/cases')},()=>{
  const {ReviewWorkspace}=load('src/ReviewWorkspace.tsx');
  const {TaskCatalog}=load('src/TaskCatalog.tsx');
  const root='output/natural_hard_audit_20261102/cases';
  const tasks=[];
  for(const id of ['VERIFY3-H1-A','VERIFY3-H1-B','VERIFY3-H2-A','VERIFY3-H2-B']){
    const candidate=JSON.parse(readFileSync(`${root}/${id}/candidate.json`,'utf8'));
    const stages=JSON.parse(readFileSync(`${root}/${id}/initial_trace.json`,'utf8')).slice(1);
    assert.equal(stages.length,id.includes('H1')?4:3);
    for(const selected of stages)for(const condition of ['ex','in-situ']){
      const html=renderToStaticMarkup(React.createElement(ReviewWorkspace,{condition,steps:stages,selected,busy:false,
        explanation:'현재 코드 동작 설명',title:stage=>stage.label,onSelect(){},onCondition(){},canSwitch:true,version:1,
        before:React.createElement('table',{'data-before':'observed'}),after:React.createElement('table',{'data-after':'observed'}),input:null,target:null,footer:null}));
      const nav=html.match(/<nav[^>]*>[\s\S]*?<\/nav>/)[0];
      assert.equal((nav.match(/<button/g)||[]).length,stages.length);
      assert.equal(html.includes('읽기 전용 Python 코드'),condition==='ex');
      assert.equal(html.includes('data-before="observed"'),condition==='in-situ');
      assert.ok(!html.includes('fault_steps')&&!html.includes('오류 2개'));
    }
    tasks.push({id,title:candidate.title,description:candidate.description,steps:stages.length,
      enabled:true,participant_enabled:false,initial_origin:candidate.provenance.initial_origin,
      original_task_id:candidate.provenance.original_task_id,trace_levels:candidate.researcher_notes.initial_trace_levels,
      has_reference_code:true,screening:{pair:candidate.researcher_notes.pair,variant:candidate.researcher_notes.variant,
        source_input_condition:candidate.provenance.source_generation_context.input_condition}});
  }
  const html=renderToStaticMarkup(React.createElement(TaskCatalog,{tasks,busy:false,onRefresh(){},async onImport(){},onPrepare(){},onLoad(){},onPublish(){}}));
  assert.ok(html.includes('Luna 원본 관찰 코드')&&html.includes('도메인 Variant')&&html.includes('표·과제 설명'));
  assert.equal((html.match(/>개발자 전용<\/span>/g)||[]).length,4);
});
