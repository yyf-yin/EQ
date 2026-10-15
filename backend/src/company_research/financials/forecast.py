from decimal import Decimal
from ..schemas import FinancialForecast, ForecastAssumption, CalculationResult
from .formulas import Calculator, FinancialError, D

OPENING_KEYS = {
    'cash',
    'receivables',
    'inventory',
    'ppe',
    'other_assets',
    'payables',
    'debt',
    'other_liabilities',
    'equity',
}
ASSUMPTION_KEYS = {
    'cost_ratio',
    'opex_ratio',
    'tax_rate',
    'depreciation',
    'capex',
    'receivables_ratio',
    'inventory_ratio',
    'payables_ratio',
    'borrowing',
    'repayment',
    'interest_rate',
    'payout_ratio',
    'shares',
    'target_pe',
}


def validate_opening(opening: dict[str, Decimal]):
    if set(opening) != OPENING_KEYS:
        raise FinancialError('期初资产负债表缺少字段或有未知字段')
    assets = sum(opening[k] for k in ['cash', 'receivables', 'inventory', 'ppe', 'other_assets'])
    liabilities = sum(opening[k] for k in ['payables', 'debt', 'other_liabilities'])
    if abs(assets - liabilities - opening['equity']) > D('.000001'):
        raise FinancialError('期初资产负债表不平衡，禁止用平衡项修正')


def validate_forecast(forecast: FinancialForecast, opening: dict[str, Decimal]) -> list[str]:
    errors = []
    b = forecast.balance
    c = forecast.cashflow
    i = forecast.income
    if abs(b['assets'] - b['liabilities'] - b['equity']) > D('.000001'):
        errors.append('资产负债表不平衡')
    if abs(b['cash'] - opening['cash'] - c['cfo'] - c['cfi'] - c['cff']) > D('.000001'):
        errors.append('期末现金与现金流不一致')
    if abs(sum(s['revenue'] for s in forecast.segments.values()) - i['revenue']) > D('.000001'):
        errors.append('分部收入合计不一致')
    if abs(sum(s['cost'] for s in forecast.segments.values()) - i['cost']) > D('.000001'):
        errors.append('分部成本合计不一致')
    if b['cash'] < 0:
        errors.append('现金为负，资金缺口需要有依据的融资假设')
    if b['ppe'] < 0 or b['debt'] < 0:
        errors.append('固定资产或债务为负')
    if forecast.period.endswith('A'):
        errors.append('预测被标为实际期间')
    return errors


