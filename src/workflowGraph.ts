import type { Run,Stage,Table } from './types';
export type WorkflowEdge={from:string;to:string;refs:string[];conservative:boolean};
export type WorkflowNode={id:string;stage:Stage;source:boolean;order:number};
export type WorkflowGraph={nodes:WorkflowNode[];edges:WorkflowEdge[];unresolved:Record<string,number>};

export function reviewRun(run:Run|undefined|null):Run|undefined {
  if(!run)return undefined;
  const aliases=new Map<string,string>(),hiddenSteps=new Set(run.stages.filter(s=>s.review_hidden).map(s=>s.id));
  for(const stage of run.stages){
    if(stage.review_hidden&&stage.output_ref)aliases.set(stage.id,stage.output_ref);
    for(const op of stage.operations||[]){
      const inputs=workflowInputs(op);
      if(op.review_hidden&&inputs.length===1)aliases.set(op.id,inputs[0].ref);
    }
    if(stage.review_hidden&&!stage.operations?.length){
      const inputs=workflowInputs(stage);
      if(inputs.length===1)aliases.set(stage.id,inputs[0].ref);
    }
  }
  const resolve=(ref:string)=>{const seen=new Set<string>();while(aliases.has(ref)&&!seen.has(ref)){seen.add(ref);ref=aliases.get(ref)!;}return ref;};
  const project=(stage:Stage):Stage=>{
    const inputs=stage.inputs?.map(input=>({...input,ref:resolve(input.ref)}));
    return {...stage,inputs,input_refs:stage.input_refs?.map(resolve),output_ref:stage.output_ref?resolve(stage.output_ref):undefined,
      depends_on:[...new Set([...(stage.depends_on||[]).filter(ref=>!hiddenSteps.has(ref)||!inputs?.length).map(resolve),...(inputs||[]).map(input=>input.ref)])],
      operations:stage.operations?.filter(op=>!op.review_hidden).map(project)};
  };
  return {...run,stages:run.stages.filter(stage=>!stage.review_hidden).map((stage,index)=>({...project(stage),order:index})),
    operations:run.operations?.filter(op=>!op.review_hidden).map(project)};
}

