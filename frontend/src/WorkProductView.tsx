import {useEffect,useRef,useState} from 'react'
import {getWorkProduct} from './api'
import type {WorkProduct} from './types'

const labels:Record<string,string>={complete:'已生成',not_produced:'尚未生成',passed:'审核通过',verified:'已校验',unverified:'未校验',unreviewed:'未审核',rejected:'不合格',current:'当前版本',stale:'已失效',completed:'已完成',limited:'完成但有限制',blocked:'审核阻断',failed:'执行失败',running:'运行中',queued:'排队中',interrupted:'已中断'}
const kinds:Record<string,string>={source:'来源',evidence:'证据',fact:'财务事实',calculation:'计算',comparison:'财务比较',assumption:'假设',forecast:'预测',block:'研究块',block_analysis:'块分析',coverage:'问题覆盖',task:'任务',review_issue:'审核记录',batch:'提取批次',section:'章节',current_review_issues:'当前审核问题',required_data:'所需数据',comparison_gaps:'比较缺口',limitations:'限制',invalidation:'失效记录'}
Object.assign(labels,{conflict:'待核实冲突',excluded:'未被选用',resolved:'已裁决',unresolved:'尚未解决'})
Object.assign(kinds,{fact_decision:'财务裁决',fact_verification:'定向核实',source_metadata:'来源元信息差异'})
Object.assign(kinds,{data_slot:'固定数据槽',collection_slot:'业务行业资料槽',slot_calculation:'固定派生计算',fixed_derived_fact:'模型派生输入',bond_presence:'债券披露状态'})
Object.assign(labels,{locked:'已锁定',not_disclosed:'未披露',not_applicable:'不适用',source_missing:'资料缺失',extraction_failed:'提取失败',ready:'资料就绪'})
export function WorkProductView({id}:{id:string}){
 const [product,setProduct]=useState<WorkProduct|null>(null),[open,setOpen]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const active=useRef(true)
 useEffect(()=>{active.current=true;return()=>{active.current=false}},[])
 // A run change remounts this component through its key in App.
 async function load(fresh=false,page=1){
  setBusy(true);setError('')
  try{const value=await getWorkProduct(id,fresh?undefined:product?.snapshot_id,page);if(active.current){setProduct(value);setOpen(true)}return value}
  catch(e){setError((e as Error).message);return null}
  finally{setBusy(false)}
 }
 async function download(format='zip'){
  setBusy(true);setError('')
  try{
   const snapshot=product||await getWorkProduct(id)
   setProduct(snapshot)
   const response=await fetch(`/api/research/${id}/work-product/download?format=${format}&snapshot_id=${encodeURIComponent(snapshot.snapshot_id)}`)
   if(!response.ok){let message='评估包导出失败，请重试';try{const body=await response.json();if(typeof body.detail==='string')message=body.detail}catch{}throw new Error(message)}
   const url=URL.createObjectURL(await response.blob()),link=document.createElement('a')
   link.href=url;link.download=`work-product-${snapshot.snapshot_id.slice(0,12)}.${format}`;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 const pages=product?Math.max(1,Math.ceil(Math.max(product.artifact_count,product.section_count,product.fact_decision_count||0)/product.page_size)):1
 return <section aria-label="阶段成果" className="mt-5 border-t border-slate-200 pt-5">
  <div className="flex flex-wrap gap-3 items-center"><button type="button" disabled={busy} onClick={()=>open?setOpen(false):void load(!product)} className="rounded-lg border border-sea px-4 py-2 text-sm text-sea disabled:opacity-50">{open?'收起阶段成果':'查看阶段成果'}</button><button type="button" disabled={busy} onClick={()=>void download()} className="rounded-lg bg-sea text-white px-4 py-2 text-sm disabled:opacity-50">导出评估包</button><span role="status" className="text-xs text-slate-500">{busy?'正在获取已保存成果…':'可获取已保存内容，供后续评估'}</span></div>
  {error&&<p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
  {product&&<p className="mt-3 text-xs text-slate-500">快照时间：{new Date(product.snapshot_time).toLocaleString('zh-CN')} · {labels[product.run_status]||product.run_status} · 对应内容最终审核{product.final_review_passed?'已通过':'未通过或尚未完成'}</p>}
  {open&&product&&<div className="mt-4 space-y-5">
   <p className="rounded-lg bg-amber-50 border-l-2 border-amber-400 p-4 text-sm text-amber-900">{product.notice}</p>
   <div className="flex flex-wrap gap-3 items-center"><button type="button" disabled={busy} onClick={()=>void load(true)} className="text-sm text-sea underline disabled:opacity-50">获取最新阶段成果</button>{['json','md'].map(format=><button type="button" disabled={busy} onClick={()=>void download(format)} key={format} className="text-sm text-sea underline disabled:opacity-50">下载 {format==='md'?'Markdown':'JSON'}</button>)}<span className="text-xs text-slate-500 break-all">快照 {product.snapshot_id.slice(0,12)}</span></div>
   <div><h3 className="font-semibold text-sm">完成情况与用量</h3><p className="mt-2 text-xs text-slate-600">停止/当前阶段：{product.run.stage} · 已保存送审轮次：{product.review_count}</p>{product.run.error&&<p className="text-sm text-red-700 mt-2">{product.run.error}</p>}<dl className="flex flex-wrap gap-x-5 gap-y-2 mt-3 text-xs text-slate-600">{Object.entries(product.counts).map(([kind,count])=><div key={kind}><dt className="inline">{kinds[kind]||kind}：</dt><dd className="inline">{count}</dd></div>)}</dl><p className="mt-3 text-xs text-slate-500">已记录调用 {product.usage.calls} 次 · 供应商已记录输入/输出 token：{product.usage.provider_input_tokens}/{product.usage.provider_output_tokens} · 缺用量记录 {product.usage.usage_missing_calls} 次。{product.usage.note}</p></div>
   {product.blocks.length>0&&<div><h3 className="font-semibold text-sm">研究块状态</h3><ul className="flex flex-wrap gap-2 mt-2 text-xs">{product.blocks.map(b=><li key={b.block_id} className="rounded bg-slate-100 px-2 py-1">{b.block_id} · {labels[b.status]||b.status}</li>)}</ul></div>}
   <div><h3 className="font-semibold text-sm">当前审核问题</h3>{product.issues.length?product.issues.map((issue,i)=><div key={issue.issue_id||i} className="mt-2 text-sm border-l-2 border-red-200 pl-3"><p>{issue.severity} · {issue.location} · {issue.rule_id}</p><p className="mt-1">{issue.description}</p><p className="text-xs text-slate-500 mt-1">修复要求：{issue.suggested_fix}</p></div>):<p className="mt-2 text-sm text-slate-500">尚无已记录审核问题；不代表审核通过。</p>}</div>
   <details><summary className="text-sm cursor-pointer">缺失与不可获取内容（{product.missing.length+product.unavailable.length}）</summary><ul className="mt-2 space-y-1 text-xs text-slate-600">{product.missing.map((v,i)=><li key={i}>{v.id}：{v.reason}</li>)}{product.unavailable.map((v,i)=><li key={`unavailable-${i}`}>{v.artifact}：{v.reason}</li>)}</ul></details>
   <div><h3 className="font-semibold text-sm">已保存章节</h3>{!product.section_count&&<p className="mt-2 text-sm text-slate-500">当前尚无写作成果。已有数据与诊断仍可导出。</p>}{(['current','stale'] as const).map(version=><div key={version}>{product.sections.some(s=>s.version_status===version)&&<h4 className={version==='stale'?'mt-4 text-sm text-red-700':'mt-4 text-sm text-slate-600'}>{version==='stale'?'历史失效章节（仅供评估）':'当前版本章节'}</h4>}{product.sections.filter(s=>s.version_status===version).map(s=><details key={s.section_id} className="mt-3 border border-slate-200 rounded-lg p-3"><summary className="cursor-pointer text-sm font-medium">{s.content.title}<span className={`ml-2 text-xs font-normal ${s.version_status==='stale'||s.validation_status==='rejected'?'text-red-700':'text-amber-800'}`}>{labels[s.generation_status]||s.generation_status} · {labels[s.validation_status]||s.validation_status} · {labels[s.version_status]||s.version_status}</span></summary><div className="mt-3 text-sm space-y-3">{s.content.paragraphs.map((p,i)=><p className="whitespace-pre-wrap break-words leading-7" key={i}>{p}</p>)}{s.content.tables.map((t,i)=><div key={i} className="overflow-x-auto"><p className="text-xs text-slate-500 mb-2">{t.title}</p><table className="w-full text-xs border-collapse"><thead><tr>{t.columns.map((c,j)=><th className="border p-2 text-left" key={j}>{c}</th>)}</tr></thead><tbody>{t.rows.map((r,j)=><tr key={j}>{r.map((c,k)=><td key={k} className="border p-2">{c}</td>)}</tr>)}</tbody></table></div>)}<p className="text-xs text-slate-500 break-all">引用：{[...s.content.evidence_ids,...s.content.calculation_ids].join('，')||'无已保存引用'}</p></div></details>)}</div>)}</div>
   {!!product.fact_decisions?.length&&<div><h3 className="font-semibold text-sm">财务冲突核验</h3><p className="mt-2 text-xs text-slate-500">候选记录全部保留。只有被选用的事实参与计算；未解决的关键输入阻止正式交付。</p>{product.fact_decisions.map(d=><details key={d.decision_id} className="mt-3 rounded border border-slate-200 p-3"><summary className="cursor-pointer text-sm">{d.identity.metric_code||'未知指标'} · {d.identity.period||'未知期间'} · {labels[d.status]||d.status}</summary><p className="mt-2 text-sm">{d.reason}</p><p className="mt-2 text-xs break-all">选用：{d.selected_ids.join('，')||'无'}；证明证据：{d.proof_evidence_ids.join('，')||'暂无'}</p><ul className="mt-2 space-y-2 text-xs break-all">{d.candidates.map(f=><li key={f.fact_id}>{f.value} {f.unit} · {f.accounting_basis} · {d.selected_ids.includes(f.fact_id)?'已选用':'未选用'}<br/>事实 {f.fact_id} · 来源 {f.source_id} · 证据 {f.evidence_id}</li>)}</ul></details>)}</div>}
   <details><summary className="text-sm cursor-pointer">成果清单（共 {product.artifact_count} 项）</summary><ul className="mt-2 space-y-1 text-xs text-slate-600">{product.artifacts.map((v,i)=><li key={i}>{kinds[v.kind]||v.kind} · {v.id||v.section_id} · {labels[v.validation_status]||v.validation_status} · {labels[v.version_status]||v.version_status}</li>)}</ul></details>
   {pages>1&&<div className="flex items-center gap-4 text-xs"><button disabled={busy||product.page===1} onClick={()=>void load(false,product.page-1)} className="text-sea disabled:opacity-40">上一页</button><span>成果清单 / 章节预览 第 {product.page} / {pages} 页</span><button disabled={busy||product.page>=pages} onClick={()=>void load(false,product.page+1)} className="text-sea disabled:opacity-40">下一页</button></div>}
   {product.notes.map((note,i)=><p className="text-xs text-slate-500" key={i}>{note}</p>)}
  </div>}
 </section>
}
