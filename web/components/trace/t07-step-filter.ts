import type { Stage } from "../../../src/types";

type ObservedStage = Stage & { operation_observations?: (Stage & { row_identity_verified?: boolean })[] };

/** A local view of an executed filter; never replace the Step's actual output. */
export function t07StepFilter(taskId: string | undefined, stage: Stage | undefined): Stage | undefined {
  if (taskId !== "PILOT4-T07" || stage?.order !== 2) return;
  for (const operation of (stage as ObservedStage).operation_observations ?? []) {
    if (operation.kind !== "filter" || !operation.row_identity_verified || !operation.input) continue;
    if (!operation.params.columns?.includes("Nationality")) continue;
    const input = operation.input, output = operation.table;
    if (JSON.stringify(input.columns) !== JSON.stringify(output.columns)) continue;
    const previous = new Map(input.rows.map(row => [row.id, row]));
    if (previous.size !== input.rows.length || new Set(output.rows.map(row => row.id)).size !== output.rows.length) continue;
    // Only the runtime's proven row identities are used. Do not infer a match
    // from equal values, row order, or the Step's transposed source table.
    if (output.rows.some(row => !previous.has(row.id) || JSON.stringify(previous.get(row.id)!.values) !== JSON.stringify(row.values))) continue;
    const expression = operation.operation_expression ?? operation.code;
    const location = operation.expression_location ?? operation.code_location;
    const transformation = stage.transformations?.find(item => item.method === "filter" && item.contributes_to_output !== false
      && item.code === expression && item.code_location.start === location?.start && item.code_location.end === location?.end
      && (!item.execution_version || item.execution_version === stage.execution_version)
      && (!item.code_version || item.code_version === stage.code_version));
    if (!transformation) continue;
    const effects = transformation.execution_effects?.filter(effect => effect.operation_id === operation.id && effect.row_identity);
    if (!effects?.length) continue;
    const surviving = new Set(output.rows.map(row => row.id));
    const removed = input.rows.filter(row => !surviving.has(row.id));
    if (removed.some(row => !effects.some(effect => effect.rows.removed.includes(row.id)))) continue;
    return { ...operation, id: stage.id, order: stage.order, execution_version: stage.execution_version, code_version: stage.code_version,
      inputs: [], operations: [], direct_tables: [], schema_origins: undefined,
      row_correspondence_complete: true, row_correspondence: Object.fromEntries(output.rows.map(row => [row.id, row.id])),
      transformations: [{ ...transformation, execution_effects: effects, revision_effects: undefined }],
    };
  }
}
