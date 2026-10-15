"""Regenerate explicitly synthetic local fixtures; no live company data."""
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]/'examples/fixtures'
root.mkdir(parents=True,exist_ok=True)
facts=[]
for year,scale in [(2022,0.7),(2023,0.8),(2024,0.9),(2025,1.0)]:
    metrics={'revenue':1000*scale,'cost':600*scale,'net_income':150*scale,'ebit':200*scale,'tax_rate':.25,'equity':300*scale,'assets':500*scale,'liabilities':200*scale,'cash':100*scale,'receivables':100*scale,'inventory':60*scale,'ppe':200*scale,'other_assets':40*scale,'payables':60*scale,'debt':100*scale,'other_liabilities':40*scale,'current_assets':260*scale,'current_liabilities':100*scale,'operating_cashflow':160*scale,'capex':30*scale,'shares':100,'price':20,'depreciation':20*scale,'ebitda':220*scale,'average_equity':285*scale,'average_assets':475*scale,'average_inventory':57*scale,'average_receivables':95*scale,'average_invested_capital':300*scale}
    metrics.update(parent_net_income=145*scale,adjusted_parent_net_income=140*scale)
    for metric,value in metrics.items():
        unit='million_shares' if metric=='shares' else 'CNY/share' if metric=='price' else 'ratio' if metric=='tax_rate' else 'CNY_million'
        facts.append({'company_id':'DEMO','metric_code':metric,'period':f'{year}A','unit':unit,'value':str(round(value,6)),'actual_or_forecast':'actual','scope':'consolidated'})
    for segment,revenue in [('设备',600),('服务',400)]:
        for metric,value in [('revenue',revenue*scale),('cost',revenue*.6*scale)]:
            facts.append({'company_id':'DEMO','metric_code':metric,'period':f'{year}A','unit':'CNY_million','value':str(round(value,6)),'actual_or_forecast':'actual','scope':'segment','segment_id':segment})
for period,scale in [('2025H1',.45),('2026H1',.50)]:
    for metric,value in {'revenue':1000*scale,'cost':600*scale,'parent_net_income':145*scale,'adjusted_parent_net_income':140*scale,'operating_cashflow':160*scale}.items():
        facts.append({'company_id':'DEMO','metric_code':metric,'period':period,'unit':'CNY_million','value':str(value),'actual_or_forecast':'actual','scope':'consolidated'})
(root/'financials.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2),encoding='utf-8')
(root/'company.md').write_text('''# 示例制造公司 模拟材料

本材料为合成 Fixture，没有真实上市公司的事实或价格。公司标识 DEMO，非实际证券代码。输入任何名称均映射此演示公司。

示例制造公司经营设备与服务两项业务。设备业务用于演示工业客户资本开支周期、交付验收与应收账款之间的关系；服务业务用于演示存量设备维护与续约的联系。上述行业机制为测试研究逻辑的假设，不代表任何具体公司。

设备行业情况：需求受客户投资周期影响，技术升级会改变采购节奏；标准化产品竞争可能压缩价格，定制化交付要求售后保障。演示公司情况：设备收入占比较高，收入确认与交付节点相连，客户回款和库存管理是经营质量观察项。没有客户名单、合同或市占率证据，不能写成确定竞争优势。

服务行业情况：客户设备存量影响维修和维护需求，续约和响应能力关系到客户留存。演示公司情况：服务业务与设备业务有联系，但缺少真实续约率、服务单价、客户流失率，不可直接假定高利润或持续增长。

模拟预测依据：基础情景假设设备与服务维持适度增长；悲观情景假设需求偏弱且成本压力增加；乐观情景假设需求改善。营运资本比例、资本开支、股本及估值倍数全部由测试人员指定，非公开市场数据。预测必须在报告中标为条件推演。

风险资料：需求弱化可能使收入增长假设落空；库存与应收占用会使利润与现金背离；资本开支超支导致自由现金流减少；估值倍数变化可以抵消盈利增长。真实资料缺失本身是最重要的限制。
''',encoding='utf-8')
print(root)
