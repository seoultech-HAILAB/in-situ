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

test('verified grouped calculations highlight their column without invented row or cell pairs', () => {
  const input=table(['Location','Revenue'],[['a',{Location:'A',Revenue:2}],['b',{Location:'A',Revenue:3}]]);
  const output=table(['Location','Revenue'],[['group-a',{Location:'A',Revenue:5}]]);
  const selected=stage(input,output,{kind:'python',trace_level:'common',schema_origins:{changed:{Revenue:[{start:30,end:32}]}}});
  const diff=workspaceDiff(selected);
  assert.equal(diff.columns.find(c=>c.name==='Revenue').kind,'changed');
  assert.equal(diff.rowCorrespondenceKnown,false);
  assert.ok(diff.rows.every(row=>!row.kind&&!row.cells.Revenue.kind));
});

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
  assert.deepEqual(diff.rows.map(r => r.kind), [undefined,undefined]);
  assert.deepEqual(diff.rows.map(r => r.observation), ['after','before']);
  assert.equal(diff.removedRows,0);
  assert.equal(diff.rowCorrespondenceKnown,false);
  assert.equal(new Set(diff.rows.map(r => r.key)).size, 2);
  const unknown = workspaceDiff(stage(table(['x'], [['a',{x:1}]]), table(['x'], [['a',{x:2}]]), {kind:'unknown'}));
  assert.deepEqual(unknown.rows.map(r => r.kind), [undefined,undefined]);
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

const effect = (kind,column,rows=[]) => ({operation_id:'verified',row_identity:true,columns:{added:[],changed:[],removed:[],[kind]:column?[column]:[]},rows:{added:[],changed:[],removed:[],reordered:[],[kind]:column?[]:rows},cells:{added:{},changed:{},removed:{},[kind]:column?{[column]:rows}:{}}});
const sourceTransform = (id, column, code, extra={}) => ({id,kind:'derive',method:'apply',code,output_columns:[column],input_columns:[column],code_location:{start:3,end:3,start_column:4,end_column:30},description:{text:`${column}만 계산한 설명`,source:'llm'},syntax_only:true,execution_version:'run-2',code_version:2,execution_effects:[effect('changed',column)],...extra});
test('common-trace selections use column-specific AST code and prose instead of the global Step operation', () => {
  const input=table(['x','y'],[['a',{x:1,y:2}]]);
  const s=stage(input,input,{trace_level:'common',execution_version:'run-2',code_version:2,code:'entire step code',
    transformations:[sourceTransform('x','x','x.apply(...)'),sourceTransform('y','y','y.map(...)')]});
  const selected=transformations(s,{kind:'changed',column:'y'});
  assert.deepEqual(selected.map(t=>t.code),['y.map(...)']);
  assert.equal(selected[0].text,'y만 계산한 설명');
  assert.equal(selected[0].source,'llm');
});
test('unresolved source correspondence returns nothing; stale metadata is never shown', () => {
  const s=stage(null,table(['z'],[]),{execution_version:'run-2',code_version:2,transformations:[sourceTransform('x','x','exact expression')]});
  assert.deepEqual(transformations(s,{kind:'added',column:'z'}),[]);
  s.transformations[0].execution_version='run-1';
  assert.deepEqual(transformations(s,{kind:'added',column:'z'}),[]);
  s.transformations=[];
  assert.deepEqual(transformations(s,{kind:'added',column:'z'}),[], 'no fallback to entire Step');
});
test('deleted row source selection isolates the filter from unrelated derived columns', () => {
  const s=stage(null,table(['x'],[]),{execution_version:'run-2',code_version:2,transformations:[sourceTransform('x','x','calculate x'),sourceTransform('filter','', 'df[df.x > 1]',{kind:'filter',output_columns:[],row_effect:'remove',execution_effects:[effect('removed',null,['a'])]})]});
  assert.deepEqual(transformations(s,{kind:'removed',row:{id:'a',kind:'removed',cells:{},number:1}}).map(t=>t.code),['df[df.x > 1]']);
});

test('legacy source-context definitions are ignored while local edit identity is retained', () => {
  const context={version:'source-dependencies-v1',original_columns:[{table:'input_df',column:'Location'}],definitions:[{symbol:'parts',code:"parts = input_df['Location'].str.split(',')",code_location:{start:2,end:2},read_only:true}],text:'Location을 분할하고 첫 부분의 공백을 제거해 City를 만듭니다.',complete:true,unresolved:[]};
  const s=stage(null,table(['City'],[]),{execution_version:'run-2',code_version:2,transformations:[sourceTransform('city','City','parts[0].str.strip()',{source_context:context,code_location:{start:11,end:11},execution_effects:[effect('added','City')]})]});
  const choices=transformations(s,{kind:'added',column:'City'});
  assert.equal(choices.length,1);assert.equal(choices[0].id,'city');assert.equal(choices[0].line.start,11);
  assert.equal(choices[0].code,'parts[0].str.strip()');assert.equal(choices[0].context,undefined);
});

