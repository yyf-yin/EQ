import {fireEvent,render,screen,waitFor} from '@testing-library/react'
import {beforeEach,expect,test,vi} from 'vitest'
import {HumanInterventionView} from '../src/HumanInterventionView'
import {getHumanIntervention,submitHumanFeedback} from '../src/api'
import type {HumanQueue,Run} from '../src/types'

vi.mock('../src/api',()=>({getHumanIntervention:vi.fn(),submitHumanFeedback:vi.fn()}))
const run:Run={run_id:'r',company_input:'测试',company_name:'测试',mode:'real',status:'waiting_human',stage:'数据核验',limitations:[],error:null}
let queue:HumanQueue
beforeEach(()=>{
 vi.clearAllMocks()
 queue={can_submit:true,sources:[{source_id:'s',title:'公司年报'}],feedback:[],issues:[{issue_id:'i',signature:'a'.repeat(64),identity:{metric_code:'revenue',period:'2024A',scope:'consolidated',unit:'CNY_million'},reason:'收入存在冲突',blocking:true,kind:'conflict',status:'open',phase:'awaiting_human',feedback_error:'',candidates:[{fact_id:'f',value:'100',unit:'CNY_million',accounting_basis:'reported',source_id:'s',evidence_id:'e',title:'公司年报',quote:'2024年度合并收入100百万元',locator:'p1'}]}]}
 vi.mocked(getHumanIntervention).mockImplementation(async()=>structuredClone(queue))
 vi.mocked(submitHumanFeedback).mockResolvedValue({feedback_id:'feedback',status:'pending',resumed:true})
})

test('展示原文依据并提交绑定候选版本的选择',async()=>{
 const refresh=vi.fn();render(<HumanInterventionView run={run} onSubmitted={refresh}/>)
 await screen.findByText('收入存在冲突')
 expect(screen.getByText('2024年度合并收入100百万元')).toBeInTheDocument()
 fireEvent.change(screen.getByLabelText('依据与处理理由'),{target:{value:'采用公司年报合并值'}})
 fireEvent.click(screen.getByRole('button',{name:'提交并核验'}))
 await waitFor(()=>expect(submitHumanFeedback).toHaveBeenCalledWith('r','i',{action:'select',signature:'a'.repeat(64),fact_id:'f',reason:'采用公司年报合并值'}))
 expect(refresh).toHaveBeenCalled()
})

test('支持补充来源原文与数值，失败反馈仍可处理',async()=>{
 queue.issues[0].feedback_error='两个原始披露仍冲突'
 render(<HumanInterventionView run={run} onSubmitted={()=>{}}/>)
 await screen.findByText(/两个原始披露仍冲突/)
 fireEvent.change(screen.getByLabelText('处理方式'),{target:{value:'supplement'}})
 for(const [label,value] of [['已收集来源','s'],['完整原文摘录','2024年度合并收入100百万元'],['原文位置','p1'],['数值','100'],['依据与处理理由','补充表头和原始数值']])fireEvent.change(screen.getByLabelText(label),{target:{value}})
 fireEvent.click(screen.getByRole('button',{name:'提交并核验'}))
 await waitFor(()=>expect(submitHumanFeedback).toHaveBeenCalled())
 expect(vi.mocked(submitHumanFeedback).mock.calls[0][2]).toMatchObject({action:'supplement',value:'100',source_id:'s',unit:'CNY_million',locator:'p1'})
})

test('指定新的补查方向并呈现服务拒绝理由',async()=>{
 vi.mocked(submitHumanFeedback).mockRejectedValue(new Error('候选已更新，请刷新'))
 render(<HumanInterventionView run={run} onSubmitted={()=>{}}/>)
 await screen.findByText('收入存在冲突')
 fireEvent.change(screen.getByLabelText('处理方式'),{target:{value:'research'}})
 fireEvent.change(screen.getByLabelText('补查方向或链接'),{target:{value:'https://cninfo.com.cn/report.pdf'}})
 fireEvent.change(screen.getByLabelText('依据与处理理由'),{target:{value:'补查更正公告'}})
 fireEvent.click(screen.getByRole('button',{name:'提交并核验'}))
 await screen.findByText('候选已更新，请刷新')
 expect(vi.mocked(submitHumanFeedback).mock.calls[0][2]).toMatchObject({action:'research',query:'https://cninfo.com.cn/report.pdf'})
})

test('处理中和未选择恢复的旧任务禁用提交',async()=>{
 queue.can_submit=false;queue.issues[0].status='researching'
 render(<HumanInterventionView run={run} onSubmitted={()=>{}}/>)
 await screen.findByText('反馈已保存，等待核验结果。')
 expect(screen.getByRole('button',{name:'提交并核验'})).toBeDisabled()
})

test('候选版本更新时清空过期输入',async()=>{
 const {rerender}=render(<HumanInterventionView run={run} onSubmitted={()=>{}}/>)
 await screen.findByText('收入存在冲突')
 fireEvent.change(screen.getByLabelText('依据与处理理由'),{target:{value:'旧候选的处理意见'}})
 queue.issues[0].signature='b'.repeat(64)
 rerender(<HumanInterventionView run={{...run,status:'running'}} onSubmitted={()=>{}}/>)
 await waitFor(()=>expect(screen.getByLabelText('依据与处理理由')).toHaveValue(''))
})
