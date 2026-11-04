import type { Stage } from "@/lib/trace";
import { WorkspaceTable } from "./workspace-table";

/** Only the server's verified, current-Step inputs; never source lineage. */
export function DirectUsedTables({ tables, identity }: { tables: NonNullable<Stage["direct_tables"]>; identity: string }) {
  if (!tables.length) return null;
  return <section className="direct-used-tables" aria-label="현재 Step에서 직접 사용한 보조 테이블">
    <h3>이 Step에서 함께 사용한 표</h3>
    {tables.map(item => <section className="direct-used-table" key={item.id} aria-label={`${item.name} · 직접 사용한 표`}>
      <header><strong>{item.name}</strong><span>{item.table.rows.length}행 × {item.table.columns.length}열</span></header>
      <ul>{item.uses.map((use,index) => <li key={index}><p>{use.text}</p>{use.line && <span className="direct-used-line">L{use.line}</span>}</li>)}</ul>
      <WorkspaceTable data={item.table} identity={`${identity}:direct:${item.id}`} />
    </section>)}
  </section>;
}
