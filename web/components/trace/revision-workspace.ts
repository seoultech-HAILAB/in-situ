import type { Run, RevisionPreview } from "@/lib/trace";

/** One candidate belongs directly after its confirmed Step, never downstream. */
export function workspaceSteps(run?: Run | null, preview?: RevisionPreview | null) {
  return (run?.stages.filter(stage => stage.kind !== "input") || []).flatMap((stage, index) => {
    const original = { ...stage, viewId: stage.id, viewLabel: `Step ${index + 1}`, viewCode: undefined as string | undefined, isCandidate: false };
    if (!preview?.stage || preview.base_run_id !== run?.id || preview.step_id !== stage.id) return [original];
    return [original, { ...preview.stage, viewId: `preview:${preview.id}`, viewLabel: preview.label, viewCode: preview.step_code, isCandidate: true }];
  });
}
