import {fireEvent, render, screen, within, act} from '@testing-library/react'
import {afterEach, expect, test, vi} from 'vitest'
import {ResearchProgress} from '../src/ResearchProgress'
import type {Progress, Run} from '../src/types'

const run:Run={run_id:'r1',company_input:'测试公司',company_name:'',mode:'real',status:'running',stage:'数据收集',limitations:[],error:null,
 created_at:'2026-10-11T00:00:00Z',updated_at:'2026-10-11T00:01:00Z',
 coverage_counts:{verified:3,missing:2},batch_counts:{validated:4,running:1},blocks:[{block_id:'F01',status:'validated',version:'v1'}],
 runtime:{artifact_counts:{source:10,evidence:20,fact:30,calculation:40,section:2},
 usage:{calls:3,running_calls:1,succeeded_calls:1,failed_calls:1,provider_input_tokens:1200,provider_output_tokens:500,usage_missing_calls:1},
 recent_calls:[{call_id:'c1',role:'researcher',model:'测试模型',result:'running',started_at:'2026-10-11T00:01:00Z'}]}}
const event=(id:number,task:string,status:string,message:string):Progress=>({event_id:id,run_id:'r1',timestamp:`2026-10-11T00:00:${String(id).padStart(2,'0')}Z`,stage:'数据收集',task_name:task,status,display_message:message})
afterEach(()=>vi.useRealTimers())

test('并行任务按任务去重，重复消息保留起始耗时，显示材料与实际用量',()=>{
 vi.useFakeTimers();vi.setSystemTime(new Date('2026-10-11T00:01:00Z'))
 render(<ResearchProgress run={run} events={[event(1,'t1','running','查找资料'),event(2,'t1','running','检查缺口'),event(3,'t2','running','已结束任务'),event(4,'t2','completed','摘要已完成')]} busy connected lastSyncedAt={Date.now()}/>)
 const tasks=screen.getByRole('list',{name:'当前执行任务'})
 expect(within(tasks).getAllByRole('listitem')).toHaveLength(1)
 expect(tasks).toHaveTextContent('检查缺口');expect(tasks).toHaveTextContent('已执行 59秒')
 expect(within(screen.getByLabelText('运行概况')).getByText('1分 0秒')).toBeInTheDocument()
 expect(screen.getByLabelText('模型用量')).toHaveTextContent('1,200')
 expect(screen.getByText(/1 次请求未返回用量/)).toBeInTheDocument()
 expect(within(screen.getByLabelText('材料统计')).getByText('30')).toBeInTheDocument()
 act(()=>vi.advanceTimersByTime(1000))
 expect(tasks).toHaveTextContent('已执行 1分 0秒')
})

test('完整日志可过滤异常，终止后隐藏旧执行任务并冻结耗时',()=>{
 vi.useFakeTimers();vi.setSystemTime(new Date('2026-10-11T01:00:00Z'))
 const events=[event(1,'t1','running','旧任务'),event(2,'pdf','warning','PDF 生成失败')]
 render(<ResearchProgress run={{...run,status:'failed'}} events={events} busy={false} connected={false} lastSyncedAt={null}/>)
 expect(screen.queryByRole('list',{name:'当前执行任务'})).toBeNull()
 expect(within(screen.getByLabelText('运行概况')).getByText('1分 0秒')).toBeInTheDocument()
 fireEvent.click(screen.getByLabelText('仅显示提示与异常'))
 const log=screen.getByRole('list',{name:'完整运行日志'})
 expect(within(log).getAllByRole('listitem')).toHaveLength(1)
 expect(log).toHaveTextContent('PDF 生成失败');expect(log).not.toHaveTextContent('旧任务')
 act(()=>vi.advanceTimersByTime(5000))
 expect(within(screen.getByLabelText('运行概况')).getByText('1分 0秒')).toBeInTheDocument()
})

test('阶段返工回退，断线时显示同步时间，旧接口缺少统计时使用占位',()=>{
 const events:Progress[]=[{...event(1,'公司识别','completed','识别完成'),stage:'公司识别'},
  {...event(2,'研究规划','completed','规划完成'),stage:'研究规划'},
  {...event(3,'revision_plan','running','重新规划'),stage:'研究规划'}]
 render(<ResearchProgress run={{...run,runtime:undefined,created_at:undefined}} events={events} busy connected={false} lastSyncedAt={Date.now()}/>)
 expect(screen.getByText('1 / 10')).toBeInTheDocument()
 expect(screen.getByText(/实时连接中断，正在重连/)).toHaveTextContent('状态同步于')
 expect(screen.getByLabelText('材料统计')).toHaveTextContent('—')
})

test('区分缓存未知与真实零命中，并展示单次请求的实际输入输出',()=>{
 const {rerender}=render(<ResearchProgress run={run} events={[]} busy={false} connected={false} lastSyncedAt={null}/>)
 expect(screen.getByLabelText('输入缓存统计')).toHaveTextContent('未记录')
 const runtime={...run.runtime!,usage:{...run.runtime!.usage,cache_reported_calls:2,cache_reported_input_tokens:1000,cache_hit_tokens:0,cache_hit_ratio:0},
  recent_calls:[{call_id:'c4',role:'reference_planner',result:'ok',duration_seconds:2.8,input_tokens:4602,output_tokens:187,cache_hit_tokens:0}]}
 rerender(<ResearchProgress run={{...run,runtime}} events={[]} busy={false} connected={false} lastSyncedAt={null}/>)
 expect(screen.getByLabelText('输入缓存统计')).toHaveTextContent('0.0%')
 const calls=screen.getByRole('list',{name:'最近模型请求'})
 expect(calls).toHaveTextContent('参考资料覆盖检查')
 expect(calls).toHaveTextContent('单次请求 2秒')
 expect(calls).toHaveTextContent('输入 4,602 / 输出 187 token')
})
