"""Auditable comparisons and deterministic financial prose share the same Decimal inputs."""

from decimal import Decimal
from .datasources import compact_locator
from .schemas import ComparisonResult, FinancialFact, RequiredData, Table, ReviewIssue
from .framework import CORE, comparison_periods, digest
from .financials.formulas import FinancialDataProcessor, FinancialError, Calculator

FINANCIAL_TITLES = {
    'F01': '（一）财务增长与盈利能力',
    'F02': '（二）资产负债与偿债能力',
    'F03': '（三）现金流与利润质量',
    'F04': '（四）分业务财务表现与驱动',
    'F05': '（五）资本配置与股东回报',
}


def requirements(brief):
    return [
        RequiredData(
            data_id='core-' + m + '-' + p,
            company_id=brief.company_id,
            metric_code=m,
            period=p,
            unit='CNY_million',
            priority='critical',
            formula_dependency=['F03' if m == 'operating_cashflow' else 'F01', 'core_yoy_v1.1'],
        )
        for m in CORE
        for p in sorted({p for pair in comparison_periods(brief) for p in pair})
    ]


def compare(current, previous, comparison_type='yoy'):
    identity = lambda f: (
        f.company_id,
        f.segment_id,
        f.metric_code,
        f.unit,
        f.scope,
        f.currency,
        f.accounting_basis,
        f.actual_or_forecast,
    )
    if identity(current) != identity(previous) or current.actual_or_forecast != 'actual':
        raise FinancialError('同比两期口径不可比')
    if current.validation_status != 'verified' or previous.validation_status != 'verified':
        raise FinancialError('同比使用未验证事实')
    if comparison_type == 'yoy' and previous.period != str(int(current.period[:4]) - 1) + current.period[4:]:
        raise FinancialError('同比比较期间或长度错误')
    if comparison_type == 'year_end_change' and previous.period != str(int(current.period[:4]) - 1) + 'A':
        raise FinancialError('较上年末期间错误')
    a, b = current.value, previous.value
    if not a.is_finite() or not b.is_finite():
        raise FinancialError('非有限比较值')
    calc = Calculator()
    refs = {'current': current.fact_id, 'previous': previous.fact_id}
    values = {'current': a, 'previous': b}
    delta = calc.calculate(
        'percentage_points' if current.unit == 'ratio' else 'comparison_delta',
        values,
        period=current.period,
        unit='percentage_points' if current.unit == 'ratio' else current.unit,
        input_refs=refs,
        output_metric=current.metric_code + '.delta',
    )
    results = [delta]
    rate = None
    cash = current.metric_code == 'operating_cashflow'
    if current.unit == 'ratio':
        status = '百分点变动'
    elif comparison_type == 'year_end_change':
        status = '较上年末变化'
    elif b > 0:
        r = calc.calculate(
            'yoy',
            values,
            period=current.period,
            unit='ratio',
            input_refs=refs,
            output_metric=current.metric_code + '.yoy',
        )
        results.append(r)
        rate = r.value
        status = (
            ('转为净流出' if cash else '转亏')
            if a < 0
            else '同比增加'
            if a > b
            else '同比减少'
            if a < b
            else '同比持平'
        )
    elif b == 0:
        status = '不适用（同期基数为零）'
    elif cash:
        status = '由净流出转为净流入' if a >= 0 else '净流出收窄' if a > b else '净流出扩大' if a < b else '净流出持平'
    else:
        status = '扭亏' if a >= 0 else '亏损收窄' if a > b else '亏损扩大' if a < b else '亏损持平'
    id = 'cmp-' + digest([current.model_dump(mode='json'), previous.model_dump(mode='json'), comparison_type])[:24]
    # Stable IDs let snapshots and prose detect changes without gratuitous invalidation.
    for i, r in enumerate(results):
        r.result_id = id + '-' + str(i)
    return ComparisonResult(
        comparison_id=id,
        metric_code=current.metric_code,
        current_fact_id=current.fact_id,
        previous_fact_id=previous.fact_id,
        current_period=current.period,
        previous_period=previous.period,
        current_value=a,
        previous_value=b,
        unit=current.unit,
        scope=current.scope,
        currency=current.currency,
        accounting_basis=current.accounting_basis,
        comparison_type=comparison_type,
        delta=delta.value,
        rate=rate,
        status=status,
        calculation_ids=[r.result_id for r in results],
    ), results


