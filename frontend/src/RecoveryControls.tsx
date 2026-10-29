import {useState} from 'react'
import type {Run} from './types'

type Budget={global_call_budget:number;global_token_budget:number;block_call_budget:number}
export function RecoveryControls({run,actionBusy,pendingAction,control,increaseBudget}:{run:Run;actionBusy:boolean;pendingAction?:'pause'|'resume'|null;control:(action:'pause'|'resume')=>Promise<void>;increaseBudget:(budget:Budget)=>Promise<void>}){
 const [editing,setEditing]=useState(false)
 const recovery=run.recovery
 const callLimitsEnabled=recovery?.budget.enforce_call_budgets!==false
 const stopped=['interrupted','failed','blocked','waiting_human'].includes(run.status)
 const active=['queued','running'].includes(run.status)
 const current=recovery?.current_session!==false
 return <div className="mt-5 rounded-xl bg-slate-50 p-4 text-sm" aria-label="研究运行控制">
  <div className="flex flex-wrap items-center gap-3" aria-busy={actionBusy}>
   {active&&current&&<button type="button" disabled={actionBusy||recovery?.can_pause===false} onClick={()=>void control('pause')} className="rounded-lg border border-sea bg-white text-sea px-5 py-2.5 disabled:opacity-50">{pendingAction==='pause'?'正在请求暂停…':'暂停研究'}</button>}
   {run.status==='pausing'&&<p role="status">正在保存进度，已发出的请求可能完成并计费，最多等待 60 秒。</p>}
   {current&&(active||stopped&&recovery?.can_resume)&&<button type="button" disabled={actionBusy||!stopped||!recovery?.can_resume} onClick={()=>void control('resume')} className="rounded-lg bg-sea text-white px-5 py-2.5 disabled:opacity-40">{pendingAction==='resume'?'正在继续…':run.status==='failed'?'从断点继续':'继续研究'}</button>}
   {stopped&&recovery?.can_increase_budget&&<button type="button" disabled={actionBusy} onClick={()=>setEditing(v=>!v)} className="rounded-lg border border-slate-300 px-4 py-2">调整续跑预算</button>}
  </div>
  {current&&(active||run.status==='interrupted')&&<p className="mt-3 text-slate-500">{active?'研究运行中，可随时暂停；暂停完成后可继续。':'研究已暂停，可从当前进度继续。'} 程序重启后，最近一个未完成的任务可在此页面继续；其它任务可导出成果包后上传继续。</p>}
  {stopped&&recovery&&<div className="mt-3 space-y-1 text-slate-600" aria-live="polite">
   <p>{recovery.reason}</p>
   <p>已保存 {recovery.saved_units.research_task||0} 个研究任务、{recovery.saved_units.model||0} 个模型步骤、{recovery.saved_units.node||0} 个流程节点；已续跑 {recovery.resume_count} 次。</p>
   <p>累计调用 {recovery.budget.calls_used.toLocaleString()}{callLimitsEnabled?` / ${recovery.budget.global_call_budget.toLocaleString()}`:'（仅统计，不设次数上限）'}；token 记账 {recovery.budget.tokens_used.toLocaleString()} / {recovery.budget.global_token_budget.toLocaleString()}（包含估算与预留，非费用账单）。</p>
   {recovery.budget.unknown_calls>0&&<p>有 {recovery.budget.unknown_calls} 次请求结果未知，重试时可能再次计费。</p>}
  </div>}
  {editing&&stopped&&recovery?.can_increase_budget&&<form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={e=>{
   e.preventDefault();const data=new FormData(e.currentTarget)
   void increaseBudget({global_call_budget:Number(data.get('calls')??recovery.budget.global_call_budget),global_token_budget:Number(data.get('tokens')),block_call_budget:Number(data.get('blocks')??recovery.budget.block_call_budget)})
  }}>
   {([['calls','总调用上限',recovery.budget.global_call_budget],['tokens','总 token 上限',recovery.budget.global_token_budget],['blocks','每块调用上限',recovery.budget.block_call_budget]] as const).filter(([name])=>callLimitsEnabled||name==='tokens').map(([name,label,value])=><label key={name} className="text-xs text-slate-600">{label}<input className="block mt-1 w-40 rounded border border-slate-300 px-3 py-2" name={name} type="number" min={value} defaultValue={value} required step={1}/></label>)}
   <button type="submit" disabled={actionBusy} className="rounded-lg bg-sea px-4 py-2 text-white disabled:opacity-50">保存总预算</button>
   <p className="w-full text-xs text-slate-500">保存后点击继续研究。只提高上限，已有消耗保持累计。</p>
  </form>}
 </div>
}
