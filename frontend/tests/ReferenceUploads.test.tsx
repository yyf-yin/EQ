import {useState} from 'react'
import {fireEvent,render,screen,waitFor} from '@testing-library/react'
import {expect,test,vi} from 'vitest'
import {ReferenceUploads,RunReferences} from '../src/ReferenceUploads'
import App from '../src/App'
import type {ReferenceAttachment} from '../src/types'

const attachment:ReferenceAttachment={attachment_id:'ref-1',filename:'公司年报.txt',size:35,content_hash:'hash',created_at:'2026-10-12',status:'ready',source_count:1}
function UploadForm(){const [files,setFiles]=useState<ReferenceAttachment[]>([]);return <ReferenceUploads attachments={files} onChange={setFiles} disabled={false} onUploading={()=>{}}/>}
class Events{addEventListener(){}close(){}onopen=null;onerror=null}

test('初始页可多选上传、显示已解析文件，并在开始研究时绑定附件',async()=>{
 vi.stubGlobal('EventSource',Events)
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>({ok:true,json:async()=>{
  if(url==='/api/startup')return {session_id:'upload-service',selected_run_id:null,answer:'N'}
  if(url.startsWith('/api/reference-attachments'))return attachment
  if(url.endsWith('/attachments'))return {attachments:[attachment]}
  return {run_id:'r-upload',company_input:'测试公司',company_name:'测试公司',mode:'real',status:'interrupted',stage:'公司识别',error:null,limitations:[]}
 }}))
 vi.stubGlobal('fetch',fetch)
 render(<App/>)
 expect(screen.getByRole('region',{name:'上传参考资料'})).toBeInTheDocument()
 const file=new File(['已审核公司年报正文'],'公司年报.txt',{type:'text/plain'})
 fireEvent.change(screen.getByLabelText('选择参考资料文件'),{target:{files:[file]}})
 await screen.findByRole('button',{name:'移除 公司年报.txt'})
 expect(fetch).toHaveBeenCalledWith('/api/reference-attachments?filename='+encodeURIComponent(file.name),expect.objectContaining({method:'POST',body:file}))
 fireEvent.change(screen.getByLabelText('输入公司名称或股票代码'),{target:{value:'测试公司'}})
 fireEvent.click(screen.getByRole('button',{name:'开始研究'}))
 await waitFor(()=>expect(fetch).toHaveBeenCalledWith('/api/research',expect.objectContaining({method:'POST',body:JSON.stringify({company:'测试公司',attachment_ids:['ref-1']})})))
 await screen.findByRole('region',{name:'本次研究参考资料'})
 expect(screen.queryByRole('button',{name:'移除 公司年报.txt'})).not.toBeInTheDocument()
})

test('上传解析未完成时禁止开始研究',async()=>{
 vi.stubGlobal('EventSource',Events)
 let complete!:(value:unknown)=>void
 const response=new Promise(resolve=>{complete=resolve})
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.startsWith('/api/reference-attachments')?response:{ok:true,json:async()=>({session_id:'pending',answer:'N'})}))
 render(<App/>)
 fireEvent.change(screen.getByLabelText('输入公司名称或股票代码'),{target:{value:'测试公司'}})
 fireEvent.change(screen.getByLabelText('选择参考资料文件'),{target:{files:[new File(['正文'],'公司年报.txt')]}})
 await screen.findByRole('status')
 expect(screen.getByRole('button',{name:'资料解析中'})).toBeDisabled()
 complete({ok:true,json:async()=>attachment})
 await screen.findByRole('button',{name:'移除 公司年报.txt'})
 expect(screen.getByRole('button',{name:'开始研究'})).toBeEnabled()
})

test('不支持格式和超限文件不发送上传请求，已选资料可以移除',async()=>{
 const fetch=vi.fn(async()=>({ok:true,json:async()=>attachment}));vi.stubGlobal('fetch',fetch)
 render(<UploadForm/>)
 fireEvent.change(screen.getByLabelText('选择参考资料文件'),{target:{files:[new File(['a'],'bad.exe')]}})
 await screen.findByRole('alert');expect(fetch).not.toHaveBeenCalled()
 const large=new File(['body'],'large.pdf');Object.defineProperty(large,'size',{value:21*1024*1024})
 fireEvent.change(screen.getByLabelText('选择参考资料文件'),{target:{files:[large]}})
 await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent('不能超过 20 MB'))
 expect(fetch).not.toHaveBeenCalled()
 fireEvent.change(screen.getByLabelText('选择参考资料文件'),{target:{files:[new File(['正文'],'公司年报.txt')]}})
 const remove=await screen.findByRole('button',{name:'移除 公司年报.txt'})
 fireEvent.click(remove)
 expect(screen.queryByRole('list',{name:'已上传参考资料'})).not.toBeInTheDocument()
})

