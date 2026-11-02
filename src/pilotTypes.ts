export type PilotApi = <T>(path:string,body?:unknown)=>Promise<T>;
export type PilotSession = {participant_id:string;session_id:string;task_id:string;review_number:number|null;title:string;
  condition:'ex'|'in-situ';started_at:string;status:string;confirmed:boolean;feedback_count:number;
  revision_requests:number;revision_failures:number;last_event_id:string|null;assignment_id?:string|null;plan_version?:string|null};
