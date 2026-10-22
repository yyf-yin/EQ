from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Callable
from ..schemas import CalculationResult, RequiredData, CalculationPlan, FinancialFact

D = Decimal


class FinancialError(ValueError):
    pass


def ratio(a: Decimal, b: Decimal) -> Decimal:
    if b == 0:
        raise FinancialError('分母为零，指标不可用')
    return a / b


def cagr(start: Decimal, end: Decimal, years: Decimal) -> Decimal:
    if start <= 0 or end <= 0 or years <= 0:
        raise FinancialError('CAGR 要求正起点、终点和年数')
    with localcontext() as context:
        context.prec = 34
        return (end / start) ** (D(1) / years) - 1


@dataclass(frozen=True)
class Formula:
    id: str
    inputs: tuple[str, ...]
    function: Callable[..., Decimal]
    unit: str
    version: str = '1.0'
    description: str = ''


REGISTRY: dict[str, Formula] = {}


def register(id: str, inputs: str, fn: Callable, unit='ratio', description=''):
    REGISTRY[id] = Formula(id, tuple(inputs.split()), fn, unit, description=description)


register('yoy', 'current previous', lambda a, b: ratio(a, b) - 1)
register('comparison_delta', 'current previous', lambda a, b: a - b, 'dynamic')
register('percentage_points', 'current previous', lambda a, b: (a - b) * 100, 'percentage_points')
register('cagr', 'start end years', cagr)
register('gross_margin', 'revenue cost', lambda r, c: ratio(r - c, r))
register('segment_share', 'segment_revenue total_revenue', ratio)
register('net_margin', 'net_income revenue', ratio)
register('operating_margin', 'ebit revenue', ratio)
register(
    'roe',
    'net_income average_equity',
    lambda n, e: ratio(n, e) if e > 0 else (_ for _ in ()).throw(FinancialError('非正平均权益时 ROE 不适用')),
)
register(
    'roic',
    'ebit tax_rate average_invested_capital',
    lambda e, t, c: (
        ratio(e * (1 - t), c) if c > 0 else (_ for _ in ()).throw(FinancialError('非正投入资本时 ROIC 不适用'))
    ),
)
register('debt_to_assets', 'liabilities assets', ratio)
register('current_ratio', 'current_assets current_liabilities', ratio, 'times')
register('quick_ratio', 'current_assets inventory current_liabilities', lambda a, i, l: ratio(a - i, l), 'times')
register('inventory_turnover', 'cost average_inventory', ratio, 'times')
register('receivables_turnover', 'revenue average_receivables', ratio, 'times')
register('asset_turnover', 'revenue average_assets', ratio, 'times')
register('fcf', 'operating_cashflow capex', lambda c, x: c - x, 'CNY_million')
register('eps', 'net_income shares', ratio, 'CNY/share')
register(
    'pe',
    'price eps',
    lambda p, e: ratio(p, e) if e > 0 else (_ for _ in ()).throw(FinancialError('亏损时 PE 无意义')),
    'times',
)
register(
    'pb',
    'price shares equity',
    lambda p, s, e: ratio(p * s, e) if e > 0 else (_ for _ in ()).throw(FinancialError('非正权益时 PB 不适用')),
    'times',
)
register('ev_ebitda', 'price shares debt cash ebitda', lambda p, s, d, c, e: ratio(p * s + d - c, e), 'times')
register('volume_price', 'volume price', lambda q, p: q * p, 'CNY_million')
register('capacity_utilization', 'capacity utilization price', lambda c, u, p: c * u * p, 'CNY_million')
register('users_arpu', 'users arpu', lambda u, a: u * a, 'CNY_million')
register('market_share', 'market_size share', lambda m, s: m * s, 'CNY_million')
register('growth', 'previous growth_rate', lambda p, g: p * (1 + g), 'CNY_million')
register('multiply', 'a b', lambda a, b: a * b, 'dynamic')
register('sum', 'a b', lambda a, b: a + b, 'dynamic')
register('subtract', 'a b', lambda a, b: a - b, 'dynamic')
register('average', 'a b', lambda a, b: (a + b) / 2, 'dynamic')
register('interest', 'opening_debt borrowing repayment rate', lambda d, b, r, i: (d + (b - r) / 2) * i, 'CNY_million')
register('tax', 'pretax tax_rate', lambda p, t: max(p, D(0)) * t, 'CNY_million')
register('cfo', 'net_income depreciation delta_working_capital', lambda n, d, w: n + d - w, 'CNY_million')
register('cff', 'borrowing repayment dividends', lambda b, r, d: b - r - d, 'CNY_million')
register('closing_cash', 'opening_cash cfo cfi cff', lambda c, o, i, f: c + o + i + f, 'CNY_million')
register('closing_equity', 'opening_equity net_income dividends', lambda e, n, d: e + n - d, 'CNY_million')
register('closing_ppe', 'opening_ppe capex depreciation', lambda p, c, d: p + c - d, 'CNY_million')
register('closing_debt', 'opening_debt borrowing repayment', lambda d, b, r: d + b - r, 'CNY_million')
register('target_price', 'eps target_pe', lambda e, p: e * p, 'CNY/share')
# Bullish valuation (valuation.py): peers' PE scaled by the ROE edge, at most 1.5 times.
register(
    'leader_pe', 'peer_pe company_roe peer_roe',
    lambda p, a, b: p * min(max(ratio(a, b), D(1)), D('1.5')), 'times',
)
register('maximum', 'a b', lambda a, b: max(a, b), 'dynamic')
register('dividend_yield', 'dps price', ratio)

