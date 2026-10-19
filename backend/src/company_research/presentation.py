"""Reader-facing layout of a finished report.

The pipeline keeps its own section ids, order and audit fields (evidence IDs,
limitations, sources) for review and resume. This module only decides what a
reader sees: a cover with the core view and a forecast summary, a contents
page, four numbered chapters (公司情况、业务情况、盈利预测与估值、风险提示),
numbered figures and tables with a data-source line, and the financial
statements as an appendix. Charts are drawn from verified facts only.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from .charts import Chart, Series
from .financials.formulas import FinancialDataProcessor, FinancialError
from .schemas import ReportDocument, ReportSection

CHAPTERS = ['一、公司情况', '二、业务情况', '三、盈利预测与估值', '四、风险提示']
LEVEL2 = '一二三四五六七八九十'
COMPANY_SOURCE = '公司公告、研究整理'
DISCLAIMER = '本报告为自动化研究辅助材料，不构成投资建议。数据来自公司定期报告与公开资料，预测基于明确假设的条件推演，不代表未来实际业绩。'
NUMBERING = re.compile(r'^\s*(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\(\d+\)|\d+[.、．])\s*')
MONEY = re.compile(r'(?<![\d.])(-?\d[\d,]*(?:\.\d+)?)\s*百万元')
BOILERPLATE = ('财务三表由确定性 Python 引擎生成', '各小节以同一有效快照说明财务数值与比较')


@dataclass
class PTable:
    title: str
    columns: list[str]
    rows: list[list[str]]
    source: str = COMPANY_SOURCE
    note: str = ''
    label: str = ''
    groups: set = field(default_factory=set)  # row indexes rendered as group headers


@dataclass
class PSection:
    section_id: str
    title: str
    level: int
    blocks: list = field(default_factory=list)  # ('p', text) | ('chart', Chart) | ('table', PTable)
    children: list = field(default_factory=list)


@dataclass
class Presentation:
    title: str
    subtitle: str
    points: list[tuple[str, str]]
    forecast_table: PTable | None
    sections: list[PSection]
    appendix: list[PTable]
    disclaimer: str = DISCLAIMER
    mode: str = 'real'

    def flat(self):
        def walk(items):
            for s in items:
                yield s
                yield from walk(s.children)

        return list(walk(self.sections))

    def figures(self):
        return [b[1] for s in self.flat() for b in s.blocks if b[0] in ('chart', 'table')]


# ---------------------------------------------------------------- text


def money(match) -> str:
    value = float(match.group(1).replace(',', ''))
    text = f'{value / 100:,.2f}亿元' if abs(value) >= 100 else f'{value * 100:,.2f}万元'
    # "2024A298945百万元" would otherwise read as one number after conversion.
    before = match.string[match.start() - 1] if match.start() else ''
    return (' ' if before.isalnum() and before.isascii() else '') + text


def clean(text: str) -> str:
    from .writers import strip_record_ids

    from .text_checks import strip_meta

    text, _ = strip_record_ids(text)
    return MONEY.sub(money, strip_meta(text)).strip()


def lead(text: str) -> tuple[str, str]:
    """Split a short opening claim from the supporting text, as in broker reports."""
    for mark in '。：:':
        at = text.find(mark)
        if 4 <= at <= 40:
            return text[: at + 1], text[at + 1 :]
    return '', text


def body_paragraphs(section: ReportSection) -> list[str]:
    from .comparisons import generated_narrative

    out = []
    for p in section.paragraphs:
        if not p or generated_narrative(p) or p.startswith(BOILERPLATE):
            continue
        text = clean(p)
        if text and text not in out:
            out.append(text)
    return out


def plain_title(title: str) -> str:
    return NUMBERING.sub('', title).strip()


def shown_title(section: ReportSection, fallback: str = '') -> str:
    """The writer's viewpoint heading when there is one, else the structural name."""
    return section.heading.strip() or fallback or plain_title(section.title)


# ---------------------------------------------------------------- facts


