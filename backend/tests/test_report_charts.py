"""Writer-proposed charts, industry-data charts and paragraph merging in the reader layout."""
from company_research.agents import WriterDraft
from company_research.presentation import body_items, industry_charts, place_items, section_chart
from company_research.schemas import ChartSeriesSpec, ChartSpec, IndustryDatum, ReportSection
from company_research.writers import draft_problems, remap_charts, resolve_draft, sanitize_draft, short_problems


def datum(id, period, value, metric='产量', publisher='国家统计局'):
    return IndustryDatum(
        data_id=id, source_id='s', evidence_id='ev-' + id, subject='全国白酒', metric=metric, period=period,
        value_text=value, publisher=publisher, quote=value, locator='l',
    )


DATA = [datum('ind-a1', '2023年', '449.20万千升'), datum('ind-a2', '2024年', '414.50万千升'), datum('ind-a3', '2025年', '354.90万千升')]
LONG = '白酒行业总量持续收缩，规模以上企业产量逐年下降，存量竞争之下份额加速向头部名酒集中，中小酒企出清，渠道库存去化仍在进行，名酒价格带分化明显。' * 2


def context(data=DATA):
    return dict(
        facts=[], calculations=[], assumptions=[], industry_data=[d.model_dump(mode='json') for d in data],
        evidence=[{'evidence_id': d.evidence_id} for d in data],
    )


def chart(refs, **overrides):
    values = dict(title='全国白酒产量', categories=['2023', '2024', '2025'], series=[ChartSeriesSpec(name='产量', refs=refs)])
    return ChartSpec(**(values | overrides))


def draft(charts, paragraphs=None):
    return WriterDraft(
        paragraphs=paragraphs or [LONG, f'白酒总量收缩。2025年全国白酒产量为[[ind:ind-a3]]，较2023年的[[ind:ind-a1]]明显回落。' + LONG],
        evidence_ids=[], calculation_ids=[], fact_ids=[], assumption_ids=[],
        industry_data_ids=['ind-a1', 'ind-a3'], charts=charts,
    )


def test_writer_chart_reads_values_from_cited_records_and_follows_its_paragraph():
    good = draft([chart(['ind:ind-a1', 'ind:ind-a2', 'ind:ind-a3'])])
    assert draft_problems(good, context()) == []
    section = resolve_draft(good, context(), 'industry-0', '（一）行业情况')
    [resolved] = section.charts
    assert resolved.series[0].values == [449.2, 414.5, 354.9] and resolved.unit == '万千升'
    assert resolved.after == 1 and resolved.source == '国家统计局'
    assert 'ev-ind-a2' in section.evidence_ids


def test_invalid_charts_are_flagged_then_dropped():
    bad = [
        chart(['ind:ind-a1', 'ind:ind-zz', 'ind:ind-a3']),  # unknown record
        chart(['ind:ind-a1', 'ind:ind-a2']),  # refs do not match categories
    ]
    problems = draft_problems(draft(bad), context())
    assert any('不是输入中可取值' in p for p in problems) and any('一一对应' in p for p in problems)
    clean, removed = sanitize_draft(draft(bad), context())
    assert clean.charts == [] and len(removed) == 2
    # Mixed sources in one series, and a chart whose data the text never cites.
    mixed = context(DATA + [datum('ind-b2', '2024年', '400万千升', publisher='中研普华')])
    assert any('不同指标或来源' in p for p in draft_problems(draft([chart(['ind:ind-a1', 'ind:ind-b2', 'ind:ind-a3'])]), mixed))
    silent = draft([chart(['ind:ind-a1', 'ind:ind-a2', 'ind:ind-a3'])], paragraphs=[LONG, LONG + '产量下降。'])
    assert any('没有在正文中引用' in p for p in draft_problems(silent, context()))


def test_chart_refs_without_prefix_are_mapped_back():
    from company_research.writers import without_record_ids
    fixed = without_record_ids(draft([chart(['ind:a1', 'ind:a2', 'ind:a3'])]), context())
    assert fixed.charts[0].series[0].refs == ['ind:ind-a1', 'ind:ind-a2', 'ind:ind-a3']


def test_runs_of_short_paragraphs_are_sent_back():
    assert short_problems(['短段。'] * 3 + [LONG]) and not short_problems(['短段。', LONG, LONG + '一', LONG + '二'])


