const {readFileSync}=require('node:fs');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const ts=require('typescript'),out={};
new Function('exports',ts.transpileModule(readFileSync('src/tableSelection.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(out);
const {combineSelection,selectedCells}=out;
const table={columns:['a','b','c'],rows:[{id:'r1'},{id:'r2'},{id:'r3'}]};
const cell=(row_id,column)=>({kind:'cell',step_id:'step-1',row_id,column});
test('Ctrl-click adds and removes exact disjoint cells without selecting their cross product',()=>{
  const first=combineSelection(cell('r1','a'),cell('r3','c'),table);
  assert.deepEqual(first.cells,[{row_id:'r1',column:'a'},{row_id:'r3',column:'c'}]);
  const removed=combineSelection(first,cell('r1','a'),table);
  assert.deepEqual(removed.cells,[{row_id:'r3',column:'c'}]);
  assert.equal(combineSelection(removed,cell('r3','c'),table),null);
});
test('Ctrl-drag preserves the original rectangle and adds a new range from the drag start',()=>{
  const previous={kind:'cells',step_id:'step-1',row_ids:['r1','r2'],columns:['a','b']};
  assert.equal(selectedCells(previous,table).length,4);
  const next=combineSelection(previous,cell('r3','c'),table,false);
  assert.equal(next.cells.length,5);
  assert.equal(selectedCells(previous,table).length,4);
});
test('Ctrl selection never combines different steps or input/output snapshots',()=>{
  for(const identity of [{step_id:'other'},{table_role:'input',input_ref:'source'}]){
    const next=combineSelection(cell('r1','a'),{...cell('r3','c'),...identity},table);
    assert.deepEqual(next.cells,[{row_id:'r3',column:'c'}]);
  }
});
