import {useCallback,useEffect,useRef,useState} from 'react'
import type {Report} from './types'
// The reader-facing layout (cover, numbered charts, appendix) is rendered once on the
// server, so the web view, DOCX and PDF show the same report. Audit data such as
// evidence IDs and limitations stays in the work-product view, not in the report.
export function ReportView({report,id,formats=[]}:{report:Report;id:string;formats?:string[]}){
 const frame=useRef<HTMLIFrameElement>(null)
 const [height,setHeight]=useState(1600)
 const fit=useCallback(()=>{const doc=frame.current?.contentDocument;if(doc?.documentElement)setHeight(doc.documentElement.scrollHeight+8)},[])
 const load=useCallback(()=>{
  fit()
  const doc=frame.current?.contentDocument
  // The frame has no scrollbar of its own, so in-report contents links scroll this page.
  doc?.addEventListener('click',event=>{
   const link=(event.target as Element|null)?.closest?.('a[href^="#"]')
   const target=link&&doc.getElementById(decodeURIComponent(link.getAttribute('href')!.slice(1)))
   if(!target||!frame.current)return
   event.preventDefault()
   window.scrollTo({top:frame.current.getBoundingClientRect().top+window.scrollY+target.getBoundingClientRect().top-16,behavior:'smooth'})
  })
 },[fit])
 useEffect(()=>{window.addEventListener('resize',fit);return()=>window.removeEventListener('resize',fit)},[fit])
 return <article className="bg-white border border-slate-200 rounded-2xl p-6 md:p-10 mt-8 shadow-sm"><div className="flex flex-wrap justify-between gap-4"><p className="text-xs tracking-widest text-sea">COMPANY RESEARCH · {report.mode==='mock'?'模拟报告':'研究报告'}</p><div className="flex gap-5"><a className="text-sm font-medium text-sea hover:underline" href={`/api/research/${id}/download?format=docx`}>下载 DOCX ↓</a>{formats.includes('pdf')&&<a className="text-sm font-medium text-sea hover:underline" href={`/api/research/${id}/download?format=pdf`}>下载 PDF ↓</a>}</div></div><h1 className="mt-4 text-2xl font-semibold leading-snug">{report.title}</h1><p className="text-sm text-slate-500 mt-2">生成时间 {new Date(report.as_of).toLocaleString('zh-CN')}</p><iframe ref={frame} title="研究报告正文" src={`/api/research/${id}/report?format=html`} sandbox="allow-same-origin allow-downloads" onLoad={load} style={{height}} className="w-full border-0 mt-6 rounded-lg"/></article>
}
