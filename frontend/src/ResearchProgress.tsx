import {useEffect, useState} from 'react'
import type {Progress, Run} from './types'

const stages=['公司识别','研究规划','数据收集','财务分析','业务研究','盈利预测','分块分析','报告写作','最终审核','文档生成']
const blockNames:Record<string,string>={C01:'公司概况',F01:'增长与盈利',F02:'资产与偿债',F03:'现金流质量',F04:'业务结构',F05:'资本效率',I01:'行业研究',B01:'业务研究',V01:'预测与估值',R01:'风险分析',X01:'核心观点'}
const stateNames:Record<string,string>={pending:'待处理',running:'进行中',pausing:'保存进度中',collecting:'收集中',ready:'资料就绪',verified:'已验证',validated:'已校验',missing:'缺失',conflict:'冲突',split:'已拆分',quarantined:'待排查',completed:'完成',queued:'排队',warning:'提示',failed:'失败',blocked:'阻断',interrupted:'已暂停',waiting_human:'待人工核验',submitted:'反馈已提交',stale:'待更新'}
const roleNames:Record<string,string>={resolver:'公司识别',brief:'范围规划',research_planner:'研究规划',reference_planner:'参考资料覆盖检查',calculation_planner:'计算规划',researcher:'资料取证',slot_extractor:'财报填槽',compression:'摘要整理',supervisor:'研究调度',financial_analyzer:'财务分析',assumption_planner:'预测假设',writer:'章节写作',reflection:'章节复核',core_writer:'核心观点',evidence_reviewer:'证据审核',editorial_reviewer:'编辑审核',critical_reviewer:'独立终审'}
const timeValue=(value?:string)=>value?Date.parse(value):NaN
export function duration(seconds:number){
 if(!Number.isFinite(seconds))return '—'
 const s=Math.max(0,Math.floor(seconds)),m=Math.floor(s/60),h=Math.floor(m/60)
 return h?`${h}小时 ${m%60}分 ${s%60}秒`:m?`${m}分 ${s%60}秒`:`${s}秒`
}
const clock=(value?:string)=>Number.isFinite(timeValue(value))?new Date(value!).toLocaleTimeString('zh-CN',{hour12:false}):'—'
const number=(value?:number)=>value===undefined?'—':value.toLocaleString('zh-CN')

function activeTasks(events:Progress[]){
 const tasks=new Map<string,{event:Progress;startedAt:string}>()
 for(const event of events){
  if(['run','delivery'].includes(event.task_name)&&['completed','limited','failed','blocked','interrupted','waiting_human','queued'].includes(event.status)){tasks.clear();continue}
  if(event.status==='running'){
   const old=tasks.get(event.task_name)
   tasks.set(event.task_name,{event,startedAt:old?.startedAt||event.timestamp})
  }else if(['completed','failed','blocked','interrupted'].includes(event.status)){
   tasks.delete(event.task_name)
   tasks.delete(event.task_name+'_business')
  }
 }
 return [...tasks.values()]
}

function Counts({label,counts}:{label:string;counts?:Record<string,number>}){
 if(!counts||!Object.values(counts).some(Boolean))return null
 return <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs"><span className="font-medium text-slate-700">{label}</span>{Object.entries(counts).filter(([,n])=>n>0).map(([state,n])=><span key={state} className={['missing','conflict','quarantined'].includes(state)?'text-amber-800':'text-slate-500'}>{stateNames[state]||state} {number(n)}</span>)}</div>
}

