const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const assert = require('node:assert/strict');
const { test } = require('node:test');
const webRequire = createRequire(path.resolve('web/package.json'));
const React = webRequire('react');
const { renderToStaticMarkup } = webRequire('react-dom/server');
const ts = require('typescript');
const cache = new Map();
function load(filename) {
  filename = path.resolve(filename);
  if (!path.extname(filename)) filename += fs.existsSync(filename + '.tsx') ? '.tsx' : '.ts';
  if (cache.has(filename)) return cache.get(filename);
  const exports = {}; cache.set(filename, exports);
  const localRequire = name => name.startsWith('@/') ? load(path.resolve('web', name.slice(2))) : name.startsWith('.') ? load(path.resolve(path.dirname(filename), name)) : webRequire(name);
  new Function('require', 'exports', ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  }).outputText)(localRequire, exports);
  return exports;
}
const { WorkspaceTable } = load('web/components/trace/workspace-table');
const { PythonCode, sourceSnippet } = load('web/components/trace/python-code');
const { TraceApp } = load('web/components/trace/trace-app');
const { ExSituExplanation } = load('web/components/trace/ex-situ-explanation');
const { TransformationDetails } = load('web/components/trace/transformation-details');
const { workspaceSteps } = load('web/components/trace/revision-workspace');
const { transformations, explainedTransformations, highlightTargets } = load('web/components/trace/workspace-diff');
const { DirectUsedTables } = load('web/components/trace/direct-used-tables');
const table = (columns, rows) => ({ columns, rows: rows.map(([id, values]) => ({id,values})), stats: {fields: Object.fromEntries(columns.map(c=>[c,{dtype:'number'}]))} });
const before = table(['x','old'], [['a',{x:1,old:10}],['b',{x:2,old:20}]]);
const after = table(['x','new'], [['a',{x:3,new:30}]]);
const stage = {kind:'derive',trace_level:'detailed',input:before,table:after,params:{},code:'result = input_df'};

test('direct input cards show the actual table and use summary without transformation highlights', () => {
  const tables=[{id:'rates',name:'rates',table:table(['Currency','rate'],[['a',{Currency:'USD',rate:1}]]),uses:[{text:'Currency 열로 연결합니다.',line:41}]}];
  const html=renderToStaticMarkup(React.createElement(DirectUsedTables,{tables,identity:'run:step3'}));
  assert.ok(html.includes('이 Step에서 함께 사용한 표'));
  assert.ok(html.includes('Currency 열로 연결합니다.'));
  assert.ok(html.includes('L41') && html.includes('>USD<'));
  assert.ok(!html.includes('data-change=') && !html.includes('변환 설명 보기'));
  assert.equal(renderToStaticMarkup(React.createElement(DirectUsedTables,{tables:[],identity:'run:step4'})),'');
  const ex=renderToStaticMarkup(React.createElement(ExSituExplanation,{step:{...stage,direct_tables:tables},number:3}));
  assert.ok(!ex.includes('direct-used-tables') && !ex.includes('>USD<'));
});

test('in-situ renders the three changes as keyboard-operable table targets and retains deleted values', () => {
  const html = renderToStaticMarkup(React.createElement(WorkspaceTable,{data:after,identity:'run:step',stage}));
  for (const kind of ['added','changed','removed']) assert.ok(html.includes(`data-change="${kind}"`));
  assert.ok(html.includes('변환 설명 보기'));
  assert.ok(html.includes('aria-haspopup="dialog"'));
  assert.ok(html.includes('aria-expanded="false"'));
  assert.ok(html.includes('>20</button>'), 'deleted rows retain their original values');
  assert.ok(html.includes('>10</button>'), 'deleted columns retain their original values');
  assert.ok(!html.includes('removed-data-note'));
});

test('the original workspace and input/target tables remain plain tables', () => {
  const html = renderToStaticMarkup(React.createElement(WorkspaceTable,{data:after,identity:'run:input'}));
  assert.ok(!html.includes('data-change='));
  assert.ok(!html.includes('aria-haspopup='));
  assert.ok(!html.includes('table-change-legend'));
  assert.ok(!html.includes('>old<'));
});

