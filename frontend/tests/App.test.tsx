import {act,render,screen,fireEvent,waitFor,within} from '@testing-library/react'
import {vi,test,expect} from 'vitest'
import App from '../src/App'
const run={run_id:'r1',company_input:'示例公司',company_name:'',mode:'mock',status:'running',stage:'公司识别',limitations:[],error:null}
class Events {static last:Events;listeners:Record<string,Function>={};onopen=null;onerror=null;constructor(){Events.last=this}addEventListener(name:string,fn:Function){this.listeners[name]=fn}close=vi.fn();emit(name:string,data:unknown){this.listeners[name]?.({data:JSON.stringify(data)})}}
vi.stubGlobal('EventSource',Events)
test('输入、启动、SSE、报告及下载',async()=>{let done=false;vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>({ok:true,json:async()=>url.endsWith('/report')?{title:'示例报告',mode:'mock',as_of:new Date().toISOString(),sections:[],sources:[],evidence:[],charts:[],limitations:['合成数据']}:init?.method==='POST'?run:{...run,status:done?'limited':'running'}})));render(<App/>);const button=screen.getByRole('button',{name:'开始研究'});expect(button).toBeDisabled();fireEvent.change(screen.getByLabelText('输入公司名称或股票代码'),{target:{value:'示例公司'}});fireEvent.click(button);await screen.findByText('模拟运行 · 合成数据');done=true;Events.last.emit('progress',{event_id:3,run_id:'r1',timestamp:new Date().toISOString(),stage:'文档生成',task_name:'delivery',status:'limited',display_message:'报告已生成'});await screen.findByText('示例报告');expect(screen.getByText('下载 DOCX ↓')).toHaveAttribute('href','/api/research/r1/download?format=docx');expect(localStorage.getItem('cdr-run')).toBe('r1')})
test('刷新恢复失败状态',async()=>{localStorage.setItem('cdr-run','r1');vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...run,status:'failed',error:'研究失败'})})));render(<App/>);await screen.findByText('研究失败');expect(screen.getByText(/研究未能完成/)).toBeInTheDocument()})
test('服务错误呈现',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,json:async()=>({detail:'队列已满'})})));render(<App/>);fireEvent.change(screen.getByLabelText('输入公司名称或股票代码'),{target:{value:'测试'}});fireEvent.click(screen.getByRole('button',{name:'开始研究'}));await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent('队列已满'))})

test('已结束任务刷新后仍重放历史事件，等待 done 才关闭 SSE',async()=>{
 localStorage.setItem('cdr-run','r1')
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...run,status:'failed',stage:'财务分析'})})))
 render(<App/>)
 await screen.findByText(/研究未能完成/)
 expect(Events.last.close).not.toHaveBeenCalled()
 Events.last.emit('progress',{event_id:1,run_id:'r1',timestamp:new Date().toISOString(),stage:'公司识别',task_name:'公司识别',status:'completed',display_message:'历史识别完成'})
 await screen.findByText('完整运行日志 · 1 条')
 expect(screen.getByRole('list',{name:'最近进度事件'})).toHaveTextContent('历史识别完成')
 expect(within(screen.getByRole('region',{name:'研究进度'})).getByRole('heading',{level:2})).toHaveTextContent('研究未能完成')
 Events.last.emit('done',{})
 expect(Events.last.close).toHaveBeenCalled()
})

test('同一任务续跑后重新连接 SSE 并保留已有日志',async()=>{
 localStorage.setItem('cdr-run','r1')
 let resumed=false
 const recovery={can_resume:true,can_increase_budget:true,reason:'已保存进度',checkpoint_node:'resolve_company',saved_units:{node:1},unfinished_units:1,resume_count:0,legacy:false,budget:{global_call_budget:240,global_token_budget:2000000,block_call_budget:40,calls_used:0,tokens_used:0,unknown_calls:0}}
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/resume')&&init?.method==='POST'){resumed=true;return {ok:true,json:async()=>({...run,status:'queued',recovery})}}
  return {ok:true,json:async()=>({...run,status:resumed?'running':'interrupted',recovery})}
 })
 vi.stubGlobal('fetch',fetch)
 render(<App/>)
 await screen.findByRole('button',{name:'继续研究'})
 const original=Events.last
 original.emit('progress',{event_id:1,run_id:'r1',timestamp:new Date().toISOString(),stage:'公司识别',task_name:'公司识别',status:'completed',display_message:'已有识别成果'})
 original.emit('done',{})
 fireEvent.click(screen.getByRole('button',{name:'继续研究'}))
 await waitFor(()=>expect(Events.last).not.toBe(original))
 expect(localStorage.getItem('cdr-run')).toBe('r1')
 expect(screen.getByRole('list',{name:'最近进度事件'})).toHaveTextContent('已有识别成果')
 Events.last.emit('progress',{event_id:2,run_id:'r1',timestamp:new Date().toISOString(),stage:'研究规划',task_name:'research_brief',status:'running',display_message:'继续规划'})
 await waitFor(()=>expect(screen.getByRole('list',{name:'最近进度事件'})).toHaveTextContent('继续规划'))
})

