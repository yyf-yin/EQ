import {useEffect,useState} from 'react'
import {getReferenceAttachments,uploadReference} from './api'
import type {ReferenceAttachment,ReferenceLimits} from './types'

const accept='.pdf,.docx,.xlsx,.csv,.txt,.md,.html,.htm,.json'
const defaultLimits:ReferenceLimits={max_files:50,max_file_bytes:20*1024*1024}
function fileSize(size:number){return size<1024*1024?`${Math.max(1,Math.round(size/1024))} KB`:`${(size/1024/1024).toFixed(1)} MB`}

export function ReferenceUploads({attachments,onChange,disabled,onUploading,limits=defaultLimits}:{attachments:ReferenceAttachment[];onChange:(value:ReferenceAttachment[])=>void;disabled:boolean;onUploading:(value:boolean)=>void;limits?:ReferenceLimits}){
 const [uploading,setUploading]=useState(false),[error,setError]=useState(''),[currentFile,setCurrentFile]=useState('')
 async function addFiles(files:File[]){
  if(disabled||uploading||!files.length)return
  setError('')
  if(attachments.length+files.length>limits.max_files){setError(`每次研究最多上传 ${limits.max_files} 份参考资料`);return}
  setUploading(true);onUploading(true)
  const ready=[...attachments],errors:string[]=[]
  try{
   for(const file of files){
    setCurrentFile(file.name)
    const ext='.'+(file.name.split('.').pop()||'').toLowerCase()
    if(!accept.split(',').includes(ext)){errors.push(`${file.name}：不支持的文件格式`);continue}
    if(file.size>limits.max_file_bytes){errors.push(`${file.name}：不能超过 ${Math.round(limits.max_file_bytes/1024/1024)} MB`);continue}
    if(!file.size){errors.push(`${file.name}：文件为空`);continue}
    try{const attachment=await uploadReference(file);ready.push(attachment);onChange([...ready])}
    catch(e){errors.push(`${file.name}：${(e as Error).message}`)}
   }
   setError(errors.join('；'))
  }finally{setUploading(false);onUploading(false);setCurrentFile('')}
 }
 return <section aria-label="上传参考资料" className="mt-5 text-left rounded-xl border border-slate-200 bg-white p-5">
  <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-semibold">年报与参考资料 <span className="ml-2 text-xs font-normal text-sea">本次指定</span></h2><p className="mt-1 text-xs text-slate-500">真实研究请上传公司年报、当年最新已披露季报或中报，以及上年同期数据（可来自本期财报比较列）；程序不自动寻找财报。研报或行业资料可一并提供。</p></div>
   <label className={`rounded-lg border border-sea px-3 py-2 text-sm text-sea ${disabled||uploading?'opacity-40':'cursor-pointer hover:bg-teal-50'}`} htmlFor="reference-files">添加文件</label>
   <input id="reference-files" type="file" className="sr-only" aria-label="选择参考资料文件" accept={accept} multiple disabled={disabled||uploading} onChange={e=>{const files=Array.from(e.currentTarget.files||[]);e.currentTarget.value='';void addFiles(files)}}/>
  </div>
  <p className="mt-3 text-xs text-slate-400">支持 PDF、Word、Excel、CSV、TXT、Markdown、HTML、JSON；每份最多 {Math.round(limits.max_file_bytes/1024/1024)} MB，最多 {limits.max_files} 份。扫描 PDF 需有可读取文本。</p>
  {!!attachments.length&&<p className="mt-2 text-xs text-sea">已上传 {attachments.length} / {limits.max_files} 份</p>}
  {uploading&&<p role="status" className="mt-3 text-sm text-sea">正在上传并解析：{currentFile}</p>}
  {error&&<p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
  {!!attachments.length&&<ul aria-label="已上传参考资料" className="mt-3 divide-y divide-slate-100">{attachments.map(a=><li key={a.attachment_id} className="flex items-center justify-between gap-3 py-3"><div className="min-w-0"><p className="break-all text-sm">{a.filename}</p><p className="mt-1 text-xs text-slate-500">{fileSize(a.size)} · 已解析 · 将优先用于本次研究</p></div><button type="button" disabled={disabled||uploading} aria-label={`移除 ${a.filename}`} className="shrink-0 text-xs text-slate-500 hover:text-red-700 disabled:opacity-40" onClick={()=>onChange(attachments.filter(v=>v.attachment_id!==a.attachment_id))}>移除</button></li>)}</ul>}
 </section>
}

export function RunReferences({id,mode}:{id:string;mode:'mock'|'real'}){
 const [attachments,setAttachments]=useState<ReferenceAttachment[]>([]),[error,setError]=useState('')
 useEffect(()=>{let disposed=false;void getReferenceAttachments(id).then(v=>{if(!disposed)setAttachments(v.attachments||[])}).catch(e=>{if(!disposed)setError((e as Error).message)});return()=>{disposed=true}},[id])
 if(!attachments.length&&!error)return null
 return <section aria-label="本次研究参考资料" className="mt-5 rounded-xl border border-slate-200 p-4"><h3 className="text-sm font-semibold">本次研究参考资料</h3>{error?<p className="mt-2 text-xs text-red-700">参考资料列表暂不可用：{error}</p>:<><p className="mt-2 text-xs text-slate-500">{mode==='mock'?'模拟模式仅保存附件；合成演示数据不会与上传的真实资料混用。':'公司年报只使用本次上传文件；业务与行业资料可补充搜索。'}</p><ul className="mt-2 space-y-1">{attachments.map(a=><li key={a.attachment_id} className="break-all text-sm">{a.filename} <span className="text-xs text-slate-400">· {fileSize(a.size)}</span></li>)}</ul></>}</section>
}
