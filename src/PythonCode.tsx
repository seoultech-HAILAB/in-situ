import { useMemo, type ReactNode } from 'react';

// Display-only lexical highlighting. Preserve source text and render every token
// as escaped React text; code is never executed or inserted as HTML.
const tokens = /(?<comment>#[^\r\n]*)|(?<string>(?:\b[rubf]{1,3})?(?:'''[\s\S]*?(?:'''|$)|"""[\s\S]*?(?:"""|$)|'(?:\\.|[^'\\\r\n])*(?:'|$)|"(?:\\.|[^"\\\r\n])*(?:"|$)))|(?<number>\b(?:0x[\da-f_]+|0b[01_]+|0o[0-7_]+|\d[\d_]*(?:\.[\d_]*)?(?:e[+-]?[\d_]+)?j?)\b)|(?<identifier>[\p{L}_][\p{L}\p{N}_]*)|(?<operator>\*\*|\/\/|:=|==|!=|<=|>=|->|[-+*/%=<>!&|^~])/giu;
const keywords = new Set('and as assert async await break case class continue def del elif else except finally for from global if import in is lambda match nonlocal not or pass raise return try while with yield'.split(' '));
const constants = new Set(['True','False','None','NotImplemented','Ellipsis']);
const builtins = new Set('abs all any bool bytes callable chr dict enumerate filter float format frozenset getattr hasattr hash hex int isinstance issubclass iter len list map max min next object open ord pow print range repr reversed round set slice sorted str sum super tuple type zip Exception ValueError TypeError KeyError'.split(' '));

function highlight(code: string): ReactNode[] {
  const output: ReactNode[]=[];
  let end=0, previousWord='';
  for (const match of code.matchAll(tokens)) {
    const start=match.index!;
    if (start>end) output.push(code.slice(end,start));
    const value=match[0], group=match.groups!;
    let kind=group.comment ? 'comment' : group.string ? 'string' : group.number ? 'number' : group.operator ? 'operator' : 'variable';
    if (group.identifier) {
      if (constants.has(value)) kind='constant';
      else if (keywords.has(value)) kind='keyword';
      else if (previousWord==='class') kind='type';
      else if (previousWord==='def' || /^\s*\(/.test(code.slice(start+value.length))) kind='function';
      else if (builtins.has(value)) kind='type';
      previousWord=value;
    } else previousWord='';
    output.push(<span className={`py-${kind}`} key={start}>{value}</span>);
    end=start+value.length;
  }
  if (end<code.length) output.push(code.slice(end));
  return output;
}

export function PythonCode({ code }: { code: string }) {
  const content=useMemo(()=>highlight(code),[code]);
  return <pre className="python-code" aria-label="읽기 전용 Python 코드"><code>{content}</code></pre>;
}