INPUT_UNITS = {
    'shares': 'million_shares',
    'price': 'CNY/share',
    'eps': 'CNY/share',
    'target_pe': 'times',
    'volume': 'million_units',
    'capacity': 'million_units',
    'users': 'million_users',
    'arpu': 'CNY/user',
    'utilization': 'ratio',
    'share': 'ratio',
    'growth_rate': 'ratio',
    'tax_rate': 'ratio',
    'rate': 'ratio',
    'years': 'years',
}


def input_unit(formula_id: str, parameter: str) -> str:
    if formula_id == 'percentage_points':
        return 'ratio'
    if formula_id in {'volume_price', 'capacity_utilization'} and parameter == 'price':
        return 'CNY/unit'
    return INPUT_UNITS.get(parameter, 'CNY_million')


class Calculator:
    def calculate(
        self,
        formula_id: str,
        inputs: dict[str, Decimal],
        *,
        period: str,
        unit: str,
        output_metric: str | None = None,
        input_refs: dict[str, str] | None = None,
        scenario='historical',
        segment_id=None,
    ) -> CalculationResult:
        if formula_id not in REGISTRY:
            raise FinancialError(f'未注册公式 {formula_id}')
        f = REGISTRY[formula_id]
        if set(inputs) != set(f.inputs):
            raise FinancialError(f'{formula_id} 输入缺失或多余：要求 {f.inputs}')
        if f.unit != 'dynamic' and unit != f.unit:
            raise FinancialError(f'{formula_id} 输出单位错误：应为 {f.unit}')
        values = {k: D(str(v)) for k, v in inputs.items()}
        if any(not x.is_finite() for x in values.values()):
            raise FinancialError('输入包含非有限值')
        value = f.function(*(values[k] for k in f.inputs))
        if not value.is_finite():
            raise FinancialError('计算结果非有限值')
        from ..framework import digest

        result_id = (
            'calc-'
            + digest(
                [
                    formula_id,
                    f.version,
                    output_metric or formula_id,
                    period,
                    unit,
                    values,
                    input_refs or {},
                    scenario,
                    segment_id,
                ]
            )[:24]
        )
        return CalculationResult(
            result_id=result_id,
            formula_id=f.id,
            formula_version=f.version,
            output_metric=output_metric or formula_id,
            period=period,
            unit=unit,
            inputs=values,
            input_refs=input_refs or {},
            value=value,
            scenario=scenario,
            segment_id=segment_id,
        )

    def recompute(self, result: CalculationResult) -> bool:
        f = REGISTRY.get(result.formula_id)
        if not f or f.version != result.formula_version:
            return False
        try:
            checked = self.calculate(result.formula_id, result.inputs, period=result.period, unit=result.unit)
            return abs(checked.value - result.value) <= D('0.00000001')
        except (FinancialError, ArithmeticError):
            return False


class DependencyResolver:
    """Bindings refer to raw metrics or registered formula IDs via formula:<id>."""

    def resolve(self, plan: CalculationPlan) -> list[RequiredData]:
        requirements: dict[tuple, RequiredData] = {}

        def expand(formula_id: str, period: str, segment_id, bindings: dict, trail: list[str]):
            if formula_id in trail:
                raise FinancialError('公式依赖图有环：' + ' → '.join(trail + [formula_id]))
            if formula_id not in REGISTRY:
                raise FinancialError(f'未注册公式 {formula_id}')
            for argument in REGISTRY[formula_id].inputs:
                metric = bindings.get(argument, argument)
                if metric.startswith('formula:'):
                    ref = metric[8:]
                    nested_period = period
                    if '@' in ref:
                        ref, nested_period = ref.rsplit('@', 1)
                    expand(ref, nested_period, segment_id, {}, trail + [formula_id])
                    continue
                data_period = period
                if '@' in metric:
                    metric, data_period = metric.rsplit('@', 1)
                unit = input_unit(formula_id, argument)
                key = (metric, plan.company_id, segment_id, data_period, unit)
                if key not in requirements:
                    requirements[key] = RequiredData(
                        metric_code=metric,
                        company_id=plan.company_id,
                        segment_id=segment_id,
                        period=data_period,
                        unit=unit,
                        priority='critical',
                        formula_dependency=[],
                    )
                requirements[key].formula_dependency = list(
                    dict.fromkeys(requirements[key].formula_dependency + trail + [formula_id])
                )

        for request in plan.calculations:
            expand(request.formula_id, request.period, request.segment_id, request.inputs, [])
        return list(requirements.values())


