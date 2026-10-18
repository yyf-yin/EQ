import { useCallback, useEffect, useRef, useState } from 'react'
import { createRun, getReport, getRun, getStartup, pauseRun, resumeRun, updateBudget } from './api'
import type { Run, Report, Progress, ReferenceLimits } from './types'
const terminal = new Set(['completed','limited','failed','blocked','interrupted','waiting_human'])
export function useResearch(){
 const [id,setId]=useState('')
 const [run,setRun]=useState<Run|null>(null), [report,setReport]=useState<Report|null>(null), [events,setEvents]=useState<Progress[]>([])
 const [error,setError]=useState(''),[busy,setBusy]=useState(false),[connected,setConnected]=useState(true)
 const [lastSyncedAt,setLastSyncedAt]=useState<number|null>(null)
 const [connectionEpoch,setConnectionEpoch]=useState(0),[actionBusy,setActionBusy]=useState(false)
 const [pendingAction,setPendingAction]=useState<'pause'|'resume'|null>(null)
 const manuallyStarted=useRef(false)
 const [referenceLimits,setReferenceLimits]=useState<ReferenceLimits>({max_files:50,max_file_bytes:20*1024*1024})
 useEffect(()=>{
  let disposed=false
  void getStartup().then(value=>{
   if(!disposed&&value.reference_limits&&Number.isInteger(value.reference_limits.max_files)&&value.reference_limits.max_files>=1&&value.reference_limits.max_files<=200&&value.reference_limits.max_file_bytes>0)setReferenceLimits(value.reference_limits)
   if(disposed||manuallyStarted.current)return
   if(!value.session_id||sessionStorage.getItem('cdr-startup-session')===value.session_id){
    setId(localStorage.getItem('cdr-run')||'')
    return
   }
   sessionStorage.setItem('cdr-startup-session',value.session_id)
   if(value.selected_run_id){
    localStorage.setItem('cdr-run',value.selected_run_id)
    setId(value.selected_run_id)
   }else if(value.answer==='N'){
    localStorage.removeItem('cdr-run')
   }else{
    setId(localStorage.getItem('cdr-run')||'')
   }
  }).catch(()=>{if(!disposed&&!manuallyStarted.current)setId(localStorage.getItem('cdr-run')||'')})
  return()=>{disposed=true}
 },[])
 useEffect(()=>{
  if(!id)return
  let disposed=false,stream:EventSource|undefined,timer:ReturnType<typeof setInterval>|undefined
  let syncing=false,refreshPending=false
  async function sync(){
   if(syncing){refreshPending=true;return}
   syncing=true
   try{
    const value=await getRun(id)
    if(disposed)return
    setRun(value);setLastSyncedAt(Date.now());setError('')
    if(terminal.has(value.status)){
     if(timer&&['completed','limited'].includes(value.status))clearInterval(timer)
     setBusy(false)
     if(['completed','limited'].includes(value.status)){
      const doc=await getReport(id);if(!disposed)setReport(doc)
     }
    }
   }catch(e){if(!disposed)setError((e as Error).message)}
   finally{syncing=false;if(refreshPending&&!disposed){refreshPending=false;void sync()}}
  }
  stream=new EventSource(`/api/research/${id}/events?after=0`)
  stream.onopen=()=>{if(!disposed){setConnected(true);void sync()}}
  stream.onerror=()=>{if(!disposed)setConnected(false)}
  stream.addEventListener('progress',(message)=>{
   if(disposed)return
   const ev:Progress=JSON.parse((message as MessageEvent).data)
   setEvents(prev=>prev.some(e=>e.event_id===ev.event_id)?prev:[...prev,ev].sort((a,b)=>a.event_id-b.event_id))
   setRun(prev=>prev&&!terminal.has(prev.status)&&(!prev.updated_at||Date.parse(ev.timestamp)>=Date.parse(prev.updated_at))?{...prev,stage:ev.stage,updated_at:ev.timestamp}:prev)
   if(terminal.has(ev.status)&&['run','delivery'].includes(ev.task_name))void sync()
  })
  // Replay saved SSE history even when the initial status is already terminal.
  stream.addEventListener('done',()=>{stream?.close();void sync()})
  timer=setInterval(()=>void sync(),1000)
  void sync()
  return()=>{disposed=true;stream?.close();if(timer)clearInterval(timer)}
 },[id,connectionEpoch])
 const start=useCallback(async(company:string,attachmentIds:string[]=[])=>{manuallyStarted.current=true;setBusy(true);setError('');try{const value=await createRun(company,attachmentIds);setRun(value);setReport(null);setEvents([]);setLastSyncedAt(null);setConnected(true);localStorage.setItem('cdr-run',value.run_id);setId(value.run_id);return true}catch(e){setError((e as Error).message);setBusy(false);return false}},[])
 const adopt=useCallback((value:Run)=>{manuallyStarted.current=true;setBusy(true);setError('');setRun(value);setReport(null);setEvents([]);setLastSyncedAt(null);setConnected(true);localStorage.setItem('cdr-run',value.run_id);setId(value.run_id)},[])
 const control=useCallback(async(action:'pause'|'resume')=>{
  if(!id||actionBusy)return
  setActionBusy(true);setPendingAction(action);setError('')
  try{
   const value=await (action==='pause'?pauseRun(id):resumeRun(id))
   setRun(value);setReport(null);setConnectionEpoch(v=>v+1)
  }catch(e){
   const message=(e as Error).message
   // A lost response does not establish whether the server accepted the action.
   try{setRun(await getRun(id));setConnectionEpoch(v=>v+1)}catch{}
   setError(message)
  }finally{setActionBusy(false);setPendingAction(null)}
 },[id,actionBusy])
 const increaseBudget=useCallback(async(budget:{global_call_budget:number;global_token_budget:number;block_call_budget:number})=>{
  if(!id||actionBusy)return
  setActionBusy(true);setError('')
  try{const recovery=await updateBudget(id,budget);setRun(prev=>prev?{...prev,recovery}:prev)}
  catch(e){setError((e as Error).message)}finally{setActionBusy(false)}
 },[id,actionBusy])
 const refresh=useCallback(()=>setConnectionEpoch(v=>v+1),[])
 return {refresh,run,report,events,error,busy:busy||!!(run&&!terminal.has(run.status)),connected,lastSyncedAt,start,adopt,actionBusy,pendingAction,control,increaseBudget,referenceLimits}
}
