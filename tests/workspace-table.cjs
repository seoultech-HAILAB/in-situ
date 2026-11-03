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
