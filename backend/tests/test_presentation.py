from decimal import Decimal
from io import BytesIO

from company_research.charts import Chart, Series, aligned_ticks, nice_ticks, to_drawing, to_png, to_svg
from company_research.presentation import CHAPTERS, clean, present, ticker
from company_research.reports import html_report, mock_report
from company_research.schemas import EvidenceRecord, FinancialFact, ReportSection

EV = 'ev-7818ceb16a961e62db3933fb'


def fact(metric, period, value, unit='CNY_million', segment=None):
    return FinancialFact(
        fact_id=f'fact-{metric}-{period}-{segment}', company_id='A股:600519', metric_code=metric, period=period,
        unit=unit, value=Decimal(str(value)), actual_or_forecast='actual',
        scope='segment' if segment else 'consolidated', segment_id=segment, source_id='s', evidence_id=EV,
        locator='page:1', validation_status='verified',
    )


def report_with_facts():
    report = mock_report('贵州茅台')
    report.company_id = 'A股:600519'
    report.title = '贵州茅台酒股份有限公司 公司深度研究报告'
    report.mode = 'real'
    values = {
        'revenue': [124100, 147694, 170899, 168838], 'cost': [10093, 11867, 13789, 14892],
        'parent_net_income': [62716, 74734, 86228, 82320], 'net_income': [65375, 77521, 89335, 85310],
        'assets': [254365, 272700, 298945, 303835], 'liabilities': [49036, 49043, 56933, 49876],
        'parent_equity': [197507, 215669, 233106, 244638], 'operating_cashflow': [36699, 66593, 92464, 61522],
    }
    for metric, series in values.items():
        for year, value in zip(['2022A', '2023A', '2024A', '2025A'], series):
            report.financial_facts.append(fact(metric, year, value))
    report.financial_facts += [fact('revenue', '2026H1', 90703, segment=None), fact('revenue', '2025H1', 89389)]
    report.financial_facts += [fact('revenue', '2026H1', 78000, segment='茅台酒'), fact('revenue', '2026H1', 12000, segment='其他系列酒')]
    report.limitations = ['内部限制说明不应出现在正文']
    report.evidence = [EvidenceRecord(evidence_id=EV, source_id='s', claim='c', quote='q', locator='page:1; page:2')]
    report.sections[2].paragraphs = [f'公司为白酒龙头。控股股东为集团（{EV}），营业收入 147693.60百万元。']
    return report


def test_skeleton_is_fixed_and_audit_data_stays_out():
    report = report_with_facts()
    view = present(report)
    assert [s.title for s in view.sections] == CHAPTERS
    assert view.title == '贵州茅台酒股份有限公司（600519.SH）'
    html = html_report(report)
    assert 'ev-' not in html and '内部限制说明' not in html and '来源及证据' not in html
    assert '1,476.94亿元' in html and '<b>公司为白酒龙头。</b>' in html
    assert '附录：财务报表' in html and '免责声明' in html


def test_charts_are_numbered_and_carry_a_source():
    view = present(report_with_facts())
    figures = view.figures()
    charts = [f for f in figures if isinstance(f, Chart)]
    assert charts and [c.label for c in charts] == [f'图{i + 1}' for i in range(len(charts))]
    titles = ' '.join(c.title for c in charts)
    assert '营业收入及增速' in titles and '分业务营业收入构成' in titles
    assert all(c.source for c in charts)
    revenue = next(c for c in charts if '营业收入及增速' in c.title)
    assert revenue.categories[-1] == '2026H1'
    assert round(revenue.series[1].values[-1], 2) == round((90703 / 89389 - 1) * 100, 2)


def test_appendix_statements_come_from_facts():
    view = present(report_with_facts())
    titles = [t.title for t in view.appendix]
    assert titles[0].startswith('资产负债表') and titles[-1] == '主要财务比率'
    income = dict((r[0], r[1:]) for r in view.appendix[1].rows)
    assert income['营业收入'] == ['147,694', '170,899', '168,838']
    assert '缺失' not in str(view.appendix)
    assert view.forecast_table.rows[0][0] == '营业收入（百万元）'


def test_chart_backends_render():
    chart = Chart('营业收入及增速', ['2024A', '2025A'], [Series('营业收入', [1709.0, 1688.4]), Series('增速', [15.7, -1.2], 'line', 'right')], unit='亿元', right_unit='%')
    assert chart.usable()
    assert to_svg(chart).startswith('<svg') and '营业收入' in to_svg(chart)
    stream = BytesIO()
    to_png(chart, stream)
    assert stream.getvalue()[:4] == b'\x89PNG'
    assert to_drawing(chart, 240).width == 240
    assert not Chart('空', ['2025A'], [Series('x', [None])]).usable()


def test_axis_ticks():
    assert nice_ticks(0, 1709)[-1] >= 1709 and nice_ticks(0, 1709)[0] == 0
    ticks = nice_ticks(91.2, 92.0, zero=False)
    assert ticks[0] > 80 and ticks[-1] < 100
    right = aligned_ticks(-1.2, 19.0, 4)
    assert len(right) == 5 and right[0] <= -1.2 and right[-1] >= 19.0


def test_helpers():
    assert ticker('A股:600519') == '600519.SH' and ticker('A股:002001') == '002001.SZ'
    assert clean('资产总额2024A298944.58百万元') == '资产总额2024A 2,989.45亿元'
    assert clean('应收账款0.57百万元') == '应收账款57.00万元'


def test_mock_report_still_renders_without_facts():
    report = mock_report('示例公司')
    report.sections[2] = ReportSection(section_id='company', title='一、公司简介', paragraphs=['示例。'])
    view = present(report)
    assert view.forecast_table is None and view.appendix
    assert '一、公司情况' in html_report(report)
