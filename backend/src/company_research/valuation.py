"""Bullish valuation: the multiple a sell-side report argues for, kept traceable.

Used when the run chose the bullish writing style. The forecast's own target price
stays (comparable companies' median PE); this adds the multiple broker reports usually
give a leader, from two observable anchors:

- 历史估值中枢: the company's median daily PE(TTM) over the last three years;
- 龙头溢价: the comparable median PE scaled by the company's ROE over the peers'
  median ROE, between 1 and 1.5 times.

The bullish multiple is their average (or the one available), never below the
comparable median. Every input is a ForecastAssumption with evidence and every step a
registered calculation, so review recomputes it like the rest of the forecast. The
Base dividend yield at today's price is computed alongside as a cross-check."""

from decimal import Decimal

from .financials.formulas import Calculator, FinancialError
from .framework import digest
from .schemas import CalculationResult, ForecastAssumption

D = Decimal
HISTORY_YEARS = 3
METRICS = ('leader_pe', 'bullish_pe', 'bullish_target_price', 'bullish_upside', 'dps', 'dividend_yield')


def median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def bullish_valuation(c: dict, history: dict | None, history_evidence: list[str]) -> tuple[list, list]:
    """(assumptions, calculations) for the first forecast year; empty when no anchor exists."""
    year = min(c['brief']['forecast_periods'])
    calcs = [CalculationResult.model_validate(r) for r in c.get('calculations', [])]
    assumptions = [ForecastAssumption.model_validate(a) for a in c.get('assumptions', [])]
    eps = {r.scenario: r for r in calcs if r.output_metric == 'eps' and r.period == year and r.scenario != 'historical'}
    base = {a.metric_code: a for a in assumptions if a.scenario == 'Base' and a.period == year and not a.segment_id}
    market = c.get('market') or {}
    company = market.get('company') or {}
    market_evidence = list(c.get('market_evidence_ids') or [])
    if 'Base' not in eps:
        return [], []

    new = []

    def assume(metric, value, unit, rationale, evidence):
        a = ForecastAssumption(
            assumption_id='asm-bull-' + digest([c.get('run_id'), metric, year, str(value)])[:20],
            metric_code=metric, period=year, value=D(str(value)), unit=unit, scenario='Base',
            rationale='看多估值：' + rationale, evidence_ids=evidence,
        )
        new.append(a)
        return a

    out = []

    def calc(formula, inputs, unit, metric, scenario='Base'):
        r = Calculator().calculate(
            formula, {k: v.value for k, v in inputs.items()}, period=year, unit=unit, output_metric=metric,
            input_refs={k: getattr(v, 'assumption_id', None) or v.result_id for k, v in inputs.items()},
            scenario=scenario,
        )
        out.append(r)
        return r

    peer_pe = base.get('target_pe') if base.get('target_pe') and base['target_pe'].value > 0 else None
    anchors = []
    if history and history_evidence:
        anchors.append(assume(
            'historical_pe_median', history['median'], 'times',
            f'公司近{history["years"]}年{history["metric"]}中位数（{history["start"]}至{history["end"]}，'
            f'25%—75%分位 {history["p25"]:.2f}—{history["p75"]:.2f} 倍）',
            history_evidence,
        ))
    peer_roes = [p['roe'] for p in market.get('peers') or [] if p.get('roe') and p['roe'] > 0]
    if peer_pe and company.get('roe') and company['roe'] > 0 and len(peer_roes) >= 2 and market_evidence:
        own = assume('company_roe', round(company['roe'] / 100, 4), 'ratio', '公司 ROE（申万行业成份数据）', market_evidence)
        peers = assume('peer_roe_median', round(median(peer_roes) / 100, 4), 'ratio', '可比公司 ROE 中位数（申万行业成份数据）', market_evidence)
        anchors.append(calc('leader_pe', {'peer_pe': peer_pe, 'company_roe': own, 'peer_roe': peers}, 'times', 'leader_pe'))
    if not anchors:
        return [], []
    try:
        # Only the final multiple is named bullish_pe; the average before the floor is not.
        average = 'bullish_pe_average' if peer_pe else 'bullish_pe'
        multiple = anchors[0] if len(anchors) == 1 else calc('average', {'a': anchors[0], 'b': anchors[1]}, 'times', average)
        if peer_pe:
            multiple = calc('maximum', {'a': multiple, 'b': peer_pe}, 'times', 'bullish_pe')
        targets = {
            s: calc('target_price', {'eps': eps[s], 'target_pe': multiple}, 'CNY/share', 'bullish_target_price', s)
            for s in ('Bear', 'Base', 'Bull') if s in eps
        }
        if company.get('price') and market_evidence:
            price = assume('share_price', company['price'], 'CNY/share', f'{market.get("as_of") or "报告日"}收盘价', market_evidence)
            calc('yoy', {'current': targets['Base'], 'previous': price}, 'ratio', 'bullish_upside')
            payout = base.get('payout_ratio')
            if payout:
                dps = calc('multiply', {'a': eps['Base'], 'b': payout}, 'CNY/share', 'dps')
                calc('dividend_yield', {'dps': dps, 'price': price}, 'ratio', 'dividend_yield')
    except FinancialError:
        return [], []
    return new, out
