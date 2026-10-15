import {test,expect} from '@playwright/test'

test('财务冲突候选与裁决依据在桌面和窄屏可查看',async({page})=>{
 const id='financial-conflict-demo',now=new Date().toISOString()
 await page.addInitScript(runId=>localStorage.setItem('cdr-run',runId),id)
 await page.route('**/api/startup',route=>route.fulfill({json:{session_id:'fixture',candidate:null,selection:{selected_run_id:null}}}))
 await page.route(`**/api/research/${id}`,route=>route.fulfill({json:{run_id:id,company_input:'核验演示',mode:'real',status:'blocked',stage:'最终审核',error:'关键收入存在冲突',limitations:[],created_at:now,updated_at:now}}))
 await page.route(`**/api/research/${id}/events?after=0`,route=>route.fulfill({contentType:'text/event-stream',body:'event: done\ndata: {}\n\n'}))
 const candidate=(n:string)=>({fact_id:'fact-'+n.repeat(24),value:n==='1'?'100':'120',unit:'CNY_million',accounting_basis:'reported',source_id:'source-'+n.repeat(24),evidence_id:'evidence-'+n.repeat(24)})
 await page.route(`**/api/research/${id}/work-product*`,route=>route.fulfill({json:{artifact_type:'work_product',snapshot_id:'a'.repeat(64),snapshot_time:now,notice:'阶段成果｜未经最终审核｜可能不完整，仅供研究流程评估',run_status:'blocked',final_review_passed:false,
  run:{company_input:'核验演示',stage:'最终审核',error:'关键收入存在冲突'},page:1,page_size:20,artifact_count:0,section_count:0,review_count:1,counts:{fact:2,fact_decision:1},blocks:[],issues:[],missing:[],unavailable:[],notes:[],artifacts:[],sections:[],usage:{calls:2,provider_input_tokens:0,provider_output_tokens:0,usage_missing_calls:2,note:'测试'},
  fact_decision_count:1,fact_decisions:[{decision_id:'d',group_id:'g',identity:{metric_code:'revenue',period:'2024A'},status:'unresolved',reason:'原始披露仍有不同数值，定向补查已耗尽；候选保留，未选入计算。',selected_ids:[],proof_evidence_ids:[],candidates:[candidate('1'),candidate('2')]}]}}))
 await page.goto('/');await page.getByRole('button',{name:'查看阶段成果'}).click()
 await expect(page.getByRole('heading',{name:'财务冲突核验'})).toBeVisible()
 await page.getByText('revenue · 2024A · 尚未解决',{exact:true}).click()
 await expect(page.getByText(/选用：无；证明证据：暂无/)).toBeVisible()
 await page.getByRole('heading',{name:'财务冲突核验'}).scrollIntoViewIfNeeded()
 await page.screenshot({path:'test-results/financial-conflict-desktop.png',fullPage:false})
 await page.setViewportSize({width:390,height:844})
 await page.getByRole('heading',{name:'财务冲突核验'}).scrollIntoViewIfNeeded()
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
 await page.screenshot({path:'test-results/financial-conflict-mobile.png',fullPage:false})
})

// Point this optional fault-suite at an isolated persisted blocked run; the normal
// application never exposes a production fault-injection API.
test('审核阻断后预览与三种评估导出，刷新保留入口且正式报告仍阻断',async({page})=>{
 const id=process.env.CDR_E2E_WORK_PRODUCT_RUN
 test.skip(!id,'需要隔离数据库中的审核阻断样例 CDR_E2E_WORK_PRODUCT_RUN')
 await page.addInitScript(runId=>localStorage.setItem('cdr-run',runId),id!)
 await page.goto('/')
 await expect(page.getByText(/审核阻断/).first()).toBeVisible()
 await expect(page.getByRole('button',{name:'查看阶段成果'})).toBeVisible()
 await page.getByRole('button',{name:'查看阶段成果'}).click()
 await expect(page.getByText('阶段成果｜未经最终审核｜可能不完整，仅供研究流程评估')).toBeVisible()
 await expect(page.getByRole('heading',{name:'当前审核问题'})).toBeVisible()
 await expect(page.getByRole('heading',{name:'已保存章节'})).toBeVisible()
 const json=await page.request.get(`/api/research/${id}/work-product`)
 const snapshot=await json.json()
 expect(snapshot.final_review_passed).toBe(false)
 expect(snapshot.review_count).toBeGreaterThan(0)
 for(const [button,extension] of [['导出评估包','zip'],['下载 JSON','json'],['下载 Markdown','md']]){
  const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:button,exact:true}).click()])
  expect(download.suggestedFilename()).toMatch(new RegExp(`\\.${extension}$`))
  expect(await download.failure()).toBeNull()
  await download.saveAs(`test-results/work-product.${extension}`)
 }
 expect((await page.request.get(`/api/research/${id}/report`)).status()).toBe(409)
 expect((await page.request.get(`/api/research/${id}/download`)).status()).toBe(409)
 await page.getByRole('region',{name:'阶段成果'}).scrollIntoViewIfNeeded()
 await page.screenshot({path:'test-results/work-product-blocked.png',fullPage:false})
 await page.reload()
 await expect(page.getByRole('button',{name:'导出评估包'})).toBeVisible()
 await page.getByRole('button',{name:'查看阶段成果'}).click()
 await expect(page.getByText(snapshot.notice)).toBeVisible()
})

test('无写作成果的失败任务仍可导出诊断，打包失败可重试',async({page})=>{
 test.skip(!process.env.CDR_E2E_WORK_PRODUCT_RUN,'需要隔离数据库中的失败样例')
 await page.addInitScript(()=>localStorage.setItem('cdr-run','v12-empty-failed'))
 await page.goto('/')
 await expect(page.getByText(/研究未能完成/)).toBeVisible()
 await page.getByRole('button',{name:'查看阶段成果'}).click()
 await expect(page.getByText('当前尚无写作成果。已有数据与诊断仍可导出。')).toBeVisible()
 await page.route('**/work-product/download?**',route=>route.fulfill({status:503,json:{detail:'阶段成果打包失败，可重试导出；研究状态未改变。'}}))
 await page.getByRole('button',{name:'导出评估包'}).click()
 await expect(page.getByRole('alert').last()).toContainText('可重试')
 await page.unroute('**/work-product/download?**')
 const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'导出评估包'}).click()])
 expect(download.suggestedFilename()).toMatch(/\.zip$/)
 expect(await download.failure()).toBeNull()
 await page.screenshot({path:'test-results/work-product-empty.png',fullPage:false})
})