class ForecastEngine:
    """Unlevered operating mechanics plus explicitly supplied financing decisions.

    No plug debt/cash/equity. Model uses consolidated net income (no minority stake).
    """

    def __init__(self):
        self.calculator = Calculator()

    def forecast(
        self,
        company_id: str,
        period: str,
        scenario: str,
        opening: dict[str, Decimal],
        segment_drivers: dict[str, dict],
        assumptions: list[ForecastAssumption],
        opening_refs: dict[str, str] | None = None,
    ) -> tuple[FinancialForecast, list[CalculationResult]]:
        opening = {k: D(str(v)) for k, v in opening.items()}
        validate_opening(opening)
        selected = [a for a in assumptions if a.period == period and a.scenario == scenario]
        global_assumptions = {a.metric_code: a for a in selected if a.segment_id is None}
        if not ASSUMPTION_KEYS.issubset(global_assumptions):
            raise FinancialError('预测假设缺失：' + ','.join(sorted(ASSUMPTION_KEYS - set(global_assumptions))))
        if any(not a.evidence_ids or not a.rationale for a in selected):
            raise FinancialError('预测假设缺少依据')
        values = {k: a.value for k, a in global_assumptions.items()}
        for k in [
            'cost_ratio',
            'opex_ratio',
            'tax_rate',
            'receivables_ratio',
            'inventory_ratio',
            'payables_ratio',
            'payout_ratio',
            'interest_rate',
        ]:
            if not 0 <= values[k] <= 1:
                raise FinancialError('比例假设越界 ' + k)
        if values['shares'] <= 0:
            raise FinancialError('股本必须为正')
        if any(values[k] < 0 for k in ['capex', 'depreciation', 'borrowing', 'repayment', 'target_pe']):
            raise FinancialError('假设必须非负')
        results = []
        refs = {}
        segments = {}

        def calc(metric, formula, inputs, unit='CNY_million', segment=None, input_refs=None):
            auto_refs = {}
            for k in inputs:
                if k in refs:
                    auto_refs[k] = refs[k]
                elif k in global_assumptions:
                    auto_refs[k] = global_assumptions[k].assumption_id
                elif k.startswith('opening_'):
                    auto_refs[k] = (opening_refs or {}).get(k[8:], 'opening:' + k[8:])
                elif k == 'operating_cashflow':
                    auto_refs[k] = refs['cfo']
                else:
                    auto_refs[k] = ''
            # Callers supply opening/fact/assumption refs where semantic keys differ.
            result = self.calculator.calculate(
                formula,
                inputs,
                period=period,
                unit=unit,
                output_metric=metric,
                input_refs=input_refs or auto_refs,
                scenario=scenario,
                segment_id=segment,
            )
            results.append(result)
            refs[metric] = result.result_id
            return result.value

        for segment, driver in segment_drivers.items():
            model = driver['model']
            parameters = {k: D(str(v)) for k, v in driver['inputs'].items()}
            revenue = calc(
                f'{segment}.revenue', model, parameters, segment=segment, input_refs=driver.get('input_refs', {})
            )
            cost_ratio = next(
                (a for a in selected if a.segment_id == segment and a.metric_code == 'cost_ratio'),
                global_assumptions['cost_ratio'],
            )
            cost = calc(
                f'{segment}.cost',
                'multiply',
                {'a': revenue, 'b': cost_ratio.value},
                segment=segment,
                input_refs={'a': refs[f'{segment}.revenue'], 'b': cost_ratio.assumption_id},
            )
            segments[segment] = {'revenue': revenue, 'cost': cost}
        if not segments:
            raise FinancialError('没有分部预测')

        def total(metric):
            pairs = [(s[metric], refs[f'{k}.{metric}']) for k, s in segments.items()]
            result, reference = pairs[0]
            for amount, ref in pairs[1:]:
                result = calc(metric, 'sum', {'a': result, 'b': amount}, input_refs={'a': reference, 'b': ref})
                reference = refs[metric]
            if len(pairs) == 1:
                result = calc(
                    metric, 'multiply', {'a': result, 'b': D(1)}, input_refs={'a': reference, 'b': 'constant:1'}
                )
            return result

        revenue, cost = total('revenue'), total('cost')
        opex = calc(
            'opex',
            'multiply',
            {'a': revenue, 'b': values['opex_ratio']},
            input_refs={'a': refs['revenue'], 'b': global_assumptions['opex_ratio'].assumption_id},
        )
        gross_profit = calc(
            'gross_profit', 'subtract', {'a': revenue, 'b': cost}, input_refs={'a': refs['revenue'], 'b': refs['cost']}
        )
        ebit = calc(
            'ebit',
            'subtract',
            {'a': gross_profit, 'b': opex},
            input_refs={'a': refs['gross_profit'], 'b': refs['opex']},
        )
        interest = calc(
            'interest',
            'interest',
            {
                'opening_debt': opening['debt'],
                'borrowing': values['borrowing'],
                'repayment': values['repayment'],
                'rate': values['interest_rate'],
            },
            input_refs={
                'opening_debt': (opening_refs or {}).get('debt', 'opening:debt'),
                'borrowing': global_assumptions['borrowing'].assumption_id,
                'repayment': global_assumptions['repayment'].assumption_id,
                'rate': global_assumptions['interest_rate'].assumption_id,
            },
        )
        pretax = calc(
            'pretax', 'subtract', {'a': ebit, 'b': interest}, input_refs={'a': refs['ebit'], 'b': refs['interest']}
        )
        tax = calc('tax', 'tax', {'pretax': pretax, 'tax_rate': values['tax_rate']})
        net_income = calc(
            'net_income', 'subtract', {'a': pretax, 'b': tax}, input_refs={'a': refs['pretax'], 'b': refs['tax']}
        )
        ebitda = calc(
            'ebitda',
            'sum',
            {'a': ebit, 'b': values['depreciation']},
            input_refs={'a': refs['ebit'], 'b': global_assumptions['depreciation'].assumption_id},
        )
        eps = calc('eps', 'eps', {'net_income': net_income, 'shares': values['shares']}, 'CNY/share')
        target_price = calc('target_price', 'target_price', {'eps': eps, 'target_pe': values['target_pe']}, 'CNY/share')
        next_balance = {'other_assets': opening['other_assets'], 'other_liabilities': opening['other_liabilities']}
        for field, base, key in [
            ('receivables', revenue, 'receivables_ratio'),
            ('inventory', cost, 'inventory_ratio'),
            ('payables', cost, 'payables_ratio'),
        ]:
            next_balance[field] = calc(
                field,
                'multiply',
                {'a': base, 'b': values[key]},
                input_refs={
                    'a': refs['revenue' if field == 'receivables' else 'cost'],
                    'b': global_assumptions[key].assumption_id,
                },
            )
        wc = calc(
            'working_capital',
            'subtract',
            {
                'a': calc(
                    'receivables_inventory',
                    'sum',
                    {'a': next_balance['receivables'], 'b': next_balance['inventory']},
                    input_refs={'a': refs['receivables'], 'b': refs['inventory']},
                ),
                'b': next_balance['payables'],
            },
            input_refs={'a': refs['receivables_inventory'], 'b': refs['payables']},
        )
        opening_ri = calc(
            'opening_receivables_inventory',
            'sum',
            {'a': opening['receivables'], 'b': opening['inventory']},
            input_refs={
                'a': (opening_refs or {}).get('receivables', 'opening:receivables'),
                'b': (opening_refs or {}).get('inventory', 'opening:inventory'),
            },
        )
        opening_wc = calc(
            'opening_working_capital',
            'subtract',
            {'a': opening_ri, 'b': opening['payables']},
            input_refs={
                'a': refs['opening_receivables_inventory'],
                'b': (opening_refs or {}).get('payables', 'opening:payables'),
            },
        )
        delta_wc = calc(
            'delta_working_capital',
            'subtract',
            {'a': wc, 'b': opening_wc},
            input_refs={'a': refs['working_capital'], 'b': refs['opening_working_capital']},
        )
        dividends = calc(
            'dividends',
            'multiply',
            {'a': max(net_income, D(0)), 'b': values['payout_ratio']},
            input_refs={'a': refs['net_income'], 'b': global_assumptions['payout_ratio'].assumption_id},
        )
        cfo = calc(
            'cfo',
            'cfo',
            {'net_income': net_income, 'depreciation': values['depreciation'], 'delta_working_capital': delta_wc},
        )
        cfi = calc(
            'cfi',
            'multiply',
            {'a': values['capex'], 'b': D(-1)},
            input_refs={'a': global_assumptions['capex'].assumption_id, 'b': 'constant:-1'},
        )
        cff = calc(
            'cff', 'cff', {'borrowing': values['borrowing'], 'repayment': values['repayment'], 'dividends': dividends}
        )
        next_balance['cash'] = calc(
            'cash',
            'closing_cash',
            {'opening_cash': opening['cash'], 'cfo': cfo, 'cfi': cfi, 'cff': cff},
            input_refs={
                'opening_cash': (opening_refs or {}).get('cash', 'opening:cash'),
                'cfo': refs['cfo'],
                'cfi': refs['cfi'],
                'cff': refs['cff'],
            },
        )
        next_balance['ppe'] = calc(
            'ppe',
            'closing_ppe',
            {'opening_ppe': opening['ppe'], 'capex': values['capex'], 'depreciation': values['depreciation']},
        )
        next_balance['debt'] = calc(
            'debt',
            'closing_debt',
            {'opening_debt': opening['debt'], 'borrowing': values['borrowing'], 'repayment': values['repayment']},
        )
        next_balance['equity'] = calc(
            'equity',
            'closing_equity',
            {'opening_equity': opening['equity'], 'net_income': net_income, 'dividends': dividends},
        )

        def balance_total(metric, keys):
            value = next_balance[keys[0]]
            reference = refs.get(keys[0], (opening_refs or {}).get(keys[0], 'opening:' + keys[0]))
            for k in keys[1:]:
                value = calc(
                    metric,
                    'sum',
                    {'a': value, 'b': next_balance[k]},
                    input_refs={'a': reference, 'b': refs.get(k, (opening_refs or {}).get(k, 'opening:' + k))},
                )
                reference = refs[metric]
            return value

        next_balance['assets'] = balance_total('assets', ['cash', 'receivables', 'inventory', 'ppe', 'other_assets'])
        next_balance['liabilities'] = balance_total('liabilities', ['payables', 'debt', 'other_liabilities'])
        fcf = calc('fcf', 'fcf', {'operating_cashflow': cfo, 'capex': values['capex']})
        forecast = FinancialForecast(
            company_id=company_id,
            period=period,
            scenario=scenario,
            income={
                'revenue': revenue,
                'cost': cost,
                'gross_profit': gross_profit,
                'opex': opex,
                'ebit': ebit,
                'interest': interest,
                'pretax': pretax,
                'tax': tax,
                'net_income': net_income,
                'depreciation': values['depreciation'],
                'ebitda': ebitda,
                'eps': eps,
                'target_price': target_price,
            },
            balance=next_balance,
            cashflow={
                'cfo': cfo,
                'cfi': cfi,
                'cff': cff,
                'capex': values['capex'],
                'delta_working_capital': delta_wc,
                'dividends': dividends,
                'fcf': fcf,
            },
            segments=segments,
            result_ids=[r.result_id for r in results],
            assumption_ids=[a.assumption_id for a in selected],
        )
        errors = validate_forecast(forecast, opening)
        if errors:
            raise FinancialError('；'.join(errors))
        return forecast, results
