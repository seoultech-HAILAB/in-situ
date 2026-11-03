"use client";

import { useMemo, type ReactNode } from "react";
import { ChevronDown, LoaderCircle, MessageSquarePlus, Undo2 } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  buildWorkflowGraph,
  groupBorder,
  groupColor,
  isExplained,
  ownerOf,
  PythonCode,
  referencedOutputs,
  reviewGroups,
  stepTitle,
  tableChanges,
  workflowInputs,
  type Condition,
  type Ref,
  type ReviewTarget,
  type Run,
  type Selection,
  type Session,
  type Stage,
} from "@/lib/trace";
import { CommentPanel, SelectionAction } from "./anchored-comment";
import { ColumnOriginDetails } from "./column-origin";
import { DataTable } from "./data-table";
import { InitialJudgment } from "./initial-judgment";
import { ScopeSelect, type Scope } from "./scope-select";
import type { Comment } from "./trace-app";

const title = (s: Stage) => s.nl_explanation?.title || stepTitle(s);

export function Review(props: {
  session: Session;
  run?: Run;
  steps: Stage[];
  step?: Stage;
  research: boolean;
  busy: string;
  errorBanner: ReactNode;
  selection: Selection | null;
  picked: ReviewTarget | null;
  comment: Comment | null;
  commentText: string;
  request: string;
  scope: Scope;
  onRequest: (v: string) => void;
  onScope: (v: Scope) => void;
  onStep: (id: string) => void;
  onRevise: () => void;
  onUndo: () => void;
  onConfirm: () => void;
  onCondition: (c: Condition) => void;
  onNewTask: () => void;
  onReloadExplanations: () => void;
  onCell: (stage: Stage, row: string, column: string, anchor: HTMLElement, role: "input" | "output", inputRef: string | undefined, additive: boolean) => void;
  onTarget: (stage: Stage, target: ReviewTarget, anchor: HTMLElement, final?: boolean, additive?: boolean, editing?: boolean) => unknown;
  onCommentEdit: () => void;
  onCommentText: (v: string) => void;
  onCommentScope: (v: Scope) => void;
  onCommentClose: () => void;
  onCommentSubmit: () => void;
}) {
  const { session, run, steps, step, busy, selection, picked, comment } = props;
  const isEx = session.condition === "ex";
  const done = !!session.confirmed;
  const locked = !!busy || done;
  const position = step ? steps.findIndex((s) => s.id === step.id) + 1 : 0;
  const graph = useMemo(() => buildWorkflowGraph(run?.stages || [], session.sources || {}), [run, session.sources]);
  const groups = useMemo(() => (step ? reviewGroups(step) : { inputRows: {}, outputCells: {}, groups: [] }), [step]);
  const delta = useMemo(() => (step ? tableChanges(step) : null), [step]);
  const inputs = step ? workflowInputs(step) : [];

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
  const columnInfo =
    selection &&
    selectedStage &&
    (selectedStage.params.formulas?.[selection.column] ||
      selectedStage.params.aggregations?.[selection.column] ||
      selectedStage.column_explanations?.[selection.column] ||
      tableChanges(selectedStage)?.addedColumns.includes(selection.column)) ? (
      <ColumnOriginDetails stage={selectedStage} column={selection.column} />
    ) : undefined;

  const shared = { picked, selection, disabled: locked, refs, keyRefs };

  const header = (
    <header className="sticky top-0 z-30 border-b bg-card/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-4 px-6">
        <span className="font-semibold tracking-tight">TRACE</span>
        <span className="h-5 w-px bg-border" aria-hidden />
        <span className="min-w-0 truncate text-sm text-muted-foreground">{session.task_display?.title}</span>
        <div className="ml-auto flex items-center gap-2">
          {props.research && <ResearchControls condition={session.condition} busy={!!busy} onCondition={props.onCondition} onNewTask={props.onNewTask} />}
          <Button variant="outline" disabled={locked || (!run?.parent_run_id && session.status !== "failed")} onClick={props.onUndo}>
            <Undo2 /> 이전 결과로 되돌리기
          </Button>
          <AlertDialog>
            <AlertDialogTrigger render={<Button disabled={locked || session.status !== "ready"} />}>
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
      </div>
    </header>
  );

  return (
    <div className="min-h-dvh pb-16">
      {header}
      {props.errorBanner}
      <div className="mx-auto max-w-[1600px] space-y-6 px-6 pt-6">
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
              <Button size="sm" variant="outline" disabled={!!busy} onClick={props.onReloadExplanations}>
                다시 불러오기
              </Button>
            </AlertAction>
          </Alert>
        )}

        <SourceTables session={session} />

        {run && step ? (
          <div className="grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
            <nav aria-label="변환 단계" className="lg:sticky lg:top-20 lg:self-start">
              <h2 className="mb-2 px-3 text-sm font-medium text-muted-foreground">단계</h2>
              <ol className="space-y-0.5">
                {steps.map((s, i) => {
                  const active = s.id === step.id;
                  return (
                    <li key={s.id}>
                      <button
                        type="button"
                        disabled={!!busy}
                        aria-current={active ? "step" : undefined}
                        onClick={() => props.onStep(s.id)}
                        className={cn(
                          "flex w-full gap-3 rounded-md px-3 py-2 text-left text-sm leading-snug transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-60",
                          active ? "bg-card font-medium shadow-[inset_3px_0_0_var(--primary)]" : "text-muted-foreground hover:bg-card hover:text-foreground",
                        )}
                      >
                        <span className="w-4 shrink-0 tabular-nums">{i + 1}</span>
                        <span>{title(s)}</span>
                      </button>
                    </li>
                  );
                })}
              </ol>
            </nav>

            <section aria-labelledby="step-title" className="relative min-w-0 space-y-5 rounded-lg border bg-card p-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <h2 id="step-title" className="text-xl font-semibold tracking-tight">
                  {position}. {title(step)}
                </h2>
                {!isEx && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={locked}
                    onClick={(e) => props.onTarget(step, { kind: "step", step_id: step.id }, e.currentTarget, true, false, true)}
                  >
                    <MessageSquarePlus /> 이 단계 전체 수정
                  </Button>
                )}
              </div>
              <p className="max-w-[72ch] leading-7">{withCode(step.nl_explanation?.text || "이 단계의 설명이 없습니다.")}</p>

              {isEx ? (
                <div className="grid gap-6 2xl:grid-cols-2">
                  <section className="min-w-0 space-y-2">
                    <h3 className="text-sm font-medium">코드</h3>
                    <div className="max-h-[480px] overflow-auto rounded-md border bg-muted/40">
                      <PythonCode code={step.code} />
                    </div>
                  </section>
                  <section className="min-w-0 space-y-2">
                    <h3 className="text-sm font-medium">
                      결과 <span className="font-normal text-muted-foreground">{step.table.stats.rows}행</span>
                    </h3>
                    <DataTable data={step.table} stage={step} />
                    <OtherOutputs step={step} run={run} render={(op) => <DataTable data={op.table} stage={op} />} />
                  </section>
                </div>
              ) : (
                <div className="grid items-start gap-4 2xl:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
                  <section className="min-w-0 space-y-2">
                    <h3 className="text-sm font-medium">변환 전</h3>
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
                            {...shared}
                            handlers={{
                              onCell: (r, c, a, add) => props.onCell(asStep, r, c, a, "input", item.ref, add),
                              onRange: (t, a, final) => props.onTarget(asStep, t, a, final),
                              onRow: (r, a, add) => props.onTarget(asStep, { kind: "row", step_id: step.id, row_id: r, table_role: "input", input_ref: item.ref }, a, true, add),
                              onColumn: (c, a, add) => props.onTarget(asStep, { kind: "column", step_id: step.id, column: c, table_role: "input", input_ref: item.ref }, a, true, add),
                            }}
                          />
                        </div>
                      );
                    })}
                    {!inputs.length && <p className="text-sm text-muted-foreground">이 단계의 입력 표를 확인하지 못했습니다.</p>}
                  </section>
                  <p className="flex items-center gap-2 text-xs text-muted-foreground tabular-nums 2xl:flex-col 2xl:gap-1 2xl:pt-12">
                    <span aria-hidden className="text-base leading-none">
                      <span className="2xl:hidden">↓</span>
                      <span className="hidden 2xl:inline">→</span>
                    </span>
                    <span className="2xl:hidden">
                      {inputs.length > 1 ? `표 ${inputs.length}개에서` : step.input ? `${step.input.stats.rows}행에서` : ""} {step.table.stats.rows}행으로
                    </span>
                    <span className="hidden whitespace-nowrap 2xl:inline">{inputs.length > 1 ? `표 ${inputs.length}개` : step.input ? `${step.input.stats.rows}행` : ""}</span>
                    <span className="hidden whitespace-nowrap 2xl:inline">{step.table.stats.rows}행</span>
                  </p>
                  <section className="min-w-0 space-y-2">
                    <h3 className="text-sm font-medium">
                      변환 후 <span className="font-normal text-muted-foreground">{step.table.stats.rows}행</span>
                    </h3>
                    <Legend delta={delta} groups={groups.groups} />
                    <DataTable
                      data={step.table}
                      stage={step}
                      annotated
                      delta={delta}
                      groupCells={groups.outputCells}
                      {...shared}
                      handlers={{
                        onCell: (r, c, a, add) => props.onCell(step, r, c, a, "output", undefined, add),
                        onRange: (t, a, final) => props.onTarget(step, t, a, final),
                        onRow: (r, a, add) => props.onTarget(step, { kind: "row", step_id: step.id, row_id: r }, a, true, add),
                        onColumn: (c, a, add) => props.onTarget(step, { kind: "column", step_id: step.id, column: c }, a, true, add),
                      }}
                    />
                    <OtherOutputs step={step} run={run} render={(op) => <DataTable data={op.table} stage={op} annotated refs={refs} keyRefs={keyRefs} />} />
                  </section>
                </div>
              )}

              {isEx && (
                <form
                  className="space-y-3 border-t pt-5"
                  onSubmit={(e) => {
                    e.preventDefault();
                    props.onRevise();
                  }}
                >
                  <label htmlFor="revision" className="text-sm font-medium">
                    수정 요청
                  </label>
                  <Textarea
                    id="revision"
                    rows={3}
                    placeholder="어떻게 바뀌어야 하는지 적어 주세요"
                    value={props.request}
                    disabled={locked}
                    onChange={(e) => props.onRequest(e.target.value)}
                    onKeyDown={(e) => {
                      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !e.nativeEvent.isComposing && props.request.trim() && !locked) {
                        e.preventDefault();
                        props.onRevise();
                      }
                    }}
                  />
                  <div className="flex items-center justify-between gap-2">
                    <ScopeSelect value={props.scope} onChange={props.onScope} disabled={locked} />
                    <Button type="submit" disabled={locked || !props.request.trim()}>
                      {busy && <LoaderCircle className="animate-spin" />}
                      {busy ? "반영하는 중" : "수정 요청"}
                    </Button>
                  </div>
                </form>
              )}

              {busy && (
                <div role="status" aria-live="polite" className="absolute inset-0 z-20 flex items-start justify-center rounded-lg bg-card/70 pt-32">
                  <span className="flex items-center gap-2 rounded-md border bg-card px-4 py-2 text-sm shadow-sm">
                    <LoaderCircle className="size-4 animate-spin" /> {busy}
                  </span>
                </div>
              )}
            </section>
          </div>
        ) : (
          <p className="text-muted-foreground">실행된 변환이 없습니다.</p>
        )}

        {session.review_baseline && <InitialJudgment key={`${session.id}:${run?.id}:${session.condition}`} session={session} busy={!!busy} />}
      </div>

      {comment &&
        !isEx &&
        (comment.editing ? (
          <CommentPanel
            anchor={comment.anchor}
            title={comment.title}
            preview={comment.preview}
            value={props.commentText}
            onChange={props.onCommentText}
            scope={comment.scope}
            onScope={props.onCommentScope}
            busy={!!busy}
            error={comment.error}
            onClose={props.onCommentClose}
            onSubmit={props.onCommentSubmit}
          />
        ) : (
          !busy && !done && <SelectionAction anchor={comment.anchor} info={columnInfo} onEdit={props.onCommentEdit} onDismiss={props.onCommentClose} />
        ))}
    </div>
  );
}

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