class FactBook:
    def __init__(self, report: ReportDocument):
        self.facts = report.financial_facts
        self.company = report.company_id
        self.processor = FinancialDataProcessor()
        self.cache = {}
        self.periods = sorted({f.period for f in self.facts if f.actual_or_forecast == 'actual'})

    def get(self, metric, period, unit='CNY_million', segment=None):
        key = (metric, period, unit, segment)
        if key not in self.cache:
            try:
                value = self.processor.get(
                    self.facts, self.company, metric, period, unit,
                    segment_id=segment, scope='segment' if segment else 'consolidated',
                ).value
                self.cache[key] = float(value)
            except FinancialError:
                self.cache[key] = None
        return self.cache[key]

    def annual(self, metric='revenue', limit=5):
        years = [p for p in self.periods if re.fullmatch(r'\d{4}A', p) and self.get(metric, p) is not None]
        return years[-limit:]

    def interim(self, metric='revenue'):
        halves = [p for p in self.periods if re.fullmatch(r'\d{4}H1', p) and self.get(metric, p) is not None]
        latest = halves[-1] if halves else None
        annual = self.annual(metric)
        return latest if latest and (not annual or latest[:4] > annual[-1][:4]) else None

    def quarters(self, metric='revenue', limit=8):
        found = [p for p in self.periods if re.fullmatch(r'\d{4}[1-4]Q', p) and self.get(metric, p) is not None]
        return found[-limit:]

    def previous(self, period):
        return str(int(period[:4]) - 1) + period[4:]

    def yoy(self, metric, period):
        now, before = self.get(metric, period), self.get(metric, self.previous(period))
        return (now / before - 1) * 100 if now is not None and before not in (None, 0) else None

    def ratio(self, numerator, denominator, period, scale=100):
        a, b = self.get(numerator, period), self.get(denominator, period)
        return a / b * scale if a is not None and b not in (None, 0) else None

    def total(self, metrics, period):
        values = [self.get(m, period) for m in metrics]
        return sum(v for v in values if v is not None) if any(v is not None for v in values) else None

    def roe(self, period):
        income, now, before = (
            self.get('parent_net_income', period),
            self.get('parent_equity', period),
            self.get('parent_equity', self.previous(period)),
        )
        if income is None or now is None:
            return None
        base = (now + before) / 2 if before is not None else now
        return income / base * 100 if base else None

    def segments(self, metric, period):
        names = {f.segment_id for f in self.facts if f.segment_id and f.period == period}
        values = {n: self.get(metric, period, segment=n) for n in sorted(names)}
        return {n: v for n, v in values.items() if v is not None}


def yi(value):
    return None if value is None else value / 100


def label(period: str) -> str:
    match = re.fullmatch(r'(\d{4})([1-4])Q', period)
    return f'{period[2:4]}Q{match.group(2)}' if match else period


# ---------------------------------------------------------------- charts


