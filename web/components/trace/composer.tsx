"use client";

import { forwardRef } from "react";
import { ArrowUp, LoaderCircle, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScopeSelect, type Scope } from "./scope-select";

/** Chat-style revision prompt shared by both conditions. */
export const Composer = forwardRef<
  HTMLTextAreaElement,
  {
    value: string;
    onChange: (v: string) => void;
    scope: Scope;
    onScope: (v: Scope) => void;
    context: string;
    preview?: string;
    onClearContext?: () => void;
    busy: boolean;
    disabled: boolean;
    error?: string;
    onSubmit: () => void;
    onFocus?: () => void;
  }
>(function Composer(p, ref) {
  const canSend = !p.disabled && !p.busy && !!p.value.trim();
  return (
    <form
      className="mx-auto w-full max-w-3xl"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) p.onSubmit();
      }}
    >
      {p.error && (
        <p role="alert" className="mb-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {p.error}
        </p>
      )}
      <div className="rounded-2xl border bg-card shadow-[0_1px_2px_rgba(16,24,40,.04),0_4px_16px_rgba(16,24,40,.06)] focus-within:border-foreground/25">
        <div className="flex items-center gap-2 px-3 pt-2.5">
          <span className="inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-md bg-muted py-0.5 pr-1 pl-2 text-xs">
            <span className="truncate font-medium">{p.context}</span>
            {p.preview && <span className="truncate text-muted-foreground">{p.preview}</span>}
            {p.onClearContext ? (
              <button type="button" aria-label="선택 해제" onClick={p.onClearContext} className="rounded-sm p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
                <X className="size-3" />
              </button>
            ) : (
              <span className="w-1" />
            )}
          </span>
        </div>
        <label htmlFor="revision" className="sr-only">
          수정 요청
        </label>
        <textarea
          ref={ref}
          id="revision"
          rows={1}
          value={p.value}
          disabled={p.disabled}
          placeholder={p.disabled ? "확정한 결과는 수정할 수 없습니다" : p.onClearContext ? "선택한 부분을 어떻게 바꿀지 적어 주세요" : "어떻게 바뀌어야 하는지 적어 주세요"}
          onFocus={p.onFocus}
          onChange={(e) => p.onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (canSend) p.onSubmit();
            }
          }}
          className="block max-h-48 min-h-11 w-full resize-none bg-transparent px-4 py-2.5 text-[15px] leading-6 [field-sizing:content] outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
        />
        <div className="flex items-center justify-between gap-2 px-2 pb-2">
          <ScopeSelect value={p.scope} onChange={p.onScope} disabled={p.disabled || p.busy} />
          <Button type="submit" size="icon" aria-label="수정 요청 보내기" disabled={!canSend} className="size-8 rounded-full">
            {p.busy ? <LoaderCircle className="animate-spin" /> : <ArrowUp />}
          </Button>
        </div>
      </div>
    </form>
  );
});
