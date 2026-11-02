import type { Table } from './types';

export type StudyTask = { id: string; title: string; description: string; review_number?: number | null };
export const taskNumber = (task: Pick<StudyTask,'id'|'review_number'>) => typeof task.review_number==='number' ? `과제 ${String(task.review_number).padStart(2,'0')}` : task.id;
export type PreparedTask = StudyTask & { input_csv: string; input: Table; target_csv:string;target:Table;sources: Record<string,Table>; researcherPreview?: boolean };
export type TaskCandidate = StudyTask & { initial_origin: string; original_task_id: string; steps: number;
  trace_levels: string[]; enabled: boolean; participant_enabled: boolean; has_reference_code: boolean; review_notes?: Record<string,string>;
  diagnostics?: {status:'error'|'normal'|'unknown';fault_steps:number[];note:string;propagated_steps:number[];evidence:string[];
    errors:{step:number;label:string;code_location:{start:number;end:number};problem:string;impact:string;repair:string;code_diff?:string}[]};
  screening?:{pair?:string;variant?:string;level?:string;source_input_condition?:string;step_metrics?:{step:number;effective_code_lines:number}[]} };