def build_comparisons(brief, facts):
    processor = FinancialDataProcessor()
    comparisons = []
    calculations = []
    gaps = []
    for period, previous in comparison_periods(brief):
        for metric in CORE:
            try:
                a = processor.get(facts, brief.company_id, metric, period)
                b = processor.get(facts, brief.company_id, metric, previous)
                c, r = compare(a, b)
                comparisons.append(c)
                calculations += r
            except FinancialError as exc:
                gaps.append(
                    {
                        'block_id': 'F03' if metric == 'operating_cashflow' else 'F01',
                        'metric': metric,
                        'period': period,
                        'previous': previous,
                        'reason': str(exc),
                    }
                )
    return comparisons, calculations, gaps


def amount(value, signed=False):
    # Preserve small directions: rounding may not erase a nonzero change.
    places = max(2, -value.normalize().as_tuple().exponent) if value and abs(value) < Decimal('.01') else 2
    return format(value, ('+' if signed else '') + '.' + str(min(places, 16)) + 'f')


def change(c):
    if c.unit == 'ratio':
        return amount(c.delta, True) + ' 个百分点'
    return (amount(c.rate * 100, True) + '%；' if c.rate is not None else '') + c.status


def narrative(c):
    direction = '增加' if c.delta > 0 else '减少' if c.delta < 0 else '持平'
    return (
        f'{c.current_period} {CORE[c.metric_code]}为 {amount(c.current_value)}百万元，'
        f'{c.previous_period}可比值为 {amount(c.previous_value)}百万元，{direction} {amount(abs(c.delta))}百万元，'
        f'同比/状态：{change(c)}。{NARRATIVE_TAIL}'
    )


# Marks generated comparison prose so a rebind replaces it; older runs used a visible
# "[比较 cmp-…]" suffix, which put a record ID into the report text.
NARRATIVE_TAIL = '驱动原因尚未确认；需依据同口径披露核实，不能由数值变化推断原因。'


def generated_narrative(paragraph):
    return '[比较 cmp-' in paragraph or paragraph.endswith(NARRATIVE_TAIL)


def comparison_table(comparisons, facts):
    by_id = {f.fact_id: f for f in facts}
    return Table(
        title='核心同比比较：实际合并口径，CNY 百万元；展示保留至少两位小数，计算不提前舍入',
        columns=[
            '指标与口径',
            '本期',
            '本期值',
            '可比期',
            '可比值',
            '增减额',
            '同比/特殊状态',
            '两期来源与事实',
            '计算引用',
        ],
        rows=[
            [
                CORE[c.metric_code]
                + '（'
                + (
                    '归母/扣非'
                    if c.metric_code == 'adjusted_parent_net_income'
                    else '归母'
                    if c.metric_code == 'parent_net_income'
                    else '合并'
                )
                + '，'
                + c.accounting_basis
                + '）',
                c.current_period,
                amount(c.current_value),
                c.previous_period,
                amount(c.previous_value),
                amount(c.delta, True),
                change(c),
                '; '.join(
                    by_id[id].source_id + '/' + id + ' @ ' + compact_locator(by_id[id].locator)
                    for id in [c.current_fact_id, c.previous_fact_id]
                ),
                '; '.join(c.calculation_ids),
            ]
            for c in comparisons
        ],
    )


def core_tables(comparisons, facts):
    tables = []
    for annual, label in [(True, '完整财年'), (False, '中期同长度期间')]:
        rows = [c for c in comparisons if c.current_period.endswith('A') == annual]
        if rows:
            table = comparison_table(rows, facts)
            table.title = label + ' — ' + table.title
            tables.append(table)
    return tables


