from company_research.agents import WriterDraft, request_messages, llm_view
from company_research.comparisons import generated_narrative, NARRATIVE_TAIL
from company_research.datasources import compact_locator, join_document_chunks, quote_locator, source_record
from company_research.writers import draft_problems, raw_numbers, resolve_draft, strip_record_ids, without_record_ids

EV = 'ev-7818ceb16a961e62db3933fb'
EV2 = 'ev-201ac9a3e81b5774037db693'


def test_compact_locator_collapses_runs_and_keeps_offsets():
    pages = '; '.join(f'page:{i}' for i in range(1, 125))
    assert compact_locator(pages + ' chars 140103:140227') == 'page:1-124 chars 140103:140227'
    assert compact_locator('page:1; page:2; page:5') == 'page:1-2; page:5'
    assert compact_locator('chars:0-5000; chars:5000-10000; chars:10000-10126') == 'chars:0-10126'
    assert compact_locator('table:1/row:2; 全文') == 'table:1/row:2; 全文'
    assert compact_locator(None) is None


def test_joined_document_keeps_id_and_quotes_get_their_real_page():
    chunks = [source_record('upload', '年报', f'第{i}页正文', f'page:{i}', local_path='a.pdf') for i in range(1, 6)]
    full = source_record('upload', '年报', '\n\n'.join(f'[page:{i}]\n第{i}页正文' for i in range(1, 6)),
                         '; '.join(f'page:{i}' for i in range(1, 6)), local_path='a.pdf')
    [joined] = join_document_chunks(chunks)
    assert joined.source_id == full.source_id
    assert joined.locator == 'page:1-5'
    start = joined.content.index('第3页正文')
    assert quote_locator(joined, '第3页正文') == f'page:3 chars {start}:{start + 5}'
    across = joined.content[joined.content.index('第3页') : joined.content.index('第4页') + 3]
    assert quote_locator(joined, across).startswith('page:3-4 chars ')
    assert quote_locator(joined, '不存在') == 'page:1-5'


def test_models_never_see_locators():
    context = {'evidence': [{'evidence_id': EV, 'quote': '原文', 'locator': 'page:1; page:2'}],
               'financial_facts': [{'fact_id': 'f', 'locator': 'page:9'}], 'section': {'block_id': 'C01'}}
    assert 'locator' not in str(llm_view(context))
    sent = request_messages('writer', context)[1]['content']
    assert 'page:1' not in sent and '原文' in sent and EV in sent


def test_record_ids_are_not_raw_numbers():
    assert raw_numbers(f'公司为贵州茅台酒股份有限公司（{EV}；证券代码见 {EV2}）') == []
    assert raw_numbers('该段绑定的 fact-slot-cc7cc1691d1357055a13db08 为年末值') == []
    assert raw_numbers(f'收入为100亿元（{EV}）')


def test_bracketed_ids_are_removed_and_kept_as_evidence():
    text, ids = strip_record_ids(f'公司为贵州茅台（{EV}；证券代码见 {EV2}），控股股东为集团（ev-182a54df、ev-7cdf3b52）。')
    assert text == '公司为贵州茅台，控股股东为集团。'
    assert ids[:2] == [EV, EV2]
    kept, _ = strip_record_ids('营业收入为 [[fact:fact-abc12345def67890]] [比较 cmp-ee248ead8a0818e885604121]')
    assert kept == '营业收入为 [[fact:fact-abc12345def67890]]'
    context = {'facts': [], 'calculations': [], 'assumptions': [], 'evidence': [{'evidence_id': EV}]}
    draft = without_record_ids(WriterDraft(paragraphs=[f'控股股东为集团（{EV}）。', ''], evidence_ids=[], calculation_ids=[], fact_ids=[], assumption_ids=[]), context)
    assert draft.paragraphs == ['控股股东为集团。', ''] and draft.evidence_ids == [EV]


def test_bare_ids_are_flagged_then_stripped_on_resolve():
    context = {'facts': [], 'calculations': [], 'assumptions': [], 'evidence': [{'evidence_id': EV}, {'evidence_id': EV2}]}
    draft = WriterDraft(paragraphs=[f'依据为 {EV}、{EV2} 所示的分产品数据。'], evidence_ids=[EV], calculation_ids=[], fact_ids=[], assumption_ids=[])
    problems = draft_problems(draft, context)
    assert any('记录 ID' in p for p in problems) and not any('直接写了数字' in p for p in problems)
    section = resolve_draft(draft, context, 'company', '公司')
    assert 'ev-' not in section.paragraphs[0]
    assert set(section.evidence_ids) == {EV, EV2}


def test_comparison_prose_has_no_visible_id():
    assert generated_narrative('2024A 营业收入为 1.00百万元，同比/状态：+1%。' + NARRATIVE_TAIL)
    assert generated_narrative('旧版 [比较 cmp-ee248ead8a0818e885604121]')
    assert not generated_narrative('分析段落。')