test('the selected chained transformation highlights its own expression without dropping source text', () => {
  const code='df["이름"].astype(str).str.strip()';
  const html=renderToStaticMarkup(React.createElement(PythonCode,{code,focus:'.strip()'}));
  const highlighted=html.match(/<mark[^>]*>([\s\S]*?)<\/mark>/)[1].replace(/<[^>]*>/g,'');
  assert.equal(highlighted,'.strip()');
  const text=html.match(/<code>([\s\S]*?)<\/code>/)[1].replace(/<[^>]*>/g,'').replace(/&quot;/g,'"');
  assert.equal(text,code);
  const plain=renderToStaticMarkup(React.createElement(PythonCode,{code,focus:'.strip()',startLine:11,plain:true}));
  assert.ok(!plain.includes('<mark')&&!plain.includes('py-'));
  assert.ok(plain.includes('>11</span>'));
  assert.equal(plain.match(/<code>([\s\S]*?)<\/code>/)[1].replace(/&quot;/g,'"'),code);
});

test('viewer line numbers use original source positions and preserve blank lines between AST statements', () => {
  const source=Array.from({length:17},(_,i)=>`# line ${i+1}`).join('\n')+'\nfirst = 1\n\n# retained comment\nsecond = 2';
  const code=sourceSnippet(source,'first = 1\nsecond = 2',{start:18,end:21});
  assert.equal(code,'first = 1\n\n# retained comment\nsecond = 2');
  const html=renderToStaticMarkup(React.createElement(PythonCode,{code,startLine:18}));
  const gutter=html.match(/<span class="python-line-numbers"[^>]*>([\s\S]*?)<\/span>\s*<code>/)[1];
  assert.deepEqual([...gutter.matchAll(/<span>(\d+)<\/span>/g)].map(m=>Number(m[1])),[18,19,20,21]);
  const content=html.match(/<code>([\s\S]*?)<\/code>/)[1].replace(/<[^>]*>/g,'');
  assert.equal(content,code);
});

test('old source-context metadata cannot render upstream variable definitions', () => {
  const context={definitions:[{symbol:'parts',code:"parts = df['Location'].str.split(',')",code_location:{start:10,end:10},read_only:true}]};
  const html=renderToStaticMarkup(React.createElement(TransformationDetails,{item:{code:'parts[0].str.strip()',text:'앞뒤 공백을 제거합니다.',context}}));
  assert.ok(!html.includes('원본 열까지의 변수 정의')&&!html.includes('Location')&&!html.includes('split'));
  assert.ok(html.includes('strip')&&html.includes('앞뒤 공백'));
  assert.ok(!html.includes('<button')&&!html.includes('<select'));
});

test('only Ex-situ has the lower explanation panel and height separator; In-situ has no reserved region', () => {
  const ex=renderToStaticMarkup(React.createElement(TraceApp,{condition:'ex'}));
  const inside=renderToStaticMarkup(React.createElement(TraceApp,{condition:'in-situ'}));
  assert.ok(ex.includes('workspace-ex-situ')&&ex.includes('코드 자연어 설명')&&ex.includes('코드·테이블과 설명 높이 조절'));
  assert.ok(inside.includes('workspace-in-situ')&&!inside.includes('코드 자연어 설명')&&!inside.includes('divider-top'));
  assert.ok(!ex.includes('reserved-pane')&&!inside.includes('reserved-pane'));
});

test('Ex-situ describes the selected code with matching line references and excludes stale execution metadata', () => {
  const selected={...stage,input:table(['City'],[['a',{City:' old '}]]),table:table(['City'],[['a',{City:'old'}]]),id:'step-2',execution_version:'run-2',code_version:2,nl_explanation:{title:'도시 정리',text:'입지에서 도시를 추출합니다.'},transformations:[
    {id:'current',execution_version:'run-2',code_version:2,code:"parts[0].str.strip()",code_location:{start:11,end:11},output_columns:['City'],description:{text:'원본 Location을 분할해 첫 부분의 공백을 제거합니다.',source:'llm'},execution_effects:[{columns:{added:[],changed:['City'],removed:[]},rows:{added:[],changed:[],removed:[]},cells:{added:{},changed:{},removed:{}}}]},
    {id:'old',execution_version:'run-1',code_version:1,code_location:{start:4,end:4},output_columns:['Old'],description:{text:'오래된 설명',source:'llm'}},
  ]};
  const html=renderToStaticMarkup(React.createElement(ExSituExplanation,{step:selected,number:2,onRefresh(){}}));
  assert.ok(html.includes('Step 02')&&html.includes('>11</span>')&&html.includes('원본 Location'));
  assert.ok(!html.includes('코드 자연어 설명 갱신')&&!html.includes('오래된 설명'));
  assert.ok(!html.includes('transformation-code-label')&&!html.includes('transformation-source')&&!html.includes('explanation-summary'));
  assert.ok(html.includes('<pre')&&html.includes('strip')&&!html.includes('변환 설명 보기'));
  assert.ok(!html.includes('py-')&&!html.includes('<mark'));
});