function SourceTables({ session }: { session: Session }) {
  return (
    <Collapsible defaultOpen className="rounded-lg border bg-card">
      <CollapsibleTrigger className="group flex w-full items-center justify-between px-5 py-3 text-left font-medium focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        Input과 Target
        <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-panel-open:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="grid gap-6 border-t px-5 py-4 lg:grid-cols-2">
        <section className="min-w-0 space-y-2">
          <h3 className="text-sm font-medium">
            Input <span className="font-normal text-muted-foreground">{session.input.stats.rows}행</span>
          </h3>
          <DataTable data={session.input} />
          {Object.entries(session.sources || {}).map(([name, table]) => (
            <div key={name} className="space-y-2 pt-2">
              <h4 className="text-sm font-medium">
                {name} <span className="font-normal text-muted-foreground">{table.stats.rows}행</span>
              </h4>
              <DataTable data={table} />
            </div>
          ))}
        </section>
        <section className="min-w-0 space-y-2">
          <h3 className="text-sm font-medium">
            Target {session.target && <span className="font-normal text-muted-foreground">{session.target.stats.rows}행</span>}
          </h3>
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
    <div className="space-y-4 pt-3">
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

function Legend({ delta, groups }: { delta: ReturnType<typeof tableChanges>; groups: { index: number; label: string }[] }) {
  const items: ReactNode[] = [];
  if (delta?.addedColumns.length) items.push(<Swatch key="a" className="bg-added" label="새로 생긴 열" />);
  if (delta?.changedCells.size) items.push(<Swatch key="c" className="bg-changed" label="값이 바뀐 셀" />);
  if (delta?.rowIdentity && delta.removedRows.length) items.push(<Swatch key="r" className="bg-removed" label={`제외된 행 ${delta.removedRows.length}개 (변환 전 표)`} />);
  if (delta?.movedRows.size) items.push(<Swatch key="m" className="bg-source" label="순서가 바뀐 행" />);
  groups.slice(0, 6).forEach((g) =>
    items.push(<Swatch key={`g${g.index}`} style={{ background: groupColor(g.index), borderColor: groupBorder(g.index) }} label={g.label} />),
  );
  if (groups.length > 6) items.push(<span key="more" className="text-muted-foreground">그룹 {groups.length}개</span>);
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
    <div className="mr-2 flex items-center gap-2 border-r pr-4">
      <div className="flex rounded-md border p-0.5" role="group" aria-label="조건">
        {(["ex", "in-situ"] as const).map((c) => (
          <button
            key={c}
            type="button"
            disabled={busy}
            aria-pressed={condition === c}
            onClick={() => condition !== c && onCondition(c)}
            className={cn("rounded-sm px-2.5 py-1 text-xs font-medium", condition === c ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}
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
