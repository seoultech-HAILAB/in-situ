"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export type Scope = "step" | "pipeline";
const items = { step: "이 단계만 수정", pipeline: "전체 단계 수정" } satisfies Record<Scope, string>;

export function ScopeSelect({ value, onChange, disabled }: { value: Scope; onChange: (v: Scope) => void; disabled?: boolean }) {
  return (
    <Select items={items} value={value} disabled={disabled} onValueChange={(v) => v && onChange(v as Scope)}>
      <SelectTrigger size="sm" aria-label="수정 범위" className="min-w-36">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {(Object.keys(items) as Scope[]).map((key) => (
          <SelectItem key={key} value={key}>
            {items[key]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