test('target type and change kind must match: deleted selection columns never fall back to sorting', () => {
  const select=sourceTransform('select','x',"df[['x']]",{kind:'select',removed_columns:['y'],execution_effects:[effect('removed','y',['a'])]});
  const sort=sourceTransform('sort','x',"df.sort_values('x')",{kind:'sort',execution_effects:[effect('changed',null,['a'])]});
  const s=stage(null,table(['x'],[]),{execution_version:'run-2',code_version:2,transformations:[select,sort]});
  assert.deepEqual(transformations(s,{kind:'removed',column:'y'}).map(item=>item.id),['select']);
  assert.deepEqual(transformations(s,{kind:'changed',column:'y'}),[]);
  assert.deepEqual(transformations(s,{kind:'removed',column:'missing'}),[]);
  assert.deepEqual(transformations(s,{kind:'removed',column:'y',row:{id:'a'}}).map(item=>item.id),['select']);
  assert.deepEqual(transformations(s,{kind:'removed',column:'y',row:{id:'b'}}),[]);
  assert.deepEqual(transformations(s,{kind:'changed',row:{id:'a'}}).map(item=>item.id),['sort']);
  assert.deepEqual(transformations(s,{kind:'removed',row:{id:'a'}}),[]);
});

test('an input column used to derive another output does not match as the changed target', () => {
  const s=stage(null,table(['x','z'],[]),{execution_version:'run-2',code_version:2,transformations:[sourceTransform('derive','z',"z=df['x']*2",{input_columns:['x'],execution_effects:[effect('added','z')]})]});
  assert.deepEqual(transformations(s,{kind:'changed',column:'x'}),[]);
  assert.deepEqual(transformations(s,{kind:'changed',column:'z'}),[]);
  assert.deepEqual(transformations(s,{kind:'added',column:'z'}).map(item=>item.id),['derive']);
});

test('legacy unmatched records never use the entire Step or an unrelated sort as a fallback', () => {
  const input=table(['x','y'],[['a',{x:1,y:2}],['b',{x:2,y:3}]]);
  const output=table(['x','y'],[['b',{x:2,y:3}],['a',{x:1,y:2}]]);
  const s=stage(input,output,{code:'entire Step',operations:[stage(input,output,{kind:'sort_values',code:'actual sort'})]});
  assert.deepEqual(transformations(s,{kind:'removed',column:'y'}),[]);
  assert.deepEqual(transformations(s,{kind:'changed',column:'x'}),[]);
  assert.deepEqual(transformations(stage(input,output),{kind:'changed',column:'x'}),[]);
});

test('revision highlights match the separate verified before/after comparison', () => {
  const s=stage(null,table(['z'],[]),{execution_version:'run-2',code_version:2,transformations:[sourceTransform('derive','z','z=x*3',{execution_effects:[effect('added','z')],revision_effects:[effect('changed','z',['a'])]})]});
  assert.deepEqual(transformations(s,{kind:'changed',column:'z'}),[]);
  assert.deepEqual(transformations(s,{kind:'changed',column:'z',revision:true}).map(item=>item.id),['derive']);
  assert.deepEqual(transformations(s,{kind:'added',column:'z',revision:true}),[]);
});

test('verified statement correspondence identifies only actually deleted rows in a common Step', () => {
  const input=table(['x','y'],[['a',{x:1,y:10}],['b',{x:2,y:20}],['c',{x:3,y:30}]]);
  const output=table(['x'],[['new-c',{x:3}],['new-a',{x:1}]]);
  const selected=stage(input,output,{kind:'python',trace_level:'common',row_correspondence_complete:true,row_correspondence:{'new-c':'c','new-a':'a'}});
  const diff=workspaceDiff(selected);
  assert.deepEqual(diff.rows.filter(row=>row.kind==='removed').map(row=>row.id),['b']);
  assert.equal(diff.removedRows,1);
  assert.deepEqual(diff.rows.filter(row=>row.kind!=='removed').map(row=>row.cells.y.value),[30,10]);
  assert.ok(diff.rows.filter(row=>row.kind!=='removed').every(row=>row.kind==='changed'));
  assert.deepEqual(diff.rows.filter(row=>row.kind!=='removed').map(row=>row.cells.x.kind),[undefined,undefined]);
});

