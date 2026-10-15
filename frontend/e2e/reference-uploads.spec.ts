import {test,expect} from '@playwright/test'

test('启动页上传、绑定研究、刷新保留资料，桌面与手机均可操作',async({page})=>{
 await page.goto('/')
 await expect(page.getByRole('region',{name:'上传参考资料'})).toBeVisible()
 await page.getByLabel('选择参考资料文件').setInputFiles([
  {name:'参考年报.txt',mimeType:'text/plain',buffer:Buffer.from('测试公司 2024年度 合并 营业收入 110百万元。\n主营业务：设备生产与服务。','utf8')},
  ...Array.from({length:11},(_,i)=>({name:`行业参考${i+1}.txt`,mimeType:'text/plain',buffer:Buffer.from(`行业报告 ${i+1}：2025年全球工业自动化需求与产业链研究。`,'utf8')}))
 ])
 await expect(page.getByRole('list',{name:'已上传参考资料'})).toContainText('参考年报.txt')
 await expect(page.getByRole('list',{name:'已上传参考资料'})).toContainText('已解析')
 await expect(page.getByText('已上传 12 / 50 份')).toBeVisible()
 await page.getByLabel('输入公司名称或股票代码').fill('参考资料演示公司')
 const created=page.waitForResponse(r=>r.url().endsWith('/api/research')&&r.request().method()==='POST')
 await page.getByRole('button',{name:'开始研究'}).click()
 const response=await created
 expect(response.status()).toBe(202)
 const run=await response.json()
 expect(run.reference_attachment_ids).toHaveLength(12)
 await expect(page.getByRole('region',{name:'本次研究参考资料'})).toContainText('参考年报.txt')
 await expect(page.getByRole('region',{name:'本次研究参考资料'})).toContainText('行业参考11.txt')
 await expect(page.getByRole('region',{name:'本次研究参考资料'})).toContainText('模拟模式仅保存附件')
 await page.reload()
 await expect(page.getByRole('region',{name:'本次研究参考资料'})).toContainText('参考年报.txt')
 await page.screenshot({path:'test-results/reference-upload-desktop.png',fullPage:false})
 await page.setViewportSize({width:390,height:844})
 await expect(page.getByRole('region',{name:'上传参考资料'})).toBeVisible()
 await page.screenshot({path:'test-results/reference-upload-mobile.png',fullPage:false})
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
})

test('初始页可删除上传文件，后端解析失败显示原因',async({page})=>{
 await page.addInitScript(()=>{localStorage.clear();sessionStorage.clear()})
 await page.goto('/')
 await page.getByLabel('选择参考资料文件').setInputFiles({name:'研报.md',mimeType:'text/markdown',buffer:Buffer.from('# 行业研究\n设备需求变化')})
 await expect(page.getByRole('button',{name:'移除 研报.md'})).toBeVisible()
 await page.getByRole('button',{name:'移除 研报.md'}).click()
 await expect(page.getByRole('list',{name:'已上传参考资料'})).toHaveCount(0)
 await page.getByLabel('选择参考资料文件').setInputFiles({name:'损坏年报.pdf',mimeType:'application/pdf',buffer:Buffer.from('not a valid PDF')})
 await expect(page.getByRole('alert')).toContainText('解析失败')
 await expect(page.getByLabel('选择参考资料文件')).toBeEnabled()
})