UNIT_SCALE = {
    'CNY': D('0.000001'),
    'CNY_thousand': D('.001'),
    'CNY_million': D(1),
    'CNY_100million': D(100),
    '元': D('.000001'),
    '千元': D('.001'),
    '万元': D('.01'),
    '百万元': D(1),
    '亿元': D(100),
    'CNY_10thousand': D('.01'),
}
FIELD_MAP = {
    '营业收入': 'revenue',
    '营业成本': 'cost',
    '归母净利润': 'parent_net_income',
    '扣非归母净利润': 'adjusted_parent_net_income',
    '净利润': 'net_income',
    '资产总计': 'assets',
    '负债合计': 'liabilities',
    '所有者权益合计': 'equity',
    '货币资金': 'cash',
    '应收账款': 'receivables',
    '存货': 'inventory',
    '固定资产': 'ppe',
    '应付账款': 'payables',
    '经营活动现金流量净额': 'operating_cashflow',
    '资本开支': 'capex',
    '总股本': 'shares',
    '股价': 'price',
    'EBIT': 'ebit',
    '折旧摊销': 'depreciation',
    '有息负债': 'debt',
}
FIELD_MAP.update(
    {
        '经营活动产生的现金流量净额': 'operating_cashflow',
        '归属于上市公司股东的净利润': 'parent_net_income',
        '归属于母公司股东的净利润': 'parent_net_income',
        '归属于上市公司股东的扣除非经常性损益的净利润': 'adjusted_parent_net_income',
    }
)


class FinancialDataProcessor:
    def normalize(self, fact: FinancialFact) -> FinancialFact:
        if not fact.value.is_finite():
            raise FinancialError('财务事实包含非有限值')
        if fact.unit.startswith('CNY/') and fact.currency != 'CNY':
            raise FinancialError('币种与 CNY 单位不一致，禁止未经证实换算')
        update = {'metric_code': FIELD_MAP.get(fact.metric_code, fact.metric_code)}
        if fact.unit in UNIT_SCALE:
            if fact.currency != 'CNY':
                raise FinancialError('币种与 CNY 单位不一致，禁止未经证实换算')
            update.update(value=fact.value * UNIT_SCALE[fact.unit], unit='CNY_million')
        elif fact.unit in {'%', 'percent', '百分比'}:
            update.update(value=fact.value / 100, unit='ratio')
        elif fact.unit not in {
            'ratio',
            'times',
            'CNY/share',
            'CNY/unit',
            'million_shares',
            'million_units',
            'million_users',
            'CNY/user',
            'years',
        }:
            raise FinancialError('未知财务单位 ' + fact.unit)
        return fact.model_copy(update=update)

    def get(
        self,
        facts: list[FinancialFact],
        company_id: str,
        metric: str,
        period: str,
        unit='CNY_million',
        segment_id=None,
        scope='consolidated',
        actual_or_forecast='actual',
    ) -> FinancialFact:
        matches = [
            self.normalize(f)
            for f in facts
            if f.company_id == company_id
            and FIELD_MAP.get(f.metric_code, f.metric_code) == metric
            and f.period == period
            and f.segment_id == segment_id
            and f.scope == scope
            and f.actual_or_forecast == actual_or_forecast
            and f.validation_status == 'verified'
        ]
        matches = [f for f in matches if f.unit == unit]
        # Legacy explicit revisions remain supported only within the exact same
        # currency/basis identity. Model declarations cannot erase other scopes.
        known = {f.fact_id: f for f in matches}
        superseded = {
            f.supersedes
            for f in matches
            if f.supersedes in known
            and f.version > 1
            and (f.currency, f.accounting_basis) == (known[f.supersedes].currency, known[f.supersedes].accounting_basis)
        }
        matches = [f for f in matches if f.fact_id not in superseded]
        if not matches:
            raise FinancialError(f'缺失数据 {company_id}/{metric}/{period}/{unit}/{scope}/{actual_or_forecast}')
        if len({(f.value, f.currency, f.accounting_basis) for f in matches}) > 1:
            raise FinancialError(f'数据冲突 {metric}/{period}')
        return matches[0]
