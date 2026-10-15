import {test, expect} from '@playwright/test'

test('运行面板展示任务、材料、模型用量和完整日志，刷新及窄屏可用',async({page})=>{
 const id='runtime-demo',created=new Date(Date.now()-90000).toISOString(),updated=new Date(Date.now()-30000).toISOString()
 const run={run_id:id,company_input:'运行信息测试',company_name:'',mode:'real',status:'running',stage:'数据收集',limitations:[],error:null,created_at:created,updated_at:updated,
  blocks:[{block_id:'F01',status:'validated',version:'v1'}],coverage_counts:{verified:3,missing:1},batch_counts:{running:1,validated:2},
  runtime:{artifact_counts:{source:8,evidence:16,fact:24,calculation:0,section:0},usage:{calls:3,running_calls:1,succeeded_calls:1,failed_calls:1,provider_input_tokens:1200,provider_output_tokens:500,usage_missing_calls:1},
   recent_calls:[{call_id:'c1',role:'researcher',model:'测试模型',result:'running',started_at:updated}]}}
 const events=[{event_id:1,run_id:id,timestamp:created,stage:'公司识别',task_name:'公司识别',status:'completed',display_message:'已核对公司身份'},
  {event_id:2,run_id:id,timestamp:updated,stage:'数据收集',task_name:'F01',status:'running',display_message:'检索收入及利润资料'},
  {event_id:3,run_id:id,timestamp:updated,stage:'数据收集',task_name:'source',status:'warning',display_message:'部分资料尚未取得'}]
 await page.addInitScript(runId=>localStorage.setItem('cdr-run',runId),id)
 await page.route(`**/api/research/${id}`,route=>route.fulfill({json:run}))
 await page.route(`**/api/research/${id}/events?after=0`,route=>route.fulfill({contentType:'text/event-stream',body:events.map(e=>`id: ${e.event_id}\nevent: progress\ndata: ${JSON.stringify(e)}\n\n`).join('')}))
 await page.goto('/')
 await expect(page.getByRole('list',{name:'当前执行任务'})).toContainText('检索收入及利润资料')
 await expect(page.getByLabel('模型用量')).toContainText('1,200')
 await expect(page.getByLabel('材料统计')).toContainText('24')
 await page.getByText('最近模型请求',{exact:true}).click()
 await expect(page.getByRole('list',{name:'最近模型请求'})).toContainText('测试模型')
 await page.getByText('完整运行日志 · 3 条',{exact:true}).click()
 await page.getByLabel('仅显示提示与异常').check()
 await expect(page.getByRole('list',{name:'完整运行日志'}).getByRole('listitem')).toHaveCount(1)
 await expect(page.getByRole('list',{name:'完整运行日志'})).toContainText('部分资料尚未取得')
 await page.getByRole('region',{name:'研究进度'}).scrollIntoViewIfNeeded()
 await page.screenshot({path:'test-results/runtime-desktop.png',fullPage:true})
 await page.reload()
 await expect(page.getByText('完整运行日志 · 3 条',{exact:true})).toBeVisible()
 await expect(page.getByRole('list',{name:'当前执行任务'}).getByRole('listitem')).toHaveCount(1)
 await page.setViewportSize({width:390,height:844})
 await page.getByRole('region',{name:'研究进度'}).scrollIntoViewIfNeeded()
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
 await page.screenshot({path:'test-results/runtime-mobile.png',fullPage:true})
})
