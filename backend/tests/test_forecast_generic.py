"""Segment table parsing, the generic historical-trend forecast, market snapshot and forecast tables."""
import sys
import types
from datetime import date
from decimal import Decimal

import pandas as pd

from company_research.financials.forecast import ASSUMPTION_KEYS, ForecastEngine
from company_research.financials.formulas import Calculator
from company_research.financials.generic import OTHER_SEGMENT, growth_path, plan
from company_research.market_data import peer_forward_pe, snapshot, summary
from company_research.presentation import comps_table, segment_split_table, valuation_paragraph, FactBook
from company_research.reports import mock_report
from company_research.schemas import FinancialFact, ResearchBrief
from company_research.standard_tables import match_segment, product_rows

TABLE_2025 = '''单位：元 币种：人民币
主营业务分行业情况
酒类 168,774,585,187.65 14,805,900,139.59 91.23 -1.08 8.63 减少 0.78 个百
分点
主营业务分产品情况
分产品 营业收入 营业成本 毛利率（%） 营业收入比上
年增减（%）
茅台酒 146,499,906,480.49 9,484,757,825.54 93.53 0.39 9.50 减少 0.53 个百
分点
其他系列酒 22,274,678,707.16 5,321,142,314.05 76.11 -9.76 7.11 减少 3.76 个百
分点
主营业务分地区情况
国内 163,924,442,864.97 14,402,942,526.84 91.21 -0.91 8.89 减少 0.79 个百
'''
TABLE_2021 = '''单位：元 币种：人民币
分产品情况
分产品 营业收入 营业成本 毛利率
（%）
茅台酒 93,464,512,115.94 5,577,910,539.00 94.03 10.18 9.36 增加 0.04 个百分点
其他系列
酒
12,594,778,226.24 3,313,079,971.72 73.69 26.06 11.06 增加 3.55 个百分点
其他系
列酒 1,000.00 999.00 50.00 1 1
主营业务分地区情况
'''


def test_product_table_is_read_with_wrapped_names_and_margin_check():
    rows = product_rows(TABLE_2025)
    assert [(r['name'], r['revenue'], r['unit']) for r in rows] == [
        ('茅台酒', '146,499,906,480.49', '元'),
        ('其他系列酒', '22,274,678,707.16', '元'),
    ]
    assert rows[1]['quote'] in TABLE_2025
    old = product_rows(TABLE_2021)
    # The last row prints a margin that does not match its revenue and cost, so it is rejected.
    assert [r['name'] for r in old] == ['茅台酒', '其他系列酒']
    assert match_segment('其他系列酒', ['茅台酒', '其他系列酒']) == '其他系列酒'
    assert match_segment('酒', ['茅台酒', '其他系列酒']) is None


def fact(metric, period, value, segment=None, unit='CNY_million'):
    return FinancialFact(
        fact_id=f'fact-{metric}-{period}-{segment}', company_id='A股:600519', metric_code=metric, period=period, unit=unit,
        value=Decimal(str(value)), actual_or_forecast='actual', scope='segment' if segment else 'consolidated',
        segment_id=segment, source_id='s', evidence_id=f'ev-{metric}', locator='page:1', validation_status='verified',
    )


def history():
    facts = []
    years = ['2022A', '2023A', '2024A', '2025A']
    series = {
        'revenue': [124100, 147694, 170899, 168838], 'cost': [10093, 11867, 13789, 14892],
        'pretax_profit': [87700, 103663, 119639, 114755], 'income_tax_expense': [22325, 26141, 30304, 29445],
        'net_income': [65375, 77521, 89335, 85310], 'parent_net_income': [62716, 74734, 86228, 82320],
        'minority_net_income': [2659, 2787, 3107, 2990], 'cash': [58274, 69070, 59296, 51691],
        'receivables': [20, 60, 19, 3], 'inventory': [38824, 46435, 54343, 61427], 'ppe': [19743, 19909, 21871, 22488],
        'payables': [2408, 3093, 3515, 4007], 'assets': [254365, 272700, 298945, 303835],
        'liabilities': [49036, 49043, 56933, 49876], 'equity': [205329, 223657, 242012, 253959],
        'purchase_long_lived_assets_cash': [5307, 2620, 4679, 3128], 'depreciation_ppe': [1500, 1700, 1800, 2000],
        'dividend_interest_cash_paid': [56000, 58755, 70951, 67242],
    }
    for metric, values in series.items():
        facts += [fact(metric, y, v) for y, v in zip(years, values)]
    facts += [fact('basic_eps_reported', y, v, unit='CNY/share') for y, v in zip(years, [49.93, 59.49, 68.64, 65.66])]
    # 2025A segments leave about 4% of revenue uncovered, forecast as 其他业务.
    for segment, revenue, cost in [('茅台酒', [107834, 126589, 145928, 140000], [6266, 7445, 8662, 9000]),
                                   ('其他系列酒', [15939, 20630, 24684, 22275], [3630, 4175, 4968, 5321])]:
        facts += [fact('revenue', y, v, segment) for y, v in zip(years, revenue)]
        facts += [fact('cost', y, v, segment) for y, v in zip(years, cost)]
    facts += [fact('revenue', '2026H1', 90703), fact('revenue', '2025H1', 89389)]
    return facts


