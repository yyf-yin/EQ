"""Industry sections follow the Guangfa reports: fixed questions, parts as subsections, policy only when found."""
from company_research.agents import WriterDraft
from company_research.framework import TEMPLATES, coverage_matrix, refresh_coverage, skeleton, validate_plan
from company_research.presentation import present
from company_research.reports import mock_report
from company_research.schemas import ResearchBrief, SectionPart
from company_research.writers import (
    INDUSTRY_PARTS, draft_problems, remap_parts, resolve_draft, sanitize_draft, section_parts,
)

BRIEF = ResearchBrief(
    company_id='c', scope='营养品', historical_periods=['2023A', '2024A', '2025A'],
    forecast_periods=['2026E', '2027E', '2028E'], segments=['营养品'],
)
CONTEXT = {'facts': [], 'calculations': [], 'assumptions': [], 'evidence': [], 'part_topics': INDUSTRY_PARTS}


def draft(paragraphs, parts, heading='寡头格局，公司产业链完整'):
    return WriterDraft(
        heading=heading, paragraphs=paragraphs, parts=parts,
        evidence_ids=[], calculation_ids=[], fact_ids=[], assumption_ids=[],
    )


def part(topic, start, heading=''):
    return SectionPart(topic=topic, start=start, heading=heading)


def test_industry_questions_follow_the_reference_structure_and_policy_is_optional():
    plan = skeleton(BRIEF)
    industry = next(b for b in plan.blocks if b.template_id == 'I01')
    assert list(industry.questions.values()) == TEMPLATES['I01'] and len(TEMPLATES['I01']) == 5
    coverage = coverage_matrix(plan, BRIEF)
    required = {e.question_id: e.required for e in coverage if e.block_id == industry.block_id}
    assert required == {f'{industry.block_id}:q{i}': i != 5 for i in range(1, 6)}
    entries = refresh_coverage(
        [e.model_dump(mode='json') for e in coverage if e.block_id == industry.block_id],
        [b.model_dump(mode='json') for b in plan.blocks], [], [], {},
    )
    assert [bool(e['gaps']) for e in entries] == [True, True, True, True, False]  # 无则过


def test_plans_saved_with_the_previous_industry_questions_still_validate():
    plan = skeleton(BRIEF)
    industry = next(b for b in plan.blocks if b.template_id == 'I01')
    industry.questions = {f'{industry.block_id}:q1': '需求规模周期价格与政策', f'{industry.block_id}:q2': '竞争格局与产业链'}
    assert validate_plan(plan, BRIEF) == []
    industry.questions = {f'{industry.block_id}:q1': '改写的问题'}
    assert any('必需问题' in e for e in validate_plan(plan, BRIEF))


def test_parts_must_follow_the_topic_order_and_cover_the_paragraphs():
    paragraphs = ['工艺成熟。', '集中度高。', '需求平稳。', '价格低位。']
    good = draft(paragraphs, [part('process', 0), part('supply', 1), part('demand', 2), part('price', 3)])
    # The one-line placeholders only trip the paragraph-length check.
    assert [p for p in draft_problems(good, CONTEXT) if '段过短' not in p] == []
    assert section_parts('industry-0') == INDUSTRY_PARTS and section_parts('position-0') == {}
    shuffled = draft(paragraphs, [part('supply', 0), part('process', 1)])
    assert any('顺序' in p for p in draft_problems(shuffled, CONTEXT))
    late = draft(paragraphs, [part('process', 1), part('supply', 4)])
    assert any('start' in p for p in draft_problems(late, CONTEXT))
    unknown = draft(paragraphs, [part('outlook', 0)])
    assert any('topic' in p for p in draft_problems(unknown, CONTEXT))
    assert any('不分小节' in p for p in draft_problems(good, CONTEXT | {'part_topics': {}}))


def test_dropped_paragraphs_move_part_starts_and_empty_parts_disappear():
    parts = [part('process', 0), part('supply', 2), part('demand', 3)]
    assert remap_parts(parts, [0, 1, None, 2]) == [part('process', 0), part('demand', 2)]
    raw = draft(['工艺成熟。', '规模达到263亿美元。', '需求平稳。'], [part('process', 0), part('supply', 1), part('demand', 2)])
    clean, removed = sanitize_draft(raw, CONTEXT)
    assert removed == ['规模达到263亿美元。']
    assert clean.paragraphs == ['工艺成熟。', '需求平稳。']
    assert clean.parts == [part('process', 0), part('demand', 1)]
    malformed = draft(['工艺成熟。'], [part('supply', 0), part('process', 0)])
    assert sanitize_draft(malformed, CONTEXT)[0].parts == []


def test_industry_parts_render_as_subsections_under_the_business_viewpoint():
    report = mock_report('示例公司')
    segment = report.sections[4].children[0]
    industry, position = segment.children
    written = resolve_draft(
        draft(
            ['合成工艺成熟，柠檬醛为关键原材料。', '行业集中度高。', '技术壁垒高。', '需求平稳增长。'],
            [part('process', 0, '（一）合成工艺成熟，柠檬醛为关键原材料。'), part('supply', 1, '行业集中度高，技术壁垒高'),
             part('demand', 3, '需求平稳增长')],
        ),
        CONTEXT, industry.section_id, industry.title,
    )
    segment.children = [written, position]
    view = present(report)
    business = next(s for s in view.sections if s.section_id == 'business')
    node = next(s for s in business.children if s.section_id == segment.section_id)
    assert node.title.endswith('设备：寡头格局，公司产业链完整')
    assert [c.title for c in node.children] == [
        '1. 合成工艺成熟，柠檬醛为关键原材料', '2. 行业集中度高，技术壁垒高', '3. 需求平稳增长', '4. 公司情况',
    ]
    # Fragments of one subsection read as one paragraph.
    assert [b[1] for b in node.children[1].blocks] == ['行业集中度高。技术壁垒高。']


def test_sections_without_parts_keep_their_snapshot(monkeypatch):
    from company_research import writers

    seen = []
    monkeypatch.setattr(writers, 'digest', lambda data: seen.append(data) or 'x')
    writers.report_snapshot(mock_report('示例公司'))
    def flat(sections):
        for s in sections:
            yield s
            yield from flat(s.get('children', []))

    sections = list(flat(seen[-1]['sections']))
    assert any(s['section_id'] == 'industry-0' for s in sections)
    assert all('parts' not in s for s in sections)