def financial_charts(book: FactBook) -> dict[str, list[Chart]]:
    charts: dict[str, list[Chart]] = {'F01': [], 'F02': [], 'F03': [], 'F05': [], 'F04': []}
    years = book.annual()
    interim = book.interim()
    span = years + ([interim] if interim else [])
    tag = f'{span[0][:4]}-{span[-1]}' if span else ''

    def add(key, chart):
        if chart.usable():
            charts[key].append(chart)

    add('F01', Chart(f'公司{tag}营业收入及增速', [label(p) for p in span], [
        Series('营业收入', [yi(book.get('revenue', p)) for p in span]),
        Series('同比增速', [book.yoy('revenue', p) for p in span], 'line', 'right'),
    ], unit='亿元', right_unit='%', keywords=('营业收入', '收入')))
    add('F01', Chart(f'公司{tag}归母净利润及增速', [label(p) for p in span], [
        Series('归母净利润', [yi(book.get('parent_net_income', p)) for p in span]),
        Series('同比增速', [book.yoy('parent_net_income', p) for p in span], 'line', 'right'),
    ], unit='亿元', right_unit='%', keywords=('归母净利润', '净利润', '利润')))
    add('F01', Chart(f'公司{tag}盈利能力情况', [label(p) for p in span], [
        Series('毛利率', [(1 - book.ratio('cost', 'revenue', p, 1)) * 100 if book.ratio('cost', 'revenue', p, 1) is not None else None for p in span], 'line'),
        Series('净利率', [book.ratio('net_income', 'revenue', p) for p in span], 'line'),
        Series('ROE', [book.roe(p) for p in years] + ([None] if interim else []), 'line'),
    ], unit='%', keywords=('毛利率', '净利率', 'ROE', '盈利能力')))
    add('F01', Chart(f'公司{tag}期间费用率', [label(p) for p in span], [
        Series('销售费用率', [book.ratio('selling_expense', 'revenue', p) for p in span], 'line'),
        Series('管理费用率', [book.ratio('administrative_expense', 'revenue', p) for p in span], 'line'),
        Series('研发费用率', [book.ratio('research_expense', 'revenue', p) for p in span], 'line'),
        Series('财务费用率', [book.ratio('finance_expense', 'revenue', p) for p in span], 'line'),
    ], unit='%', labels=False, keywords=('费用',)))
    quarters = book.quarters()
    if len(quarters) >= 4:
        add('F01', Chart(f'公司单季度营业收入与归母净利润', [label(q) for q in quarters], [
            Series('营业收入', [yi(book.get('revenue', q)) for q in quarters]),
            Series('归母净利润', [yi(book.get('parent_net_income', q)) for q in quarters]),
        ], unit='亿元', labels=False, keywords=('单季', '季度', 'Q2', 'Q3')))
    balance = book.annual('assets') + ([interim] if interim and book.get('assets', interim) is not None else [])
    add('F02', Chart('公司存货、合同负债与资产负债率', [label(p) for p in balance], [
        Series('存货', [yi(book.get('inventory', p)) for p in balance]),
        Series('合同负债', [yi(book.get('contract_liabilities', p)) for p in balance]),
        Series('资产负债率', [book.ratio('liabilities', 'assets', p) for p in balance], 'line', 'right'),
    ], unit='亿元', right_unit='%', labels=False, keywords=('存货', '合同负债', '负债', '偿债')))
    add('F02', Chart('公司货币资金与流动比率', [label(p) for p in balance], [
        Series('货币资金', [yi(book.get('cash', p)) for p in balance]),
        Series('流动比率', [book.ratio('current_assets', 'current_liabilities', p, 1) for p in balance], 'line', 'right'),
    ], unit='亿元', right_unit='倍', keywords=('货币资金', '现金', '流动比率')))
    add('F03', Chart(f'公司{tag}经营活动现金流与归母净利润', [label(p) for p in span], [
        Series('经营活动现金流净额', [yi(book.get('operating_cashflow', p)) for p in span]),
        Series('归母净利润', [yi(book.get('parent_net_income', p)) for p in span]),
        Series('净现比', [book.ratio('operating_cashflow', 'parent_net_income', p, 1) for p in span], 'line', 'right'),
    ], unit='亿元', right_unit='倍', labels=False, keywords=('现金流', '经营活动', '净现比')))
    add('F03', Chart(f'公司{tag}销售商品收到的现金与营业收入', [label(p) for p in span], [
        Series('销售商品、提供劳务收到的现金', [yi(book.get('sales_cash_received', p)) for p in span]),
        Series('营业收入', [yi(book.get('revenue', p)) for p in span]),
    ], unit='亿元', labels=False, keywords=('收现', '销售商品', '回款')))
    add('F05', Chart(f'公司{years[0][:4] if years else ""}-{years[-1] if years else ""}资本开支情况', [label(p) for p in years], [
        Series('购建长期资产支付的现金', [yi(book.get('purchase_long_lived_assets_cash', p)) for p in years]),
    ], unit='亿元', keywords=('资本开支', '购建', '投资')))
    add('F05', Chart('公司固定资产及在建工程情况', [label(p) for p in balance], [
        Series('固定资产', [yi(book.get('ppe', p)) for p in balance]),
        Series('在建工程', [yi(book.get('construction_in_progress', p)) for p in balance]),
    ], unit='亿元', labels=False, keywords=('固定资产', '在建工程', '产能')))
    add('F05', Chart(f'公司{tag}分配股利、利润或偿付利息支付的现金', [label(p) for p in span], [
        Series('分红及付息现金', [yi(book.get('dividend_interest_cash_paid', p)) for p in span]),
        Series('归母净利润', [yi(book.get('parent_net_income', p)) for p in span]),
    ], unit='亿元', labels=False, keywords=('分红', '股东回报', '派息')))
    with_segments = [p for p in book.periods if len(book.segments('revenue', p)) >= 2]
    if len(with_segments) >= 2:
        names = sorted({n for p in with_segments for n in book.segments('revenue', p)})
        add('F04', Chart('公司分业务营业收入', [label(p) for p in with_segments], [
            Series(n, [yi(book.segments('revenue', p).get(n)) for p in with_segments]) for n in names
        ], unit='亿元', kind='stacked', labels=False, keywords=('分业务', '收入结构', '占比')))
    elif with_segments:
        period = with_segments[-1]
        values = book.segments('revenue', period)
        add('F04', Chart(f'公司{period}分业务营业收入构成', list(values), [Series(period, [yi(v) for v in values.values()])],
                         unit='亿元', kind='pie', keywords=('分业务', '收入结构', '占比', '构成')))
    return charts


