import io
from zipfile import ZipFile
import pytest
from pypdf import PdfReader
from company_research.reports import mock_report,export_docx,html_report,toc,TITLES
from company_research.renderers import export_pdf
from company_research.writers import resolve_draft
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
