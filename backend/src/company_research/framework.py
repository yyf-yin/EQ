"""Versioned mandatory research framework. The model may enrich, never replace it."""

import hashlib
import json
import re
from .schemas import ResearchBlock, ResearchPlan, ResearchTask, CoverageEntry, ResearchBrief
from .financials.formulas import FinancialError

VERSION = '1.1'
CORE = {
    'revenue': '营业收入',
    'cost': '营业成本',
    'parent_net_income': '归母净利润',
    'adjusted_parent_net_income': '扣非归母净利润',
    'operating_cashflow': '经营活动现金流量净额',
}
TEMPLATES = {
    'C01': ['身份、发展、股权与治理、业务划分', '披露时间、研究范围与报告口径'],
    'F01': ['收入成本归母及扣非利润同比', '毛利率、费用率、盈利变化及原因'],
    'F02': ['资产负债现金债务及偿债', '应收存货、流动性与营运风险'],
    'F03': ['经营现金流同比及利润质量', '营运资本、资本开支与自由现金流'],
    'F04': ['分业务收入毛利占比及同比', '量价结构驱动与分部披露限制'],
    'F05': ['ROE、ROIC与资本效率', '投资研发分红回购融资与股东回报'],
    'I01': [
        '产品用途、工艺路线与关键原料',
        '供给格局、集中度、主要产能与壁垒',
        '下游需求结构、市场规模与增速预测',
        '价格走势、周期位置与驱动因素',
        '近期政策与贸易事件及其影响',
    ],
    'B01': ['产品客户渠道产能与量价', '竞争位置壁垒及业务展望'],
    'V01': ['分业务假设与未来三年三表', 'Bear/Base/Bull、估值与敏感性'],
    'R01': ['主要结论反例、触发条件与影响方向', '重大证据缺口与风险机制'],
    'X01': ['收入现金匹配与预测总量约束', '估值证据、资源竞争与集中度', '整体判断催化剂与不确定性'],
}

# Earlier question sets still validate, so plans saved before a rewrite can resume.
LEGACY_TEMPLATES = {'I01': [['需求规模周期价格与政策', '竞争格局与产业链']]}
# Answered when the material supports them; their absence is not a coverage gap
# (not every industry has a recent policy or trade event).
OPTIONAL_QUESTIONS = {'I01': {4}}


def accepted_questions(template):
    return [TEMPLATES[template], *LEGACY_TEMPLATES.get(template, [])]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def comparison_periods(brief):
    periods = list(brief.historical_periods)
    if brief.interim_period:
        periods.append(brief.interim_period)
    return [(p, str(int(p[:4]) - 1) + p[4:]) for p in periods]


def validate_brief(brief):
    years = brief.historical_periods
    if len(years) != 3 or len(set(years)) != 3 or any(not re.fullmatch(r'\d{4}A', p) for p in years):
        raise FinancialError('v1.1 要求三个已披露连续完整财年')
    if sorted(int(p[:4]) for p in years) != list(range(int(min(years)[:4]), int(min(years)[:4]) + 3)):
        raise FinancialError('完整财年必须连续')
    if len(brief.forecast_periods) != 3 or sorted(brief.forecast_periods) != [
        f'{int(max(years)[:4]) + i}E' for i in (1, 2, 3)
    ]:
        raise FinancialError('预测必须覆盖后续三个财年')
    if not brief.segments or len(set(brief.segments)) != len(brief.segments):
        raise FinancialError('业务清单无效')
    if brief.interim_period and not re.fullmatch(r'\d{4}(?:H1|Q[1-3]|[1-3]Q)', brief.interim_period):
        raise FinancialError('中期必须区分累计 Q/H1 与单季度 nQ')


def skeleton(brief, budget=20):
    validate_brief(brief)
    blocks = []
    for template, questions in TEMPLATES.items():
        for segment in brief.segments if template in {'I01', 'B01'} else [None]:
            id = template if segment is None else template + '-' + str(brief.segments.index(segment))
            deps = [] if template == 'C01' else ['C01']
            if template == 'B01':
                deps += ['I01-' + str(brief.segments.index(segment))]
            if template == 'F04':
                deps += ['B01-' + str(i) for i in range(len(brief.segments))]
            if template == 'V01':
                deps = list(b.block_id for b in blocks)
            if template == 'R01':
                deps = list(b.block_id for b in blocks)
            if template == 'X01':
                deps = list(b.block_id for b in blocks)
            blocks.append(
                ResearchBlock(
                    block_id=id,
                    template_id=template,
                    company_id=brief.company_id,
                    segment_id=segment,
                    questions={id + ':q' + str(i + 1): q for i, q in enumerate(questions)},
                    dependencies=deps,
                    call_budget=budget,
                )
            )
    tasks = [
        ResearchTask(
            task_id=b.block_id,
            block_id=b.block_id,
            question_ids=list(b.questions),
            company_id=b.company_id,
            segment_id=b.segment_id,
            topic='；'.join(b.questions.values()),
            role='business' if b.segment_id else 'financial' if b.template_id.startswith('F') else 'company',
            queries=[brief.company_id + ' ' + (b.segment_id or '') + ' ' + q for q in b.questions.values()],
        )
        for b in blocks
    ]
    return ResearchPlan(
        company_id=brief.company_id, segments=brief.segments, tasks=tasks, template_version=VERSION, blocks=blocks
    )