def forecast_chart(report: ReportDocument, book: FactBook):
    base = sorted((f for f in report.forecasts if f.scenario == 'Base'), key=lambda f: f.period)
    if not base:
        return None
    years = book.annual()[-3:]
    chart = Chart('公司营业收入与归母净利润预测', [label(p) for p in years] + [f.period for f in base], [
        Series('营业收入', [yi(book.get('revenue', p)) for p in years] + [yi(float(f.income['revenue'])) if 'revenue' in f.income else None for f in base]),
        Series('净利润', [yi(book.get('net_income', p)) for p in years] + [yi(float(f.income['net_income'])) if 'net_income' in f.income else None for f in base]),
    ], unit='亿元', labels=False, keywords=('预测', '预计'))
    return chart if chart.usable() else None


def place(paragraphs: list[str], charts: list[Chart], tables: list[PTable] = ()) -> list:
    """Interleave figures after the first paragraph that discusses them; the rest follow the text."""
    after = {i: [] for i in range(len(paragraphs))}
    rest = []
    for chart in charts:
        index = next((i for i, p in enumerate(paragraphs) if any(k in p for k in chart.keywords)), None)
        (after[index] if index is not None else rest).append(('chart', chart))
    blocks = []
    for i, p in enumerate(paragraphs):
        blocks.append(('p', p))
        blocks.extend(after[i])
    return blocks + rest + [('table', t) for t in tables]


# ---------------------------------------------------------------- tables


def cell(value, kind='money'):
    if value is None:
        return '—'
    if kind == 'money':
        return f'{value:,.0f}' if abs(value) >= 10 else f'{value:,.2f}'
    if kind == 'pct':
        return f'{value:.1f}%'
    if kind == 'times':
        return f'{value:.2f}'
    return f'{value:,.2f}'


def forecast_rows(report: ReportDocument):
    return sorted((f for f in report.forecasts if f.scenario == 'Base'), key=lambda f: f.period)


def forecast_value(forecast, part, key):
    value = getattr(forecast, part).get(key)
    return float(value) if isinstance(value, (int, float, Decimal)) else None


def summary_table(report: ReportDocument, book: FactBook) -> PTable | None:
    years = book.annual()[-3:]
    base = forecast_rows(report)
    if not years:
        return None
    columns = ['主要财务指标'] + years + [f.period for f in base]
    revenue = [book.get('revenue', p) for p in years] + [forecast_value(f, 'income', 'revenue') for f in base]
    profit = [book.get('parent_net_income', p) for p in years] + [forecast_value(f, 'income', 'net_income') for f in base]

    def growth(series, first_prev):
        out = []
        for i, v in enumerate(series):
            before = series[i - 1] if i else first_prev
            out.append((v / before - 1) * 100 if v is not None and before not in (None, 0) else None)
        return out

    rows = [
        ['营业收入（百万元）'] + [cell(v) for v in revenue],
        ['增长率（%）'] + [cell(v, 'pct') for v in growth(revenue, book.get('revenue', book.previous(years[0])))],
        ['归母净利润（百万元）'] + [cell(v) for v in profit],
        ['增长率（%）'] + [cell(v, 'pct') for v in growth(profit, book.get('parent_net_income', book.previous(years[0])))],
        ['EPS（元/股）'] + [cell(book.get('basic_eps_reported', p, 'CNY/share'), 'num') for p in years]
        + [cell(forecast_value(f, 'income', 'eps'), 'num') for f in base],
        ['ROE（%）'] + [cell(book.roe(p), 'pct') for p in years] + ['—' for _ in base],
        ['毛利率（%）'] + [cell((1 - c / r) * 100 if c is not None and r else None, 'pct') for c, r in zip(
            [book.get('cost', p) for p in years] + [forecast_value(f, 'income', 'cost') for f in base], revenue)],
    ]
    return PTable('盈利预测', columns, rows, source='公司公告、研究整理')


