const {readFileSync}=require('node:fs');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const ts=require('typescript');
function moduleExports(file){const result={};new Function('exports',ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(result);return result;}
const {t07StepFilter}=moduleExports('web/components/trace/t07-step-filter.ts');
const {workspaceDiff,transformations}=moduleExports('web/components/trace/workspace-diff.ts');
function fixture(country='Canada'){
  const columns=['name','Nationality'];
  const rows=[{id:'a',values:{name:'A',Nationality:'Canada'}},{id:'b',values:{name:'B',Nationality:'USA'}}];
  const table=rows=>({columns,rows:structuredClone(rows),stats:{fields:{name:{dtype:'str'},Nationality:{dtype:'str'}}}});
  const output=table(rows.filter(row=>row.values.Nationality===country));
  const removed=rows.filter(row=>row.values.Nationality!==country).map(row=>row.id);
  const code=`staff.loc[staff['Nationality'].eq('${country}')]`;
  const effects={operation_id:'observed-filter',row_identity:true,columns:{added:[],changed:[],removed:[]},rows:{added:[],changed:[],removed,reordered:[]},cells:{added:{},changed:{},removed:Object.fromEntries(columns.map(c=>[c,removed]))}};
  const transform={id:'filter',method:'filter',code,code_location:{start:15,end:15},execution_version:'run',code_version:1,description:{text:`Keep ${country}.`,source:'llm'},output_columns:[],execution_effects:[effects]};
  return {id:'step-2',order:2,execution_version:'run',code_version:1,table:output,input:table([]),transformations:[transform],operation_observations:[{id:'observed-filter',kind:'filter',row_identity_verified:true,params:{columns:['Nationality']},code,code_location:{start:15,end:15},input:table(rows),table:output}]};
}
test('T07 Step 2 shows only its real filter input/output and retains the exact existing prose and code',()=>{
  const stage=fixture(),snapshot=JSON.stringify(stage);
  const local=t07StepFilter('PILOT4-T07',stage),diff=workspaceDiff(local);
  assert.equal(local.table,stage.operation_observations[0].table);
  assert.equal(diff.removedRows,1);assert.equal(diff.columns.filter(c=>c.kind).length,0);
  const removed=diff.rows.find(row=>row.kind==='removed');
  const items=transformations(local,{kind:'removed',row:removed});
  assert.deepEqual(items.map(item=>({code:item.code,text:item.text})),[{code:stage.transformations[0].code,text:'Keep Canada.'}]);
  assert.deepEqual(transformations(local,{kind:'removed',row:removed,column:'Nationality'}).map(t=>t.id),['filter']);
  assert.equal(JSON.stringify(stage),snapshot);
});
test('country and explanation come from the current executed filter, never a fixed Canada note',()=>{
  const stage=fixture('USA');const local=t07StepFilter('PILOT4-T07',stage);
  assert.equal(local.table.rows[0].values.Nationality,'USA');
  assert.equal(local.transformations[0].description.text,'Keep USA.');
  assert.ok(!local.transformations[0].code.includes('Canada'));
});
test('other tasks, other Steps, stale mappings and unverified row matches receive no additional view',()=>{
  const stage=fixture();
  for(const task of ['PILOT4-T01','PILOT4-T03','PILOT4-T05',undefined])assert.equal(t07StepFilter(task,stage),undefined);
  assert.equal(t07StepFilter('PILOT4-T07',{...stage,order:3}),undefined);
  for(const edit of [
    s=>s.operation_observations[0].row_identity_verified=false,
    s=>s.transformations[0].execution_version='old',
    s=>s.transformations[0].code_location.start=12,
    s=>s.transformations[0].execution_effects[0].operation_id='other',
    s=>s.transformations[0].execution_effects[0].rows.removed=[],
    s=>s.operation_observations[0].table.rows[0].id='unknown',
    s=>s.operation_observations[0].table.rows[0].values.name='changed',
  ]){const altered=structuredClone(stage);edit(altered);assert.equal(t07StepFilter('PILOT4-T07',altered),undefined);}
});