BRIEF = {'historical_periods': ['2023A', '2024A', '2025A'], 'forecast_periods': ['2026E', '2027E', '2028E'],
         'segments': ['茅台酒', '其他系列酒'], 'interim_period': '2026H1'}
MARKET = {
    'as_of': '2026-10-16', 'industry': '白酒Ⅲ', 'industry_valuation': {'pe_ttm': 20.0},
    'company': {'code': '600519', 'name': '贵州茅台', 'price': 1329.0, 'market_cap': 16563.2, 'pe_ttm': 20.3,
                'eps': {'2025A': 65.66, '2026E': 67.16, '2027E': 71.08}},
    'peers': [
        {'code': '000858', 'name': '五粮液', 'price': 72.07, 'market_cap': 2826.6, 'pe_ttm': 21.6, 'eps': {'2026E': 3.91, '2027E': 4.36}},
        {'code': '600809', 'name': '山西汾酒', 'price': 116.7, 'market_cap': 1451.8, 'pe_ttm': 14.3, 'eps': {'2026E': 8.5, '2027E': 9.22}},
        {'code': '000568', 'name': '泸州老窖', 'price': 71.94, 'market_cap': 1069.2, 'pe_ttm': 14.2, 'eps': {'2026E': 5.37}},
    ],
}


def roll(result):
    opening = {k: Decimal(v) for k, v in result['opening'].items()}
    forecasts = []
    for scenario in ['Bear', 'Base', 'Bull']:
        balance, prev = dict(opening), {s: Decimal(v) for s, v in result['previous'].items()}
        for year in BRIEF['forecast_periods']:
            drivers = {s: {'model': 'growth', 'inputs': {'previous': prev[s], 'growth_rate': next(
                a.value for a in result['assumptions'] if (a.scenario, a.period, a.segment_id, a.metric_code) == (scenario, year, s, 'growth_rate'))}}
                for s in result['segments']}
            f, _ = ForecastEngine().forecast('A股:600519', year, scenario, balance, drivers, result['assumptions'])
            forecasts.append(f)
            balance, prev = {k: f.balance[k] for k in opening}, {s: v['revenue'] for s, v in f.segments.items()}
    return forecasts


def test_generic_plan_covers_every_scenario_and_rolls_the_engine():
    result = plan(history(), 'A股:600519', BRIEF, MARKET, ['ev-market'])
    assert result['segments'] == ['茅台酒', '其他系列酒', OTHER_SEGMENT]
    for scenario in ['Bear', 'Base', 'Bull']:
        for year in BRIEF['forecast_periods']:
            keys = {a.metric_code for a in result['assumptions'] if a.scenario == scenario and a.period == year and a.segment_id is None}
            assert ASSUMPTION_KEYS | {'minority_ratio'} <= keys
    assert all(a.evidence_ids and a.rationale for a in result['assumptions'])
    # No borrowings in the facts: debt opens at zero and the identity closes on the "other" lines.
    assert Decimal(result['opening']['debt']) == 0 and any('有息负债' in n for n in result['notes'])
    # Derived opening items and 其他业务 revenue trace to facts through recomputable calculations.
    facts = {f.fact_id: f for f in history()}
    calcs = {r.result_id: r for r in result['calculations']}
    refs = list(result['opening_refs'].values()) + list(result['previous_refs'].values())
    refs += [r for c in calcs.values() for r in c.input_refs.values()]
    assert all(r in facts or r in calcs or r.startswith('constant:') for r in refs)
    assert all(Calculator().recompute(c) for c in calcs.values())
    other = calcs[result['previous_refs'][OTHER_SEGMENT]]
    assert other.value == Decimal(168838 - 140000 - 22275) == Decimal(result['previous'][OTHER_SEGMENT])
    forecasts = roll(result)
    base = [f for f in forecasts if f.scenario == 'Base']
    bear = next(f for f in forecasts if f.scenario == 'Bear' and f.period == '2026E')
    assert len(forecasts) == 9 and bear.income['revenue'] < base[0].income['revenue']
    assert all(f.income['eps'] > 0 for f in base)
    pe = next(a for a in result['assumptions'] if a.metric_code == 'target_pe' and a.period == '2026E')
    assert pe.evidence_ids == ['ev-market'] and abs(float(pe.value) - peer_forward_pe(MARKET, '2026E')) < 0.01