def validate_plan(plan, brief, expected=None):
    expected = expected or skeleton(brief)
    errors = []
    known = {b.block_id: b for b in plan.blocks}
    target = {b.block_id: b for b in expected.blocks}
    if len(known) != len(plan.blocks) or set(known) != set(target):
        errors.append('必需块缺失、重复或未知')
    if plan.company_id != brief.company_id or plan.segments != brief.segments:
        errors.append('公司或业务 ID 错误')
    for id, b in known.items():
        ref = target.get(id)
        if not ref:
            continue
        if b.company_id != ref.company_id or b.segment_id != ref.segment_id or b.template_id != ref.template_id:
            errors.append(id + ':身份错误')
        if not any(
            all(b.questions.get(f'{id}:q{i + 1}') == q for i, q in enumerate(questions))
            for questions in accepted_questions(ref.template_id)
        ):
            errors.append(id + ':必需问题语义遗漏或被改写')
        if set(b.dependencies) != set(ref.dependencies):
            errors.append(id + ':依赖错误')
        if b.call_budget < 1 or b.call_budget > ref.call_budget:
            errors.append(id + ':预算无效')
    visited = set()
    trail = set()

    def visit(id):
        if id in trail:
            raise ValueError('依赖环')
        if id in visited:
            return
        if id not in known:
            raise ValueError('未知依赖')
        trail.add(id)
        for dep in known[id].dependencies:
            visit(dep)
        trail.remove(id)
        visited.add(id)

    try:
        for id in known:
            visit(id)
    except ValueError as exc:
        errors.append(str(exc))
    covered = {}
    for t in plan.tasks:
        if t.company_id != brief.company_id or t.segment_id not in [None] + brief.segments or not t.queries:
            errors.append('任务身份/查询无效')
        if t.block_id in known:
            covered.setdefault(t.block_id, set()).update(t.question_ids)
    for id, b in target.items():
        if plan.collection_mode == 'fixed':
            if any(t.role == 'financial' or t.required_data_ids for t in plan.tasks):
                errors.append('固定表不能生成动态财务检索任务')
            if b.template_id not in {'C01', 'I01', 'B01'}:
                continue
            all_questions = {q for t in plan.tasks for q in t.question_ids}
            if not set(b.questions).issubset(all_questions):
                errors.append(id + ':资料包未关联分析块')
        elif not set(b.questions).issubset(covered.get(id, set())):
            errors.append(id + ':责任任务未覆盖必需问题')
    return errors


def coverage_matrix(plan, brief):
    result = []
    for b in plan.blocks:
        for i, q in enumerate(b.questions):
            metrics = (
                list(CORE)[:4]
                if b.template_id == 'F01' and i == 0
                else ['operating_cashflow']
                if b.template_id == 'F03' and i == 0
                else []
            )
            needs = [m + '@' + p for m in metrics for pair in comparison_periods(brief) for p in pair]
            result.append(
                CoverageEntry(
                    block_id=b.block_id,
                    question_id=q,
                    required=i not in OPTIONAL_QUESTIONS.get(b.template_id, set()),
                    requirements=list(dict.fromkeys(needs)),
                    task_id=b.block_id,
                )
            )
    return result


def refresh_coverage(entries, blocks, facts, evidence, analyses, reference_support=None):
    """Coverage is evidence validation, never task completion. Noncore gaps stay visible."""
    blocks = {b['block_id']: b for b in blocks}
    for entry in entries:
        b = blocks[entry['block_id']]
        refs = []
        gaps = []
        if entry['requirements']:
            for need in entry['requirements']:
                m, p = need.split('@')
                matches = [
                    f
                    for f in facts
                    if f['metric_code'] == m
                    and f['period'] == p
                    and f['company_id'] == b['company_id']
                    and f['scope'] == 'consolidated'
                    and f['validation_status'] == 'verified'
                    and f['actual_or_forecast'] == 'actual'
                ]
                if not matches:
                    gaps.append(need)
                else:
                    from .financials.formulas import FinancialDataProcessor, FinancialError
                    from .schemas import FinancialFact

                    try:
                        fact = FinancialDataProcessor().get(
                            [FinancialFact.model_validate(f) for f in matches], b['company_id'], m, p
                        )
                        refs.append(fact.fact_id)
                    except FinancialError as exc:
                        gaps.append(need + '：' + str(exc))
        else:
            terms = set(re.findall(r'[\u4e00-\u9fff]{2}', b['questions'][entry['question_id']]))
            reference_ids = set((reference_support or {}).get(entry['question_id'], []))
            matches = [
                e
                for e in evidence
                if e['validation_status'] == 'verified'
                and (
                    e['evidence_id'] in reference_ids
                    or (any(t in e['quote'] for t in terms) and (not b['segment_id'] or b['segment_id'] in e['quote']))
                )
            ]
            refs = [e['evidence_id'] for e in matches]
            if not refs and entry.get('required', True):
                gaps = ['无问题相关已验证证据；不能以调用完成代替覆盖']
        entry.update(
            status='missing' if gaps else 'verified' if b['block_id'] in analyses else 'ready',
            gaps=gaps,
            verified_refs=refs,
            validation='program-evidence-check-v1.1',
        )
    return entries


def descendants(blocks, affected):
    result = set(affected)
    changed = True
    while changed:
        before = len(result)
        result.update(b['block_id'] for b in blocks if set(b['dependencies']) & result)
        changed = len(result) != before
    return result
