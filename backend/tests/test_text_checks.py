from decimal import Decimal as D
from company_research.text_checks import direction_problems, gap_problems
from company_research.writers import TOKEN, draft_problems
from company_research.agents import WriterDraft


def fact(id, metric, period, value, **k):
    return {'fact_id': id, 'metric_code': metric, 'period': period, 'value': str(value), 'unit': 'CNY_million',
            'scope': 'consolidated', 'segment_id': None, 'evidence_id': 'ev-' + id} | k


FACTS = [fact('opex-25', 'opex', '2025H1', '7029.07'), fact('opex-26', 'opex', '2026H1', '6956.59'),
         fact('rev-25', 'revenue', '2025H1', '100'), fact('rev-26', 'revenue', '2026H1', '110'),
         fact('np-24', 'parent_net_income', '2024A', '100'), fact('np-25', 'parent_net_income', '2025A', '98'),
         fact('sell-26', 'selling_expense', '2026H1', '3206.31')]
COMPARISONS = [{'comparison_id': 'cmp-np', 'current_fact_id': 'np-25', 'previous_fact_id': 'np-24', 'current_period': '2025A',
                'previous_period': '2024A', 'delta': '-2', 'rate': '-0.02', 'calculation_ids': ['cmp-np-0', 'cmp-np-1']}]


def directions(text):
    return direction_problems([text], TOKEN.findall, FACTS, COMPARISONS)


def gaps(text):
    return gap_problems([text], TOKEN.findall, FACTS)


def test_direction_contradicting_cited_data_is_flagged():
    found = directions('费用合计绝对额上升：2025H1 [[fact:opex-25]]、2026H1 [[fact:opex-26]]。')
    assert len(found) == 1 and found[0][0] == 0 and '实际下降' in found[0][1]
    assert not directions('费用合计绝对额下降：2025H1 [[fact:opex-25]]、2026H1 [[fact:opex-26]]。')
    assert directions('归母净利润同比增长[[calc:cmp-np-1]]。') and not directions('归母净利润同比下降[[calc:cmp-np-1]]。')
    assert directions('归母净利润由[[fact:np-24]]增加至[[fact:np-25]]。')


def test_direction_in_a_later_clause_about_the_same_metric():
    found = directions('费用合计绝对额2025H1[[fact:opex-25]]、2026H1[[fact:opex-26]]，收入正增长的同时费用绝对额上升，但缺少分项。')
    assert len(found) == 1 and '“上升”' in found[0][1]
    # The later clause is about revenue, not the expense figures before it.
    assert not directions('费用合计绝对额2025H1[[fact:opex-25]]、2026H1[[fact:opex-26]]，在收入同比下降背景下仍处高位。')


def test_ambiguous_direction_sentences_are_left_alone():
    assert not directions('收入增速下降，但收入仍由[[fact:rev-25]]到[[fact:rev-26]]。')
    assert not directions('毛利率因此走低[[fact:rev-25]]、[[fact:rev-26]]。')
    assert not directions('费用并未上升，[[fact:opex-25]]与[[fact:opex-26]]。')
    assert not directions('费用上升的风险仍在，[[fact:opex-26]]。')
    assert not directions('收入[[fact:rev-26]]高于费用[[fact:opex-26]]。')
    assert not directions('收入由[[fact:rev-25]]增长到[[fact:rev-26]]而费用由[[fact:opex-25]]下降到[[fact:opex-26]]。')
    assert not directions('收入由[[fact:rev-25]]增长到[[fact:rev-26]]，费用由[[fact:opex-25]]下降到[[fact:opex-26]]。')


def test_gap_claim_against_present_fact_is_flagged():
    assert gaps('本节输入未提供销售费用，无法判断费用率。')
    assert gaps('输入未提供可引用的财务事实、计算与预测条目。')
    assert not gaps('未提供销售费用分项金额，无法拆分渠道投放。')
    assert not gaps('未披露2027H1销售费用。')
    assert not gaps('销售费用[[fact:sell-26]]已披露，但未提供研发人员构成。')
    assert not gaps('未提供研发费用资本化政策。')


def test_gap_claim_about_a_segment_needs_that_segments_fact():
    segment = FACTS + [fact('seg-rev', 'revenue', '2026H1', '90', scope='segment', segment_id='茅台酒')]
    claim = '茅台酒：营业收入缺少可比披露。'
    assert not gap_problems([claim], TOKEN.findall, FACTS, ['茅台酒', '其他系列酒'])
    assert gap_problems([claim], TOKEN.findall, segment, ['茅台酒', '其他系列酒'])


def test_draft_problems_ask_the_writer_to_fix_direction_and_gap():
    draft = WriterDraft(paragraphs=['费用上升：[[fact:opex-25]]、[[fact:opex-26]]。', '输入未提供销售费用。'],
                        evidence_ids=[], calculation_ids=[], fact_ids=['opex-25', 'opex-26'], assumption_ids=[])
    context = {'facts': FACTS, 'calculations': [], 'assumptions': [], 'evidence': [], 'comparisons': COMPARISONS}
    problems = draft_problems(draft, context)
    assert any(p.startswith('第1段') and '实际下降' in p for p in problems)
    assert any(p.startswith('第2段') and '销售费用' in p for p in problems)


def test_prose_review_checks_rendered_sections():
    from company_research.reviewers import prose_review
    from company_research.schemas import ReportDocument, ReportSection, FinancialFact
    facts = [FinancialFact(**{k: v for k, v in f.items() if k != 'value'}, value=D(f['value']), company_id='c',
                           actual_or_forecast='actual', source_id='s', locator='p') for f in FACTS[:2]]
    section = ReportSection(section_id='F01', title='财务', paragraphs=['结论。', '费用合计上升：7029.07百万元、6956.59百万元。'],
                            number_bindings={'fact:opex-25': '7029.07百万元', 'fact:opex-26': '6956.59百万元'})
    report = ReportDocument(title='t', company_id='c', mode='real', sources=[], financial_facts=facts, sections=[section])
    [problem] = prose_review(report)
    assert (problem.rule_id, problem.section_id, problem.paragraphs, problem.severity) == ('heuristic.direction', 'F01', [2], 'error')
    assert problem.target_node == 'write_sections' and problem.block_id == 'F01'
