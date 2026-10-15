import {useCallback, useEffect, useState} from 'react'
import {getHumanIntervention, submitHumanFeedback} from './api'
import type {HumanIssue, HumanQueue, Run} from './types'

function IssueForm({issue,queue,id,onSubmitted}:{issue:HumanIssue;queue:HumanQueue;id:string;onSubmitted:()=>void}){
 const [action,setAction]=useState<'select'|'supplement'|'research'>(issue.candidates.length?'select':'research')
 const [saving,setSaving]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('')
 const pending=['submitted','researching'].includes(issue.status)
 const disabled=saving||pending||!queue.can_submit
 return <article className="mt-4 border border-slate-200 rounded-xl p-4">
  <h3 className="font-medium">{issue.identity.metric_code} · {issue.identity.period} · {issue.identity.segment_id||issue.identity.scope}</h3>
  <p className="text-xs mt-1 text-slate-500">{issue.blocking?'关键依赖，解决前等待计算':'非关键问题，不阻止计算'} · {issue.phase==='checking'?'其他采集与自动核验继续中':'等待人工处理'}</p>
  <p className="mt-3 text-sm">{issue.reason}</p>
  {issue.candidates.map(candidate=><details key={candidate.fact_id} className="mt-2 text-sm bg-slate-50 p-3 rounded-lg">
   <summary>{candidate.value} {candidate.unit} · {candidate.accounting_basis} · {candidate.title||candidate.source_id}</summary>
   <p className="mt-2 whitespace-pre-wrap break-words">{candidate.quote||'未提供可定位摘录'}</p>
   <p className="text-xs text-slate-500 mt-1">位置：{candidate.locator} · 候选：{candidate.fact_id}</p>
   {candidate.source_url&&/^https?:\/\//i.test(candidate.source_url)&&<a href={candidate.source_url} target="_blank" rel="noreferrer" className="text-sea underline">查看来源</a>}
  </details>)}
  {issue.feedback_error&&<p role="alert" className="mt-3 text-sm text-red-700">核验未通过：{issue.feedback_error}</p>}
  {pending&&<p role="status" className="mt-3 text-sm text-sea">反馈已保存，等待核验结果。</p>}
  <form aria-label={`处理 ${issue.identity.metric_code} ${issue.identity.period}`} className="mt-4 space-y-3 text-sm" onSubmit={async e=>{
   e.preventDefault();if(disabled)return
   const data=new FormData(e.currentTarget)
   const body:Record<string,unknown>={signature:issue.signature,action,reason:String(data.get('reason')||'').trim()}
   if(action==='select')body.fact_id=data.get('fact_id')
   if(action==='research')body.query=String(data.get('query')||'').trim()
   if(action==='supplement')for(const key of ['source_id','quote','locator','value','unit','accounting_basis'])body[key]=String(data.get(key)||'').trim()
   setSaving(true);setError('');setNotice('')
   try{const result=await submitHumanFeedback(id,issue.issue_id,body);setNotice(result.resume_reason?'反馈已保存；'+result.resume_reason:result.resumed?'反馈已保存，已继续核验。':'反馈已保存；暂停的任务需点击继续研究。');onSubmitted()}
   catch(err){setError((err as Error).message);onSubmitted()}
   finally{setSaving(false)}
  }}>
   <fieldset disabled={disabled} className="space-y-3 disabled:opacity-60">
    <label className="block">处理方式<select value={action} onChange={e=>setAction(e.target.value as typeof action)} className="block w-full mt-1 border rounded px-3 py-2">
     {issue.candidates.length>0&&<option value="select">选择有原始证据的候选</option>}
     <option value="research">指定补查方向或公开材料链接</option><option value="supplement">从已收集原文补充或修正数据</option>
    </select></label>
    {action==='select'&&<label className="block">候选数据<select name="fact_id" required className="block w-full mt-1 border rounded px-3 py-2">{issue.candidates.map(c=><option key={c.fact_id} value={c.fact_id}>{c.value} {c.unit} · {c.accounting_basis} · {c.fact_id}</option>)}</select></label>}
    {action==='research'&&<label className="block">补查方向或链接<input name="query" required maxLength={1000} className="block w-full mt-1 border rounded px-3 py-2" placeholder="公司、期间、指标、更正公告，或公开披露 URL"/></label>}
    {action==='supplement'&&<>
     <label className="block">已收集来源<select name="source_id" required className="block w-full mt-1 border rounded px-3 py-2"><option value="">选择来源</option>{queue.sources.map(s=><option key={s.source_id} value={s.source_id}>{s.title} · {s.source_id}</option>)}</select></label>
     <label className="block">完整原文摘录<textarea name="quote" required maxLength={12000} rows={4} className="block w-full mt-1 border rounded px-3 py-2" placeholder="包含公司、期间、指标、单位、合并或分部范围及数值的原文"/></label>
     <label className="block">原文位置<input name="locator" required maxLength={500} className="block w-full mt-1 border rounded px-3 py-2" placeholder="页码、表格或段落"/></label>
     <div className="grid sm:grid-cols-3 gap-3">
      <label>数值<input name="value" required type="number" step="any" className="block w-full mt-1 border rounded px-3 py-2"/></label>
      <label>原文单位<input name="unit" required defaultValue={issue.identity.unit||''} maxLength={50} className="block w-full mt-1 border rounded px-3 py-2"/></label>
      <label>会计口径<input name="accounting_basis" required defaultValue="reported" maxLength={100} className="block w-full mt-1 border rounded px-3 py-2"/></label>
     </div>
    </>}
    <label className="block">依据与处理理由<textarea name="reason" required minLength={3} maxLength={2000} rows={2} className="block w-full mt-1 border rounded px-3 py-2"/></label>
    <button type="submit" className="rounded-lg bg-sea text-white px-4 py-2">{saving?'正在保存…':'提交并核验'}</button>
   </fieldset>
   {error&&<p role="alert" className="text-red-700">{error}</p>}{notice&&<p role="status" className="text-sea">{notice}</p>}
  </form>
 </article>
}

export function HumanInterventionView({run,onSubmitted}:{run:Run;onSubmitted:()=>void}){
 const [queue,setQueue]=useState<HumanQueue>({issues:[],sources:[],feedback:[],can_submit:false})
 const [error,setError]=useState(''),[epoch,setEpoch]=useState(0)
 useEffect(()=>{
  let disposed=false,loading=false
  const sync=async()=>{
   if(loading)return;loading=true
   try{const value=await getHumanIntervention(run.run_id);if(!disposed&&Array.isArray(value.issues)){setQueue(value);setError('')}}
   catch(err){if(!disposed)setError((err as Error).message)}finally{loading=false}
  }
  void sync()
  const timer=setInterval(()=>void sync(),1500)
  return()=>{disposed=true;clearInterval(timer)}
 },[run.run_id,run.status,epoch])
 const submitted=useCallback(()=>{setEpoch(e=>e+1);onSubmitted()},[onSubmitted])
 const open=queue.issues.filter(i=>i.status!=='resolved')
 if(!queue.issues.length&&run.status!=='waiting_human')return null
 return <section aria-label="人工数据核验" className="mt-6 border-t border-slate-200 pt-5">
  <h2 className="font-semibold">人工数据核验 · {open.length} 项待处理</h2>
  <p className="mt-2 text-sm text-slate-500">其他资料继续收集。关键问题解决前等待计算分析；反馈通过原文核验后生效，原始候选保留。</p>
  {!queue.can_submit&&<p className="text-xs text-slate-500 mt-2">本轮已进入计算或当前任务不可编辑，待办仅供查看。</p>}
  {error&&<p role="alert" className="text-red-700 mt-2">{error}</p>}
  {open.map(issue=><IssueForm key={issue.issue_id+issue.signature} issue={issue} queue={queue} id={run.run_id} onSubmitted={submitted}/>)}
  {queue.issues.some(i=>i.status==='resolved')&&<details className="mt-4 text-sm text-slate-500"><summary>查看已解决问题</summary>{queue.issues.filter(i=>i.status==='resolved').map(i=><p key={i.issue_id} className="mt-2">{i.identity.metric_code} · {i.identity.period} · 已重新核验</p>)}</details>}
 </section>
}
