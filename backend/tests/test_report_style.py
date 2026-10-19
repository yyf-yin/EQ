"""Broker-report writing style: viewpoint headings, claim-first paragraphs, no internal audit wording."""
from company_research.agents import WriterDraft, request_messages
from company_research.presentation import present
from company_research.reports import mock_report
from company_research.text_checks import meta_problems, meta_terms, strip_meta
from company_research.writers import clean_heading, draft_problems, report_snapshot, resolve_draft

CONTEXT = {'facts': [], 'calculations': [{'result_id': 'r', 'value': '0.1571', 'unit': 'ratio'}], 'assumptions': [], 'evidence': [{'evidence_id': 'e'}]}


def draft(paragraphs, heading=''):
    return WriterDraft(heading=heading, paragraphs=paragraphs, evidence_ids=['e'], calculation_ids=['r'], fact_ids=[], assumption_ids=[])


def test_internal_wording_is_flagged_but_ordinary_prose_is_not():
    assert meta_terms('本章结论：公司为白酒龙头。本块 financial_facts 为空，输入未提供吨价。')
    assert meta_terms('成立条件：渠道库存去化；推翻条件：批价倒挂。')
    assert not meta_terms('白酒行业或已处于本轮周期底部。公司营业收入同比增长[[calc:r]]，盈利能力稳健。')
    assert not meta_terms('原材料等输入成本上升压缩毛利率。')
    problems = meta_problems(['公司为白酒龙头。', '本章不对估值作判断。'])
    assert len(problems) == 1 and problems[0].startswith('第2段')


def test_final_cleanup_drops_run_talk_and_keeps_the_analysis():
    text = '本章结论：公司为白酒龙头。本块 facts 为空，因此本章不引用具体数值。营业收入同比增长[[calc:r]]。'
    assert strip_meta(text) == '公司为白酒龙头。营业收入同比增长[[calc:r]]。'
    section = resolve_draft(draft([text], heading='（一）业绩中枢再上台阶，盈利能力稳健。'), CONTEXT, 'F01', '（一）财务增长与盈利能力')
    assert section.paragraphs == ['公司为白酒龙头。营业收入同比增长15.71%。']
    assert section.heading == '业绩中枢再上台阶，盈利能力稳健'
    assert section.title == '（一）财务增长与盈利能力'


def test_draft_problems_ask_for_rewrites_once():
    problems = draft_problems(draft(['本章结论：公司为白酒龙头。', '输入中缺少吨价。'], heading='很' * 40), CONTEXT)
    assert sum('内部审核措辞' in p for p in problems) == 2
    assert any('heading 过长' in p for p in problems)
    assert clean_heading('二、[[calc:r]]业绩回落（ev-7818ceb16a961e62）') == '业绩回落'


def test_viewpoint_headings_replace_structural_titles_in_the_report():
    report = mock_report('示例公司')
    report.sections[2].heading = '锐意进取的精细化工龙头'
    view = present(report)
    company = view.sections[0]
    assert company.title == '一、公司情况'
    assert company.children[0].title == '（一）锐意进取的精细化工龙头'


def test_old_reports_keep_their_approved_snapshot():
    report = mock_report('示例公司')
    before = report_snapshot(report)
    data = report.model_dump(mode='json')
    for s in data['sections']:
        s.pop('heading', None)
    from company_research.schemas import ReportDocument

    assert report_snapshot(ReportDocument.model_validate(data)) == before
    report.sections[2].heading = '新标题'
    assert report_snapshot(report) != before


def test_house_style_reaches_writing_roles_only():
    for role in ['writer', 'core_writer', 'reflection']:
        assert '研报写法' in request_messages(role, {'section': {'block_id': 'C01'}})[0]['content']
    patch = request_messages('writer', {'patch_contract': {'targets': []}, 'section': {'block_id': 'C01'}})[0]['content']
    assert '章节修订' in patch and '研报写法' in patch
    for role in ['researcher', 'critical_reviewer', 'evidence_reviewer']:
        assert '研报写法' not in request_messages(role, {'section': {'block_id': 'C01'}})[0]['content']
