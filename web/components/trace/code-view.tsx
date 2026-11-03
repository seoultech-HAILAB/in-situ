import { PythonCode } from "@/lib/trace";

/** Read-only editor view: line-number gutter plus optional highlighted line ranges. */
export function CodeView({ code, highlight = [] }: { code: string; highlight?: { start: number; end: number }[] }) {
  const lines = code.split("\n").length;
  return (
    <div className="code-view relative flex min-w-max">
      <div aria-hidden className="code-gutter select-none">
        {Array.from({ length: lines }, (_, i) => (
          <div key={i}>{i + 1}</div>
        ))}
      </div>
      <div className="relative min-w-0 flex-1">
        {highlight.map((h, i) => (
          <div
            key={i}
            aria-hidden
            className="code-mark"
            style={{ top: `calc(var(--code-pad) + ${h.start - 1} * var(--code-line))`, height: `calc(${h.end - h.start + 1} * var(--code-line))` }}
          />
        ))}
        <PythonCode code={code} />
      </div>
    </div>
  );
}