export function ResearchProgress({run,events,busy,connected,lastSyncedAt}:{run:Run;events:Progress[];busy:boolean;connected:boolean;lastSyncedAt:number|null}){
 const [now,setNow]=useState(Date.now()),[onlyProblems,setOnlyProblems]=useState(false)
 useEffect(()=>{if(!busy)return;const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer)},[busy])
 const complete=new Set<string>()
 for(const event of events){
  if(event.status==='running')complete.delete(event.stage)
  if(event.status==='completed'&&stages.includes(event.task_name))complete.add(event.task_name)
 }
 const active=busy?activeTasks(events):[]
 const latest=events.at(-1)
 const elapsed=((busy?now:timeValue(run.updated_at))-timeValue(run.created_at))/1000
 const quiet=(now-timeValue(latest?.timestamp||run.updated_at))/1000
 const usage=run.runtime?.usage,counts=run.runtime?.artifact_counts
 const log=onlyProblems?events.filter(e=>['warning','failed','blocked','interrupted'].includes(e.status)):events
 return <div>
  <ol className="grid grid-cols-5 md:grid-cols-10 gap-3 mt-6" aria-label="研究阶段">{stages.map((s,i)=><li key={s} className="text-xs"><span className={`inline-flex h-6 w-6 items-center justify-center rounded-full mb-2 ${complete.has(s)?'bg-sea text-white':run.stage===s?'bg-teal-100 text-sea':'bg-slate-100 text-slate-400'}`}>{complete.has(s)?'✓':i+1}</span><p className={run.stage===s?'text-sea font-medium':'text-slate-500'}>{s}</p></li>)}</ol>
  <dl className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-6" aria-label="运行概况">{[
   ['运行耗时',duration(elapsed)],['已完成阶段',`${complete.size} / ${stages.length}`],['当前任务',run.status==='waiting_human'?'待人工核验':busy?`${active.length} 项`:'已结束'],['最近进度',clock(latest?.timestamp)],
  ].map(([label,value])=><div key={label} className="rounded-xl bg-slate-50 px-4 py-3"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 text-lg font-medium tabular-nums">{value}</dd></div>)}</dl>
  <p className="text-xs text-slate-400 mt-2">阶段数按已完成事件统计，补查或返工时可能回退。</p>
  {busy&&<div className="mt-5 border-t border-slate-100 pt-4">
   <div className="flex flex-wrap items-center justify-between gap-2 text-xs"><p aria-live="polite" className={connected?'text-sea':'text-amber-800'}>{connected?'实时进度已连接':'实时连接中断，正在重连'}{lastSyncedAt!==null&&` · 状态同步于 ${clock(new Date(lastSyncedAt).toISOString())}`}</p><span className="text-slate-400">状态每秒刷新</span></div>
   <ul className="mt-3 space-y-2" aria-label="当前执行任务">{active.map(({event,startedAt})=><li key={event.task_name} className="rounded-lg bg-teal-50/60 px-3 py-2 text-sm flex flex-wrap justify-between gap-2"><span><span className="text-sea mr-2">{event.stage}</span>{event.display_message}</span><span className="text-xs text-slate-500 tabular-nums">已执行 {duration((now-timeValue(startedAt))/1000)}</span></li>)}</ul>
   {!active.length&&<p className="text-sm text-slate-600 mt-3">{run.status==='queued'?'任务已排队，等待开始':`正在执行：${run.stage}`}</p>}
   {quiet>=30&&<p className="mt-3 text-xs text-slate-500">已有 {duration(quiet)} 未收到新进度；模型请求或资料检索可能仍在处理中。</p>}
  </div>}
  <div className="mt-5 border-t border-slate-100 pt-4">
   <h3 className="text-sm font-medium">已保存材料</h3>
   <dl className="grid grid-cols-3 sm:grid-cols-5 gap-3 mt-3" aria-label="材料统计">{[['source','资料来源'],['evidence','证据'],['fact','财务事实'],['calculation','计算结果'],['section','章节草稿']].map(([key,label])=><div key={key}><dt className="text-xs text-slate-500">{label}</dt><dd className="text-lg tabular-nums mt-1">{number(counts?.[key])}</dd></div>)}</dl>
   <p className="text-xs text-slate-400 mt-2">数量包含已保存的阶段材料，审核结果以阶段成果为准。</p>
   <div className="mt-3 space-y-3"><Counts label="问题覆盖" counts={run.coverage_counts}/><Counts label="取证批次" counts={run.batch_counts}/></div>
  </div>
  <div className="mt-5 border-t border-slate-100 pt-4">
   <h3 className="text-sm font-medium">模型调用</h3>
   {run.mode==='mock'?<p className="mt-2 text-xs text-slate-500">模拟运行未调用真实模型。</p>:<>
    <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3" aria-label="模型用量">{[['请求次数',number(usage?.calls)],['请求处理中',busy?number(usage?.running_calls):'0'],['输入 Token',number(usage?.provider_input_tokens)],['输出 Token',number(usage?.provider_output_tokens)]].map(([label,value])=><div key={label}><dt className="text-xs text-slate-500">{label}</dt><dd className="text-lg tabular-nums mt-1">{value}</dd></div>)}</dl>
    <p className="mt-2 text-xs text-slate-400">Token 为服务商已返回用量；处理中请求尚未计入。{usage&&`成功 ${usage.succeeded_calls} 次，失败或中断 ${usage.failed_calls} 次。`}{!!usage?.usage_missing_calls&&`${usage.usage_missing_calls} 次请求未返回用量，统计不完整。`}</p>
    <p className="mt-2 text-xs text-slate-500" aria-label="输入缓存统计">{usage?.cache_hit_ratio!=null?`输入缓存命中 ${(usage.cache_hit_ratio*100).toFixed(1)}% · 已记录 ${number(usage.cache_hit_tokens)} / ${number(usage.cache_reported_input_tokens)} token（${number(usage.cache_reported_calls)} 次请求，按 token 加权；历史未记录请求不计入）`:'输入缓存命中率未记录，不能按 0% 解读。'}</p>
    {!!run.runtime?.recent_calls.length&&<details className="mt-3"><summary className="cursor-pointer text-xs text-sea">最近模型请求</summary><ul className="space-y-2 mt-3 text-xs text-slate-600" aria-label="最近模型请求">{run.runtime.recent_calls.map(call=><li key={call.call_id} className="flex flex-wrap gap-x-3 gap-y-1"><span>{roleNames[call.role]||call.role}</span><span className="text-slate-400">{call.response_model||call.model||'模型未记录'}</span><span>{call.result==='running'?(busy?'处理中':'结果未记录'):call.result==='ok'?'成功':call.result==='interrupted'?'中断':'失败'}</span>{call.attempt!==undefined&&call.attempt>0&&<span>第 {call.attempt+1} 次尝试</span>}<span className="tabular-nums">单次请求 {call.result==='running'&&busy?duration((now-timeValue(call.started_at))/1000):duration(call.duration_seconds??NaN)}</span>{call.input_tokens!=null&&<span>输入 {number(call.input_tokens)} / 输出 {number(call.output_tokens)} token</span>}{call.cache_hit_tokens!=null&&<span>缓存命中 {number(call.cache_hit_tokens)} token</span>}{call.reasoning_tokens!=null&&<span>思考 {number(call.reasoning_tokens)} token</span>}</li>)}</ul></details>}
   </>}
  </div>
  {!!run.blocks?.length&&<details className="mt-5 border-t border-slate-100 pt-4"><summary className="cursor-pointer text-sm font-medium">分析块状态 · {run.blocks.filter(b=>b.status==='validated').length} / {run.blocks.length} 已校验</summary><ul className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-3 text-xs" aria-label="分析块状态">{run.blocks.map(b=><li key={b.block_id} className="rounded-lg bg-slate-50 p-3"><span>{blockNames[b.block_id.split('-')[0]]||b.block_id} <span className="text-slate-400">{b.block_id}</span></span><p className={`mt-1 ${b.status==='validated'?'text-sea':'text-slate-500'}`}>{stateNames[b.status]||b.status}</p></li>)}</ul></details>}
  <div className="mt-5 border-t border-slate-100 pt-4"><h3 className="text-sm font-medium">最近进度</h3><ul className="mt-3 space-y-2 text-xs text-slate-500" aria-label="最近进度事件">{events.slice(-8).map(e=><li key={e.event_id} className="flex gap-3"><time className="shrink-0 tabular-nums">{clock(e.timestamp)}</time><span>{e.display_message}</span></li>)}</ul>{!events.length&&<p className="mt-2 text-xs text-slate-400">正在读取进度记录…</p>}
   <details className="mt-3"><summary className="cursor-pointer text-xs text-sea">完整运行日志 · {events.length} 条</summary><label className="flex items-center gap-2 text-xs text-slate-500 mt-3"><input type="checkbox" checked={onlyProblems} onChange={e=>setOnlyProblems(e.target.checked)}/>仅显示提示与异常</label><ol className="max-h-80 overflow-y-auto mt-3 space-y-2 text-xs text-slate-600 pr-2" aria-label="完整运行日志">{log.map(e=><li key={e.event_id} className="rounded-lg bg-slate-50 px-3 py-2"><div className="flex flex-wrap gap-x-3 gap-y-1 text-slate-400 mb-1"><time>{clock(e.timestamp)}</time><span>{e.stage}</span><span className={['warning','blocked','failed'].includes(e.status)?'text-amber-800':''}>{stateNames[e.status]||e.status}</span></div><p>{e.display_message}</p></li>)}</ol>{!log.length&&<p className="mt-2 text-xs text-slate-400">{onlyProblems?'暂无提示或异常。':'暂无进度记录。'}</p>}</details>
  </div>
 </div>
}
