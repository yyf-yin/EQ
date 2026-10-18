import {fireEvent,render,screen,waitFor} from '@testing-library/react'
import {expect,test,vi} from 'vitest'
import {ResumePackageImport} from '../src/ResumePackage'
import type {PackageInfo} from '../src/types'

const info:PackageInfo={
 package_id:'p1',created_at:'2026-10-19T08:00:00Z',checkpoint_node:'assemble',
 source:{run_id:'old',company_input:'测试公司',company_name:'测试公司',mode:'real',status:'blocked',stage:'最终审核',error:'终审阻断：风险章节缺少监测指标'},
 levels:[
  {level:'collection',label:'资料与数据收集',stages:['数据收集'],available:true},
  {level:'forecast',label:'财务分析与盈利预测',stages:['盈利预测'],available:true},
  {level:'blocks',label:'分块分析',stages:['分块分析'],available:true},
  {level:'writing',label:'合格章节',stages:['分块分析'],available:true},
 ],
 recommended_level:'writing',recommendation:'沿用合格章节，只重写不合格章节。',
 review:{snapshot_id:'s',reviewed:true,unmapped_issues:[],sections:[
  {section_id:'company',title:'一、公司简介',status:'passed',issues:[],default_keep:true},
  {section_id:'risk',title:'五、风险提示',status:'failed',issues:['风险章节缺少监测指标'],default_keep:false},
 ]},
 attachments:[{filename:'年报.pdf',size:10}],
 risks:[{field:'prompts',label:'提示词',level:'medium',message:'沿用的成果按旧提示词生成'}],
 incompatible:null,
}

test('上传成果包后默认沿用合格章节，确认风险后才能导入',async()=>{
 const fetch=vi.fn(async(url:string)=>({ok:true,json:async()=>url==='/api/resume-packages'?info:{run_id:'new',status:'queued'}}))
 vi.stubGlobal('fetch',fetch)
 const onImported=vi.fn()
 render(<ResumePackageImport disabled={false} onImported={onImported}/>)
 fireEvent.change(screen.getByLabelText('选择成果包文件'),{target:{files:[new File(['zip'],'pkg.zip')]}})
 await screen.findByText('当前配置与成果包生成时不同')
 expect(screen.getByRole('radio',{name:/合格章节/})).toBeChecked()
 expect(screen.getByRole('checkbox',{name:/一、公司简介/})).toBeChecked()
 expect(screen.getByRole('checkbox',{name:/五、风险提示/})).not.toBeChecked()
 const submit=screen.getByRole('button',{name:'导入并继续'})
 expect(submit).toBeDisabled()
 fireEvent.click(screen.getByRole('checkbox',{name:/我已了解以上风险/}))
 fireEvent.click(submit)
 await waitFor(()=>expect(onImported).toHaveBeenCalledWith({run_id:'new',status:'queued'}))
 expect(fetch).toHaveBeenLastCalledWith('/api/resume-packages/p1/import',expect.objectContaining({body:JSON.stringify({level:'writing',keep_sections:['company'],accept_risks:true})}))
})

test('不兼容的成果包不能导入',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({...info,risks:[],incompatible:'成果包来自模拟运行，当前为真实研究，不能混用。'})})))
 render(<ResumePackageImport disabled={false} onImported={()=>{}}/>)
 fireEvent.change(screen.getByLabelText('选择成果包文件'),{target:{files:[new File(['zip'],'pkg.zip')]}})
 await screen.findByText('成果包来自模拟运行，当前为真实研究，不能混用。')
 expect(screen.getByRole('button',{name:'导入并继续'})).toBeDisabled()
})