def statement_tables(report: ReportDocument, book: FactBook) -> list[PTable]:
    """Appendix statements with every line the annual reports disclose; '—' only when truly absent."""
    years = [p for p in (report.brief.historical_periods if report.brief else []) if book.get('assets', p) is not None]
    years = years or book.annual('assets', 3)
    base = forecast_rows(report)
    columns = ['至12月31日'] + years + [f.period for f in base]

    def row(name, fn, forecast=None, kind='money', required=False):
        values = [fn(p) for p in years]
        predicted = [forecast_value(f, *forecast) if forecast else None for f in base]
        if not required and all(v is None for v in values + predicted):
            return None
        return [name] + [cell(v, kind) for v in values + predicted]

    g = book.get
    t = book.total
    receivables = ['receivables', 'notes_receivable', 'receivables_financing', 'prepayments', 'other_receivables']
    current_named = ['cash', 'inventory'] + receivables + ['trading_financial_assets']
    noncurrent_named = ['long_term_equity_investments', 'ppe', 'construction_in_progress', 'intangible_assets', 'right_of_use_assets']

    def rest(total, parts):
        return lambda p: (g(total, p) - (t(parts, p) or 0)) if g(total, p) is not None else None

    balance = [
        row('流动资产', lambda p: g('current_assets', p)),
        row('货币资金', lambda p: g('cash', p), ('balance', 'cash'), required=True),
        row('交易性金融资产', lambda p: g('trading_financial_assets', p)),
        row('应收及预付', lambda p: t(receivables, p), ('balance', 'receivables'), required=True),
        row('存货', lambda p: g('inventory', p), ('balance', 'inventory'), required=True),
        row('其他流动资产', rest('current_assets', current_named)),
        row('非流动资产', lambda p: g('noncurrent_assets', p)),
        row('长期股权投资', lambda p: g('long_term_equity_investments', p)),
        row('固定资产', lambda p: g('ppe', p), ('balance', 'ppe'), required=True),
        row('在建工程', lambda p: g('construction_in_progress', p)),
        row('无形资产', lambda p: g('intangible_assets', p)),
        row('使用权资产', lambda p: g('right_of_use_assets', p)),
        row('其他非流动资产', rest('noncurrent_assets', noncurrent_named)),
        row('资产总计', lambda p: g('assets', p), ('balance', 'assets'), required=True),
        row('流动负债', lambda p: g('current_liabilities', p)),
        row('应付账款', lambda p: g('payables', p), ('balance', 'payables'), required=True),
        row('合同负债', lambda p: g('contract_liabilities', p)),
        row('应付职工薪酬', lambda p: g('employee_payables', p)),
        row('应交税费', lambda p: g('tax_payables', p)),
        row('其他应付款', lambda p: g('other_payables', p)),
        row('非流动负债', lambda p: g('noncurrent_liabilities', p)),
        row('租赁负债', lambda p: g('lease_liabilities', p)),
        row('有息负债', lambda p: g('debt', p), ('balance', 'debt')),
        row('负债合计', lambda p: g('liabilities', p), ('balance', 'liabilities'), required=True),
        row('归属母公司股东权益', lambda p: g('parent_equity', p)),
        row('少数股东权益', lambda p: g('minority_equity', p)),
        row('股东权益合计', lambda p: g('equity', p), ('balance', 'equity'), required=True),
    ]
    income = [
        row('营业收入', lambda p: g('revenue', p), ('income', 'revenue'), required=True),
        row('营业成本', lambda p: g('cost', p), ('income', 'cost'), required=True),
        row('税金及附加', lambda p: g('taxes_surcharges', p)),
        row('销售费用', lambda p: g('selling_expense', p)),
        row('管理费用', lambda p: g('administrative_expense', p)),
        row('研发费用', lambda p: g('research_expense', p)),
        row('财务费用', lambda p: g('finance_expense', p), ('income', 'interest')),
        row('期间费用合计', lambda p: t(['selling_expense', 'administrative_expense', 'research_expense', 'finance_expense'], p), ('income', 'opex')),
        row('信用减值损失', lambda p: g('credit_impairment', p)),
        row('投资收益', lambda p: g('investment_income', p)),
        row('公允价值变动收益', lambda p: g('fair_value_change', p)),
        row('其他收益', lambda p: g('other_income', p)),
        row('营业利润', lambda p: g('operating_profit', p), ('income', 'ebit'), required=True),
        row('营业外收支', lambda p: (g('nonoperating_income', p) or 0) - (g('nonoperating_expense', p) or 0)
            if g('nonoperating_income', p) is not None or g('nonoperating_expense', p) is not None else None),
        row('利润总额', lambda p: g('pretax_profit', p)),
        row('所得税', lambda p: g('income_tax_expense', p), ('income', 'tax'), required=True),
        row('净利润', lambda p: g('net_income', p), ('income', 'net_income'), required=True),
        row('少数股东损益', lambda p: g('minority_net_income', p)),
        row('归母净利润', lambda p: g('parent_net_income', p), required=True),
        row('EPS（元/股）', lambda p: g('basic_eps_reported', p, 'CNY/share'), ('income', 'eps'), kind='num'),
    ]
    depreciation = ['depreciation_ppe', 'depreciation_rou', 'amortization_intangibles', 'amortization_long_term']
    cashflow = [
        row('经营活动现金流', lambda p: g('operating_cashflow', p), ('cashflow', 'cfo'), required=True),
        row('净利润', lambda p: g('net_income', p)),
        row('折旧摊销', lambda p: t(depreciation, p), ('income', 'depreciation'), required=True),
        row('销售商品收到的现金', lambda p: g('sales_cash_received', p)),
        row('投资活动现金流', lambda p: g('investing_cashflow', p), ('cashflow', 'cfi'), required=True),
        row('资本支出', lambda p: -g('purchase_long_lived_assets_cash', p) if g('purchase_long_lived_assets_cash', p) is not None else None,
            ('cashflow', 'capex'), required=True),
        row('筹资活动现金流', lambda p: g('financing_cashflow', p), ('cashflow', 'cff'), required=True),
        row('分红及付息支付的现金', lambda p: g('dividend_interest_cash_paid', p), ('cashflow', 'dividends')),
        row('现金净增加额', lambda p: g('cash_equivalent_change', p)),
        row('期初现金余额', lambda p: g('opening_cash_equivalents', p)),
        row('期末现金余额', lambda p: g('closing_cash_equivalents', p)),
    ]

    def growth(metric):
        return lambda p: book.yoy(metric, p)

    def turnover(numerator, average):
        def fn(p):
            now, before, flow = g(average, p), g(average, book.previous(p)), g(numerator, p)
            if now is None or flow is None:
                return None
            base = (now + before) / 2 if before is not None else now
            return flow / base if base else None

        return fn

    ratios = [
        ['成长能力'] + [''] * (len(columns) - 1),
        row('营业收入增长', growth('revenue'), kind='pct'),
        row('营业利润增长', growth('operating_profit'), kind='pct'),
        row('归母净利润增长', growth('parent_net_income'), kind='pct'),
        ['获利能力'] + [''] * (len(columns) - 1),
        row('毛利率', lambda p: (1 - g('cost', p) / g('revenue', p)) * 100 if g('cost', p) is not None and g('revenue', p) else None, kind='pct'),
        row('净利率', lambda p: book.ratio('net_income', 'revenue', p), kind='pct'),
        row('ROE', book.roe, kind='pct'),
        ['偿债能力'] + [''] * (len(columns) - 1),
        row('资产负债率', lambda p: book.ratio('liabilities', 'assets', p), kind='pct'),
        row('流动比率', lambda p: book.ratio('current_assets', 'current_liabilities', p, 1), kind='times'),
        row('速动比率', lambda p: (g('current_assets', p) - g('inventory', p)) / g('current_liabilities', p)
            if None not in (g('current_assets', p), g('inventory', p)) and g('current_liabilities', p) else None, kind='times'),
        ['营运能力'] + [''] * (len(columns) - 1),
        row('总资产周转率', turnover('revenue', 'assets'), kind='times'),
        row('存货周转率', turnover('cost', 'inventory'), kind='times'),
    ]

    def table(title, rows):
        kept = [r for r in rows if r is not None]
        groups = {i for i, r in enumerate(kept) if all(c == '' for c in r[1:])}
        return PTable(title, columns, kept, source='公司公告、研究整理', groups=groups)

    return [
        table('资产负债表（单位：百万元）', balance),
        table('利润表（单位：百万元）', income),
        table('现金流量表（单位：百万元）', cashflow),
        table('主要财务比率', ratios),
    ]


