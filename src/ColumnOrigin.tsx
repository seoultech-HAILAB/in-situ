import type {Stage} from './types';

const operations:Record<string,string>={sum:'합계',mean:'평균',min:'최솟값',max:'최댓값',count:'결측을 제외한 개수',size:'행 개수',nunique:'고유값 개수',median:'중앙값',first:'첫 값',last:'마지막 값',prod:'곱'};

export function ColumnOriginDetails({stage,column}:{stage:Stage;column:string}){
  // A semantic Step can contain several real operations. Its own params may be
  // empty; use the executed operation's verified column metadata and explanation.
  const direct=stage.trace_level==='detailed'&&(stage.params.formulas?.[column]||stage.params.aggregations?.[column]);
  const operation=direct?stage:[...(stage.operations||[])].reverse().find(op=>op.trace_level==='detailed'&&(op.params.formulas?.[column]||op.params.aggregations?.[column]));
  const formula=operation?.params.formulas?.[column],aggregation=operation?.params.aggregations?.[column];
  const description=stage.column_explanations?.[column]||operation?.column_explanations?.[column];
  const sources=formula?.sources||(aggregation?[aggregation.column==='*'?'그룹의 행':aggregation.column]:[]);
  return <div className="column-origin-detail">
      <strong>생성 관계</strong>
      {sources.length>0&&<div className="column-origin-path"><span>{sources.join(' · ')}</span><span aria-hidden="true">→</span><b>{column}</b></div>}
      <p>{description||(aggregation&&operations[aggregation.operation]?`${operation?.params.keys?.length?operation.params.keys.join(' · ')+'별 ':''}${aggregation.column==='*'?'':aggregation.column+' '}${operations[aggregation.operation]}`:'이 열의 생성 방식에 대한 상세 설명은 확인되지 않았습니다.')}</p>
    </div>;
}

export function ColumnOrigin({stage,column}:{stage:Stage;column:string}){
  return <details className="column-origin" onClick={event=>event.stopPropagation()}>
    <summary title="클릭하여 열 생성 관계 확인">+ {column} 열 <span aria-hidden="true">⌄</span></summary>
    <ColumnOriginDetails stage={stage} column={column}/>
  </details>;
}
