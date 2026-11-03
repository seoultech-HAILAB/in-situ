const { readFileSync } = require('node:fs');
const assert = require('node:assert/strict');
const { test } = require('node:test');
const ts = require('typescript');
const exportsUnderTest = {};
new Function('exports', ts.transpileModule(readFileSync('web/components/trace/workspace-diff.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText)(exportsUnderTest);
const { workspaceDiff, transformations, comparisonInput } = exportsUnderTest;
function table(columns, rows, dtypes = {}) {
  return { columns, rows: rows.map(([id, values]) => ({ id, values })), stats: { rows: rows.length, columns: columns.length, fields: Object.fromEntries(columns.map(c => [c, { dtype: dtypes[c] || 'number' }])) } };
}
function stage(input, output, extra = {}) {
  return { id: 'step', kind: 'derive', trace_level: 'detailed', code: 'result = input_df.copy()', params: {}, input, table: output, ...extra };
}

test('additions, edits, deleted rows and dropped columns coexist without mutating the executed table', () => {
  const input = table(['x', 'old'], [['a', {x:1, old:9}], ['b', {x:2, old:8}], ['c', {x:3, old:7}]]);
  const output = table(['x', 'new'], [['a', {x:10, new:5}], ['c', {x:3, new:6}], ['d', {x:4, new:7}]]);
  const snapshot = JSON.stringify(output), diff = workspaceDiff(stage(input, output));
  assert.deepEqual(diff.columns.map(c => [c.name, c.kind]), [['x','changed'], ['new','added'], ['old','removed']]);
  assert.deepEqual(diff.rows.map(r => [r.id, r.kind]), [['a','changed'], ['b','removed'], ['c',undefined], ['d','added']]);
  assert.equal(diff.rows[0].cells.x.kind, 'changed');
  assert.equal(diff.rows[2].cells.x.kind, undefined, 'one edited cell must not color the rest of its column');
  assert.equal(diff.rows[0].cells.old.value, 9);
  assert.equal(diff.rows[1].cells.x.value, 2);
  assert.equal(diff.rows[1].cells.new.kind, undefined, 'a deleted row has no value in a subsequently added column');
  assert.equal(diff.rows[3].cells.old.kind, undefined);
  assert.equal(diff.removedRows, 1); assert.equal(diff.removedColumns, 1);
  assert.equal(JSON.stringify(output), snapshot);
});

test('cleared cells remain red with the old value, missing cells added later are green, unchanged nulls stay neutral', () => {
  const input = table(['x'], [['a',{x:7}], ['b',{x:null}], ['c',{}]]);
  const output = table(['x'], [['a',{x:null}], ['b',{x:null}], ['c',{x:5}]]);
  const rows = workspaceDiff(stage(input, output)).rows;
  assert.deepEqual(rows[0].cells.x, {value:7,before:7,after:null,kind:'removed'});
  assert.equal(rows[1].cells.x.kind, undefined);
  assert.equal(rows[1].kind, undefined);
  assert.equal(rows[2].cells.x.kind, 'added');
});

test('all deleted rows and columns stay inspectable even when the result is empty', () => {
  const diff = workspaceDiff(stage(table(['x'], [['a',{x:3}]]), table([],[])));
  assert.equal(diff.rows.length, 1); assert.equal(diff.columns.length, 1);
  assert.equal(diff.rows[0].cells.x.value, 3);
  assert.equal(diff.rows[0].cells.x.kind, 'removed');
});

test('sorting marks moved row headers without inventing cell edits; filtering does not mark shifted survivors', () => {
  const input = table(['x'], [['a',{x:1}], ['b',{x:2}], ['c',{x:3}]]);
  const sorted = workspaceDiff(stage(input, table(['x'], [['c',{x:3}], ['a',{x:1}], ['b',{x:2}]])));
  assert.ok(sorted.rows.every(r => r.kind === 'changed'));
  assert.ok(sorted.rows.every(r => r.cells.x.kind === undefined));
  const filtered = workspaceDiff(stage(input, table(['x'], [['a',{x:1}], ['c',{x:3}]])));
  assert.equal(filtered.rows.find(r => r.id === 'c').kind, undefined);
});

test('type conversions color existing cells yellow even if the serialized value is unchanged', () => {
  const diff = workspaceDiff(stage(table(['x'], [['a',{x:1}]], {x:'int'}), table(['x'], [['a',{x:1}]], {x:'float'})));
  assert.equal(diff.rows[0].cells.x.kind, 'changed'); assert.equal(diff.columns[0].kind, 'changed');
});

test('untraced observation IDs never masquerade as verified edited rows', () => {
  const diff = workspaceDiff(stage(table(['x'], [['a',{x:1}]]), table(['x'], [['a',{x:2}]]), {trace_level:'common'}));
  assert.deepEqual(diff.rows.map(r => r.kind), ['added','removed']);
  assert.equal(new Set(diff.rows.map(r => r.key)).size, 2);
  const unknown = workspaceDiff(stage(table(['x'], [['a',{x:1}]]), table(['x'], [['a',{x:2}]]), {kind:'unknown'}));
  assert.deepEqual(unknown.rows.map(r => r.kind), ['added','removed']);
});

test('a composite Step compares against its main consumed input, not an unrelated preparation table', () => {
  const main = table(['x','y'], [['a',{x:1,y:2}]]), side = table(['lookup'], [['z',{lookup:7}]]);
  const s = stage(side, main, {inputs:[{ref:'side',table:side},{ref:'main',table:main}]});
  assert.equal(comparisonInput(s), main); assert.equal(workspaceDiff(s).rows[0].kind, undefined);
});

test('a clicked column resolves to its own operation code and natural-language description', () => {
  const before = table(['x'], [['a',{x:1}]]), after = table(['x','y'], [['a',{x:1,y:2}]]);
  const op = stage(before, after, { code:'result["y"] = input_df["x"] * 2', code_location:{start:7,end:7}, params:{formulas:{y:{sources:['x'],formula:'x * 2'}}}, column_explanations:{y:'x 값에 2를 곱합니다.'} });
  const s = stage(before, after, {code:'unrelated\n'+op.code, operations:[stage(before,before,{kind:'copy',code:'unrelated'}),op]});
  const info = transformations(s,{kind:'added',column:'y'});
  assert.equal(info.length,1); assert.equal(info[0].code,op.code); assert.equal(info[0].text,'x 값에 2를 곱합니다.'); assert.equal(info[0].line.start,7);
});

test('deleted row explanations resolve the actual filter rather than a later derived column', () => {
  const before = table(['x'], [['a',{x:1}],['b',{x:2}]]), kept = table(['x'], [['b',{x:2}]]), after = table(['x','y'], [['b',{x:2,y:4}]]);
  const filter = stage(before,kept,{kind:'filter',code:'kept = input_df[input_df.x > 1]',params:{condition:'x > 1'}});
  const derive = stage(kept,after,{code:'result = kept.assign(y=4)',params:{formulas:{y:{sources:[],formula:'4'}}}});
  const s=stage(before,after,{operations:[filter,derive]});
  const deleted = workspaceDiff(s).rows.find(r=>r.kind==='removed');
  assert.deepEqual(transformations(s,{kind:'removed',row:deleted}).map(t=>t.code),[filter.code]);
});
