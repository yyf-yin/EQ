"""Bullish valuation: historical PE anchor and leader premium, traceable and recomputable."""
from decimal import Decimal

from company_research.financials.formulas import Calculator
from company_research.schemas import ForecastAssumption
from company_research.valuation import bullish_valuation

HISTORY = {'metric': 'PE(TTM)', 'years': 3, 'start': '2023-10-23', 'end': '2026-10-20', 'days': 725,
           'median': 21.85, 'p25': 20.04, 'p75': 24.16, 'min': 17.66, 'max': 31.97}


def context(peer_pe='14.97', own_roe=17.95, peer_roes=(7.34, 16.57, 9.09, 5.54, 8.67)):
    eps = {s: Calculator().calculate('eps', {'net_income': Decimal(v), 'shares': Decimal('1253.73')}, period='2026E',
                                     unit='CNY/share', output_metric='eps', scenario=s)
           for s, v in (('Bear', '82806'), ('Base', '88217'), ('Bull', '93750'))}
    assumptions = [
        ForecastAssumption(assumption_id='pe', metric_code='target_pe', period='2026E', value=Decimal(peer_pe), unit='times',
                           scenario='Base', rationale='可比公司 2026E 一致预期 PE 中位数', evidence_ids=['ev-m']),
        ForecastAssumption(assumption_id='payout', metric_code='payout_ratio', period='2026E', value=Decimal('0.7798'),
                           unit='ratio', scenario='Base', rationale='分红率', evidence_ids=['ev-m']),
    ]
    return {
        'run_id': 'r', 'brief': {'forecast_periods': ['2026E', '2027E']}, 'market_evidence_ids': ['ev-m'],
        'market': {'as_of': '2026-10-20', 'company': {'price': 1331.88, 'roe': own_roe},
                   'peers': [{'roe': r} for r in peer_roes]},
        'calculations': [r.model_dump(mode='json') for r in eps.values()],
        'assumptions': [a.model_dump(mode='json') for a in assumptions],
    }


def values(calcs):
    return {(r.output_metric, r.scenario): round(float(r.value), 4) for r in calcs}


def test_multiple_averages_history_and_capped_leader_premium():
    assumptions, calcs = bullish_valuation(context(), HISTORY, ['ev-h'])
    v = values(calcs)
    assert v[('leader_pe', 'Base')] == round(14.97 * 1.5, 4)  # ROE edge 2.07x is capped at 1.5x
    assert v[('bullish_pe', 'Base')] == round((21.85 + 14.97 * 1.5) / 2, 4)
    assert v[('bullish_target_price', 'Base')] == round(88217 / 1253.73 * (21.85 + 22.455) / 2, 4)
    assert {s for m, s in v if m == 'bullish_target_price'} == {'Bear', 'Base', 'Bull'}
    assert round(v[('bullish_upside', 'Base')], 2) == 0.17 and round(v[('dividend_yield', 'Base')], 3) == 0.041
    assert {a.metric_code for a in assumptions} == {'historical_pe_median', 'company_roe', 'peer_roe_median', 'share_price'}
    assert all(a.evidence_ids for a in assumptions)
    assert all(Calculator().recompute(r) for r in calcs)
    # Deterministic records: a rerun of the writing stage adds nothing new.
    again = bullish_valuation(context(), HISTORY, ['ev-h'])
    assert [a.assumption_id for a in again[0]] == [a.assumption_id for a in assumptions]
    assert [r.result_id for r in again[1]] == [r.result_id for r in calcs]


def test_multiple_never_falls_below_peers_and_needs_an_anchor():
    low = dict(HISTORY, median=10.0)
    v = values(bullish_valuation(context(own_roe=5.0), low, ['ev-h'])[1])
    assert v[('leader_pe', 'Base')] == 14.97  # no ROE edge: no premium
    assert v[('bullish_pe', 'Base')] == 14.97  # average 12.49 floored at the peer PE
    only_history = values(bullish_valuation(context(peer_pe='0'), HISTORY, ['ev-h'])[1])
    assert only_history[('bullish_target_price', 'Base')] == round(88217 / 1253.73 * 21.85, 4)
    assert bullish_valuation(context(peer_pe='0'), None, []) == ([], [])


def test_bullish_table_shows_only_in_bullish_reports():
    from company_research.presentation import bullish_table
    from company_research.schemas import CalculationResult, ReportDocument

    c = context()
    assumptions, calcs = bullish_valuation(c, HISTORY, ['ev-h'])
    report = ReportDocument(
        title='t', company_id='A股:600519', mode='real', sections=[], sources=[],
        assumptions=[ForecastAssumption.model_validate(a) for a in c['assumptions']] + assumptions,
        calculations=[CalculationResult.model_validate(r) for r in c['calculations']] + calcs,
    )
    assert bullish_table(report) is None
    table = bullish_table(report.model_copy(update={'writing_style': 'bullish'}))
    rows = {r[0]: r[1] for r in table.rows}
    assert rows['历史估值中枢'] == '21.85 倍' and rows['龙头溢价 PE'] == '22.45 倍' and rows['看多目标市盈率'] == '22.15 倍'
    assert rows['看多目标价'].endswith('元') and rows['2026E 股息率（现价）'] == '4.12%'
