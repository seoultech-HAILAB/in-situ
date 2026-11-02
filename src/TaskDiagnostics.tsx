import type {TaskCandidate} from './studyTypes';

export function TaskDiagnostics({task}:{task:TaskCandidate}) {
  const diagnosis=task.diagnostics;
  if(!diagnosis)return null;
  const title=diagnosis.status==='normal'?'오류 없음 · 정상 대조':diagnosis.status==='error'
    ?`오류 ${diagnosis.fault_steps.length}개 Step · ${diagnosis.fault_steps.map(step=>`Step ${step}`).join(', ')}`:'오류 정보 미등록';
  return <details className="catalog-diagnostics">
    <summary>초기 오류 해설 · {title}</summary>
    <p className="diagnostic-scope">연구자 전용 · 저장된 초기 코드 기준입니다. 수정 후 현재 실행에 대한 판정은 아닙니다. 코드 줄 번호는 초기 전체 코드 기준입니다.</p>
    <p>{diagnosis.note}</p>
    {diagnosis.errors.map(error=><section className="diagnostic-error" key={error.step}>
      <h5>Step {error.step} · {error.label}</h5>
      <small>초기 코드 {error.code_location.start}–{error.code_location.end}줄</small>
      <dl><dt>잘못된 처리</dt><dd>{error.problem}</dd><dt>데이터에 미치는 영향</dt><dd>{error.impact}</dd><dt>올바른 수정</dt><dd>{error.repair}</dd></dl>
      {error.code_diff&&<details className="diagnostic-diff"><summary>이 Step의 초기·참조 코드 차이</summary><pre>{error.code_diff}</pre></details>}
    </section>)}
    {!!diagnosis.propagated_steps.length&&<p>참조 실행과 차이가 관찰된 후속 Step: {diagnosis.propagated_steps.join(', ')}. 이 차이는 앞선 오류의 전파이며 추가 오류 위치로 세지 않습니다.</p>}
    {!!diagnosis.evidence.length&&<div className="diagnostic-evidence"><strong>저장된 검증 기록</strong><ul>{diagnosis.evidence.map(item=><li key={item}>{item}</li>)}</ul></div>}
  </details>;
}