def assumption_table(report: ReportDocument) -> PTable | None:
    if not report.assumptions:
        return None
    from .writers import number

    rows = [
        [a.metric_code, a.scenario, a.period, a.segment_id or '公司', number(a.value, a.unit)]
        for a in report.assumptions
    ]
    return PTable('关键盈利预测假设', ['参数', '情景', '期间', '业务', '数值'], rows)


def section_tables(section: ReportSection) -> list[PTable]:
    """Writer-made text tables stay; machine audit tables (IDs, long-format dumps) do not."""
    keep = []
    for table in section.tables:
        if any(w in c for c in table.columns for w in ('来源', '引用', '计算 ID', '事实')):
            continue
        if not table.rows or table.title.startswith(('历史财务指标', '情景预测', '预测假设', '利润表', '资产负债表', '现金流量表')):
            continue
        if '同比' in table.title or '核心同比比较' in table.title:
            continue
        keep.append(PTable(clean(table.title), table.columns, [[clean(c) for c in r] for r in table.rows]))
    return keep


# ---------------------------------------------------------------- assembly


def ticker(company_id: str) -> str:
    code = company_id.split(':')[-1]
    if re.fullmatch(r'\d{6}', code):
        return code + ('.SH' if code[0] in '69' else '.BJ' if code[0] in '48' else '.SZ')
    return code