def test_short_fragments_merge_and_charts_keep_their_paragraph():
    section = ReportSection(section_id='s', title='t', paragraphs=[LONG, '新增供给受工艺时滞约束。', LONG + '一', LONG + '二'])
    items = body_items(section)
    assert [i for i, _ in items] == [[0, 1], [2], [3]]
    resolved = resolve_draft(draft([chart(['ind:ind-a1', 'ind:ind-a2', 'ind:ind-a3'])]), context(), 'x', 't').charts[0]
    blocks = place_items(items, [(1, section_chart(resolved))])
    assert [kind for kind, _ in blocks] == ['p', 'chart', 'p', 'p']
    # A patch that deletes the chart's paragraph moves the chart to the paragraph before.
    assert remap_charts([resolved], [0, None])[0].after == 0


def test_cited_industry_series_gets_a_chart_unless_the_writer_drew_it():
    section = ReportSection(
        section_id='industry-0', title='t', paragraphs=['2025年产量为354.90万千升。'],
        number_bindings={'ind:ind-a3': '354.90万千升'},
    )
    [(figure, quotes)] = industry_charts(section, DATA)
    assert figure.categories == ['2023', '2024', '2025'] and quotes == {'354.90万千升'}
    drawn = section.model_copy(update={'charts': [resolve_draft(draft([chart(['ind:ind-a1', 'ind:ind-a2', 'ind:ind-a3'])]), context(), 'x', 't').charts[0]]})
    assert industry_charts(drawn, DATA) == []


def test_tokens_written_without_their_kind_are_completed():
    from company_research.writers import without_record_ids
    ids = ['ind-' + c * 24 for c in 'abc']
    data = [datum(i, f'{2023 + k}年', v) for k, (i, v) in enumerate(zip(ids, ['449.20万千升', '414.50万千升', '354.90万千升']))]
    raw = WriterDraft(
        paragraphs=[LONG, f'2025年全国白酒产量为[[{ids[2]}]]。' + LONG],
        evidence_ids=[], calculation_ids=[], fact_ids=[], assumption_ids=[],
        charts=[chart([ids[0], 'ind:' + ids[1], 'ind:' + ids[2][4:]])],
    )
    fixed = without_record_ids(raw, context(data))
    assert f'[[ind:{ids[2]}]]' in fixed.paragraphs[1] and fixed.industry_data_ids == [ids[2]]
    assert fixed.charts[0].series[0].refs == ['ind:' + i for i in ids]
    assert draft_problems(fixed, context(data)) == []
    from company_research.presentation import clean
    assert clean('合并营业收入[]，同比-1.21%。') == '合并营业收入，同比-1.21%。'


def test_risk_and_core_drafts_carry_no_charts():
    from company_research.writers import without_record_ids
    assert without_record_ids(draft([chart(['ind:ind-a1', 'ind:ind-a2', 'ind:ind-a3'])]), context() | {'no_charts': True}).charts == []


def test_co_published_industry_data_forms_one_series():
    data = DATA[:2] + [datum('ind-a3', '2025年', '354.90万千升', publisher='国家统计局、中国酒业协会')]
    section = ReportSection(
        section_id='industry-0', title='t', paragraphs=['2025年产量为354.90万千升。'],
        number_bindings={'ind:ind-a3': '354.90万千升'},
    )
    [(figure, _)] = industry_charts(section, data)
    assert figure.series[0].values == [449.2, 414.5, 354.9] and figure.source == '国家统计局'


def test_charts_repeating_a_fixed_or_earlier_chart_are_dropped():
    from company_research.charts import Chart, Series
    from company_research.presentation import PSection, Presentation, drop_repeated_charts
    fixed = Chart('公司盈利能力情况', ['2023', '2024', '2025'], [Series('毛利率', [91.96, 91.93, 91.18]), Series('ROE', [36.2, 38.4, 34.5])])
    same = Chart('毛利率', ['2023A', '2024A', '2025A'], [Series('毛利率', [91.961, 91.93, 91.18])], origin='writer')
    price = Chart('批价', ['原箱', '散装', '普五'], [Series('批价', [1710, 1695, 770])], origin='writer')
    again = Chart('批价对比', ['飞天原箱', '飞天散装', '八代五粮液'], [Series('批价', [1710, 1695, 770])], origin='writer')
    view = Presentation('t', 's', [], None, [
        PSection('a', 'a', 1, [('p', 'x'), ('chart', same), ('chart', fixed), ('chart', price)]),
        PSection('b', 'b', 1, [('chart', again), ('p', 'y')]),
    ], [])
    drop_repeated_charts(view)
    assert [b[1].title for s in view.flat() for b in s.blocks if b[0] == 'chart'] == ['公司盈利能力情况', '批价']