def bind_financial_sections(report):
    financial = next(s for s in report.sections if s.section_id == 'financial')
    sections = {s.section_id: s for s in financial.children}
    for block in ['F01', 'F03']:
        section = sections.get(block)
        if not section:
            continue
        rows = [c for c in report.comparisons if (c.metric_code == 'operating_cashflow') == (block == 'F03')]
        section.tables = core_tables(rows, report.financial_facts)
        # Remove old generated prose, retain independently reviewed explanations.
        section.paragraphs = [p for p in section.paragraphs if not generated_narrative(p)] + [narrative(c) for c in rows]
        from .writers import number

        refs = {f.fact_id: f for f in report.financial_facts} | {r.result_id: r for r in report.calculations}
        for c in rows:
            for id in [c.current_fact_id, c.previous_fact_id]:
                f = refs[id]
                section.number_bindings['fact:' + id] = number(f.value, f.unit)
                if f.evidence_id not in section.evidence_ids:
                    section.evidence_ids.append(f.evidence_id)
            section.calculation_ids = list(dict.fromkeys(section.calculation_ids + c.calculation_ids))
        # Generated prose uses canonical precision; reviewer validates it separately.
        section.number_bindings = {
            k: v for k, v in section.number_bindings.items() if any(v in p for p in section.paragraphs)
        }


def core_gate(report):
    if report.rules_version != '1.1':
        return []
    issues = []

    def fail(block, rule, desc, target='write_sections', refs=None):
        issues.append(
            ReviewIssue(
                issue_type='financial',
                severity='critical',
                location=block,
                block_id=block,
                rule_id=rule,
                snapshot_id=report.snapshot_id,
                description=desc,
                suggested_fix='仅补查/重算并修复责任财务块，保留必需表格和正文',
                target_node=target,
                affected_refs=refs or [],
            )
        )

    if not report.brief:
        fail('F01', 'core.brief', '比较展示范围缺失', 'supervisor')
        return issues
    if report.brief.quarterly_collection:
        period = report.brief.interim_period
        if not period or not report.brief.as_of or period[:4] != report.brief.as_of[:4]:
            fail('F01', 'core.latest_interim', '缺少研究当年最新披露期间及上年同期数据', 'supervisor')
    expected, results, gaps = build_comparisons(report.brief, report.financial_facts)
    for g in gaps:
        fail(g['block_id'], 'core.comparable', g['reason'], 'supervisor')
    actual = {c.comparison_id: c for c in report.comparisons}
    calc = {r.result_id: r for r in report.calculations}
    if len(actual) != len(report.comparisons) or set(actual) != {c.comparison_id for c in expected}:
        fail('F01', 'core.coverage', '核心比较覆盖缺失、重复或存在额外错误期间', 'financial_analysis')
    for c in expected:
        if actual.get(c.comparison_id) != c:
            fail(
                'F03' if c.metric_code == 'operating_cashflow' else 'F01',
                'core.value',
                '同比值、口径或特殊状态与事实不符',
                'financial_analysis',
            )
    for r in results:
        if calc.get(r.result_id) != r:
            fail('F01', 'core.formula', '比较计算引用或注册公式结果不一致', 'financial_analysis')
    fin = next((s for s in report.sections if s.section_id == 'financial'), None)
    sections = {s.section_id: s for s in fin.children} if fin else {}
    if list(sections) != list(FINANCIAL_TITLES):
        fail('F01', 'core.structure', '财务章缺少 F01–F05 五个小节')
    for block in ['F01', 'F03']:
        s = sections.get(block)
        rows = [c for c in expected if (c.metric_code == 'operating_cashflow') == (block == 'F03')]
        if not s or not rows:
            continue
        if any(t not in s.tables for t in core_tables(rows, report.financial_facts)):
            fail(block, 'core.table', '核心同比表格缺失或数值/来源被改动')
        for c in rows:
            if narrative(c) not in s.paragraphs or not set(c.calculation_ids).issubset(s.calculation_ids):
                fail(block, 'core.prose', '核心变化解释缺失、数字与表格矛盾或未绑定引用', refs=[c.comparison_id])
    return issues


