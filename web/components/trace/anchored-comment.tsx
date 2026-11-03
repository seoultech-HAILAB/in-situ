"use client";

import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { LoaderCircle, Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScopeSelect, type Scope } from "./scope-select";

/** Keeps a floating panel next to a table element, flipping above when needed. */
export function useAnchoredPosition(anchor: HTMLElement, panel: React.RefObject<HTMLDivElement | null>, hideWhenClipped: boolean) {
  const [pos, setPos] = useState({ left: 12, top: 12, visible: false, above: false, arrowLeft: 20 });
  useLayoutEffect(() => {
    let frame = 0;
    const place = () => {
      if (!panel.current || !anchor.isConnected) return setPos((p) => ({ ...p, visible: false }));
      const a = anchor.getBoundingClientRect();
      const p = panel.current.getBoundingClientRect();
      const clip = anchor.closest('[role="region"]')?.getBoundingClientRect();
      const inView =
        a.bottom > 0 && a.top < innerHeight && (!clip || (a.bottom > clip.top && a.top < clip.bottom && a.right > clip.left && a.left < clip.right));
      const left = Math.max(12, Math.min(a.left, innerWidth - p.width - 12));
      const below = a.bottom + 8;
      const top =
        below + p.height <= innerHeight - 12 ? below : a.top - p.height - 8 >= 12 ? a.top - p.height - 8 : Math.max(12, innerHeight - p.height - 12);
      setPos({ left, top, visible: !hideWhenClipped || inView, above: top < a.top, arrowLeft: Math.max(18, Math.min(p.width - 18, a.left + a.width / 2 - left)) });
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(place);
    };
    const observer = new ResizeObserver(schedule);
    if (panel.current) observer.observe(panel.current);
    observer.observe(anchor);
    const viewport = anchor.closest('[role="region"]');
    if (viewport) observer.observe(viewport);
    place();
    addEventListener("resize", schedule);
    addEventListener("scroll", schedule, true);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      removeEventListener("resize", schedule);
      removeEventListener("scroll", schedule, true);
    };
  }, [anchor, panel, hideWhenClipped]);
  return pos;
}

export function useDismiss(anchor: HTMLElement, panel: React.RefObject<HTMLDivElement | null>, onDismiss: () => void, locked: boolean) {
  useLayoutEffect(() => {
    const outside = (e: PointerEvent) => {
      if (locked || !(e.target instanceof Node)) return;
      if (panel.current?.contains(e.target) || anchor.contains(e.target)) return;
      // Popovers/selects render in their own portal; treat them as inside.
      if ((e.target as Element).closest?.("[data-slot$='content'],[role='listbox']")) return;
      onDismiss();
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !locked) onDismiss();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [anchor, panel, onDismiss, locked]);
}

/** Small toolbar shown right after a selection: the only entry to a comment. */
export function SelectionAction({
  anchor,
  info,
  onEdit,
  onDismiss,
}: {
  anchor: HTMLElement;
  info?: ReactNode;
  onEdit: () => void;
  onDismiss: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const pos = useAnchoredPosition(anchor, panel, true);
  useDismiss(anchor, panel, onDismiss, false);
  return createPortal(
    <div
      ref={panel}
      role="toolbar"
      aria-label="선택한 영역"
      style={{ left: pos.left, top: pos.top, visibility: pos.visible ? "visible" : "hidden" }}
      className="fixed z-40 flex max-w-80 flex-col gap-2 rounded-md border bg-popover p-1.5 shadow-lg"
    >
      <Button size="sm" onClick={onEdit} className="self-start">
        <Pencil /> 수정 요청
      </Button>
      {info && <div className="border-t px-1.5 pt-2 pb-1">{info}</div>}
    </div>,
    document.body,
  );
}

export function CommentPanel({
  anchor,
  title,
  preview,
  value,
  onChange,
  scope,
  onScope,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  anchor: HTMLElement;
  title: string;
  preview: string;
  value: string;
  onChange: (text: string) => void;
  scope: Scope;
  onScope: (scope: Scope) => void;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const pos = useAnchoredPosition(anchor, panel, false);
  useDismiss(anchor, panel, onClose, busy);
  useLayoutEffect(() => input.current?.focus({ preventScroll: true }), [anchor]);
  return createPortal(
    <div
      ref={panel}
      role="dialog"
      aria-label="수정 요청"
      style={{ left: pos.left, top: pos.top }}
      className="fixed z-50 flex w-[min(420px,calc(100vw-24px))] flex-col gap-3 rounded-lg border bg-popover p-4 shadow-xl"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{title}</p>
          {preview && <p className="mt-0.5 line-clamp-3 text-xs whitespace-pre-line text-muted-foreground">{preview}</p>}
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="닫기" disabled={busy} onClick={onClose}>
          <X />
        </Button>
      </div>
      <Textarea
        ref={input}
        aria-label="수정할 내용"
        placeholder="어떻게 바뀌어야 하는지 적어 주세요"
        value={value}
        disabled={busy}
        rows={3}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !e.nativeEvent.isComposing && !busy && value.trim()) {
            e.preventDefault();
            onSubmit();
          }
        }}
      />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex items-center justify-between gap-2">
        <ScopeSelect value={scope} onChange={onScope} disabled={busy} />
        <Button disabled={busy || !value.trim()} onClick={onSubmit}>
          {busy && <LoaderCircle className="animate-spin" />}
          {busy ? "반영하는 중" : "수정 요청"}
        </Button>
      </div>
    </div>,
    document.body,
  );
}
