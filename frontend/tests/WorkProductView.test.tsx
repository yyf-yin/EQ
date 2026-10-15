import {fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,test,vi} from 'vitest'
import {WorkProductView} from '../src/WorkProductView'

const product={artifact_type:'work_product',snapshot_id:'a'.repeat(64),snapshot_time:'2026-10-10T01:00:00Z',notice:'阶段成果｜未经最终审核｜可能不完整，仅供研究流程评估',run_status:'blocked',final_review_passed:false,
 run:{company_input:'公司',company_name:'',stage:'最终审核',error:'缺少同比基数',mode:'mock'},page:1,page_size:20,artifact_count:1,section_count:1,review_count:2,formats:['zip','json','md'],counts:{fact:5},
 blocks:[],issues:[{issue_id:'i1',severity:'critical',location:'F01',rule_id:'core',description:'缺少 2022A',suggested_fix:'补查同期'}],missing:[{kind:'data',id:'f',reason:'基数缺失'}],unavailable:[],notes:[],
 artifacts:[{kind:'section',section_id:'F01',generation_status:'complete',validation_status:'rejected',version_status:'current'}],
 sections:[{section_id:'F01',block_id:'F01',generation_status:'complete',validation_status:'rejected',version_status:'current',content:{section_id:'F01',title:'收入分析',paragraphs:['<script>alert(1)</script>'],children:[],tables:[],evidence_ids:['e1'],calculation_ids:[]}}],
 usage:{calls:2,provider_input_tokens:10,provider_output_tokens:5,usage_missing_calls:1,note:'未记录不代表零消耗'}}
afterEach(()=>vi.restoreAllMocks())

test('财务核验显示候选值、选择结果及裁决依据',async()=>{
 const value={...product,fact_decision_count:1,fact_decisions:[{decision_id:'d',group_id:'g',identity:{metric_code:'revenue',period:'2024A'},status:'unresolved',reason:'两份原始披露冲突，未解决',selected_ids:[],proof_evidence_ids:[],candidates:[{fact_id:'f1',value:'100',unit:'CNY_million',accounting_basis:'reported',source_id:'s1',evidence_id:'e1'},{fact_id:'f2',value:'120',unit:'CNY_million',accounting_basis:'reported',source_id:'s2',evidence_id:'e2'}]}]}
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>value})))
 render(<WorkProductView id="blocked"/>);fireEvent.click(screen.getByRole('button',{name:'查看阶段成果'}))
 await screen.findByText('财务冲突核验');expect(screen.getByText(/revenue · 2024A · 尚未解决/)).toBeInTheDocument()
 expect(screen.getByText('两份原始披露冲突，未解决')).toBeInTheDocument()
 expect(screen.getByText(/选用：无；证明证据：暂无/)).toBeInTheDocument()
 expect(screen.getByText(/事实 f2 · 来源 s2 · 证据 e2/)).toBeInTheDocument()
})

test('手动获取阶段成果，显示阻断原因、质量标签和安全正文',async()=>{
 const fetch=vi.fn(async()=>({ok:true,json:async()=>product}));vi.stubGlobal('fetch',fetch)
 const {container}=render(<WorkProductView id="blocked"/>);expect(fetch).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'查看阶段成果'}));await screen.findByText(product.notice)
 expect(screen.getByText('缺少同比基数')).toBeInTheDocument();expect(screen.getByText('缺少 2022A')).toBeInTheDocument()
 expect(screen.getAllByText(/不合格 · 当前版本/).length).toBeGreaterThan(0)
 expect(container.textContent).toContain('<script>alert(1)</script>');expect(container.querySelector('script')).toBeNull()
 expect(screen.getByText(/已保存送审轮次：2/)).toBeInTheDocument()
})

test('下载使用预览快照，打包失败可重试且不重新研究',async()=>{
 let fail=true
 const fetch=vi.fn(async(url:string)=>url.includes('/download')?{ok:!fail,json:async()=>({detail:'阶段成果打包失败，可重试'}),blob:async()=>new Blob(['zip'])}:{ok:true,json:async()=>product})
 vi.stubGlobal('fetch',fetch);vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:vi.fn(()=> 'blob:fixture'),revokeObjectURL:vi.fn()}))
 const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{})
 render(<WorkProductView id="blocked"/>);fireEvent.click(screen.getByRole('button',{name:'查看阶段成果'}));await screen.findByText(product.notice)
 fireEvent.click(screen.getByRole('button',{name:'导出评估包'}));await screen.findByRole('alert')
 expect(screen.getByRole('alert')).toHaveTextContent('可重试');fail=false
 fireEvent.click(screen.getByRole('button',{name:'导出评估包'}));await waitFor(()=>expect(click).toHaveBeenCalled())
 expect(fetch.mock.calls.filter(([url])=>url.includes('/download')).every(([url])=>url.includes(`snapshot_id=${product.snapshot_id}`))).toBe(true)
 expect(fetch.mock.calls.every(([url])=>url.includes('/work-product'))).toBe(true)
})

test('没有报告时显示空成果，元数据读取失败后可重新获取',async()=>{
 let fail=true;vi.stubGlobal('fetch',vi.fn(async()=>({ok:!fail,json:async()=>fail?{detail:'数据库暂时不可读取'}:{...product,sections:[],section_count:0,issues:[]}})))
 render(<WorkProductView id="failed"/>);fireEvent.click(screen.getByRole('button',{name:'查看阶段成果'}));await screen.findByRole('alert')
 expect(screen.getByRole('alert')).toHaveTextContent('数据库暂时不可读取');fail=false
 fireEvent.click(screen.getByRole('button',{name:'查看阶段成果'}));await screen.findByText('当前尚无写作成果。已有数据与诊断仍可导出。')
})

test('翻页固定快照，刷新显式获取最新成果',async()=>{
 const fetch=vi.fn(async(url:string)=>({ok:true,json:async()=>({...product,artifact_count:40,page:url.includes('page=2')?2:1})}));vi.stubGlobal('fetch',fetch)
 render(<WorkProductView id="running"/>);fireEvent.click(screen.getByRole('button',{name:'查看阶段成果'}));await screen.findByText(product.notice)
 fireEvent.click(screen.getByRole('button',{name:'下一页'}));await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2))
 expect(fetch.mock.calls[1][0]).toContain(`snapshot_id=${product.snapshot_id}`)
 await waitFor(()=>expect(screen.getByRole('button',{name:'获取最新阶段成果'})).toBeEnabled())
 fireEvent.click(screen.getByRole('button',{name:'获取最新阶段成果'}));await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(3))
 expect(fetch.mock.calls[2][0]).not.toContain('snapshot_id')
})