test('Ex-situ headings identify actual added, changed and removed columns without coloring prose or code', () => {
  const effect=(columns={},rows={},cells={})=>({columns:{added:[],changed:[],removed:[],...columns},rows:{added:[],changed:[],removed:[],reordered:[],...rows},cells:{added:{},changed:{},removed:{},...cells}});
  const item=(id,output,effects)=>({id,kind:'derive',method:'assignment',code:`result['${id}'] = value`,code_location:{start:11,end:11},output_columns:output,input_columns:['Location'],description:{text:'현재 값을 처리합니다.',source:'llm'},execution_effects:effects});
  const selected={...stage,input:table(['Location','Cost'],[['a',{Location:'old',Cost:10}],['b',{Location:'removed',Cost:20}]]),table:table(['City','Cost'],[['a',{City:'new',Cost:null}]]),transformations:[
    item('created',['City'],[effect({added:['City']},{},{added:{City:['a']}})]),
    item('converted',['Cost'],[effect({changed:['Cost']},{},{changed:{Cost:['a']}})]),
    item('selected',['City','Cost'],[effect({removed:['Location']},{},{removed:{Location:['a']}})]),
    item('filtered',[],[effect({},{removed:['b']},{removed:{City:['b'],Cost:['b']}})]),
    item('cleared',['Cost'],[effect({},{changed:['a']},{removed:{Cost:['a']}})]),
    item('unverified',['Unknown'],[]),
  ]};
  const html=renderToStaticMarkup(React.createElement(ExSituExplanation,{step:selected,number:2}));
  const headings=[...html.matchAll(/<h3 class="explanation-change-heading">([\s\S]*?)<\/h3>/g)].map(match=>match[1]);
  assert.equal(headings.length,5);
  assert.ok(headings[0].includes('data-change-kind="added"')&&headings[0].includes('City')&&!headings[0].includes('Location'));
  assert.ok(headings[1].includes('data-change-kind="changed"')&&headings[1].includes('Cost'));
  assert.ok(headings[2].includes('data-change-kind="removed"')&&headings[2].includes('Location')&&!headings[2].includes('City'));
  assert.ok(headings[3].includes('data-change-kind="removed"')&&headings[3].includes('>행<')&&!headings[3].includes('Cost'));
  assert.ok(headings[4].includes('data-change-kind="changed"')&&!headings[4].includes('data-change-kind="removed"'));
  assert.ok(!html.includes('Unknown'));
  assert.ok(!html.includes('py-')&&!html.includes('<mark'));
});

test('Ex-situ candidate headings use the confirmed-to-candidate difference rather than pipeline-input additions', () => {
  const effect=kind=>({columns:{added:[],changed:[],removed:[],[kind]:['City']},rows:{added:[],changed:[],removed:[],reordered:[]},cells:{added:{},changed:{},removed:{}}});
  const original=table(['City'],[['a',{City:'old'}]]);
  const selected={...stage,table:table(['City'],[['a',{City:'new'}]]),transformations:[{id:'city',code:'result = build_city()',code_location:{start:11,end:11},output_columns:['City'],description:{text:'도시를 처리합니다.',source:'llm'},execution_effects:[effect('added')],revision_effects:[effect('changed')]}]};
  const html=renderToStaticMarkup(React.createElement(ExSituExplanation,{step:selected,number:2,label:'Step 2a',comparison:original}));
  assert.ok(html.includes('data-change-kind="changed"')&&!html.includes('data-change-kind="added"'));
});

