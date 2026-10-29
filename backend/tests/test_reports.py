import io
from zipfile import ZipFile
import pytest
from pypdf import PdfReader
from company_research.reports import mock_report,export_docx,html_report,toc,TITLES
from company_research.renderers import export_pdf
from company_research.writers import resolve_draft,raw_numbers,draft_problems,sanitize_draft
from company_research.agents import WriterDraft
from company_research.financials import FinancialError


def test_render_formats(tmp_path):
    report=mock_report('示例公司')
    assert [s.title for s in report.sections]==TITLES
    assert len(toc(report.sections))>7
    export_docx(report,tmp_path/'report.docx');export_pdf(report,tmp_path/'report.pdf')
    with ZipFile(tmp_path/'report.docx') as doc:
        assert '<w:tbl>' in doc.read('word/document.xml').decode()
    reader=PdfReader(tmp_path/'report.pdf')
    text=''.join(page.extract_text() for page in reader.pages)
    assert '免责声明' in text and len(reader.pages)>=2
    assert (tmp_path/'report.pdf').stat().st_size>2000
    assert 'href="#company"' in html_report(report)


def test_writer_number_binding_and_reject():
    c={'facts':[],'calculations':[{'result_id':'r','value':'100.5','unit':'CNY_million'}],'assumptions':[],'evidence':[{'evidence_id':'e'}]}
    draft=WriterDraft(paragraphs=['收入为 [[calc:r]]，仍需审慎检验。'],evidence_ids=['e'],calculation_ids=['r'],fact_ids=[],assumption_ids=[])
    section=resolve_draft(draft,c,'financial','财务')
    assert '100.50百万元' in section.paragraphs[0]
    assert section.number_bindings=={'calc:r':'100.50百万元'}
    with pytest.raises(FinancialError):resolve_draft(draft.model_copy(update={'paragraphs':['收入为100亿元。']}),c,'f','财务')
    with pytest.raises(FinancialError):resolve_draft(draft.model_copy(update={'paragraphs':['收入 [[calc:unknown]]']}),c,'f','财务')


def test_writer_allows_dates_and_periods_but_not_quantities():
    assert raw_numbers('截至2025年12月31日，2023-2025年及2026E、2025H1、第3季度与Q3的对比（1）渠道；2、品牌')==[]
    assert raw_numbers('收入为100亿元。') and raw_numbers('毛利率91.5%') and raw_numbers('有3家子公司')


def test_writer_problems_are_specific_and_sanitize_keeps_valid_text():
    c={'facts':[],'calculations':[{'result_id':'r','value':'100.5','unit':'CNY_million'}],'assumptions':[],'evidence':[{'evidence_id':'e'}]}
    draft=WriterDraft(paragraphs=['2025年收入为 [[calc:r]]。另一口径约为80亿元。来自 [[fact:x]] 的推断。'],evidence_ids=['e','ghost'],calculation_ids=['r'],fact_ids=[],assumption_ids=[])
    problems=draft_problems(draft,c)
    assert any('ghost' in p for p in problems) and any('80亿元' in p for p in problems) and any('fact:x' in p for p in problems)
    clean,removed=sanitize_draft(draft,c)
    assert len(removed)==2 and draft_problems(clean,c)==[]
    section=resolve_draft(clean,c,'financial','财务')
    assert section.paragraphs==['2025年收入为 100.50百万元。']


def test_parent_income_label_must_cite_parent_net_income():
    from company_research.agents import WriterDraft
    from company_research.writers import draft_problems

    calc = lambda id, metric: dict(result_id=id, output_metric=metric, period='2026E', scenario='base', value='1', unit='CNY_million')
    local = dict(
        facts=[], assumptions=[], evidence=[], industry_data=[],
        calculations=[calc('calc-net', 'net_income'), calc('calc-parent', 'parent_net_income')],
    )
    draft = lambda id: WriterDraft(
        paragraphs=[f'预计2026E归母净利润[[calc:{id}]]。'],
        evidence_ids=[], calculation_ids=[id], fact_ids=[], assumption_ids=[],
    )
    assert any('合并净利润' in p for p in draft_problems(draft('calc-net'), local))
    assert not any('合并净利润' in p for p in draft_problems(draft('calc-parent'), local))
    # Without minority interests net_income is the owners' income; nothing to flag.
    local['calculations'] = local['calculations'][:1]
    assert not any('合并净利润' in p for p in draft_problems(draft('calc-net'), local))
