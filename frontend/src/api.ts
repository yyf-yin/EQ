import type { Run, Report, WorkProduct } from './types'
export async function request<T>(path:string,init?:RequestInit):Promise<T> {const res=await fetch(`/api${path}`,init); if(!res.ok){let message='请求失败';try{const error=await res.json();message=typeof error.detail==='string'?error.detail:'请求参数无效'}catch{}throw new Error(message)}return res.json()}
export const createRun=(company:string,attachmentIds:string[]=[])=>request<Run>('/research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({company,...(attachmentIds.length?{attachment_ids:attachmentIds}:{})})})
export const uploadReference=(file:File)=>request<import('./types').ReferenceAttachment>(`/reference-attachments?filename=${encodeURIComponent(file.name)}`,{method:'POST',body:file})
export const getReferenceAttachments=(id:string)=>request<{attachments:import('./types').ReferenceAttachment[]}>(`/research/${id}/attachments`)
export const getRun=(id:string)=>request<Run>(`/research/${id}`)
export const getDataSlots=(id:string,signal?:AbortSignal)=>request<import('./types').DataSlots>(`/research/${id}/data-slots`,{signal})
export const getStartup=()=>request<{session_id:string;selected_run_id:string|null;answer:'Y'|'N'|null;reference_limits?:import('./types').ReferenceLimits}>('/startup')
export const pauseRun=(id:string)=>request<Run>(`/research/${id}/pause`,{method:'POST'})
export const resumeRun=(id:string)=>request<Run>(`/research/${id}/resume`,{method:'POST'})
export const updateBudget=(id:string,budget:{global_call_budget:number;global_token_budget:number;block_call_budget:number})=>request<import('./types').Recovery>(`/research/${id}/budget`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(budget)})
export const getReport=(id:string)=>request<Report>(`/research/${id}/report`)
export const getWorkProduct=(id:string,snapshotId?:string,page=1)=>request<WorkProduct>(`/research/${id}/work-product?page=${page}${snapshotId?`&snapshot_id=${encodeURIComponent(snapshotId)}`:''}`)

export const getHumanIntervention=(id:string)=>request<import('./types').HumanQueue>(`/research/${id}/human-intervention`)
export const submitHumanFeedback=(id:string,issue:string,body:Record<string,unknown>)=>request<{feedback_id:string;status:string;resumed:boolean;resume_reason?:string|null}>(`/research/${id}/human-intervention/${issue}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
