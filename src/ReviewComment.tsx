import { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowUpRight, Check, LoaderCircle, MessageSquare, X } from 'lucide-react';
import type { ReviewCommentRecord } from './types';

export type CommentReceipt = { run_id: string; version: number };
export type CommentHistory = { id: string; code_version: number; review_comment?: ReviewCommentRecord }[];

export function ReviewComment({ anchor, title, preview, version, value, onChange, scope, onScope,
  source, demo, busy, error, receipt, history, onClose, onSubmit }: {
  anchor: HTMLElement; title: string; preview: string; version: number; value: string;
  onChange: (text: string) => void; scope: 'step' | 'pipeline';
  onScope: (value: 'step' | 'pipeline') => void; source: boolean; demo: boolean; busy: boolean;
  error: string; receipt?: CommentReceipt; history: CommentHistory;
  onClose: () => void; onSubmit: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const [position, setPosition] = useState({ left: 12, top: 12 });
  useLayoutEffect(() => {
    let frame = 0;
    function place() {
      if (!panel.current || !anchor.isConnected) return;
      const a = anchor.getBoundingClientRect(), p = panel.current.getBoundingClientRect();
      const left = Math.max(12, Math.min(a.left, window.innerWidth - p.width - 12));
      const below = a.bottom + 10;
      const top = below + p.height <= window.innerHeight - 12 ? below :
        a.top - p.height - 10 >= 12 ? a.top - p.height - 10 : Math.max(12, window.innerHeight - p.height - 12);
      setPosition({ left, top });
    }
    const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(place); };
    const observer = new ResizeObserver(schedule);
    if (panel.current) observer.observe(panel.current);
    place(); window.addEventListener('resize', schedule); window.addEventListener('scroll', schedule, true);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener('resize', schedule); window.removeEventListener('scroll', schedule, true); };
  }, [anchor]);
  useLayoutEffect(() => { if (!receipt) input.current?.focus({ preventScroll: true }); }, [anchor, receipt]);
  useLayoutEffect(() => {
    function outside(event: PointerEvent) {
      if (!busy && event.target instanceof Node && !panel.current?.contains(event.target) && !anchor.contains(event.target)) onClose();
    }
    function escape(event: KeyboardEvent) { if (event.key === 'Escape' && !busy) { onClose(); if (anchor.isConnected) anchor.focus({ preventScroll: true }); } }
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [anchor, busy, onClose]);
  return createPortal(<div ref={panel} className="review-comment" style={position} role="dialog" aria-label="선택 위치 수정 댓글" aria-modal="false">
    <header><MessageSquare size={17}/><strong>수정 댓글</strong><span>v{version}</span><button className="icon-button" aria-label="수정 댓글 닫기" disabled={busy} onClick={onClose}><X size={17}/></button></header>
    <blockquote><strong>{title}</strong><p>{preview}</p></blockquote>
    {!!history.length && <div className="comment-history" aria-label="이 Step의 이전 수정 요청">{history.map(r => <article key={r.id}><p>{r.review_comment?.request}</p><span>v{r.review_comment?.base_code_version} → v{r.code_version} · 재실행 완료</span></article>)}</div>}
    {receipt ? <div className="comment-receipt" role="status"><Check size={17}/><span>수정·재실행 완료 · v{receipt.version}<small>변경된 표를 확인하고 다시 선택해 요청할 수 있습니다.</small></span></div> : <>
      <label className="comment-scope">수정 범위<select aria-label="댓글 수정 범위" disabled={busy || source} value={scope} onChange={e => onScope(e.target.value as 'step' | 'pipeline')}><option value="step">선택 Step</option><option value="pipeline">전체 파이프라인</option></select></label>
      {source && <p className="comment-note">입력 데이터를 참고해 전체 파이프라인의 수정을 요청합니다.</p>}
      {demo && <p className="comment-note">데모 · 사전 작성 코드와 제한된 수정 규칙을 사용합니다.</p>}
      <textarea ref={input} aria-label="선택 위치 자연어 수정 요청" placeholder="이 부분을 어떻게 바꿀까요?" value={value} disabled={busy} onChange={e => onChange(e.target.value)} onKeyDown={e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !e.nativeEvent.isComposing && !busy && value.trim()) { e.preventDefault(); onSubmit(); } }}/>
      {error && <p className="comment-error" role="alert">{error}</p>}
      <footer><span>{busy ? '수정·재실행 중' : 'Ctrl/⌘ + Enter로 전송'}</span><button className="primary" disabled={busy || !value.trim()} onClick={onSubmit}>{busy ? <LoaderCircle className="spin" size={15}/> : <ArrowUpRight size={15}/>} 수정 요청</button></footer>
    </>}
  </div>, document.body);
}