export function sourceStage(name:string,data:Table,executionVersion=''):Stage {
  return {id:`source:${name}`,order:0,kind:'input',label:name,summary:'',code:'',code_location:null,input:null,table:data,
    params:{},removed:null,lineage:Object.fromEntries(data.rows.map(row=>[row.id,Object.fromEntries(data.columns.map(column=>[column,[{table_id:name,row_id:row.id,column}]]))])),
    row_sources:Object.fromEntries(data.rows.map(row=>[row.id,[row.id]])),trace_level:'detailed',depends_on:[],code_version:0,execution_version:executionVersion};
}
export function ownerOf(graph:Pick<WorkflowGraph,'nodes'>,ref:string) {
  return graph.nodes.find(n=>n.id===ref)?.id||graph.nodes.find(n=>ref.startsWith(n.id+'/'))?.id;
}
export function buildWorkflowGraph(stages:Stage[],sources:Record<string,Table>={}):WorkflowGraph {
  const graph:WorkflowGraph={nodes:[...stages.filter(s=>s.kind==='input').map(stage=>({id:stage.id,stage,source:true,order:0})),
    ...Object.entries(sources).map(([name,table])=>({id:`source:${name}`,stage:sourceStage(name,table,stages[0]?.execution_version),source:true,order:0})),
    ...stages.filter(s=>s.kind!=='input').map(stage=>({id:stage.id,stage,source:false,order:stage.order}))],edges:[],unresolved:{}};
  for(const stage of stages.filter(s=>s.kind!=='input')){
    const refs=[...new Set([...(stage.inputs?.map(i=>i.ref)||stage.input_refs||[]),...(stage.depends_on||[])])];
    const conservative=(stage.operations?.length?stage.operations:[stage]).some(op=>(op.params as {dependency_kind?:string}).dependency_kind==='conservative_code_reference');
    for(const ref of refs){
      const from=ownerOf(graph,ref);
      if(!from){graph.unresolved[stage.id]=(graph.unresolved[stage.id]||0)+1;continue;}
      if(from===stage.id)continue;
      const edge=graph.edges.find(e=>e.from===from&&e.to===stage.id);
      if(edge)edge.refs.push(ref);else graph.edges.push({from,to:stage.id,refs:[ref],conservative});
    }
  }
  return graph;
}
export function graphNeighbors(graph:WorkflowGraph,id:string){
  return {parents:graph.nodes.filter(n=>graph.edges.some(e=>e.from===n.id&&e.to===id)),children:graph.nodes.filter(n=>graph.edges.some(e=>e.from===id&&e.to===n.id))};
}
export function workflowReviewWindow(graph:WorkflowGraph,id:string):Stage[]{
  const current=graph.nodes.find(n=>n.id===id);
  if(!current)return [];
  const next=graph.nodes.filter(n=>!n.source&&(current.source
    ? graph.edges.some(e=>e.from===current.id&&e.to===n.id)
    : n.order>current.order)).sort((a,b)=>a.order-b.order)[0];
  return next?[current.stage,next.stage]:[current.stage];
}
export function workflowSourceColors(graph:WorkflowGraph){
  const palette=['#2563eb','#d97706','#9333ea','#059669','#db2777','#0891b2'];
  const sources=graph.nodes.filter(n=>n.source).map((n,i)=>({id:n.id,label:n.stage.label,color:palette[i]||`hsl(${(i*137.5)%360} 65% 40%)`}));
  const operations=new Map(graph.nodes.flatMap(n=>(n.stage.operations||[]).map(op=>[op.id,op] as const)));
  const cache=new Map<string,Set<string>>();
  const origins=(ref:string,visiting=new Set<string>()):Set<string>=>{
    if(cache.has(ref))return cache.get(ref)!;
    if(visiting.has(ref))return new Set();
    const owner=graph.nodes.find(n=>n.id===ownerOf(graph,ref));
    if(!owner)return new Set();
    if(owner.source)return new Set([owner.id]);
    const next=new Set(visiting).add(ref),op=operations.get(ref);
    // Resolve exact operation references before falling back to the Step's inputs.
    const refs=op&&(op.inputs!==undefined||op.input_refs!==undefined||op.depends_on!==undefined)
      ? [...(op.inputs?.map(i=>i.ref)||op.input_refs||[]),...(op.depends_on||[])]
      : ref===owner.id&&owner.stage.output_ref&&operations.has(owner.stage.output_ref)
        ? [owner.stage.output_ref]
        : graph.edges.filter(e=>e.to===owner.id).flatMap(e=>e.refs);
    const result=new Set(refs.flatMap(input=>[...origins(input,next)]));cache.set(ref,result);return result;
  };
  const edgeSources=new Map(graph.edges.map(edge=>{
    const ids=new Set(edge.refs.flatMap(ref=>[...origins(ref)]));
    return [edge,sources.filter(source=>ids.has(source.id))] as const;
  }));
  return {sources,edgeSources};
}
// Simplify only the overview. Execution inputs and the original graph stay intact.
export function workflowDisplayGraph(graph:WorkflowGraph):WorkflowGraph {
  const {edgeSources}=workflowSourceColors(graph);
  const signature=(edge:WorkflowEdge)=>(edgeSources.get(edge)||[]).map(s=>s.id).sort().join('\n');
  let edges=[...graph.edges];
  for(const candidate of graph.edges){
    const source=signature(candidate);
    if(!source||candidate.conservative)continue;
    const pending=[candidate.from],seen=new Set<string>();let alternate=false;
    while(pending.length){
      const id=pending.pop()!;
      if(id===candidate.to){alternate=true;break;}
      if(seen.has(id))continue;
      seen.add(id);
      pending.push(...edges.filter(e=>e!==candidate&&e.from===id&&!e.conservative&&signature(e)===source).map(e=>e.to));
    }
    if(alternate)edges=edges.filter(e=>e!==candidate);
  }
  return {...graph,edges};
}
export function layoutWorkflow(graph:WorkflowGraph,width:number){
  const rank=new Map(graph.nodes.filter(n=>n.source).map(n=>[n.id,0]));
  for(let pass=0;pass<graph.nodes.length;pass++)for(const node of graph.nodes){
    if(rank.has(node.id))continue;
    const parents=graph.edges.filter(e=>e.to===node.id).map(e=>e.from);
    if(parents.every(id=>rank.has(id)))rank.set(node.id,Math.max(0,...parents.map(id=>rank.get(id)!))+1);
  }
  const maxRank=Math.max(1,...rank.values());
  const nodeRank=(id:string)=>rank.get(id)??1;
  const channels=new Map<number,WorkflowEdge[]>();
  for(const edge of graph.edges){
    for(const boundary of new Set([nodeRank(edge.from),nodeRank(edge.to)-1])){
      const edges=channels.get(boundary)||[];edges.push(edge);channels.set(boundary,edges);
    }
  }
  const gap=Math.max(40,...[...channels.values()].map(edges=>edges.length*10+20));
  const degree=Math.max(1,...graph.nodes.flatMap(n=>[graph.edges.filter(e=>e.from===n.id).length,graph.edges.filter(e=>e.to===n.id).length]));
  const nodeHeight=Math.max(78,degree*10+20),rowHeight=nodeHeight+24;
  const nodeWidth=Math.max(112,Math.min(150,(width-24-maxRank*gap)/(maxRank+1)));
  const layers=Array.from({length:maxRank+1},(_,r)=>graph.nodes.filter(n=>(rank.get(n.id)??1)===r));
  const height=Math.max(1,...layers.map(l=>l.length))*rowHeight+24;
  const positions=new Map<string,{x:number;y:number}>();
  layers.forEach((layer,r)=>{
    layer.sort((a,b)=>{const center=(id:string)=>{const parents=graph.edges.filter(e=>e.to===id).flatMap(e=>positions.get(e.from)?.y??[]);return parents.length?parents.reduce((a,b)=>a+b,0)/parents.length:0;};return center(a.id)-center(b.id)||a.order-b.order;});
    layer.forEach((node,i)=>positions.set(node.id,{x:12+r*(nodeWidth+gap),y:(height-layer.length*rowHeight)/2+i*rowHeight}));
  });
  const rail=(edge:WorkflowEdge,boundary:number)=>{
    const edges=channels.get(boundary)!;
    return 12+boundary*(nodeWidth+gap)+nodeWidth+10+(edges.indexOf(edge)+.5)*(gap-20)/edges.length;
  };
  const port=(edge:WorkflowEdge,outgoing:boolean)=>{
    const id=outgoing?edge.from:edge.to;
    const edges=graph.edges.filter(e=>outgoing?e.from===id:e.to===id).sort((a,b)=>{
      const other=(e:WorkflowEdge)=>positions.get(outgoing?e.to:e.from)?.y??0;
      return other(a)-other(b);
    });
    return positions.get(id)!.y+10+(edges.indexOf(edge)+1)*(nodeHeight-20)/(edges.length+1);
  };
  // Reserve horizontal levels per gutter so unrelated edges never share a segment.
  const levels=new Map<number,Set<number>>();
  const reserve=(boundary:number,y:number)=>{
    const used=levels.get(boundary)||new Set<number>();
    while(used.has(y))y+=.25;
    used.add(y);levels.set(boundary,used);return y;
  };
  let bypasses=0;
  const routes=graph.edges.flatMap(edge=>{
    const from=positions.get(edge.from),to=positions.get(edge.to);
    if(!from||!to)return [];
    const start=nodeRank(edge.from),end=nodeRank(edge.to)-1;
    const x1=from.x+nodeWidth,x2=to.x-3,y1=reserve(start,port(edge,true));
    const arrival=port(edge,false);
    const y2=start===end&&arrival===y1?y1:reserve(end,arrival);
    const exit=rail(edge,start),entry=rail(edge,end);
    const bypass=start!==end;
    const lane=height+8+bypasses*12;
    const points=bypass
      ? [{x:x1,y:y1},{x:exit,y:y1},{x:exit,y:lane},{x:entry,y:lane},{x:entry,y:y2},{x:x2,y:y2}]
      : [{x:x1,y:y1},{x:exit,y:y1},{x:exit,y:y2},{x:x2,y:y2}];
    const path=points.map((p,i)=>`${i?'L':'M'}${p.x},${p.y}`).join(' ');
    if(bypass)bypasses++;
    return [{edge,path,points}];
  });
  return {positions,routes,nodeWidth,nodeHeight,width:Math.max(width,24+(maxRank+1)*nodeWidth+maxRank*gap),height:height+(bypasses?bypasses*12+12:0)};
}
export function workflowInputs(stage:Stage){return stage.inputs?.length?stage.inputs:stage.input?[{ref:stage.input_refs?.[0]||'',table:stage.input}]:[];}
export function referencedOutputs(stage:Stage,stages:Stage[]){
  const used=new Set(stages.filter(s=>s.id!==stage.id).flatMap(s=>(s.inputs||[]).map(input=>input.ref)));
  return (stage.operations||[]).filter(op=>op.id!==stage.output_ref&&used.has(op.id));
}
