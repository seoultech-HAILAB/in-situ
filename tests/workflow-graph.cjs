const {readFileSync}=require('node:fs');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const ts=require('typescript');
const helpers={};
new Function('exports',ts.transpileModule(readFileSync('src/workflowGraph.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(helpers);
const {buildWorkflowGraph,graphNeighbors,layoutWorkflow,referencedOutputs,workflowSourceColors,workflowDisplayGraph,workflowReviewWindow,reviewRun}=helpers;
const table={columns:['x'],rows:[{id:'r0001',values:{x:1}}],stats:{rows:1,columns:1,fields:{}}};
const step=(id,order,refs)=>({id,order,kind:'derive',table,params:{},inputs:refs.map(ref=>({ref,table})),depends_on:refs,operations:[],output_ref:id+'/operation-1'});
const root={id:'input',kind:'input',order:0,table,params:{}};
const a=step('a',1,['input']),b=step('b',2,['source:other']),joined=step('join',3,['a/operation-1','b/operation-1']);

test('working copies are excluded and each source reconnects independently with stable IDs',()=>{
  const one={...step('prepare/operation-1',1,['input']),kind:'copy',review_hidden:true};
  const two={...step('prepare/operation-2',1,['source:other']),kind:'copy',review_hidden:true};
  const prepare={...step('prepare',1,['input','source:other']),review_hidden:true,operations:[one,two],output_ref:two.id};
  const left={...step('left',2,[one.id]),depends_on:['prepare']};
  const right={...step('right',3,[two.id]),depends_on:['prepare']};
  const run={id:'execution',code:'original code',stages:[root,prepare,left,right],operations:[one,two],pipeline:{steps:[{id:'prepare'}]}};
  const original=JSON.stringify(run),visible=reviewRun(run);
  assert.deepEqual(visible.stages.map(s=>[s.id,s.order]),[['input',0],['left',1],['right',2]]);
  assert.deepEqual(visible.stages[1].inputs.map(i=>i.ref),['input']);
  assert.deepEqual(visible.stages[2].inputs.map(i=>i.ref),['source:other']);
  const graph=buildWorkflowGraph(visible.stages,{other:table});
  assert.deepEqual(graph.edges.map(e=>e.from+'>'+e.to).sort(),['input>left','source:other>right']);
  assert.deepEqual(graph.unresolved,{});
  assert.deepEqual(workflowReviewWindow(graph,'left').map(s=>s.id),['left','right']);
  assert.equal(visible.code,run.code);assert.equal(visible.id,run.id);
  assert.equal(JSON.stringify(run),original);
});

test('embedded and chained copies disappear while transformations and actual final output remain intact',()=>{
  const copy1={...step('prepare/operation-1',1,['input']),kind:'copy',review_hidden:true};
  const prepare={...step('prepare',1,['input']),review_hidden:true,operations:[copy1],output_ref:copy1.id};
  const copy2={...step('work/operation-1',2,[copy1.id]),kind:'copy',review_hidden:true};
  const change=step('work/operation-2',2,[copy2.id]);
  const work={...step('work',2,[copy1.id]),operations:[copy2,change],output_ref:change.id};
  const tail=step('final',3,[change.id]);tail.review_hidden=true;tail.kind='copy';tail.inputs=[{ref:'input',table}];tail.operations=[];
  const run={stages:[root,prepare,work,tail],operations:[copy1,copy2,change],code:'unchanged'};
  const visible=reviewRun(run);
  assert.deepEqual(visible.stages.map(s=>s.id),['input','work']);
  assert.deepEqual(visible.stages[1].operations.map(s=>s.id),[change.id]);
  assert.deepEqual(visible.stages[1].operations[0].inputs.map(i=>i.ref),['input']);
  assert.deepEqual(run.stages.at(-1),tail);
});

test('parallel inputs and join use only recorded references, never sequence adjacency',()=>{
  const graph=buildWorkflowGraph([root,a,b,joined],{other:table});
  assert.deepEqual(graph.edges.map(e=>e.from+'>'+e.to).sort(),['a>join','b>join','input>a','source:other>b'].sort());
  assert.deepEqual(graphNeighbors(graph,'join').parents.map(n=>n.id),['a','b']);
  assert.equal(graph.edges.some(e=>e.from==='a'&&e.to==='b'),false);
  const layout=layoutWorkflow(graph,1200);
  assert.equal(layout.positions.get('a').x,layout.positions.get('b').x);
  assert.ok(layout.positions.get('join').x>layout.positions.get('a').x);
});
test('later reuse of original input is a branch, not an edge from the previous result',()=>{
  const late=step('late',4,['input']);const graph=buildWorkflowGraph([root,a,b,joined,late],{other:table});
  assert.deepEqual(graphNeighbors(graph,'late').parents.map(n=>n.id),['input']);
  assert.equal(layoutWorkflow(graph,1200).positions.get('late').x,layoutWorkflow(graph,1200).positions.get('a').x);
});
test('unresolved and conservative references stay explicit',()=>{
  const unknown=step('unknown',1,['not-a-recorded-source']);unknown.params.dependency_kind='conservative_code_reference';
  const graph=buildWorkflowGraph([root,unknown]);assert.equal(graph.edges.length,0);assert.equal(graph.unresolved.unknown,1);
  unknown.inputs=[{ref:'input',table}];unknown.depends_on=['input'];
  assert.equal(buildWorkflowGraph([root,unknown]).edges[0].conservative,true);
});
test('detail includes other observed outputs actually referenced downstream',()=>{
  const producer=step('prepare',1,['input']);producer.output_ref='prepare/operation-2';
  producer.operations=[{id:'prepare/operation-1',table},{id:'prepare/operation-2',table}];
  assert.deepEqual(referencedOutputs(producer,[producer,step('use',2,['prepare/operation-1'])]).map(op=>op.id),['prepare/operation-1']);
});

test('source colors follow exact operation references and retain both sources after a merge',()=>{
  const prepare=step('prepare',1,['input','source:other']);
  prepare.operations=[step('prepare/one',1,['input']),step('prepare/two',2,['source:other'])];
  prepare.output_ref='prepare/two';
  const left=step('left',2,['prepare/one']),right=step('right',3,['prepare/two']);
  const merge=step('merge',4,['left','right']),after=step('after',5,['merge']);
  const graph=buildWorkflowGraph([root,prepare,left,right,merge,after],{other:table});
  const {sources,edgeSources}=workflowSourceColors(graph);
  const ids=(from,to)=>edgeSources.get(graph.edges.find(e=>e.from===from&&e.to===to)).map(s=>s.id);
  assert.equal(sources.length,2);assert.equal(new Set(sources.map(s=>s.color)).size,2);
  assert.deepEqual(ids('prepare','left'),['input']);
  assert.deepEqual(ids('prepare','right'),['source:other']);
  assert.deepEqual(ids('left','merge'),['input']);
  assert.deepEqual(ids('right','merge'),['source:other']);
  assert.deepEqual(ids('merge','after'),['input','source:other']);
});

test('overview hides same-source shortcuts without changing execution references',()=>{
  const four=step('four',4,['input']),five=step('five',5,['four']),six=step('six',6,['four','five']);
  const graph=buildWorkflowGraph([root,four,five,six]);
  const display=workflowDisplayGraph(graph);
  assert.equal(display.edges.some(e=>e.from==='four'&&e.to==='six'),false);
  assert.ok(display.edges.some(e=>e.from==='four'&&e.to==='five'));
  assert.ok(display.edges.some(e=>e.from==='five'&&e.to==='six'));
  assert.ok(graph.edges.some(e=>e.from==='four'&&e.to==='six'));
  assert.deepEqual(six.inputs.map(i=>i.ref),['four','five']);
});

test('overview retains a shortcut when the alternative route has different sources',()=>{
  const four=step('four',4,['input']),five=step('five',5,['four','source:other']),six=step('six',6,['four','five']);
  const display=workflowDisplayGraph(buildWorkflowGraph([root,four,five,six],{other:table}));
  assert.ok(display.edges.some(e=>e.from==='four'&&e.to==='six'));
});

test('review window shows n and n+1 for single and multiple inputs without pinning Step 1',()=>{
  const stages=[root,a,b,joined];
  for(const sources of [{},{other:table}]){
    const graph=buildWorkflowGraph(stages,sources);
    assert.deepEqual(workflowReviewWindow(graph,'a').map(s=>s.id),['a','b']);
    assert.deepEqual(workflowReviewWindow(graph,'b').map(s=>s.id),['b','join']);
    assert.deepEqual(workflowReviewWindow(graph,'join').map(s=>s.id),['join']);
    assert.deepEqual(workflowReviewWindow(graph,'missing'),[]);
    if(sources.other)assert.deepEqual(workflowReviewWindow(graph,'source:other').map(s=>s.id),['source:other','b']);
  }
});

test('branch and merge edges have separate ports and never share line segments or cross cards',()=>{
  const stages=[root,step('s1',1,['input']),step('s2',2,['input','source:other']),
    step('s3',3,['s1','input','source:other']),step('s4',4,['s2','s3','input']),
    step('s5',5,['s3','s4','source:other']),step('s6',6,['s1','s2','s3','s4','s5','input','source:other'])];
  const graph=buildWorkflowGraph(stages,{other:table});
  for(const width of [600,1366]){
    const layout=layoutWorkflow(graph,width);
    const segments=layout.routes.flatMap((route,index)=>route.points.slice(1).map((p,i)=>({index,a:route.points[i],b:p})))
      .filter(({a,b})=>a.x!==b.x||a.y!==b.y);
    const overlaps=(a,b,c,d)=>Math.min(Math.max(a,b),Math.max(c,d))-Math.max(Math.min(a,b),Math.min(c,d))>1e-6;
    for(let i=0;i<segments.length;i++)for(const other of segments.slice(i+1)){
      const {index,a,b}=segments[i];if(index===other.index)continue;
      const {a:c,b:d}=other;
      assert.ok(!(a.x===b.x&&c.x===d.x&&Math.abs(a.x-c.x)<1e-6&&overlaps(a.y,b.y,c.y,d.y)), 'shared vertical segment');
      assert.ok(!(a.y===b.y&&c.y===d.y&&Math.abs(a.y-c.y)<1e-6&&overlaps(a.x,b.x,c.x,d.x)), 'shared horizontal segment');
    }
    for(const {a,b} of segments)for(const p of layout.positions.values()){
      const crosses=a.x===b.x
        ? a.x>p.x&&a.x<p.x+layout.nodeWidth&&overlaps(a.y,b.y,p.y,p.y+layout.nodeHeight)
        : a.y>p.y&&a.y<p.y+layout.nodeHeight&&overlaps(a.x,b.x,p.x,p.x+layout.nodeWidth);
      assert.equal(crosses,false,'edge enters a card');
    }
    for(const node of graph.nodes)for(const outgoing of [true,false]){
      const ports=layout.routes.filter(r=>outgoing?r.edge.from===node.id:r.edge.to===node.id)
        .map(r=>outgoing?r.points[0].y:r.points.at(-1).y);
      assert.equal(new Set(ports).size,ports.length,'shared arrow endpoint');
    }
  }
});