def present(report: ReportDocument) -> Presentation:
    by_id = {s.section_id: s for s in report.sections}
    book = FactBook(report)
    charts = financial_charts(book) if report.financial_facts else {}

    def leaf(section: ReportSection, title: str, level: int, extra_charts=()):
        node = PSection(section.section_id, title, level)
        node.blocks = place(body_paragraphs(section), list(extra_charts), section_tables(section))
        return node

    def part_leaves(section: ReportSection, level: int):
        from .writers import INDUSTRY_PARTS

        nodes = []
        for k, part in enumerate(section.parts):
            end = section.parts[k + 1].start if k + 1 < len(section.parts) else len(section.paragraphs)
            node = PSection(
                f'{section.section_id}-{part.topic}', part.heading or INDUSTRY_PARTS.get(part.topic, part.topic), level
            )
            text = section.model_copy(update={'paragraphs': section.paragraphs[part.start : end]})
            node.blocks = place(body_paragraphs(text), [])
            nodes.append(node)
        if nodes:
            nodes[-1].blocks += [('table', t) for t in section_tables(section)]
        return nodes

    chapters = []
    # 一、公司情况
    company = PSection('company', CHAPTERS[0], 1)
    subsections = []
    if 'company' in by_id:
        subsections.append(leaf(by_id['company'], shown_title(by_id['company'], '公司概况'), 2))
    financial = by_id.get('financial')
    written = {c.section_id for c in financial.children} if financial else set()
    for child in financial.children if financial else []:
        if child.section_id == 'F04':
            continue
        subsections.append(leaf(child, shown_title(child), 2, charts.get(child.section_id, [])))
    orphans = [c for key in ('F01', 'F02', 'F03', 'F05') if key not in written for c in charts.get(key, [])]
    if orphans or (financial and financial.paragraphs and not financial.children):
        overview = PSection('financial', '财务分析', 2)
        overview.blocks = place(body_paragraphs(financial) if financial else [], orphans)
        subsections.append(overview)
    company.children = [s for s in subsections if s.blocks]
    chapters.append(company)

    # 二、业务情况
    business = PSection('business', CHAPTERS[1], 1)
    source = by_id.get('business')
    if source:
        business.blocks = [('p', p) for p in body_paragraphs(source)]
    segment_finance = next((c for c in financial.children if c.section_id == 'F04'), None) if financial else None
    parts = []
    if segment_finance:
        parts.append(leaf(segment_finance, shown_title(segment_finance, '分业务经营与财务表现'), 2, charts.get('F04', [])))
    elif charts.get('F04'):
        business.blocks += [('chart', c) for c in charts['F04']]
    for segment in source.children if source else []:
        # An industry section written in parts reads like the reference reports: the
        # business carries the industry viewpoint, each part is its own subsection.
        industry = next((c for c in segment.children if c.section_id.startswith('industry-') and c.parts), None)
        title = plain_title(segment.title)
        if industry and industry.heading.strip():
            title += '：' + industry.heading.strip()
        node = PSection(segment.section_id, title, 2)
        node.blocks = [('p', p) for p in body_paragraphs(segment)]
        node.children = [
            n for c in segment.children for n in (part_leaves(c, 3) if c is industry else [leaf(c, shown_title(c), 3)])
        ]
        node.children = [c for c in node.children if c.blocks]
        parts.append(node)
    business.children = [p for p in parts if p.blocks or p.children]
    chapters.append(business)

    # 三、盈利预测与估值
    forecast = PSection('forecast', CHAPTERS[2], 1)
    if 'forecast' in by_id:
        paragraphs = [p for p in body_paragraphs(by_id['forecast']) if not p.startswith('假设依据：') or len(p) > 12]
        figure = forecast_chart(report, book)
        tables = [t for t in [assumption_table(report)] if t]
        if report.forecasts:
            summary = summary_table(report, book)
            if summary:
                summary.title = '盈利预测与估值汇总'
                tables.insert(0, summary)
        forecast.blocks = place(paragraphs, [figure] if figure else [], tables)
    chapters.append(forecast)

    # 四、风险提示
    risk = PSection('risk', CHAPTERS[3], 1)
    if 'risk' in by_id:
        risk.blocks = [('p', p) for p in body_paragraphs(by_id['risk'])]
    chapters.append(risk)

    # Two-level numbering: （一）（二）… then 1. 2. …
    for chapter in chapters:
        for i, child in enumerate(chapter.children):
            child.title = f'（{LEVEL2[i] if i < len(LEVEL2) else i + 1}）{child.title}'
            for j, grand in enumerate(child.children):
                grand.title = f'{j + 1}. {grand.title}'

    presentation = Presentation(
        title=f'{company_name(report)}（{ticker(report.company_id)}）',
        subtitle='公司深度研究报告' if report.mode != 'mock' else '模拟报告（合成数据，仅用于流程演示）',
        points=[lead(p) for p in body_paragraphs(by_id['core'])] if 'core' in by_id else [],
        forecast_table=summary_table(report, book) if report.financial_facts else None,
        sections=chapters,
        appendix=statement_tables(report, book) if report.financial_facts else legacy_statements(by_id.get('statements')),
        mode=report.mode,
    )
    number_figures(presentation)
    return presentation


def company_name(report: ReportDocument) -> str:
    return re.sub(r'\s*公司深度研究报告$', '', report.title).strip() or report.title


def legacy_statements(section: ReportSection | None) -> list[PTable]:
    if not section:
        return []
    return [PTable(t.title, t.columns, [['—' if c == '缺失' else c for c in r] for r in t.rows]) for t in section.tables]


def number_figures(presentation: Presentation):
    charts = tables = 0
    for section in presentation.flat():
        for kind, item in section.blocks:
            if kind == 'chart':
                charts += 1
                item.label = f'图{charts}'
            elif kind == 'table':
                tables += 1
                item.label = f'表{tables}'
