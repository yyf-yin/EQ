"""Generic forecast: every assumption the three-statement engine needs, derived from history.

Used when evidence-based assumptions cannot be planned (missing opening items, model
failure, incomplete scenario/year coverage), so a report always carries a forecast.
Each assumption names its historical basis in `rationale` and cites the facts it was
computed from. The method is deliberately plain and stated in the report:

- segment revenue grows at g: the first year blends the latest interim growth (60%) with
  the average of last-year growth and the multi-year CAGR (40%); later years fade
  linearly toward half the CAGR, kept within -2%…8%. Bear/Bull move g by ±5 points.
- segment cost = revenue × the segment's recent-weighted cost ratio (Bear +1 point,
  Bull −1 point). Revenue the segment table does not cover is forecast as 其他业务.
- one comprehensive expense ratio is calibrated so EBIT equals historical pretax profit
  (it absorbs taxes and surcharges, period expenses, other income and net finance
  income); ratios average the last three years weighted 0.2/0.3/0.5 toward the latest;
  working-capital ratios, payout and minority share use the latest year; capex and depreciation scale with revenue; debt is held flat.
- the target PE is the peers' median consensus PE for that year, else the company's
  own consensus PE, else the industry's trailing PE.
"""

from decimal import Decimal

from ..schemas import ForecastAssumption
from .formulas import FinancialDataProcessor, FinancialError

OTHER_SEGMENT = '其他业务'
COMPANY_SEGMENT = '公司整体'
SPREAD_GROWTH = Decimal('0.05')
SPREAD_COST = Decimal('0.01')
DEBT_PARTS = ['debt', 'short_term_borrowings', 'long_term_borrowings', 'bonds_payable', 'lease_liabilities']


def D(value):
    return Decimal(str(value))


def clamp(value, low, high):
    return max(D(low), min(D(high), value))


class History:
    def __init__(self, facts, company_id):
        self.facts, self.company = facts, company_id
        self.processor = FinancialDataProcessor()

    def fact(self, metric, period, unit='CNY_million', segment=None):
        try:
            return self.processor.get(
                self.facts, self.company, metric, period, unit,
                segment_id=segment, scope='segment' if segment else 'consolidated',
            )
        except FinancialError:
            return None

    def value(self, metric, period, unit='CNY_million', segment=None):
        f = self.fact(metric, period, unit, segment)
        return f.value if f else None

    def evidence(self, *pairs):
        ids = []
        for metric, period, *rest in pairs:
            f = self.fact(metric, period, *(rest or []))
            if f and f.evidence_id not in ids:
                ids.append(f.evidence_id)
        return ids


def recent_weighted(values):
    """Average of up to the last three yearly values, weighting the latest most (0.2/0.3/0.5)."""
    values = [v for v in values if v is not None][-3:]
    if not values:
        return None
    weights = [D('0.2'), D('0.3'), D('0.5')][-len(values):]
    return sum(v * w for v, w in zip(values, weights)) / sum(weights)


def growth_path(series, interim, years):
    """Annual growth rates for the forecast years from a revenue history (oldest first)."""
    values = [v for v in series if v is not None and v > 0]
    if len(values) < 2:
        base = interim if interim is not None else D(0)
        cagr = base
    else:
        last = values[-1] / values[-2] - 1
        cagr = (values[-1] / values[0]) ** (D(1) / (len(values) - 1)) - 1 if len(values) > 2 else last
        base = (last + cagr) / 2
        if interim is not None:
            base = interim * D('0.6') + base * D('0.4')
    first = clamp(base, '-0.3', '0.6')
    long_run = clamp(cagr / 2, '-0.02', '0.08')
    n = len(years)
    return [first + (long_run - first) * D(i) / D(max(n - 1, 1)) for i in range(n)]


