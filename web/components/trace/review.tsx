"use client";

import { useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowDown, ChevronDown, LoaderCircle, Table2, Undo2 } from "lucide-react";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import {
  buildWorkflowGraph,
  groupBorder,
  groupColor,
  isExplained,
  ownerOf,
  referencedOutputs,
  reviewGroups,
  stepTitle,
  tableChanges,
  targetKey,
  workflowInputs,
  type Condition,
  type HistoryEntry,
  type HistoryEvent,
  type Ref,
  type ReviewTarget,
  type Run,
  type Selection,
  type Session,
  type Stage,
} from "@/lib/trace";
import { CodeView } from "./code-view";
import { Composer } from "./composer";
import { DataTable } from "./data-table";
import { hasActivity, recordsFor, tableMarks, VIEW_LABEL, type TargetRecord } from "./history";
import { InitialJudgment } from "./initial-judgment";
import { PreviewPanel } from "./preview-panel";
import { Inspector } from "./inspector";
import type { Scope } from "./scope-select";
import { describeTarget } from "./target-text";

const title = (s: Stage) => s.nl_explanation?.title || stepTitle(s);

export type Pick = { target: ReviewTarget; stage: Stage };

export function Review(props: {
  session: Session;
  run?: Run;
  steps: Stage[];
  step?: Stage;
  research: boolean;
  busy: string;
  error: string;
  selection: Selection | null;
  pick: Pick | null;
  history: HistoryEntry[];
  request: string;
  scope: Scope;
  onRequest: (v: string) => void;
  onScope: (v: Scope) => void;
  onStep: (id: string) => void;
  onSubmit: () => void;
  onApplyPreview: () => void;
  onDiscardPreview: () => void;
  onUndo: () => void;
  onConfirm: () => void;
  onCondition: (c: Condition) => void;
  onNewTask: () => void;
  onReloadExplanations: () => void;
  onCell: (stage: Stage, row: string, column: string, role: "input" | "output", inputRef: string | undefined, additive: boolean) => void;
  onTarget: (stage: Stage, target: ReviewTarget, final?: boolean, additive?: boolean) => unknown;
  onClearPick: () => void;
  onHistory: (event: HistoryEvent, target: ReviewTarget, extra?: Record<string, unknown>) => void;
  onAsk: (target: ReviewTarget) => void;
  onSummaryOpen: () => void;
}) {
  const { session, run, steps, step, busy, selection, pick } = props;
  const isEx = session.condition === "ex";
  const done = !!session.confirmed;
  const locked = !!busy || done;
  const composer = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const [sourcesOpen, setSourcesOpen] = useState(true);
  const position = step ? steps.findIndex((s) => s.id === step.id) + 1 : 0;
  const runIndex = run ? session.runs.findIndex((r) => r.id === run.id) + 1 : 0;
  const runLabel = runIndex ? `실행 ${runIndex}번째 결과` : "";
  const graph = useMemo(() => buildWorkflowGraph(run?.stages || [], session.sources || {}), [run, session.sources]);
  const groups = useMemo(() => (step ? reviewGroups(step) : { inputRows: {}, outputCells: {}, groups: [] }), [step]);
  const delta = useMemo(() => (step ? tableChanges(step) : null), [step]);
  const inputs = step ? workflowInputs(step) : [];
  const records = useMemo(() => recordsFor(props.history, session.run?.id), [props.history, session.run?.id]);
  const picked = pick?.target ?? null;
  const pickText = pick ? describeTarget(pick.target, pick.stage.table) : null;

  // Provenance of the single selected cell (same derivation as the legacy client).
  const selectedReview = run?.stages.find((s) => s.id === selection?.step);
  const selectedOperation = run?.operations?.find((s) => s.id === selection?.operation_id);
  const selectedInput =
    selection?.table_role === "input" && selectedReview ? workflowInputs(selectedReview).find((i) => i.ref === selection.input_ref) : undefined;
  const inputOwner = selectedInput ? graph.nodes.find((n) => n.id === ownerOf(graph, selectedInput.ref))?.stage : undefined;
  const inputSnapshot = selectedInput ? run?.operations?.find((op) => op.id === selectedInput.ref) || inputOwner : undefined;
  const selectedStage: Stage | undefined =
    selectedInput && selectedReview
      ? {
          ...(inputSnapshot || { ...selectedReview, params: {}, column_explanations: {} }),
          id: selectedReview.id,
          table: selectedInput.table,
          lineage: inputSnapshot?.lineage || {},
          row_sources: inputSnapshot?.row_sources || {},
          trace_level: inputSnapshot?.trace_level || "common",
        }
      : selectedOperation
        ? { ...selectedOperation, id: selectedReview?.id || selectedOperation.id }
        : selectedReview;
  const context = selection && selectedStage?.contexts?.[selection.row]?.[selection.column];
  const refs: Ref[] = (!isEx && selection && selectedStage?.lineage[selection.row]?.[selection.column]) || [];
  const keyRefs: Ref[] = isEx ? [] : context?.key_sources || (selection && selectedStage?.params.decision_sources?.[selection.row]) || [];
  const shared = { picked, selection, disabled: locked, refs, keyRefs };

  const ask = () => {
    if (picked) props.onAsk(picked);
    composer.current?.focus();
  };
  const jump = (rec: TargetRecord) => {
    const s = steps.find((x) => x.id === rec.target.step_id);
    if (!s) return;
    const table = tableFor(s, rec.target);
    props.onStep(s.id);
    if (table) props.onTarget({ ...s, table }, rec.target, true);
  };

  const composerContext = isEx
    ? { context: `${position}단계` }
    : pickText
      ? { context: pickText.title, preview: pickText.preview.split("\n")[0], onClearContext: props.onClearPick }
      : { context: `${position}단계 전체` };

  return (
    <div className="flex h-dvh flex-col bg-background">
      <TopBar {...props} locked={locked} done={done} />

      <div className="flex min-h-0 flex-1">
        <aside aria-label="과제와 단계" className="hidden w-64 shrink-0 flex-col border-r bg-sidebar md:flex">
          <div className="p-2">
            <button
              type="button"
              onClick={() => {
                setSourcesOpen(true);
                scroller.current?.scrollTo({ top: 0, behavior: "smooth" });
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm hover:bg-black/5"
            >
              <Table2 className="size-4 text-muted-foreground" /> Input과 Target
            </button>
          </div>
          <nav aria-label="변환 단계" className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
            <p className="px-2.5 pt-2 pb-1.5 text-xs font-medium text-muted-foreground">단계</p>
            <ol className="space-y-0.5">
              {steps.map((s, i) => {
                const active = s.id === step?.id;
                const mine = [...records.values()].filter((r) => r.target.step_id === s.id && hasActivity(r));
                const checked = mine.filter((r) => r.checked).length;
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      disabled={!!busy}
                      aria-current={active ? "step" : undefined}
                      onClick={() => props.onStep(s.id)}
                      className={cn(
                        "flex w-full gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm leading-snug transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-60",
                        active ? "bg-black/[.07] font-medium" : "text-foreground/80 hover:bg-black/5",
                      )}
                    >
                      <span className="w-4 shrink-0 text-muted-foreground tabular-nums">{i + 1}</span>
                      <span className="min-w-0">
                        <span className="block">{title(s)}</span>
                        {!isEx && mine.length > 0 && (
                          <span className="mt-0.5 block text-xs font-normal text-muted-foreground">
                            기록한 대상 {mine.length}개{checked ? `, 확인 표시 ${checked}개` : ""}
                          </span>
                        )}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
          {!isEx && <ReviewSummary records={records} history={props.history} runId={session.run?.id} steps={steps} onJump={jump} onOpen={props.onSummaryOpen} />}
        </aside>

        <main className="relative flex min-w-0 flex-1 flex-col">
          <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto max-w-[1280px] space-y-5 px-6 pt-5 pb-6">
              <nav aria-label="변환 단계" className="flex gap-1 overflow-x-auto md:hidden">
                {steps.map((s, i) => (
                  <Button key={s.id} size="sm" variant={s.id === step?.id ? "secondary" : "ghost"} disabled={!!busy} onClick={() => props.onStep(s.id)}>
                    {i + 1}. {title(s)}
                  </Button>
                ))}
              </nav>
              <Notices {...props} done={done} />
              <SourceTables session={session} open={sourcesOpen} onOpenChange={setSourcesOpen} />

              {run && step ? (
                <section aria-labelledby="step-title" className="space-y-4">
                  <div className="space-y-1.5">
                    <p className="text-xs text-muted-foreground tabular-nums">
                      {position}/{steps.length}단계
                    </p>
                    <h1 id="step-title" className="text-xl font-semibold tracking-tight">
                      {title(step)}
                    </h1>
                    <p className="max-w-[75ch] leading-7 text-foreground/90">{withCode(step.nl_explanation?.text || "이 단계의 설명이 없습니다.")}</p>
                  </div>

                  {session.preview && session.run ? (
                    <PreviewPanel
                      preview={session.preview}
                      run={session.run}
                      annotated={!isEx}
                      busy={!!busy}
                      onApply={props.onApplyPreview}
                      onDiscard={props.onDiscardPreview}
                    />
                  ) : isEx ? (
                    <div className="grid overflow-hidden rounded-xl border xl:grid-cols-2">
                      <Panel label="코드" meta={`${step.code.split("\n").length}줄`}>
                        <div className="max-h-[560px] overflow-auto bg-[#fbfbfc]">
                          <CodeView code={step.code} />
                        </div>
                      </Panel>
                      <Panel label="결과" meta={`${step.table.stats.rows}행 ${step.table.columns.length}열`} className="border-t xl:border-t-0 xl:border-l">
                        <div className="space-y-4 p-3">
                          <DataTable data={step.table} stage={step} />
                          <OtherOutputs step={step} run={run} render={(op) => <DataTable data={op.table} stage={op} />} />
                        </div>
                      </Panel>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <Panel label="변환 전" meta={inputs.length > 1 ? `표 ${inputs.length}개` : step.input ? `${step.input.stats.rows}행` : ""} className="rounded-xl border">
                        <div className="space-y-3 p-3">
                          {inputs.map((item, index) => {
                            const owner = ownerOf(graph, item.ref);
                            const known = run.operations?.find((op) => op.id === item.ref) || graph.nodes.find((n) => n.id === owner)?.stage;
                            const snapshot: Stage = known
                              ? { ...known, table: item.table }
                              : { ...run.stages[0], table: item.table, lineage: {}, row_sources: {}, trace_level: "common" };
                            const asStep = { ...step, table: item.table };
                            return (
                              <div key={item.ref + index} className="space-y-1.5">
                                {inputs.length > 1 && <p className="text-xs text-muted-foreground">{item.variable || `입력 ${index + 1}`}</p>}
                                <DataTable
                                  data={item.table}
                                  stage={{ ...snapshot, id: step.id, view_operation_id: undefined }}
                                  role="input"
                                  inputRef={item.ref}
                                  annotated
                                  inputDelta={inputs.length === 1 ? delta : null}
                                  groupRows={groups.inputRows}
                                  marks={tableMarks(records, { step: step.id, role: "input", inputRef: item.ref }, item.table)}
                                  {...shared}
                                  handlers={{
                                    onCell: (r, c, _a, add) => props.onCell(asStep, r, c, "input", item.ref, add),
                                    onRange: (t, _a, final) => props.onTarget(asStep, t, final),
                                    onRow: (r, _a, add) => props.onTarget(asStep, { kind: "row", step_id: step.id, row_id: r, table_role: "input", input_ref: item.ref }, true, add),
                                    onColumn: (c, _a, add) => props.onTarget(asStep, { kind: "column", step_id: step.id, column: c, table_role: "input", input_ref: item.ref }, true, add),
                                  }}
                                />
                              </div>
                            );
                          })}
                          {!inputs.length && <p className="text-sm text-muted-foreground">이 단계의 입력 표를 확인하지 못했습니다.</p>}
                        </div>
                      </Panel>
                      <p className="flex items-center justify-center gap-1.5 text-xs text-muted-foreground tabular-nums">
                        <ArrowDown className="size-3.5" />
                        {inputs.length > 1 ? `표 ${inputs.length}개에서` : step.input ? `${step.input.stats.rows}행에서` : ""} {step.table.stats.rows}행으로
                      </p>
                      <Panel label="변환 후" meta={`${step.table.stats.rows}행 ${step.table.columns.length}열`} className="rounded-xl border">
                        <div className="space-y-2 p-3">
                          <Legend delta={delta} groups={groups.groups} marked={records.size > 0} />
                          <DataTable
                            data={step.table}
                            stage={step}
                            annotated
                            delta={delta}
                            groupCells={groups.outputCells}
                            marks={tableMarks(records, { step: step.id, role: "output" }, step.table)}
                            {...shared}
                            handlers={{
                              onCell: (r, c, _a, add) => props.onCell(step, r, c, "output", undefined, add),
                              onRange: (t, _a, final) => props.onTarget(step, t, final),
                              onRow: (r, _a, add) => props.onTarget(step, { kind: "row", step_id: step.id, row_id: r }, true, add),
                              onColumn: (c, _a, add) => props.onTarget(step, { kind: "column", step_id: step.id, column: c }, true, add),
                            }}
                          />
                          <OtherOutputs step={step} run={run} render={(op) => <DataTable data={op.table} stage={op} annotated refs={refs} keyRefs={keyRefs} />} />
                        </div>
                      </Panel>
                      <div className="rounded-xl border xl:hidden">{inspector()}</div>
                    </div>
                  )}
                </section>
              ) : (
                <p className="text-muted-foreground">실행된 변환이 없습니다.</p>
              )}

              {session.review_baseline && <InitialJudgment key={`${session.id}:${run?.id}:${session.condition}`} session={session} busy={!!busy} />}
            </div>
          </div>

          <div className="bg-gradient-to-t from-background from-70% to-transparent px-6 pt-3 pb-4">
            <Composer
              ref={composer}
              value={props.request}
              onChange={props.onRequest}
              scope={props.scope}
              onScope={props.onScope}
              {...composerContext}
              busy={!!busy}
              disabled={done || !run}
              error={props.error}
              onSubmit={props.onSubmit}
            />
          </div>

          {busy && (
            <div role="status" aria-live="polite" className="absolute inset-0 z-20 flex items-start justify-center bg-background/60 pt-40">
              <span className="flex items-center gap-2 rounded-full border bg-card px-4 py-2 text-sm shadow-sm">
                <LoaderCircle className="size-4 animate-spin" /> {busy}
              </span>
            </div>
          )}
        </main>

        {!isEx && step && <aside aria-label="선택 상세" className="hidden w-[360px] shrink-0 border-l xl:block">{inspector()}</aside>}
      </div>

      <footer className="flex h-7 shrink-0 items-center gap-4 border-t bg-sidebar px-4 text-xs text-muted-foreground">
        <span>{runLabel}</span>
        {step && (
          <span className="tabular-nums">
            {position}단계 결과 {step.table.stats.rows}행 {step.table.columns.length}열
          </span>
        )}
        {!isEx && pickText && <span className="ml-auto truncate">선택: {pickText.title}</span>}
      </footer>
    </div>
  );

  function inspector() {
    if (!step) return null;
    const rec = picked ? records.get(targetKey(picked)) : undefined;
    return (
      <Inspector
        target={picked}
        title={pickText?.title || ""}
        preview={pickText?.preview || ""}
        step={step}
        stage={picked?.table_role === "input" ? selectedStage : selectedStage || step}
        refs={refs}
        keyRefs={keyRefs}
        record={rec}
        runLabel={runLabel}
        locked={locked}
        onView={(event) => picked && props.onHistory(event, picked)}
        onNote={(note) => picked && props.onHistory("review_note_saved", picked, { note })}
        onMark={(checked) => picked && props.onHistory("review_mark_set", picked, { checked })}
        onAsk={ask}
      />
    );
  }
}

function TopBar(props: Parameters<typeof Review>[0] & { locked: boolean; done: boolean }) {
  const { session, run, locked, done } = props;
  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b px-4">
      <span className="font-semibold tracking-tight">TRACE</span>
      <span className="text-muted-foreground/60" aria-hidden>
        /
      </span>
      <span className="min-w-0 truncate text-sm">{session.task_display?.title}</span>
      <div className="ml-auto flex items-center gap-2">
        {props.research && <ResearchControls condition={session.condition} busy={!!props.busy} onCondition={props.onCondition} onNewTask={props.onNewTask} />}
        <Button variant="ghost" size="sm" disabled={locked || (!run?.parent_run_id && session.status !== "failed")} onClick={props.onUndo}>
          <Undo2 /> 이전 결과로 되돌리기
        </Button>
        <AlertDialog>
          <AlertDialogTrigger render={<Button size="sm" disabled={locked || session.status !== "ready"} />}>
            {done ? "확정 완료" : "이 결과로 확정"}
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>현재 결과로 확정할까요?</AlertDialogTitle>
              <AlertDialogDescription>확정하면 이 과제의 검수를 마칩니다. 이후에는 수정 요청을 보낼 수 없습니다.</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>계속 검수하기</AlertDialogCancel>
              <AlertDialogAction onClick={props.onConfirm}>확정</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </header>
  );
}

function Notices(props: Parameters<typeof Review>[0] & { done: boolean }) {
  const { session, run, done } = props;
  return (
    <>
      {done && (
        <Alert>
          <AlertTitle>검수를 마쳤습니다</AlertTitle>
          <AlertDescription>결과를 확정했습니다. 연구자에게 알려 주세요.</AlertDescription>
        </Alert>
      )}
      {session.error && !done && (
        <Alert variant="destructive">
          <AlertTitle>마지막 수정 요청을 적용하지 못했습니다</AlertTitle>
          <AlertDescription>{session.error.message} 아래 표는 그 전 결과입니다.</AlertDescription>
        </Alert>
      )}
      {run && !isExplained(run) && (
        <Alert>
          <AlertTitle>단계 설명을 불러오지 못했습니다</AlertTitle>
          <AlertDescription>{run.explanation_error}</AlertDescription>
          <AlertAction>
            <Button size="sm" variant="outline" disabled={!!props.busy} onClick={props.onReloadExplanations}>
              다시 불러오기
            </Button>
          </AlertAction>
        </Alert>
      )}
    </>
  );
}

/** Editor-style panel: a tab strip with the label and a size, then the content. */
function Panel({ label, meta, className, children }: { label: string; meta?: string; className?: string; children: ReactNode }) {
  return (
    <section className={cn("min-w-0 overflow-hidden bg-card", className)}>
      <div className="flex h-9 items-center gap-2 border-b bg-panel-head px-3 text-xs">
        <span className="font-medium">{label}</span>
        {meta && <span className="text-muted-foreground tabular-nums">{meta}</span>}
      </div>
      {children}
    </section>
  );
}

/** Collapsible summary of this run's review records, grouped by step (in-situ). */
function ReviewSummary({
  records,
  history,
  runId,
  steps,
  onJump,
  onOpen,
}: {
  records: Map<string, TargetRecord>;
  history: HistoryEntry[];
  runId?: string;
  steps: Stage[];
  onJump: (r: TargetRecord) => void;
  onOpen: () => void;
}) {
  const active = [...records.values()].filter(hasActivity);
  const earlier = history.filter((e) => e.execution_version !== runId).length;
  return (
    <Collapsible
      className="border-t"
      onOpenChange={(open) => {
        if (open) onOpen();
      }}
    >
      <CollapsibleTrigger className="group flex w-full items-center justify-between px-4 py-2.5 text-left text-sm hover:bg-black/5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none focus-visible:ring-inset">
        <span>
          검수 기록 <span className="text-muted-foreground tabular-nums">{active.length}</span>
        </span>
        <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-panel-open:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="max-h-72 space-y-3 overflow-y-auto px-2 pb-3">
        {steps.map((s, i) => {
          const mine = active.filter((r) => r.target.step_id === s.id);
          if (!mine.length) return null;
          return (
            <div key={s.id}>
              <p className="px-2 pb-1 text-xs text-muted-foreground">
                {i + 1}. {title(s)}
              </p>
              <ul>
                {mine.map((r) => (
                  <li key={targetKey(r.target)}>
                    <button type="button" onClick={() => onJump(r)} className="w-full rounded-md px-2 py-1.5 text-left text-xs hover:bg-black/5">
                      <span className="block truncate">{describeTarget(r.target, tableFor(s, r.target) || s.table).title}</span>
                      <span className="block text-muted-foreground">
                        {[...[...r.viewed].map((v) => VIEW_LABEL[v]), r.note && "메모", r.checked && "확인 표시"].filter(Boolean).join(", ")}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {!active.length && <p className="px-2 text-xs text-muted-foreground">이 결과에서 남긴 기록이 없습니다</p>}
        {earlier > 0 && <p className="px-2 text-xs text-muted-foreground">이전 결과에서 남긴 기록 {earlier}건은 현재 결과에 이어지지 않습니다</p>}
      </CollapsibleContent>
    </Collapsible>
  );
}

const tableFor = (s: Stage, t: ReviewTarget) =>
  t.table_role === "input" ? workflowInputs(s).find((i) => i.ref === t.input_ref)?.table : s.table;

/** Explanations mark identifiers with backticks; show them as inline code. */
function withCode(text: string) {
  return text.split(/`([^`]+)`/).map((part, i) =>
    i % 2 ? (
      <code key={i} className="rounded-sm bg-muted px-1 py-0.5 font-mono text-[0.85em]">
        {part}
      </code>
    ) : (
      part
    ),
  );
}

function SourceTables({ session, open, onOpenChange }: { session: Session; open: boolean; onOpenChange: (v: boolean) => void }) {
  return (
    <Collapsible open={open} onOpenChange={onOpenChange} className="rounded-xl border">
      <CollapsibleTrigger className="group flex w-full items-center justify-between rounded-xl px-4 py-2.5 text-left text-sm font-medium hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        Input과 Target
        <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-panel-open:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="grid gap-5 border-t px-4 py-4 lg:grid-cols-2">
        <section className="min-w-0 space-y-2">
          <h2 className="text-sm font-medium">
            Input <span className="font-normal text-muted-foreground">{session.input.stats.rows}행</span>
          </h2>
          <DataTable data={session.input} />
          {Object.entries(session.sources || {}).map(([name, table]) => (
            <div key={name} className="space-y-2 pt-2">
              <h3 className="text-sm font-medium">
                {name} <span className="font-normal text-muted-foreground">{table.stats.rows}행</span>
              </h3>
              <DataTable data={table} />
            </div>
          ))}
        </section>
        <section className="min-w-0 space-y-2">
          <h2 className="text-sm font-medium">
            Target {session.target && <span className="font-normal text-muted-foreground">{session.target.stats.rows}행</span>}
          </h2>
          {session.target ? <DataTable data={session.target} /> : <p className="text-sm text-muted-foreground">Target이 없습니다.</p>}
        </section>
      </CollapsibleContent>
    </Collapsible>
  );
}

function OtherOutputs({ step, run, render }: { step: Stage; run: Run; render: (op: Stage) => ReactNode }) {
  const outputs = referencedOutputs(step, run.stages);
  if (!outputs.length) return null;
  return (
    <div className="space-y-4 pt-2">
      {outputs.map((op, i) => (
        <div key={op.id} className="space-y-1.5">
          <p className="text-xs text-muted-foreground">
            다음 단계에서 쓰는 중간 표 {(step.operations?.indexOf(op) ?? i) + 1}, {op.table.stats.rows}행
          </p>
          {render(op)}
        </div>
      ))}
    </div>
  );
}

function Legend({ delta, groups, marked }: { delta: ReturnType<typeof tableChanges>; groups: { index: number; label: string }[]; marked: boolean }) {
  const items: ReactNode[] = [];
  if (delta?.addedColumns.length) items.push(<Swatch key="a" className="bg-added" label="새로 생긴 열" />);
  if (delta?.changedCells.size) items.push(<Swatch key="c" className="bg-changed" label="값이 바뀐 셀" />);
  if (delta?.rowIdentity && delta.removedRows.length) items.push(<Swatch key="r" className="bg-removed" label={`제외된 행 ${delta.removedRows.length}개 (변환 전 표)`} />);
  if (delta?.movedRows.size) items.push(<Swatch key="m" className="bg-source" label="순서가 바뀐 행" />);
  groups.slice(0, 6).forEach((g) =>
    items.push(<Swatch key={`g${g.index}`} style={{ background: groupColor(g.index), borderColor: groupBorder(g.index) }} label={g.label} />),
  );
  if (groups.length > 6) items.push(<span key="more" className="text-muted-foreground">그룹 {groups.length}개</span>);
  if (marked)
    items.push(
      <span key="h" className="inline-flex items-center gap-1.5">
        <span aria-hidden className="relative size-3 overflow-hidden rounded-sm border border-foreground/10 bg-card">
          <span className="absolute top-0 right-0 border-t-[6px] border-l-[6px] border-t-foreground/40 border-l-transparent" />
        </span>
        내가 근거를 연 곳
      </span>,
    );
  if (!items.length) return null;
  return <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">{items}</div>;
}

function Swatch({ label, className, style }: { label: string; className?: string; style?: React.CSSProperties }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("size-3 rounded-sm border border-foreground/10", className)} style={style} aria-hidden />
      {label}
    </span>
  );
}

function ResearchControls({ condition, busy, onCondition, onNewTask }: { condition: Condition; busy: boolean; onCondition: (c: Condition) => void; onNewTask: () => void }) {
  const participantUrl = () => {
    const url = new URL(location.href);
    url.searchParams.delete("research");
    return url.toString();
  };
  return (
    <div className="mr-1 flex items-center gap-1 border-r pr-3">
      <div className="flex rounded-lg border p-0.5" role="group" aria-label="조건">
        {(["ex", "in-situ"] as const).map((c) => (
          <button
            key={c}
            type="button"
            disabled={busy}
            aria-pressed={condition === c}
            onClick={() => condition !== c && onCondition(c)}
            className={cn("rounded-md px-2.5 py-1 text-xs font-medium", condition === c ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}
          >
            {c === "ex" ? "Ex-situ" : "In-situ"}
          </button>
        ))}
      </div>
      <Button variant="ghost" size="sm" disabled={busy} onClick={onNewTask}>
        과제 변경
      </Button>
      <Button variant="ghost" size="sm" render={<a href={participantUrl()} />}>
        참가자 화면
      </Button>
      <Button variant="ghost" size="sm" render={<a href="/legacy?research=1" />}>
        연구자 도구
      </Button>
    </div>
  );
}
