import { PythonCode } from "./python-code";
import type { Transformation } from "./workspace-diff";

/** The same minimal explanation and numbered code in both conditions. */
export function TransformationDetails({ item, plainCode = false }: { item: Transformation; plainCode?: boolean }) {
  return <section className="transformation-operation">
    <p>{item.text}</p>
    <div className="transformation-code"><PythonCode code={item.code} focus={item.focus} startLine={item.line?.start ?? 1} plain={plainCode} /></div>
  </section>;
}