test('解析失败显示服务端原因，并允许重新选择材料',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,json:async()=>({detail:'扫描 PDF 无可提取文本，需提供 OCR 后材料'})})))
 render(<UploadForm/>)
 fireEvent.change(screen.getByLabelText('选择参考资料文件'),{target:{files:[new File(['pdf'],'扫描年报.pdf')]}})
 await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent('OCR'))
 expect(screen.getByLabelText('选择参考资料文件')).toBeEnabled()
 expect(screen.queryByRole('list',{name:'已上传参考资料'})).not.toBeInTheDocument()
})

test('刷新任务后从后端显示已绑定资料，模拟模式明确说明仅保存附件',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({attachments:[attachment]})})))
 render(<RunReferences id="r" mode="mock"/>)
 await screen.findByText('公司年报.txt')
 expect(screen.getByText(/模拟模式仅保存附件/)).toBeInTheDocument()
})

test('一次可以上传超过十份资料，显示数量和五十份默认上限',async()=>{
 let sequence=0
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...attachment,attachment_id:`ref-${++sequence}`,filename:`行业资料${sequence}.txt`})})))
 render(<UploadForm/>)
 fireEvent.change(screen.getByLabelText('选择参考资料文件'),{target:{files:Array.from({length:12},(_,i)=>new File(['行业信息'],`行业资料${i}.txt`))}})
 await screen.findByText('已上传 12 / 50 份')
 expect(screen.getAllByRole('button',{name:/移除 行业资料/})).toHaveLength(12)
})

test('使用后端上传数量上限，超限选择不发送文件',async()=>{
 vi.stubGlobal('EventSource',Events)
 const fetch=vi.fn(async()=>({ok:true,json:async()=>({session_id:'custom-limit',selected_run_id:null,answer:'N',reference_limits:{max_files:11,max_file_bytes:20*1024*1024}})}))
 vi.stubGlobal('fetch',fetch)
 render(<App/>)
 await screen.findByText(/最多 11 份/)
 fireEvent.change(screen.getByLabelText('选择参考资料文件'),{target:{files:Array.from({length:12},(_,i)=>new File(['行业信息'],`行业资料${i}.txt`))}})
 await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent('最多上传 11 份'))
 expect(fetch.mock.calls).toHaveLength(1)
})

test('真实研究未提供年报文件时禁止启动，上传后可开始且提示仅使用本次文件',async()=>{
 vi.stubGlobal('EventSource',Events)
 const fetch=vi.fn(async(url:string)=>({ok:true,json:async()=>
  url==='/api/startup'?{session_id:'annual-required',answer:'N',reference_limits:{max_files:50,max_file_bytes:20*1024*1024,annual_reports_required:true}}:
  url.startsWith('/api/reference-attachments')?attachment:
  url.endsWith('/attachments')?{attachments:[attachment]}:
  {run_id:'r-annual',company_input:'测试公司',company_name:'测试公司',mode:'real',status:'queued',stage:'等待开始',error:null,limitations:[]}}))
 vi.stubGlobal('fetch',fetch)
 render(<App/>)
 fireEvent.change(screen.getByLabelText('输入公司名称或股票代码'),{target:{value:'测试公司'}})
 await waitFor(()=>expect(screen.getByRole('button',{name:'开始研究'})).toBeDisabled())
 fireEvent.submit(screen.getByRole('button',{name:'开始研究'}).closest('form')!)
 expect(fetch.mock.calls.some(([url])=>url==='/api/research')).toBe(false)
 expect(screen.getByText(/程序不自动寻找财报/)).toBeInTheDocument()
 expect(screen.getByText(/当年最新已披露季报或中报/)).toBeInTheDocument()
 fireEvent.change(screen.getByLabelText('选择参考资料文件'),{target:{files:[new File(['正文'],'公司年报.txt')]}})
 await screen.findByRole('button',{name:'移除 公司年报.txt'})
 expect(screen.getByRole('button',{name:'开始研究'})).toBeEnabled()
 fireEvent.click(screen.getByRole('button',{name:'开始研究'}))
 await screen.findByText('公司年报只使用本次上传文件；业务与行业资料可补充搜索。')
})
