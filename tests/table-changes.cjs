// Fresh execution of synthetic examples; no ignored local logs are required.
// Compile the pure TS helper in memory; no browser/model stubs or inferred lineage.
const {readFileSync,existsSync} = require('node:fs');
const {spawnSync}=require('node:child_process');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const ts = require('typescript');
const moduleExports = {};
new Function('exports', ts.transpileModule(readFileSync('src/tableChanges.ts','utf8'), {
  compilerOptions: {module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},
}).outputText)(moduleExports);
const {tableChanges,cellKey,focusWindow,conciseOperation} = moduleExports;
const runtime=spawnSync(process.env.TRACE_TEST_PYTHON || (existsSync('.venv/Scripts/python.exe')?'.venv/Scripts/python.exe':'python'),['tests/workflow_fixtures.py'],{encoding:'utf8',timeout:20000});
assert.equal(runtime.status,0,runtime.stderr);
const fixtures=JSON.parse(runtime.stdout);
const load=name=>fixtures[name];
const long = load('long8').run.stages;

test('focus window never loses the selected Step at either edge or in a long workflow',()=>{
  for(const name of ['short2','short3','long6','long8']) {
    const stages=load(name).run.stages;
    stages.forEach((s,i)=>{const visible=focusWindow(stages,i);assert.equal(visible.length,Math.min(3,stages.length));assert.ok(visible.includes(s));assert.deepEqual(visible.map(v=>v.order),[...visible.map(v=>v.order)].sort((a,b)=>a-b));});
  }
});
test('dropna and dedup report only verified removed rows, not shifted survivors',()=>{
  assert.equal(tableChanges(long[1]).removedRows.length,1);
  assert.equal(tableChanges(long[3]).removedRows.length,1);
  assert.equal(tableChanges(long[1]).movedRows.size,0);
  assert.equal(tableChanges(long[1]).changedCells.size,0);
});
test('fillna marks the actual changed cell without consulting Target or a previous run',()=>{
  const stage=long[2],d=tableChanges(stage);
  assert.equal(d.rowIdentity,true);assert.equal(d.changedCells.size,1);
  const missing=stage.input.rows.find(r=>r.values.quantity===null);
  assert.ok(d.changedCells.has(cellKey(missing.id,'quantity')));
  const altered=structuredClone(stage);altered.diff={output_changed:false};
  assert.equal(tableChanges(altered).changedCells.size,1);
});
test('derived and renamed columns are schema changes rather than fabricated old values',()=>{
  assert.deepEqual(tableChanges(long[4]).addedColumns,['amount']);
  assert.equal(tableChanges(long[4]).changedCells.size,0);
  assert.deepEqual(tableChanges(long[5]).addedColumns,['area']);
  assert.deepEqual(tableChanges(long[5]).removedColumns,['region']);
});
test('sorting highlights order rather than value changes or deletions',()=>{
  const d=tableChanges(long[6]);assert.ok(d.movedRows.size>0);
  assert.equal(d.changedCells.size,0);assert.equal(d.removedRows.length,0);
});
test('aggregation does not label all contributing input rows as deleted',()=>{
  const d=tableChanges(long[7]);assert.equal(d.rowIdentity,false);
  assert.equal(d.removedRows.length,0);assert.equal(d.changedCells.size,0);
  assert.deepEqual(d.addedColumns,['total']);
});
test('common tracing and coincidentally matching IDs never establish cell correspondence',()=>{
  for(const stage of load('common').run.stages.slice(1)) {
    assert.equal(stage.trace_level,'common');const d=tableChanges(stage);
    assert.equal(d.rowIdentity,false);assert.equal(d.changedCells.size,0);
    assert.equal(d.removedRows.length,0);
  }
  const stage=structuredClone(long[2]);stage.trace_level='common';
  assert.equal(tableChanges(stage).changedCells.size,0);
});
test('unknown detailed operators remain conservative and internal operation uses its own boundary',()=>{
  const stage=structuredClone(long[2]);stage.kind='unrecognized';stage.operations=[];
  assert.equal(tableChanges(stage).rowIdentity,false);
  const sort=long[6].operations.find(op=>op.kind==='sort_values');
  assert.equal(tableChanges({...sort,view_operation_id:sort.id,operations:[{kind:'aggregate'}]}).rowIdentity,true);
});
test('labels suppress arguments and distinguish unverifiable semantics',()=>{
  assert.ok(!conciseOperation(long[6]).includes('인자'));
  assert.equal(conciseOperation(load('common').run.stages[1]),'Python 변환');
  assert.equal(tableChanges(long[0]),null);
});