def supplemental_financial_tables(report):
    """Noncore facts remain optional; never manufacture undisclosed segment or allocation data."""
    from .writers import number

    processor = FinancialDataProcessor()
    facts = report.financial_facts
    company = report.company_id
    sections = {s.section_id: s for s in report.sections[3].children}
    if not sections or not report.brief:
        return
    latest = max(report.brief.historical_periods)
    previous = str(int(latest[:4]) - 1) + 'A'
    groups = {
        'F02': {
            'assets': '资产',
            'liabilities': '负债',
            'cash': '现金',
            'debt': '有息债务',
            'receivables': '应收账款',
            'inventory': '存货',
        },
        'F03': {'capex': '资本开支'},
        'F05': {
            'capex': '投资资本开支',
            'research_expense': '研发',
            'dividends': '分红',
            'buybacks': '回购',
            'debt': '债务融资余额',
        },
    }
    for block, metrics in groups.items():
        rows = []
        for metric, label in metrics.items():
            try:
                a = processor.get(facts, company, metric, latest)
                b = processor.get(facts, company, metric, previous)
                comparison, computed = compare(a, b)
                report.calculations += computed
                rows.append(
                    [
                        label,
                        latest,
                        amount(a.value),
                        previous,
                        amount(b.value),
                        amount(comparison.delta, True),
                        change(comparison),
                        a.fact_id + ' / ' + b.fact_id,
                    ]
                )
                p = f'{label}期末/年度值为 {number(a.value, a.unit)}，上年同口径 {number(b.value, b.unit)}，增减额 {amount(comparison.delta, True)}百万元，{change(comparison)}；驱动原因尚未确认。'
                sections[block].paragraphs.append(p)
                sections[block].number_bindings.update(
                    {'fact:' + a.fact_id: number(a.value, a.unit), 'fact:' + b.fact_id: number(b.value, b.unit)}
                )
                sections[block].evidence_ids = list(
                    dict.fromkeys(sections[block].evidence_ids + [a.evidence_id, b.evidence_id])
                )
                sections[block].calculation_ids += comparison.calculation_ids
                sections[block].number_bindings.update(
                    {'calc:' + r.result_id: number(r.value, r.unit) for r in computed}
                )
            except FinancialError:
                sections[block].paragraphs.append(label + '缺少可比披露，未估算；属于非核心限制。')
        if rows:
            sections[block].tables.append(
                Table(
                    title='同口径年度/期末同比：百万元',
                    columns=['指标', '本期', '本期值', '上年同期间', '同期值', '增减额', '同比/状态', '两期事实引用'],
                    rows=rows,
                )
            )
    rows = []
    for segment in report.brief.segments:
        for metric in ['revenue', 'cost']:
            try:
                a = processor.get(facts, company, metric, latest, segment_id=segment, scope='segment')
                b = processor.get(facts, company, metric, previous, segment_id=segment, scope='segment')
                comparison, computed = compare(a, b)
                report.calculations += computed
                rows.append(
                    [
                        segment,
                        CORE[metric],
                        latest,
                        amount(a.value),
                        previous,
                        amount(b.value),
                        amount(comparison.delta, True),
                        change(comparison),
                        a.fact_id + ' / ' + b.fact_id,
                    ]
                )
                sections['F04'].paragraphs.append(
                    f'{segment}{CORE[metric]}为 {number(a.value, a.unit)}，同期 {number(b.value, b.unit)}，变化 {amount(comparison.delta, True)}百万元，{change(comparison)}；量价驱动未被披露确认。'
                )
                sections['F04'].number_bindings.update(
                    {'fact:' + a.fact_id: number(a.value, a.unit), 'fact:' + b.fact_id: number(b.value, b.unit)}
                )
                sections['F04'].evidence_ids = list(
                    dict.fromkeys(sections['F04'].evidence_ids + [a.evidence_id, b.evidence_id])
                )
                sections['F04'].calculation_ids += comparison.calculation_ids
                sections['F04'].number_bindings.update(
                    {'calc:' + r.result_id: number(r.value, r.unit) for r in computed}
                )
            except FinancialError:
                sections['F04'].paragraphs.append(
                    segment + '：' + CORE[metric] + '缺少可比披露；禁止分摊或估造业务数字。'
                )
    if rows:
        sections['F04'].tables.append(
            Table(
                title='分业务年度同比：百万元',
                columns=['业务', '指标', '本期', '本期值', '同期', '同期值', '增减额', '同比/状态', '两期事实引用'],
                rows=rows,
            )
        )
    for segment in report.brief.segments:
        try:
            values = []
            for period in [latest, previous]:
                revenue = processor.get(facts, company, 'revenue', period, segment_id=segment, scope='segment')
                cost = processor.get(facts, company, 'cost', period, segment_id=segment, scope='segment')
                total = processor.get(facts, company, 'revenue', period)
                for formula, inputs in [
                    ('comparison_delta', {'current': revenue, 'previous': cost}),
                    ('gross_margin', {'revenue': revenue, 'cost': cost}),
                    ('segment_share', {'segment_revenue': revenue, 'total_revenue': total}),
                ]:
                    r = Calculator().calculate(
                        formula,
                        {k: f.value for k, f in inputs.items()},
                        period=period,
                        unit='CNY_million' if formula == 'comparison_delta' else 'ratio',
                        output_metric=segment + '.' + ('gross_profit' if formula == 'comparison_delta' else formula),
                        segment_id=segment,
                        input_refs={k: f.fact_id for k, f in inputs.items()},
                    )
                    values.append(r)
                    report.calculations.append(r)
            for current, prior in zip(values[:3], values[3:]):
                unit = 'percentage_points' if current.unit == 'ratio' else current.unit
                delta = Calculator().calculate(
                    'percentage_points' if current.unit == 'ratio' else 'comparison_delta',
                    {'current': current.value, 'previous': prior.value},
                    period=latest,
                    unit=unit,
                    input_refs={'current': current.result_id, 'previous': prior.result_id},
                    output_metric=current.output_metric + '.change',
                )
                report.calculations.append(delta)
                label = {'gross_profit': '毛利', 'gross_margin': '毛利率', 'segment_share': '收入占比'}[
                    current.output_metric.split('.')[-1]
                ]
                sections['F04'].paragraphs.append(
                    f'{segment}{label}本期为 {number(current.value, current.unit)}，同期 {number(prior.value, prior.unit)}，变化 {number(delta.value, unit)}；占比和毛利按同口径披露数据计算。'
                )
                for r in [current, prior, delta]:
                    sections['F04'].number_bindings['calc:' + r.result_id] = number(r.value, r.unit)
                    sections['F04'].calculation_ids.append(r.result_id)
        except FinancialError:
            sections['F04'].paragraphs.append(segment + '毛利或收入占比缺少同口径输入，未估算。')
    # Ratios use their registered formulas and percentage points, independently from monetary YoY.
    ratios = []
    for formula, block in [('gross_margin', 'F01'), ('roe', 'F05'), ('roic', 'F05'), ('fcf', 'F03')]:
        from .financials.formulas import REGISTRY, input_unit

        values = []
        try:
            for period in [latest, previous]:
                inputs = {
                    k: processor.get(facts, company, k, period, input_unit(formula, k))
                    for k in REGISTRY[formula].inputs
                }
                r = Calculator().calculate(
                    formula,
                    {k: f.value for k, f in inputs.items()},
                    period=period,
                    unit=REGISTRY[formula].unit,
                    input_refs={k: f.fact_id for k, f in inputs.items()},
                )
                report.calculations.append(r)
                values.append(r)
            a, b = values
            delta = Calculator().calculate(
                'percentage_points' if a.unit == 'ratio' else 'comparison_delta',
                {'current': a.value, 'previous': b.value},
                period=latest,
                unit='percentage_points' if a.unit == 'ratio' else a.unit,
                input_refs={'current': a.result_id, 'previous': b.result_id},
                output_metric=formula + '.change',
            )
            report.calculations.append(delta)
            sections[block].calculation_ids += [r.result_id for r in values] + [delta.result_id]
            label = {'gross_margin': '毛利率', 'roe': 'ROE', 'roic': 'ROIC', 'fcf': '自由现金流'}[formula]
            sections[block].paragraphs.append(
                f'{label}为 {number(a.value, a.unit)}，同期 {number(b.value, b.unit)}，变化 {number(delta.value, delta.unit)}；按注册公式计算，变化原因尚未确认。'
            )
            sections[block].number_bindings.update(
                {'calc:' + r.result_id: number(r.value, r.unit) for r in values + [delta]}
            )
        except FinancialError:
            sections[block].paragraphs.append(formula + '输入缺失或不适用，未填零或以期末替代平均值。')
    report.calculations = list({r.result_id: r for r in report.calculations}.values())