test('新浏览器窗口自动打开 CMD 启动选择的任务',async()=>{
 localStorage.setItem('cdr-run','older')
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>({ok:true,json:async()=>url==='/api/startup'?{session_id:'new-service',selected_run_id:'chosen'}:{...run,run_id:url.includes('chosen')?'chosen':'older',status:'interrupted'}})))
 render(<App/>)
 await waitFor(()=>expect(localStorage.getItem('cdr-run')).toBe('chosen'))
 expect(sessionStorage.getItem('cdr-startup-session')).toBe('new-service')
 await waitFor(()=>expect(within(screen.getByRole('region',{name:'研究进度'})).getByRole('heading',{level:2})).toHaveTextContent('研究已暂停'))
})

test('同次服务刷新不重新切回启动时选择的旧任务',async()=>{
 localStorage.setItem('cdr-run','manually-created')
 sessionStorage.setItem('cdr-startup-session','same-service')
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>({ok:true,json:async()=>url==='/api/startup'?{session_id:'same-service',selected_run_id:'old-choice'}:{...run,run_id:'manually-created',status:'interrupted'}})))
 render(<App/>)
 await waitFor(()=>expect(within(screen.getByRole('region',{name:'研究进度'})).getByRole('heading',{level:2})).toHaveTextContent('研究已暂停'))
 expect(localStorage.getItem('cdr-run')).toBe('manually-created')
})

test('启动选择 N 等待确认后清除旧任务并保持初始页面，刷新也不加载旧任务',async()=>{
 localStorage.setItem('cdr-run','older')
 let resolveStartup!:(value:unknown)=>void
 const startup=new Promise(resolve=>{resolveStartup=resolve})
 const fetch=vi.fn(async(url:string)=>({ok:true,json:async()=>startup}))
 vi.stubGlobal('fetch',fetch)
 const view=render(<App/>)
 expect(fetch).toHaveBeenCalledTimes(1)
 expect(fetch).toHaveBeenCalledWith('/api/startup',undefined)
 expect(screen.queryByRole('region',{name:'研究进度'})).not.toBeInTheDocument()
 resolveStartup({session_id:'declined-service',selected_run_id:null,answer:'N'})
 await waitFor(()=>expect(localStorage.getItem('cdr-run')).toBeNull())
 expect(screen.getByLabelText('输入公司名称或股票代码')).toHaveValue('')
 expect(screen.getByRole('button',{name:'开始研究'})).toBeDisabled()
 expect(fetch).toHaveBeenCalledTimes(1)
 view.unmount()
 render(<App/>)
 await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2))
 expect(fetch.mock.calls.every(([url])=>url==='/api/startup')).toBe(true)
 expect(screen.queryByRole('region',{name:'研究进度'})).not.toBeInTheDocument()
})

test('启动选择 N 后手动开始新公司，刷新仍保持新任务',async()=>{
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>({ok:true,json:async()=>url==='/api/startup'
  ?{session_id:'declined-service',selected_run_id:null,answer:'N'}
  :{...run,run_id:'new-company',company_input:'新公司',status:'interrupted'}}))
 vi.stubGlobal('fetch',fetch)
 const view=render(<App/>)
 await waitFor(()=>expect(sessionStorage.getItem('cdr-startup-session')).toBe('declined-service'))
 fireEvent.change(screen.getByLabelText('输入公司名称或股票代码'),{target:{value:'新公司'}})
 fireEvent.click(screen.getByRole('button',{name:'开始研究'}))
 await screen.findByRole('heading',{level:2,name:/新公司/})
 expect(fetch).toHaveBeenCalledWith('/api/research',expect.objectContaining({method:'POST',body:JSON.stringify({company:'新公司'})}))
 view.unmount()
 render(<App/>)
 await screen.findByRole('heading',{level:2,name:/新公司/})
 expect(localStorage.getItem('cdr-run')).toBe('new-company')
})

test('启动响应延迟时不会清除用户已经手动创建的新任务',async()=>{
 let resolveStartup!:(value:unknown)=>void
 const startup=new Promise(resolve=>{resolveStartup=resolve})
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>({ok:true,json:async()=>url==='/api/startup'?startup:{...run,status:'interrupted'}})))
 render(<App/>)
 fireEvent.change(screen.getByLabelText('输入公司名称或股票代码'),{target:{value:'示例公司'}})
 fireEvent.click(screen.getByRole('button',{name:'开始研究'}))
 await screen.findByRole('heading',{level:2,name:/示例公司/})
 await act(async()=>{resolveStartup({session_id:'delayed-service',selected_run_id:null,answer:'N'})})
 expect(localStorage.getItem('cdr-run')).toBe('r1')
 expect(within(screen.getByRole('region',{name:'研究进度'})).getByRole('heading',{level:2})).toHaveTextContent('示例公司')
})