test('only the revised Step receives a candidate immediately after its baseline, in both conditions', () => {
  const run={id:'confirmed',stages:[{id:'input',kind:'input'},...[1,2,3].map(n=>({id:`s${n}`,kind:'derive',code:`code${n}`}))]};
  const preview={id:'p',base_run_id:'confirmed',step_id:'s2',label:'Step 2a',stage:{id:'s2',kind:'derive',code:'candidate'},step_code:'candidate # source'};
  const items=workspaceSteps(run,preview);
  assert.deepEqual(items.map(x=>x.viewLabel),['Step 1','Step 2','Step 2a','Step 3']);
  assert.deepEqual(items.map(x=>x.isCandidate),[false,false,true,false]);
  assert.equal(items[2].viewCode,'candidate # source');
  assert.equal(items[1].code,'code2');
  assert.deepEqual(workspaceSteps(run,{...preview,base_run_id:'stale'}).map(x=>x.viewLabel),['Step 1','Step 2','Step 3']);
  assert.equal(workspaceSteps(run,null).length,3);
});

test('Ex-situ and the In-situ selected transformation render the same local prose and code without definitions', () => {
  const item={id:'t',code:"parts[0].str.strip()",code_location:{start:11,end:11,start_column:12},output_columns:['City'],input_columns:[],description:{source:'llm',text:'원본 Location에서 도시를 추출하고 공백을 제거합니다.'},source_context:{complete:true,unresolved:[],definitions:[{symbol:'parts',code:"parts = input_df['Location'].str.split(',')",code_location:{start:8,end:8}}]}};
  item.statement_code="stores['City'] = parts[0].str.strip()";
  item.statement_location={start:11,end:11,start_column:0,end_column:item.statement_code.length};
  const selected={...stage,input:table(['City'],[['a',{City:' old '}]]),table:table(['City'],[['a',{City:'old'}]]),id:'s2',transformations:[item],execution_version:'candidate',code_version:2};
  item.execution_effects=[{columns:{added:[],changed:['City'],removed:[]},rows:{added:[],changed:[],removed:[]},cells:{added:{},changed:{},removed:{}}}];
  const inItem=transformations(selected,{kind:'changed',column:'City'})[0];
  const shared=renderToStaticMarkup(React.createElement(TransformationDetails,{item:inItem}));
  const plain=renderToStaticMarkup(React.createElement(TransformationDetails,{item:inItem,plainCode:true}));
  const ex=renderToStaticMarkup(React.createElement(ExSituExplanation,{step:selected,number:2,label:'Step 2a',revision:{label:'Step 2a',request:'도시를 정리해줘'}}));
  assert.ok(ex.includes(plain));
  assert.ok(!plain.includes('py-')&&!plain.includes('<mark'));
  assert.ok(shared.includes(item.description.text)&&shared.includes('python-line-numbers'));
  assert.ok(!shared.includes('transformation-code-label')&&!shared.includes('transformation-source'));
  assert.ok(!shared.includes('source-definitions')&&!shared.includes('split'));
  assert.ok(ex.includes('Step 2a')&&!ex.includes('수정 내용')&&!ex.includes('도시를 정리해줘'));
  assert.equal(inItem.code,item.statement_code);
  assert.deepEqual(explainedTransformations(selected).map(item=>item.id),[...new Set(highlightTargets(selected).flatMap(target=>transformations(selected,target).map(item=>item.id)))]);
});

test('candidate table changes compare confirmed output to candidate output instead of candidate input', () => {
  const input=table(['x'],[['a',{x:1}]]);
  const original=table(['x','y'],[['a',{x:1,y:2}]]);
  const candidate=table(['x','y'],[['a',{x:1,y:3}]]);
  const selected={...stage,input,table:candidate};
  const html=renderToStaticMarkup(React.createElement(WorkspaceTable,{data:candidate,identity:'preview',stage:selected,comparison:original}));
  assert.ok(html.includes('data-change="changed"'));
  assert.ok(!html.includes('data-change="added"'));
});

test('composer Step is read-only with no scope dropdown', () => {
  for(const condition of ['ex','in-situ']) {
    const html=renderToStaticMarkup(React.createElement(TraceApp,{condition}));
    assert.ok(html.includes('현재 관찰 중인 Step')&&html.includes('composer-step'));
    assert.ok(!html.includes('aria-label="수정 범위"'));
  }
});