test('global Step search exposes only matching removal candidates, never unrelated code', () => {
  const removed=effect('removed','y',['a']);removed.attribution='step-search-candidate';
  const selected=stage(null,table(['x'],[]),{execution_version:'run-2',code_version:2,transformations:[
    sourceTransform('selection','x','result[keep]',{kind:'select',execution_effects:[removed]}),
    sourceTransform('sort','x','result.sort_values(...)',{kind:'sort',execution_effects:[effect('changed',null,['a'])]}),
  ]});
  const choices=transformations(selected,{kind:'removed',column:'y'});
  assert.deepEqual(choices.map(item=>item.id),['selection']);
  assert.equal(choices[0].candidates,true);
  assert.deepEqual(transformations(selected,{kind:'removed',column:'unknown'}),[]);
});

test('unknown row correspondence does not create row events but actual schema changes remain clickable', () => {
  const input=table(['x','Location'],[['old',{x:1,Location:'A'}]]);
  const output=table(['x','City'],[['new',{x:1,City:'A'}]]);
  const selected=stage(input,output,{trace_level:'common',execution_version:'run-2',code_version:2,transformations:[
    sourceTransform('City','City',"df['City'] = parts[0].str.strip()",{method:'assignment',execution_effects:[effect('added','City',['new'])]}),
    sourceTransform('select','x',"df[['x','City']]",{kind:'select',execution_effects:[effect('removed','Location',['internal-row'])]}),
  ]});
  const diff=workspaceDiff(selected);
  assert.ok(diff.rows.every(row=>row.kind===undefined));
  assert.equal(diff.removedRows,0);
  assert.deepEqual(diff.rows.map(row=>row.observation),['after','before']);
  assert.equal(diff.rows[0].cells.x.kind,undefined);
  assert.equal(diff.rows[0].cells.City.kind,'added');
  assert.equal(diff.rows[1].cells.Location.kind,'removed');
  assert.deepEqual(transformations(selected,{kind:'added',column:'City',row:diff.rows[0]}).map(item=>item.id),['City']);
  assert.deepEqual(transformations(selected,{kind:'removed',column:'Location',row:diff.rows[1]}).map(item=>item.id),['select']);
});

test('an actual column assignment takes precedence over its nested Series code for City creation', () => {
  const selected=stage(null,table(['City'],[]),{execution_version:'run-2',code_version:2,transformations:[
    sourceTransform('strip','City','parts[0].str.strip()',{statement_index:4,execution_effects:[effect('added','City')]}),
    sourceTransform('assignment','City',"df['City'] = parts[0].str.strip()",{method:'assignment',statement_index:4,execution_effects:[effect('added','City')]}),
  ]});
  assert.deepEqual(transformations(selected,{kind:'added',column:'City'}).map(item=>item.id),['assignment']);
  assert.deepEqual(transformations(selected,{kind:'removed',column:'Location'}),[]);
});

test('observed-change LLM code wins only for its exact change; unresolved changes retain verified operations', () => {
  const selected=stage(null,table(['City'],[]),{execution_version:'run-2',code_version:2,transformations:[
    sourceTransform('strip','City','parts[0].str.strip()',{execution_effects:[effect('added','City',['a'])]}),
    sourceTransform('mapped','City',"df['City'] = parts[0].str.strip()",{method:'observed_change',mapping_status:'matched',execution_effects:[effect('added','City',['a'])]}),
    sourceTransform('delete','x',"df[['City']]",{kind:'select',execution_effects:[effect('removed','Location',['a'])]}),
  ]});
  assert.deepEqual(transformations(selected,{kind:'added',column:'City',row:{id:'a'}}).map(t=>t.id),['mapped']);
  assert.equal(transformations(selected,{kind:'added',column:'City'})[0].mapping,'matched');
  assert.deepEqual(transformations(selected,{kind:'removed',column:'Location'}).map(t=>t.id),['delete']);
  assert.deepEqual(transformations(selected,{kind:'changed',column:'City'}),[]);
});

test('Step-only LLM associations are marked as candidates and do not bypass revision matching', () => {
  const observed=effect('added','City',['a']);observed.attribution='llm-step-candidate';
  const selected=stage(null,table(['City'],[]),{execution_version:'run-2',code_version:2,transformations:[
    sourceTransform('mapped','City',"df['City'] = calculate()",{method:'observed_change',mapping_status:'candidate',execution_effects:[observed]}),
  ]});
  const items=transformations(selected,{kind:'added',column:'City'});
  assert.equal(items[0].candidates,true);assert.equal(items[0].mapping,'candidate');
  assert.deepEqual(transformations(selected,{kind:'changed',column:'City',revision:true}),[]);
});
