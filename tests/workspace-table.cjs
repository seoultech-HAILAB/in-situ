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
const { ReferenceDefinitions } = load('web/components/trace/transformation-bubble');
const table = (columns, rows) => ({ columns, rows: rows.map(([id, values]) => ({id,values})), stats: {fields: Object.fromEntries(columns.map(c=>[c,{dtype:'number'}]))} });
const before = table(['x','old'], [['a',{x:1,old:10}],['b',{x:2,old:20}]]);
const after = table(['x','new'], [['a',{x:3,new:30}]]);
const stage = {kind:'derive',trace_level:'detailed',input:before,table:after,params:{},code:'result = input_df'};

test('in-situ renders the three changes as keyboard-operable table targets and retains deleted values', () => {
  const html = renderToStaticMarkup(React.createElement(WorkspaceTable,{data:after,identity:'run:step',stage}));
  for (const kind of ['added','changed','removed']) assert.ok(html.includes(`data-change="${kind}"`));
  assert.ok(html.includes('변환 설명 보기'));
  assert.ok(html.includes('aria-haspopup="dialog"'));
  assert.ok(html.includes('aria-expanded="false"'));
  assert.ok(html.includes('>20</button>'), 'deleted rows retain their original values');
  assert.ok(html.includes('>10</button>'), 'deleted columns retain their original values');
  assert.ok(html.includes('결과 CSV에는 포함되지 않습니다'));
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

test('popup reference code is numbered read-only context without controls that can switch the edit target', () => {
  const context={definitions:[{symbol:'parts',code:"parts = df['Location'].str.split(',')",code_location:{start:10,end:10},read_only:true}]};
  const html=renderToStaticMarkup(React.createElement(ReferenceDefinitions,{context}));
  assert.ok(html.includes('참고용')&&html.includes('원본 열까지의 변수 정의')&&html.includes('L10'));
  assert.ok(html.includes('Location')&&html.includes('split'));
  assert.ok(!html.includes('<button')&&!html.includes('<select'));
});
