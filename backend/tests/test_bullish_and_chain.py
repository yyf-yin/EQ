"""The sell-side bullish option and the cost structure read from annual reports."""
from company_research.agents import WriterDraft, request_messages
from company_research.cost_structure import cost_rows, derived_lines
from company_research.schemas import ResearchRun, SourceRecord
from company_research.writers import draft_problems

TABLE = '''贵州茅台酒股份有限公司 2021 年年度报告
成本分析表
单位：元
分行业情况
酒类  8,890,990,510.72 100 8,083,371,418.24 100 9.99
分产品情况
酒类
直接材料 5,006,828,759.74 56.32 4,426,309,798.99 54.76 13.12
直接人工 2,776,100,778.17 31.22 2,626,407,879.93 32.49 5.70
燃料及动力 271,547,032.80 3.05 244,593,638.55 3.03 11.02
合计 8,890,990,510.72 100.00 8,083,371,418.24 100.00 9.99
(5). 报告期主要子公司股权变动导致合并范围变化
前五名客户销售额 1,498,273.79 万元，占年度销售总额 14.13%；其中前五名客户销售额中关联方
前五名供应商采购额 291,734.79 万元， 占年度采购总额43.33%； 其中前五名供应商采购额中
'''


def test_cost_table_and_top_five_shares_become_citable_lines():
    rows = cost_rows(TABLE)
    assert [(r['product'], r['item'], r['share'], r['change']) for r in rows] == [
        ('酒类', '直接材料', '56.32', '13.12'), ('酒类', '直接人工', '31.22', '5.70'), ('酒类', '燃料动力', '3.05', '11.02'),
    ]
    label, lines = derived_lines(SourceRecord(kind='upload', title='2021.pdf', content=TABLE))
    assert label == '2021年'
    values = {(subject, metric): value for subject, metric, value, _ in lines}
    assert values[('公司酒类', '直接材料占营业成本比重')] == '56.32%'
    assert values[('公司', '前五名供应商采购占比')] == '43.33%' and values[('公司', '前五名客户销售占比')] == '14.13%'


def test_bullish_style_reaches_writers_and_reviewers_only_when_chosen():
    writer = request_messages('writer', {'writing_style': 'bullish', 'section': {}})[0]['content']
    assert '卖方看多逻辑写法' in writer
    assert '卖方看多逻辑写法' not in request_messages('writer', {'section': {}})[0]['content']
    review = request_messages('critical_reviewer', {'writing_style': 'bullish', 'section': {}})[0]['content']
    assert '有证据支持的正面判断' in review
    assert '有证据支持的正面判断' not in request_messages('critical_reviewer', {'section': {}})[0]['content']
    assert ResearchRun(company_input='x', mode='mock').bullish is False


def test_short_risk_items_pass_only_in_the_compact_risk_list():
    items = ['需求恢复不及预期：若商务需求修复偏慢，则收入增速可能低于预测。'] * 4
    draft = WriterDraft(paragraphs=items, evidence_ids=[], calculation_ids=[], fact_ids=[], assumption_ids=[])
    local = dict(facts=[], calculations=[], assumptions=[], evidence=[], industry_data=[])
    assert any('段过短' in p for p in draft_problems(draft, local))
    assert not any('段过短' in p for p in draft_problems(draft, local | {'compact': True}))
