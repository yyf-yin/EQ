"""Industry numbers: admitted only from located quotes, cited as [[ind:ID]], rendered verbatim."""
from company_research.agents import WriterDraft
from company_research.contexts import block_context
from company_research.industry_data import IndustryDataProposal, admit
from company_research.reviewers import financial_review
from company_research.schemas import IndustryDatum, ReportDocument, ReportSection, SourceRecord
from company_research.writers import draft_problems, resolve_draft, sanitize_draft

TEXT = 'IAL的数据显示，2017年全球香精香料市场规模达到263亿美元，较2016年同比增长7.37%。'
SOURCE = SourceRecord(source_id='s', kind='web', title='香精香料行业报告', content='行业概况\n' + TEXT + '\n其他内容')


def proposal(**overrides):
    values = dict(
        source_id='s', subject='全球香精香料', metric='市场规模', period='2017年',
        value_text='263亿美元', quote=TEXT, publisher='IAL',
    )
    return IndustryDataProposal(**(values | overrides))


def test_value_must_be_one_number_written_in_the_located_quote():
    evidence, datum = admit(proposal(), SOURCE)
    assert datum.value_text == '263亿美元' and datum.evidence_id == evidence.evidence_id
    assert evidence.quote == TEXT and datum.data_id.startswith('ind-')
    assert admit(proposal(value_text='7.37%', metric='同比增速'), SOURCE)
    assert admit(proposal(value_text='300亿美元'), SOURCE) is None  # not in the quote
    assert admit(proposal(value_text='2017年263亿美元'), SOURCE) is None  # not a single value
    assert admit(proposal(quote='全球市场规模达到263亿美元，同比增长显著。'), SOURCE) is None  # quote not located
    assert admit(proposal(source_id='other'), SOURCE) is None


def context():
    evidence, datum = admit(proposal(), SOURCE)
    return dict(
        facts=[], calculations=[], assumptions=[],
        evidence=[evidence.model_dump(mode='json')],
        industry_data=[datum.model_dump(mode='json')],
    ), datum


def test_writer_cites_industry_data_and_renders_the_original_wording():
    local, datum = context()
    token = f'[[ind:{datum.data_id}]]'
    draft = WriterDraft(
        paragraphs=[f'全球香精香料市场平稳增长。IAL数据显示，2017年全球市场规模达到{token}。'],
        evidence_ids=[], calculation_ids=[], fact_ids=[], assumption_ids=[], industry_data_ids=[datum.data_id],
    )
    assert draft_problems(draft, local) == []
    section = resolve_draft(draft, local, 'industry-0', '（一）行业情况')
    assert section.paragraphs == ['全球香精香料市场平稳增长。IAL数据显示，2017年全球市场规模达到263亿美元。']
    assert section.number_bindings == {f'ind:{datum.data_id}': '263亿美元'}
    assert section.evidence_ids == [datum.evidence_id]


def test_hand_written_or_undeclared_industry_numbers_are_flagged_and_dropped():
    local, datum = context()
    raw = WriterDraft(
        paragraphs=['全球市场规模达到263亿美元。', f'市场平稳增长。规模达到[[ind:{datum.data_id}]]。'],
        evidence_ids=[], calculation_ids=[], fact_ids=[], assumption_ids=[],
    )
    problems = draft_problems(raw, local)
    assert any('[[ind:ID]]' in p for p in problems)
    assert any('未在对应 ID 列表中声明' in p for p in problems)
    clean, removed = sanitize_draft(raw, local)
    assert removed == ['全球市场规模达到263亿美元。']
    assert clean.industry_data_ids == [datum.data_id]


def test_industry_blocks_receive_material_evidence_and_its_data():
    local, datum = context()
    c = dict(
        company=dict(company_id='c', name='示例公司', source_ids=[]),
        brief=dict(historical_periods=['2023A', '2024A', '2025A'], forecast_periods=['2026E', '2027E', '2028E'],
                   segments=['日化原料'], interim_period=None),
        plan=dict(blocks=[
            dict(block_id='I01-0', template_id='I01', segment_id='日化原料', dependencies=['C01'], questions={'I01-0:q1': '需求规模周期价格与政策'}),
            dict(block_id='F01', template_id='F01', segment_id=None, dependencies=['C01'], questions={'F01:q1': '收入成本'}),
        ]),
        evidence=local['evidence'],
        industry_data=local['industry_data'],
        material_collections=[dict(
            topic='行业资料：香精香料', block_id='I01-0', scope=dict(linked_segments=['日化原料']),
            direction_statuses={'market': dict(status='found', evidence_ids=[datum.evidence_id], reason='')},
        )],
    )
    # The quote never names the business 日化原料; it arrives through the industry material slot.
    content = block_context(c, 'I01-0', 'writing').content
    assert [e['evidence_id'] for e in content['evidence']] == [datum.evidence_id]
    assert content['evidence'][0]['quote'] == TEXT
    assert [d['data_id'] for d in content['industry_data']] == [datum.data_id]
    assert 'industry_data' not in block_context(c, 'F01', 'writing').content


def test_reports_without_industry_data_keep_their_snapshot(monkeypatch):
    from company_research import writers
    from company_research.reports import mock_report

    report = mock_report('示例公司')
    seen = []
    monkeypatch.setattr(writers, 'digest', lambda data: seen.append(data) or 'x')
    writers.report_snapshot(report)
    assert 'industry_data' not in seen[-1]  # same digest input as before the field existed
    _, datum = context()
    report.industry_data = [datum]
    writers.report_snapshot(report)
    assert seen[-1]['industry_data'][0]['data_id'] == datum.data_id


def test_review_checks_industry_bindings_against_the_original_text():
    _, datum = context()
    binding = f'ind:{datum.data_id}'

    def issues(rendered):
        section = ReportSection(
            section_id='industry-0', title='（一）行业情况',
            paragraphs=[f'2017年全球市场规模达到{rendered}。'], number_bindings={binding: rendered},
        )
        report = ReportDocument(
            title='t', company_id='c', mode='real', sections=[section], sources=[SOURCE],
            industry_data=[IndustryDatum.model_validate(datum.model_dump())],
        )
        return [i for i in financial_review(report) if i.description == '正文数字与数据引用不一致']

    assert issues('263亿美元') == []
    assert issues('300亿美元')
