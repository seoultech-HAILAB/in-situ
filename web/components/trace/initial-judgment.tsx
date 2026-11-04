"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { api, type Session } from "@/lib/trace";

type Answer = "steps" | "none" | "uncertain";
const answers: [Answer, string][] = [
  ["steps", "문제가 있는 단계가 있다"],
  ["none", "문제 없음"],
  ["uncertain", "판단하기 어렵다"],
];

/** Questionnaire about the initial pipeline; appears only when the task defines a baseline. */
export function InitialJudgment({ session, busy }: { session: Session; busy: boolean }) {
  const baseline = session.review_baseline;
  const prior = session.initial_step_judgments?.filter((j) => j.condition === session.condition).at(-1);
  const [answer, setAnswer] = useState<Answer>(prior?.answer || "uncertain");
  const [chosen, setChosen] = useState<string[]>(prior?.step_ids || []);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  if (!baseline || !session.run) return null;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      await api(`/sessions/${session.id}/initial-step-judgment`, {
        submission_id: crypto.randomUUID(),
        initial_run_id: baseline!.run_id,
        execution_version: session.run!.id,
        condition: session.condition,
        answer,
        step_ids: answer === "steps" ? chosen : [],
      });
      setMessage("응답을 저장했습니다.");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} className="rounded-md border bg-card p-5">
      <fieldset disabled={busy || saving} className="space-y-4">
        <legend className="font-medium">처음 결과에 대한 판단</legend>
        <p className="text-sm text-muted-foreground">수정하기 전 처음 결과를 기준으로 답해 주세요.</p>
        <RadioGroup
          value={answer}
          onValueChange={(v) => {
            setAnswer(v as Answer);
            setMessage("");
          }}
          className="flex flex-wrap gap-x-6 gap-y-2"
        >
          {answers.map(([value, label]) => (
            <Label key={value} className="flex items-center gap-2 font-normal">
              <RadioGroupItem value={value} />
              {label}
            </Label>
          ))}
        </RadioGroup>
        {answer === "steps" && (
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            {baseline.steps.map((s) => (
              <Label key={s.id} className="flex items-center gap-2 font-normal">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={chosen.includes(s.id)}
                  onChange={(e) => {
                    setChosen((ids) => (e.target.checked ? [...ids, s.id] : ids.filter((id) => id !== s.id)));
                    setMessage("");
                  }}
                />
                {s.order}. {s.label}
              </Label>
            ))}
          </div>
        )}
        <div className="flex items-center gap-3">
          <Button type="submit" variant="outline" disabled={answer === "steps" && !chosen.length}>
            {saving ? "저장하는 중" : "응답 저장"}
          </Button>
          {message && (
            <p role="status" className="text-sm text-muted-foreground">
              {message}
            </p>
          )}
        </div>
      </fieldset>
    </form>
  );
}