def test_growth_moves_from_recent_toward_the_long_run_rate():
    path = growth_path([Decimal(100), Decimal(120), Decimal(140), Decimal(141)], Decimal('0.02'), ['a', 'b', 'c'])
    cagr = (Decimal(141) / Decimal(100)) ** (Decimal(1) / 3) - 1
    assert path[-1] == cagr / 2 and path[0] < path[1] < path[-1]
    fast = growth_path([Decimal(100), Decimal(300)], None, ['a', 'b'])
    assert fast[0] == Decimal('0.6') and fast[-1] == Decimal('0.08')


def test_forecast_tables_read_like_a_broker_report():
    facts = history()
    result = plan(facts, 'A股:600519', BRIEF, MARKET, ['ev-market'])
    report = mock_report('贵州茅台')
    report.company_id = 'A股:600519'
    report.brief = ResearchBrief.model_validate(BRIEF | {'company_id': 'A股:600519', 'scope': 's', 'industries': {}, 'source_ids': [], 'as_of': '2026-10-18'})
    report.financial_facts = facts
    report.forecasts, report.assumptions, report.market, report.forecast_model = roll(result), result['assumptions'], MARKET, 'generic'
    split = segment_split_table(report, FactBook(report))
    names = [r[0] for i, r in enumerate(split.rows) if i in split.groups]
    assert names == ['茅台酒', '其他系列酒', OTHER_SEGMENT, '合计']
    assert split.columns[1:] == ['2023A', '2024A', '2025A', '2026E', '2027E', '2028E']
    assert split.rows[1][1:4] == ['126,589', '145,928', '140,000']
    comps = comps_table(report)
    assert [r[0] for r in comps.rows] == ['五粮液', '山西汾酒', '泸州老窖', '可比公司中位数', '贵州茅台（本公司）']
    text = valuation_paragraph(report)
    assert text.startswith('盈利预测与估值。我们预计公司2026—2028年归母净利润') and '目标价' in text and '1329.00元' in text


def test_market_snapshot_degrades_piece_by_piece(monkeypatch):
    fake = types.SimpleNamespace(
        stock_industry_change_cninfo=lambda **k: pd.DataFrame([{'分类标准': '申银万国行业分类标准', '变更日期': '2021-07-30', '行业中类': '白酒Ⅲ'}]),
        sw_index_third_info=lambda: pd.DataFrame([{'行业代码': '851251.SI', '行业名称': '白酒Ⅲ', '静态市盈率': 19.0, 'TTM(滚动)市盈率': 20.0, '市净率': 4.1}]),
        sw_index_third_cons=lambda symbol: pd.DataFrame([
            {'股票代码': '600519.SH', '股票简称': '贵州茅台', '市值': 16563.2, '市盈率': 20.2, '市盈率ttm': 20.3, '市净率': 6.6, 'ROE(%)': 18.0},
            {'股票代码': '000858.SZ', '股票简称': '五粮液', '市值': 2826.6, '市盈率': 31.6, '市盈率ttm': 21.6, '市净率': 2.4, 'ROE(%)': 7.3},
        ]),
        stock_zh_a_daily=lambda **k: pd.DataFrame([{'date': '2026-10-16', 'close': 1329.0}]),
        stock_financial_abstract_ths=lambda **k: pd.DataFrame([{'报告期': '2025', '基本每股收益': '65.66'}]),
        stock_profit_forecast_ths=lambda **k: (_ for _ in ()).throw(ConnectionError('down')),
    )
    monkeypatch.setitem(sys.modules, 'akshare', fake)
    data = snapshot('600519', date(2026, 10, 18), '2025', ['2026', '2027'])
    assert data['industry'] == '白酒Ⅲ' and data['as_of'] == '2026-10-16'
    assert data['company']['eps'] == {'2025A': 65.66} and [p['name'] for p in data['peers']] == ['五粮液']
    assert '可比公司 五粮液' in summary(data)
