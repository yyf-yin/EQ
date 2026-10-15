import {fireEvent,render,screen,within} from '@testing-library/react'
import {afterEach,expect,test,vi} from 'vitest'
import {DataSlotsView} from '../src/DataSlotsView'
import type {DataSlots,Run} from '../src/types'

const run:Run={run_id:'fixed',company_input:'测试',company_name:'测试',mode:'real',status:'limited',stage:'文档生成',limitations:[],error:null,data_template_version:'fixed-slots-1'}
afterEach(()=>vi.unstubAllGlobals())
const field=(field_id:string,label:string)=>({field_id,label,normalized_unit:'CNY_million',requirement:'O'})
const data:DataSlots={template_version:'fixed-slots-1',groups:[
 {group_id:'income',title:'利润表',fields:[field('income.revenue','营业收入'),field('income.cost','营业成本')]},
 {group_id:'bond',title:'逐只债券',fields:[]},
 {group_id:'segment',title:'单业务',fields:[field('segment.volume','销量')]}],
 slots:[{slot_id:'zero',field_id:'income.revenue',label:'营业收入',period:'2025A',segment_id:null,bond_id:null,state:'locked',raw_value:'0',raw_unit:'元',normalized_value:'0',normalized_unit:'CNY_million',source_id:'annual',locator:'page:12',reason:'原值锁定',locked_at:'2026-10-14'},
 {slot_id:'missing',field_id:'income.cost',label:'营业成本',period:'2025A',segment_id:null,bond_id:null,state:'not_disclosed',raw_value:null,raw_unit:null,normalized_value:null,normalized_unit:'CNY_million',source_id:null,locator:null,reason:'未披露成本',locked_at:null}],materials:[],bond_presence:[]}

test('保留真实零值与未披露状态，缺少债券资料不显示无债券',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>data}))
 render(<DataSlotsView run={run}/>)
 const table=await screen.findByRole('table',{name:'利润表'})
 expect(table).toHaveTextContent('0 元');expect(table).toHaveTextContent('未披露')
 fireEvent.click(screen.getByRole('button',{name:'逐只债券'}))
 expect(screen.getByText(/不能据此认定没有债券/)).toBeInTheDocument()
})

test('年度、累计和单季度分别展示，最新期间与上年同期标记必需',async()=>{
 const slots=[...data.slots,
  {...data.slots[0],slot_id:'latest',period:'2026H1',period_label:'2026年上半年累计',requirement:'C',raw_value:'120'},
  {...data.slots[0],slot_id:'prior',period:'2025H1',period_label:'2025年上半年累计',requirement:'C',raw_value:'100'},
  {...data.slots[0],slot_id:'first',period:'2026Q1',period_label:'2026年一季度累计',requirement:'O',raw_value:'50'},
  {...data.slots[1],slot_id:'quarter',period:'20252Q',period_label:'2025年第2季度单季',requirement:'O'}]
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({...data,slots,latest_interim_period:'2026H1'})}))
 render(<DataSlotsView run={run}/>)
 const table=await screen.findByRole('table',{name:'利润表'})
 expect(table).toHaveTextContent('2025A');expect(table).not.toHaveTextContent('2026H1')
 fireEvent.click(screen.getByRole('button',{name:'季度／中期累计'}))
 expect(table).toHaveTextContent('2026年上半年累计');expect(table).toHaveTextContent('2025年上半年累计')
 expect(within(table).getAllByRole('columnheader').map(h=>h.textContent)).toEqual(['固定字段','2025H12025年上半年累计','2026Q12026年一季度累计','2026H12026年上半年累计'])
 expect(within(table).getAllByText('同比必需')).toHaveLength(2)
 expect(table).not.toHaveTextContent('20252Q')
 fireEvent.click(screen.getByRole('button',{name:'单季度'}))
 expect(table).toHaveTextContent('20252Q');expect(table).toHaveTextContent('未披露')
 expect(table).not.toHaveTextContent('同比必需')
 expect(screen.getByText(/当年最新披露期间：2026H1/)).toBeInTheDocument()
})

test('多产品经营数量以固定明细分别显示原单位',async()=>{
 const details={...data,slots:['吨','台'].map((unit,i)=>({...data.slots[0],slot_id:String(i),field_id:'segment.volume',label:'销量',segment_id:'设备',detail_id:'d'+i,product_name:i?'产品乙':'产品甲',raw_value:i?'20':'10',raw_unit:unit}))}
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>details}))
 render(<DataSlotsView run={run}/>)
 await screen.findByRole('button',{name:'单业务'})
 fireEvent.click(screen.getByRole('button',{name:'单业务'}))
 expect(screen.getByText('设备 / 产品甲')).toBeInTheDocument()
 expect(screen.getByText('设备 / 产品乙')).toBeInTheDocument()
 const tables=screen.getAllByRole('table')
 expect(within(tables[0]).getByText('10 吨')).toBeInTheDocument()
 expect(within(tables[1]).getByText('20 台')).toBeInTheDocument()
})

test('资料方向展示预设、模型补充及未找到与无变化的区别',async()=>{
 const materials:DataSlots['materials']=[{slot_id:'industry',topic:'行业资料：制造业',state:'ready',search_count:2,search_budget:3,
  limitations:['政策未取得适用资料'],scope:{subject:'制造业',start_date:'2023-01-01',as_of:'2026-10-14',policy_start_date:'2023-10-14',region:'地域未明确',linked_segments:['设备']},
  directions:[{direction_id:'policy',label:'政策与监管变化',description:'近期政策及适用范围',origin:'preset',reason:'通用方向',required:false},
   {direction_id:'trade',label:'贸易规则与海外布局',description:'贸易条件',origin:'model',reason:'设备出口业务',required:false},
   {direction_id:'rule',label:'设备许可规则',description:'规则的实际变化',origin:'model',reason:'许可条件',required:false}],
  direction_statuses:{policy:{status:'not_found',evidence_ids:[],reason:'限定来源中未取得资料'},trade:{status:'partial',evidence_ids:['e1'],reason:'仅取得部分地域资料'},rule:{status:'no_change',evidence_ids:['e2'],reason:'仅限某项许可规则在披露期间'}},
  stop_reason:'no_new_evidence',search_history:[{query:'制造业 政策与监管变化',direction_ids:['policy'],state:'completed',warnings:[]}]}]
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({...data,materials})}))
 render(<DataSlotsView run={run}/>)
 const table=await screen.findByRole('table',{name:'行业资料：制造业资料方向'})
 expect(table).toHaveTextContent('通用预设');expect(table).toHaveTextContent('模型补充')
 expect(table).toHaveTextContent('限定检索后未找到');expect(table).toHaveTextContent('部分取得')
 expect(table).toHaveTextContent('有证据支持无变化');expect(table).toHaveTextContent('设备出口业务')
 expect(screen.getByText(/未找到不代表不存在或无变化/)).toBeInTheDocument()
 expect(screen.getByText(/政策变化自 2023-10-14 起/)).toBeInTheDocument()
 expect(screen.getByText(/补查未取得新增证据/)).toBeInTheDocument()
})