def plan(facts, company_id, brief, market=None, market_evidence=None):
    """Segments, opening balance and assumptions for Bear/Base/Bull over the forecast years."""
    h = History(facts, company_id)
    years = sorted(brief['historical_periods'])
    anchor = years[-1]
    prior = str(int(anchor[:4]) - 1) + 'A'
    annual = [str(int(anchor[:4]) - k) + 'A' for k in range(4, -1, -1)]
    forecast_years = sorted(brief['forecast_periods'])
    interim = brief.get('interim_period')
    interim_prev = str(int(interim[:4]) - 1) + interim[4:] if interim else None
    notes = []

    revenue = h.value('revenue', anchor)
    cost = h.value('cost', anchor)
    if revenue is None or cost is None or revenue <= 0:
        raise FinancialError('通用预测缺少最新年度营业收入或营业成本')

    # Segments: those with revenue and cost in the anchor year, plus the uncovered remainder.
    segments = [s for s in brief.get('segments') or [] if h.value('revenue', anchor, segment=s) and h.value('cost', anchor, segment=s) is not None]
    covered = sum((h.value('revenue', anchor, segment=s) for s in segments), D(0))
    if segments and covered > revenue * D('1.000001'):
        notes.append('分业务收入合计超过合并营业收入，改按公司整体预测')
        segments = []
    history = {}
    for s in segments:
        history[s] = {
            p: (h.value('revenue', p, segment=s), h.value('cost', p, segment=s)) for p in annual
        }
    if segments:
        rest_rev = revenue - covered
        rest_cost = cost - sum((h.value('cost', anchor, segment=s) for s in segments), D(0))
        if rest_rev > revenue * D('0.0005'):
            segments.append(OTHER_SEGMENT)
            history[OTHER_SEGMENT] = {anchor: (rest_rev, rest_cost)}
    else:
        segments = [COMPANY_SEGMENT]
        history[COMPANY_SEGMENT] = {p: (h.value('revenue', p), h.value('cost', p)) for p in annual}

    def interim_growth(segment):
        if not interim:
            return None
        key = None if segment in (COMPANY_SEGMENT, OTHER_SEGMENT) else segment
        now, before = h.value('revenue', interim, segment=key), h.value('revenue', interim_prev, segment=key)
        return now / before - 1 if now is not None and before not in (None, 0) else None

    company_series = [h.value('revenue', p) for p in annual]
    paths, cost_ratios = {}, {}
    for s in segments:
        if s == OTHER_SEGMENT:
            paths[s] = growth_path(company_series, interim_growth(s), forecast_years)
            rev, cst = history[s][anchor]
            cost_ratios[s] = clamp(cst / rev, '0', '1.5')
            continue
        series = [history[s].get(p, (None, None))[0] for p in annual]
        paths[s] = growth_path(series, interim_growth(s), forecast_years)
        ratios = [c / r if r and c is not None else None for r, c in (history[s].get(p, (None, None)) for p in annual[-3:])]
        cost_ratios[s] = clamp(recent_weighted(ratios), '0', '1.5')

    def averaged(numerator, denominator, periods=annual[-3:], low='0', high='1'):
        pairs = [(h.value(numerator, p), h.value(denominator, p)) for p in periods]
        value = recent_weighted([a / b if a is not None and b not in (None, 0) else None for a, b in pairs])
        return clamp(value, low, high) if value is not None else None

    company_cost = averaged('cost', 'revenue')
    gross = [(h.value('revenue', p), h.value('cost', p), h.value('pretax_profit', p)) for p in annual[-3:]]
    opex_samples = [(r - c - t) / r if None not in (r, c, t) and r else None for r, c, t in gross]
    if any(v is not None for v in opex_samples):
        opex = clamp(recent_weighted(opex_samples), '0', '1')
    else:
        parts = ['taxes_surcharges', 'selling_expense', 'administrative_expense', 'research_expense', 'finance_expense']
        total = sum((h.value(m, anchor) or D(0) for m in parts), D(0))
        opex = clamp(total / revenue, '0', '1')
        notes.append('缺少利润总额，综合费用率按税金及附加与期间费用合计估计')
    tax = averaged('income_tax_expense', 'pretax_profit', high='0.5')
    if tax is None:
        tax = D('0.25')
        notes.append('缺少所得税与利润总额，所得税率按 25% 估计')
    receivables_ratio = clamp((h.value('receivables', anchor) or D(0)) / revenue, '0', '10')
    inventory_ratio = clamp((h.value('inventory', anchor) or D(0)) / cost, '0', '10') if cost else D(0)
    payables_ratio = clamp((h.value('payables', anchor) or D(0)) / cost, '0', '10') if cost else D(0)
    dividends, last_profit = h.value('dividend_interest_cash_paid', anchor), h.value('parent_net_income', prior)
    payout = clamp(dividends / last_profit, '0', '1') if dividends is not None and last_profit else D('0.3')
    depreciation_parts = ['depreciation_ppe', 'depreciation_rou', 'amortization_intangibles', 'amortization_long_term']
    depreciation = sum((h.value(m, anchor) or D(0) for m in depreciation_parts), D(0))
    capex_values = [h.value('purchase_long_lived_assets_cash', p) for p in annual[-3:]]
    capex_values = [v for v in capex_values if v is not None]
    capex = sum(capex_values, D(0)) / len(capex_values) if capex_values else depreciation
    parent, eps = h.value('parent_net_income', anchor), h.value('basic_eps_reported', anchor, 'CNY/share')
    if not parent or not eps:
        raise FinancialError('通用预测缺少最新年度归母净利润或基本每股收益，无法确定股本')
    shares = (parent / eps).quantize(D('0.01'))
    net = h.value('net_income', anchor)
    minority = h.value('minority_net_income', anchor)
    minority_ratio = clamp(minority / net, '0', '0.99') if minority and net else None

    # Opening balance: debt is what the balance sheet lists (zero when it lists none);
    # the two "other" lines close the accounting identity rather than plug a forecast.
    opening, refs = {}, {}
    for key in ['cash', 'receivables', 'inventory', 'ppe', 'payables', 'equity', 'assets']:
        f = h.fact(key, anchor)
        if f is None and key in ('cash', 'ppe', 'equity', 'assets'):
            raise FinancialError(f'通用预测缺少期初 {key}')
        opening[key] = f.value if f else D(0)
        refs[key] = f.fact_id if f else 'derived:zero'
    debt_fact = h.fact('debt', anchor)
    if debt_fact:
        opening['debt'], refs['debt'] = debt_fact.value, debt_fact.fact_id
    else:
        listed = [f for m in DEBT_PARTS[1:] if (f := h.fact(m, anchor))]
        opening['debt'] = sum((f.value for f in listed), D(0))
        refs['debt'] = 'derived:listed-debt'
        notes.append('有息负债按资产负债表列示的借款、债券与租赁负债合计；未列示视为零')
    assets = opening.pop('assets')
    opening['other_assets'] = assets - opening['cash'] - opening['receivables'] - opening['inventory'] - opening['ppe']
    opening['other_liabilities'] = assets - opening['equity'] - opening['payables'] - opening['debt']
    refs['other_assets'] = refs['other_liabilities'] = 'derived:balance-identity'
    interest = h.value('interest_expense', anchor)
    rate = clamp(interest / opening['debt'], '0', '0.15') if interest and opening['debt'] > 0 else D(0)

    previous = {s: str(history[s][anchor][0]) for s in segments}
    previous_refs = {}
    for s in segments:
        f = h.fact('revenue', anchor, segment=None if s in (COMPANY_SEGMENT, OTHER_SEGMENT) else s)
        previous_refs[s] = (f.fact_id if f and s != OTHER_SEGMENT else 'derived:other-business-revenue')

    base_evidence = h.evidence(('revenue', anchor), ('cost', anchor), ('pretax_profit', anchor), ('parent_net_income', anchor))
    segment_evidence = {
        s: (h.evidence(('revenue', anchor, 'CNY_million', s), ('cost', anchor, 'CNY_million', s)) or base_evidence)
        if s not in (COMPANY_SEGMENT, OTHER_SEGMENT)
        else base_evidence
        for s in segments
    }

    def target_pe(year):
        if not market:
            return None, None
        from ..market_data import pe, peer_forward_pe

        label = year[:4] + 'E'
        value = peer_forward_pe(market, label)
        if value:
            return D(round(value, 2)), f'可比公司 {label} 一致预期 PE 中位数'
        company = market.get('company') or {}
        own = pe(company.get('price'), (company.get('eps') or {}).get(label))
        if own:
            return D(round(own, 2)), f'公司 {label} 一致预期 PE'
        industry = (market.get('industry_valuation') or {}).get('pe_ttm')
        if industry:
            return D(round(industry, 2)), '申万行业 TTM 市盈率'
        return None, None

    assumptions = []
    revenue_path = {}
    for scenario, shift, cost_shift in [('Bear', -SPREAD_GROWTH, SPREAD_COST), ('Base', D(0), D(0)), ('Bull', SPREAD_GROWTH, -SPREAD_COST)]:
        level = {s: D(previous[s]) for s in segments}
        for i, year in enumerate(forecast_years):
            for s in segments:
                g = paths[s][i] + shift
                level[s] = level[s] * (1 + g)
                assumptions.append(ForecastAssumption(
                    metric_code='growth_rate', period=year, value=g.quantize(D('0.0001')), unit='ratio', scenario=scenario,
                    segment_id=s, evidence_ids=segment_evidence[s],
                    rationale=f'历史趋势模型：近一年增速与多年复合增速平均，结合最新中期增速，逐年向长期增速收敛（情景偏移 {shift * 100:+.0f} 个百分点）',
                ))
                assumptions.append(ForecastAssumption(
                    metric_code='cost_ratio', period=year, value=clamp(cost_ratios[s] + cost_shift, '0', '1.5').quantize(D('0.0001')),
                    unit='ratio', scenario=scenario, segment_id=s, evidence_ids=segment_evidence[s],
                    rationale='历史趋势模型：近三年该业务营业成本占收入比例的平均值',
                ))
            scale = sum(level.values(), D(0)) / revenue
            revenue_path[(scenario, year)] = scale
            pe_value, pe_basis = target_pe(year)
            company_level = {
                'cost_ratio': (clamp((company_cost or cost / revenue) + cost_shift, '0', '1'), '近三年营业成本占营业收入比例（近年权重更高）'),
                'opex_ratio': (opex, '综合费用率：按近三年（营业收入−营业成本−利润总额）/营业收入加权校准，含税金及附加、期间费用与其他损益'),
                'tax_rate': (tax, '近三年所得税费用/利润总额（近年权重更高）'),
                'depreciation': ((depreciation * scale).quantize(D('0.01')), '最新年度折旧摊销合计，按收入规模同比例调整'),
                'capex': ((capex * scale).quantize(D('0.01')), '近三年购建长期资产支付现金的平均值，按收入规模同比例调整'),
                'receivables_ratio': (receivables_ratio, '最新年末应收账款/营业收入'),
                'inventory_ratio': (inventory_ratio, '最新年末存货/营业成本'),
                'payables_ratio': (payables_ratio, '最新年末应付账款/营业成本'),
                'borrowing': (D(0), '有息负债维持期初规模'),
                'repayment': (D(0), '有息负债维持期初规模'),
                'interest_rate': (rate, '最新年度利息费用/有息负债'),
                'payout_ratio': (payout, '最新年度分配股利、利润或偿付利息支付的现金/上年归母净利润'),
                'shares': (shares, '最新年度归母净利润/基本每股收益'),
                'target_pe': (pe_value if pe_value is not None else D(0), pe_basis or '无可用市场估值数据，不给目标价'),
            }
            if minority_ratio is not None:
                company_level['minority_ratio'] = (minority_ratio, '最新年度少数股东损益/净利润')
            for metric, (value, rationale) in company_level.items():
                evidence = list(market_evidence or []) if metric == 'target_pe' and pe_value is not None else base_evidence
                assumptions.append(ForecastAssumption(
                    metric_code=metric, period=year, value=D(value).quantize(D('0.0001')) if metric.endswith(('ratio', 'rate')) else D(value),
                    unit='ratio' if metric.endswith(('_ratio', '_rate')) else 'million_shares' if metric == 'shares' else 'times' if metric == 'target_pe' else 'CNY_million',
                    scenario=scenario, evidence_ids=evidence or base_evidence, rationale='历史趋势模型：' + rationale,
                ))
    return {
        'segments': segments,
        'models': {s: 'growth' for s in segments},
        'previous': previous,
        'previous_refs': previous_refs,
        'opening': {k: str(v) for k, v in opening.items()},
        'opening_refs': refs,
        'assumptions': assumptions,
        'notes': notes,
    }
