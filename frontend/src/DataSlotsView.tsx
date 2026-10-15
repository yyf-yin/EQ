import {useEffect,useState} from 'react'
import {getDataSlots} from './api'
import type {DataSlots,DataSlot,Run} from './types'

const labels:Record<string,string>={pending:'待填',filling:'填槽中',locked:'已锁定',not_disclosed:'未披露',not_applicable:'不适用',source_missing:'资料缺失',extraction_failed:'提取失败',ready:'资料就绪',limited:'资料受限'}
const materialLabels:Record<string,string>={pending:'待收集',found:'已取得适用资料',partial:'部分取得',not_found:'限定检索后未找到',no_change:'有证据支持无变化',not_applicable:'不适用',retrieval_failed:'获取失败'}
const stopLabels:Record<string,string>={coverage_complete:'适用资料已覆盖',search_budget:'检索预算已用完',document_budget:'阅读预算已用完',search_unavailable:'搜索未配置',duplicate_query:'已检索过相同范围',no_new_evidence:'补查未取得新增证据'}
const entityKey=(s:DataSlot)=>s.detail_id?`detail:${s.detail_id}`:s.segment_id||s.bond_id||''

export function DataSlotsView({run}:{run:Run}){
 const [data,setData]=useState<DataSlots|null>(null),[error,setError]=useState(''),[group,setGroup]=useState('income')
 const [periodMode,setPeriodMode]=useState('annual')
 const active=['queued','running','pausing'].includes(run.status)
 useEffect(()=>{
  if(!run.data_template_version)return
  const controller=new AbortController();let running=false
  const load=async()=>{if(running)return;running=true;try{const next=await getDataSlots(run.run_id,controller.signal);if(!controller.signal.aborted){setData(next);setError('')}}catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:'固定表读取失败')}finally{running=false}}
  void load();const timer=active?setInterval(()=>void load(),3000):undefined
  return()=>{controller.abort();if(timer)clearInterval(timer)}
 },[run.run_id,run.data_template_version,active])
 if(!run.data_template_version)return null
 const groupRows=data?.slots.filter(s=>s.field_id.startsWith(group+'.'))||[]
 const hasQuarterly=groupRows.some(s=>/\d{4}(?:Q1|H1|Q3|[1-4]Q)$/.test(s.period))
 const rows=groupRows.filter(s=>!hasQuarterly||group==='security'||(periodMode==='annual'?s.period.endsWith('A'):periodMode==='single'?/\dQ$/.test(s.period):/(?:Q1|H1|Q3)$/.test(s.period)))
 const periodOrder=(p:string)=>rows.find(s=>s.period===p)?.period_end||p.replace(/H1$/,'Q2')
 const periods=[...new Set(rows.map(s=>s.period))].sort((a,b)=>periodOrder(a).localeCompare(periodOrder(b)))
 const entities=[...new Set(rows.map(entityKey))]
 const fields=data?.groups.find(g=>g.group_id===group)?.fields||[]
 return <details className="mt-5 border-t border-slate-100 pt-4" open>
  <summary className="cursor-pointer text-sm font-medium">固定财务与证券表 · 已锁定 {data?.slots.filter(s=>s.state==='locked').length||0} 项</summary>
  <p className="mt-2 text-xs text-slate-500">财报值通过提取检查后锁定。单季度与年初累计分别展示；历史季度未披露可留空，缺失项不会自动填零。</p>
  {hasQuarterly&&<><p className="mt-2 text-xs text-slate-500">{data?.latest_interim_period?`当年最新披露期间：${data.latest_interim_period}；该期间及上年同期核心数据为必需。`:'缺少当年已披露季报或中报，正式交付前须补齐最新期间及上年同期核心数据。'}</p><div className="flex gap-2 mt-3" aria-label="财务期间类型">{[['annual','年度'],['cumulative','季度／中期累计'],['single','单季度']].map(([value,label])=><button type="button" key={value} aria-pressed={periodMode===value} onClick={()=>setPeriodMode(value)} className={`rounded px-3 py-2 text-xs ${periodMode===value?'bg-teal-50 text-sea':'bg-slate-50 text-slate-600'}`}>{label}</button>)}</div></>}
  {error&&<p role="alert" className="mt-2 text-xs text-red-700">{error}</p>}
  <div className="flex flex-wrap gap-2 mt-3" aria-label="固定数据区域">{data?.groups.map(g=><button type="button" key={g.group_id} onClick={()=>setGroup(g.group_id)} aria-pressed={group===g.group_id} className={`rounded px-3 py-2 text-xs ${group===g.group_id?'bg-teal-50 text-sea':'bg-slate-50 text-slate-600'}`}>{g.title}</button>)}</div>
  {entities.map(entity=><div key={entity} className="mt-3 overflow-x-auto">{entity&&<p className="mb-2 text-sm font-medium">{entity.startsWith('detail:')?`${rows.find(s=>entityKey(s)===entity)?.segment_id} / ${rows.find(s=>entityKey(s)===entity)?.product_name}`:entity}</p>}
   <table className="w-full text-xs text-left border-collapse" aria-label={`${data?.groups.find(g=>g.group_id===group)?.title||group}${entity}`}>
    <thead><tr><th scope="col" className="p-2 border-b">固定字段</th>{periods.map(p=><th scope="col" key={p} className="p-2 border-b whitespace-nowrap" title={rows.find(s=>s.period===p)?.period_label}>{p}<span className="block font-normal text-slate-400">{rows.find(s=>s.period===p)?.period_label}</span></th>)}</tr></thead>
    <tbody>{fields.filter(f=>!entity.startsWith('detail:')||rows.some(s=>s.field_id===f.field_id&&entityKey(s)===entity)).map(f=><tr key={f.field_id}><th scope="row" className="p-2 border-b font-normal whitespace-nowrap">{f.label}</th>{periods.map(p=>{
     const slot=rows.find(s=>s.field_id===f.field_id&&s.period===p&&entityKey(s)===entity)
     return <td key={p} className="p-2 border-b align-top min-w-36">{slot?<details><summary className="cursor-pointer"><span className={slot.state==='locked'?'text-sea':'text-slate-500'}>{slot.state==='locked'?`${slot.raw_value} ${slot.raw_unit==='—'?'':slot.raw_unit||''}`:labels[slot.state]||slot.state}</span>{slot.state==='locked'&&<span className="block text-slate-400 mt-1">已锁定</span>}{slot.requirement==='C'&&!p.endsWith('A')&&<span className="block text-amber-700 mt-1">同比必需</span>}</summary><p className="mt-2 text-slate-500 break-all">{slot.reason}{slot.period_start&&<><br/>{slot.period_start} 至 {slot.period_end}</>}{slot.locator&&<><br/>{slot.locator}</>}{slot.source_id&&<><br/>来源 {slot.source_id}</>}</p></details>:<span>—</span>}</td>
    })}</tr>)}</tbody>
   </table>
  </div>)}
  {!rows.length&&<p className="mt-3 text-xs text-slate-500">{group==='bond'?(data?.bond_presence.some(b=>b.state==='absent')?'指定披露说明无债券；无对应年份债券记录。':'尚未取得债券记录，不能据此认定没有债券。'):'正在准备固定数据槽。'}</p>}
  {!!data?.materials.length&&<div className="mt-4"><h3 className="text-xs font-medium">业务与行业资料槽</h3>
   <p className="text-xs text-slate-500 mt-2">按通用方向及业务、行业特有方向整理资料。未找到不代表不存在或无变化，资料缺口会交给分析。</p>
   <ul className="mt-2 space-y-3 text-xs">{data.materials.map(s=><li key={s.slot_id} className="border border-slate-100 rounded-lg p-3">
    <p>{s.topic} · {labels[s.state]||s.state} · 检索 {s.search_count}{s.search_budget!==undefined?` / ${s.search_budget}`:''} 次</p>
    {s.scope&&<p className="text-slate-500 mt-1">资料期间 {s.scope.start_date} 至 {s.scope.as_of}；政策变化自 {s.scope.policy_start_date} 起。{s.scope.region}</p>}
    {!!s.directions?.length&&<table className="w-full mt-2 text-left" aria-label={`${s.topic}资料方向`}><thead><tr><th className="py-2">资料方向</th><th>覆盖状态</th></tr></thead>
     <tbody>{s.directions.map(d=>{const finding=s.direction_statuses?.[d.direction_id];return <tr key={d.direction_id} className="border-t border-slate-100">
      <td className="py-2 pr-3 align-top"><p>{d.label}</p><span className="text-slate-400">{d.origin==='model'?'模型补充':'通用预设'}</span><p className="text-slate-500 mt-1">{d.description}</p>{d.origin==='model'&&<p className="text-slate-500 mt-1">适用理由：{d.reason}</p>}</td>
      <td className="py-2 align-top"><p>{materialLabels[finding?.status||'pending']||finding?.status}</p>{finding?.reason&&<p className="text-slate-500 mt-1">{finding.reason}</p>}{!!finding?.evidence_ids.length&&<details className="mt-1 text-slate-500"><summary className="cursor-pointer">证据 {finding.evidence_ids.length} 项</summary><p className="break-all mt-1">{finding.evidence_ids.join('、')}</p></details>}</td>
     </tr>})}</tbody></table>}
    {s.stop_reason&&<p className="text-slate-500 mt-2">收集结束：{stopLabels[s.stop_reason]||s.stop_reason}</p>}
    {!!s.search_history?.length&&<details className="mt-2 text-slate-500"><summary className="cursor-pointer">检索范围记录</summary>{s.search_history.map((h,i)=><p key={i} className="mt-1">{h.query}{h.warnings.length?`；${h.warnings.join('；')}`:''}</p>)}</details>}
    {s.limitations.length>0&&<p className="text-slate-500 mt-2">{s.limitations.join('；')}</p>}
   </li>)}</ul></div>}
 </details>
}
