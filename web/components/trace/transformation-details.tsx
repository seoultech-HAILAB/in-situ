import { PythonCode } from "./python-code";
import type { Transformation } from "./workspace-diff";

/** Shared verbatim by the In-situ bubble and the Ex-situ explanation panel. */
export function TransformationDetails({ item }: { item: Transformation }) {
  return <section className="transformation-operation">
    <p>{item.text}</p>
    <div className="transformation-code"><div className="transformation-code-label">현재 연산 · 수정 대상{item.line && <span>L{item.line.start}{item.line.start_column !== undefined ? `:${(item.line.start_character ?? item.line.start_column)+1}` : ""}{item.line.end !== item.line.start ? `–L${item.line.end}` : ""}</span>}</div><PythonCode code={item.code} focus={item.focus} startLine={item.line?.start ?? 1} /></div>
    {item.source === "ast" && <span className="transformation-source">코드 분석으로 작성한 설명</span>}
  </section>;
}
