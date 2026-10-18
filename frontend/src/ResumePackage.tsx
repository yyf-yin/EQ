import {useState} from 'react'
import {importPackage,inspectPackage} from './api'
import type {PackageInfo,Run} from './types'

const statusNames:Record<string,string>={passed:'审核通过',failed:'不合格',unreviewed:'未审核'}
const riskNames:Record<string,string>={high:'高',medium:'中',low:'低'}
const runNames:Record<string,string>={completed:'已完成',limited:'完成但有限制',blocked:'审核阻断',failed:'执行失败',interrupted:'已暂停',waiting_human:'等待人工核验'}
const stoppedStatuses=['completed','limited','blocked','failed','interrupted','waiting_human']

export function ResumePackageExport({run}:{run:Run}){
 const [busy,setBusy]=useState(false),[error,setError]=useState('')
 if(!stoppedStatuses.includes(run.status))return null
 async function download(){
  setBusy(true);setError('')
  try{
   const response=await fetch(`/api/research/${run.run_id}/resume-package`)
   if(!response.ok){let message='成果包导出失败，请重试';try{const body=await response.json();if(typeof body.detail==='string')message=body.detail}catch{}throw new Error(message)}
   const url=URL.createObjectURL(await response.blob()),link=document.createElement('a')
   link.href=url;link.download=`resume-package-${run.run_id.slice(0,8)}.zip`;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 return <div className="mt-5 rounded-xl border border-slate-200 p-4 text-sm" aria-label="导出成果包">
  <div className="flex flex-wrap items-center gap-3"><button type="button" disabled={busy} onClick={()=>void download()} className="rounded-lg border border-sea px-4 py-2 text-sea disabled:opacity-50">{busy?'正在打包…':'导出成果包'}</button><span className="text-xs text-slate-500">包含已完成的资料、数据、计算与章节；下次在首页上传，可跳过合格部分继续。</span></div>
  {error&&<p role="alert" className="mt-3 text-red-700">{error}</p>}
 </div>
}

export function ResumePackageImport({disabled,onImported}:{disabled:boolean;onImported:(run:Run)=>void}){
 const [info,setInfo]=useState<PackageInfo|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const [level,setLevel]=useState<string>(''),[keep,setKeep]=useState<string[]>([]),[accepted,setAccepted]=useState(false)
 async function upload(file:File){
  setBusy(true);setError('');setInfo(null)
  try{
   const value=await inspectPackage(file)
   setInfo(value);setLevel(value.recommended_level||'');setAccepted(false)
   setKeep(value.review?.sections.filter(s=>s.default_keep).map(s=>s.section_id)||[])
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 async function submit(){
  if(!info||!level)return
  setBusy(true);setError('')
  try{const run=await importPackage(info.package_id,{level,keep_sections:level==='writing'?keep:[],accept_risks:accepted});setInfo(null);onImported(run)}
  catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 const needsRisk=!!info?.risks.length
 const canSubmit=!!info&&!info.incompatible&&!!level&&(!needsRisk||accepted)&&!busy&&!disabled
 return <section aria-label="从成果包继续" className="mt-5 text-left rounded-xl border border-slate-200 bg-white p-5">
  <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-semibold">从成果包继续</h2><p className="mt-1 text-xs text-slate-500">上传之前导出的成果包，沿用已完成且合格的部分，只做未完成或不合格的工作。原任务保持不变。</p></div>
   <label className={`rounded-lg border border-sea px-3 py-2 text-sm text-sea ${disabled||busy?'opacity-40':'cursor-pointer hover:bg-teal-50'}`} htmlFor="resume-package-file">选择成果包</label>
   <input id="resume-package-file" type="file" accept=".zip" className="sr-only" aria-label="选择成果包文件" disabled={disabled||busy} onChange={e=>{const file=e.currentTarget.files?.[0];e.currentTarget.value='';if(file)void upload(file)}}/>
  </div>
  {busy&&!info&&<p role="status" className="mt-3 text-sm text-sea">正在校验成果包…</p>}
  {error&&<p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
  {info&&<div className="mt-4 space-y-4 text-sm">
   <p>{info.source.company_name||info.source.company_input} · {runNames[info.source.status]||info.source.status} · 导出于 {new Date(info.created_at).toLocaleString('zh-CN')}{info.attachments.length?` · 含 ${info.attachments.length} 份上传资料`:''}</p>
   {info.source.error&&<p className="text-xs text-slate-500">原任务停止原因：{info.source.error}</p>}
   {info.incompatible?<p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{info.incompatible}</p>:<>
    <fieldset><legend className="font-medium">沿用到哪一步</legend>
     <div className="mt-2 space-y-2">{info.levels.map(l=><label key={l.level} className={`flex gap-2 ${l.available?'':'opacity-40'}`}><input type="radio" name="resume-level" value={l.level} disabled={!l.available} checked={level===l.level} onChange={()=>setLevel(l.level)}/><span>{l.label}{l.level===info.recommended_level&&<span className="ml-2 text-xs text-sea">建议</span>}<span className="block text-xs text-slate-500">沿用：{l.stages.join('、')}{l.level==='writing'?'，以及下方勾选的章节':''}{l.available?'':'（原任务未完成此阶段）'}</span></span></label>)}</div>
     <p className="mt-2 text-xs text-slate-500">{info.recommendation}</p>
    </fieldset>
    {level==='writing'&&info.review&&<fieldset><legend className="font-medium">沿用的章节</legend><p className="mt-1 text-xs text-slate-500">未勾选的章节重新写作；有章节重写时核心观点也会重写。沿用的章节仍会重新经过终审。</p>
     <ul className="mt-2 space-y-2">{info.review.sections.map(s=><li key={s.section_id}><label className="flex gap-2"><input type="checkbox" checked={keep.includes(s.section_id)} onChange={e=>setKeep(v=>e.target.checked?[...v,s.section_id]:v.filter(x=>x!==s.section_id))}/><span>{s.title}<span className={`ml-2 text-xs ${s.status==='failed'?'text-red-700':'text-slate-500'}`}>{statusNames[s.status]}</span>{s.issues.map((issue,i)=><span key={i} className="block text-xs text-slate-500">{issue}</span>)}</span></label></li>)}</ul>
    </fieldset>}
    {needsRisk&&<div className="rounded-lg bg-amber-50 border-l-2 border-amber-400 p-3" role="note"><p className="font-medium text-amber-900">当前配置与成果包生成时不同</p><ul className="mt-2 space-y-1 text-xs text-amber-900">{info.risks.map(r=><li key={r.field}>{r.label}（风险{riskNames[r.level]}）：{r.message}</li>)}</ul><label className="mt-3 flex gap-2 text-xs"><input type="checkbox" checked={accepted} onChange={e=>setAccepted(e.target.checked)}/>我已了解以上风险，仍沿用这些成果</label></div>}
   </>}
   <div className="flex gap-3"><button type="button" disabled={!canSubmit} onClick={()=>void submit()} className="rounded-lg bg-sea text-white px-5 py-2.5 disabled:opacity-40">{busy?'正在导入…':'导入并继续'}</button><button type="button" disabled={busy} onClick={()=>{setInfo(null);setError('')}} className="rounded-lg border border-slate-300 px-4 py-2">取消</button></div>
  </div>}
 </section>
}
