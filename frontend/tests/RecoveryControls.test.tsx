import {render,screen,fireEvent} from '@testing-library/react'
import {vi,test,expect} from 'vitest'
import {RecoveryControls} from '../src/RecoveryControls'
import type {Run} from '../src/types'

const run:Run={run_id:'r',company_input:'测试',company_name:'',mode:'mock',status:'failed',stage:'报告写作',limitations:[],error:'请求失败',recovery:{
 can_resume:true,can_increase_budget:true,reason:'保留已保存成果，从未完成的步骤继续。',checkpoint_node:'analyze_blocks',
 saved_units:{research_task:3,model:7,node:5},unfinished_units:2,resume_count:1,legacy:false,
 budget:{global_call_budget:240,global_token_budget:2000000,block_call_budget:40,calls_used:10,tokens_used:10000,unknown_calls:1},
}}

test('失败任务保留数量、累计预算与继续入口',()=>{
 const control=vi.fn(async()=>{}),increaseBudget=vi.fn(async()=>{})
 render(<RecoveryControls run={run} actionBusy={false} control={control} increaseBudget={increaseBudget}/>)
 expect(screen.getByText(/已保存 3 个研究任务、7 个模型步骤/)).toBeInTheDocument()
 expect(screen.getByText(/有 1 次请求结果未知/)).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button',{name:'从断点继续'}))
 expect(control).toHaveBeenCalledWith('resume')
 fireEvent.click(screen.getByRole('button',{name:'调整续跑预算'}))
 fireEvent.change(screen.getByLabelText('总调用上限'),{target:{value:'300'}})
 fireEvent.click(screen.getByRole('button',{name:'保存总预算'}))
 expect(increaseBudget).toHaveBeenCalledWith({global_call_budget:300,global_token_budget:2000000,block_call_budget:40})
})

test('运行中暂停，保存期间不能继续，质量阻断无续跑按钮',()=>{
 const control=vi.fn(async()=>{}),increaseBudget=vi.fn(async()=>{})
 const {rerender}=render(<RecoveryControls run={{...run,status:'running'}} actionBusy={false} control={control} increaseBudget={increaseBudget}/>)
 fireEvent.click(screen.getByRole('button',{name:'暂停研究'}))
 expect(control).toHaveBeenCalledWith('pause')
 rerender(<RecoveryControls run={{...run,status:'pausing'}} actionBusy={false} control={control} increaseBudget={increaseBudget}/>)
 expect(screen.getByRole('status')).toHaveTextContent('正在保存进度')
 expect(screen.queryByRole('button',{name:'继续研究'})).not.toBeInTheDocument()
 rerender(<RecoveryControls run={{...run,status:'blocked',recovery:{...run.recovery!,can_resume:false,can_increase_budget:false,reason:'不能跳过审核'}}} actionBusy={false} control={control} increaseBudget={increaseBudget}/>)
 expect(screen.queryByRole('button',{name:'从断点继续'})).not.toBeInTheDocument()
 expect(screen.getByText('不能跳过审核')).toBeInTheDocument()
})

test('重启后的旧任务隐藏控制，正在请求时显示反馈并禁止重复提交',()=>{
 const control=vi.fn(async()=>{}),increaseBudget=vi.fn(async()=>{})
 const {rerender}=render(<RecoveryControls run={{...run,status:'running'}} actionBusy={true} pendingAction="pause" control={control} increaseBudget={increaseBudget}/>)
 expect(screen.getByRole('button',{name:'正在请求暂停…'})).toBeDisabled()
 expect(screen.getByRole('button',{name:'继续研究'})).toBeDisabled()
 rerender(<RecoveryControls run={{...run,status:'interrupted',recovery:{...run.recovery!,current_session:false,can_resume:false,can_increase_budget:false,reason:'程序已重启，请新建研究'}}} actionBusy={false} control={control} increaseBudget={increaseBudget}/>)
 expect(screen.queryByRole('button',{name:'继续研究'})).not.toBeInTheDocument()
 expect(screen.queryByRole('button',{name:'暂停研究'})).not.toBeInTheDocument()
 expect(screen.getByText('程序已重启，请新建研究')).toBeInTheDocument()
})

test('次数只统计时隐藏次数预算并只调整 token',()=>{
 const control=vi.fn(async()=>{}),increaseBudget=vi.fn(async()=>{})
 const unlimitedRun={...run,recovery:{...run.recovery!,budget:{...run.recovery!.budget,enforce_call_budgets:false}}}
 render(<RecoveryControls run={unlimitedRun} actionBusy={false} control={control} increaseBudget={increaseBudget}/>)
 expect(screen.getByText(/累计调用 10（仅统计，不设次数上限）/)).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button',{name:'调整续跑预算'}))
 expect(screen.queryByLabelText('总调用上限')).not.toBeInTheDocument()
 expect(screen.queryByLabelText('每块调用上限')).not.toBeInTheDocument()
 fireEvent.change(screen.getByLabelText('总 token 上限'),{target:{value:'20000000'}})
 fireEvent.click(screen.getByRole('button',{name:'保存总预算'}))
 expect(increaseBudget).toHaveBeenCalledWith({global_call_budget:240,global_token_budget:20000000,block_call_budget:40})
})
