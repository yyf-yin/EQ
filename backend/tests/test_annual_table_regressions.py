"""Regressions from a real annual/interim report run (amounts synthetic): table
headers with annotations or share columns, per-field failure marking, and block
analysis inputs that must expose only citable IDs."""
import json

import pytest

from company_research.agents import FinancialAnalysis, ask_bounded
from company_research.fixed_collection import SlotProposal, periods as input_periods
from company_research.graphs import analyzer_view, near_id, resolve_citations
from company_research.reporting_periods import period_columns
from company_research.schemas import SourceRecord
from company_research.table_columns import financial_columns
from test_fixed_collection import prepared, context

QUARTER_HEADER = '第一季度\n（1-3 月份）\n第二季度\n（4-6 月份）\n第三季度\n（7-9 月份）\n第四季度\n（10-12 月份）'
SHARE_HEADER = ('项目名称 本期期末数\n本期期末\n数占总资\n产的比例\n（%）\n上年期末数\n上年期末\n数占总资\n产的比例\n（%）\n'
                '本期期末\n金额较上\n年期末变\n动比例（%）')


def test_quarter_month_annotation_is_not_a_cumulative_column():
    assert period_columns(QUARTER_HEADER, default_year='2025') == ['20251Q', '20252Q', '20253Q', '20254Q']
    assert financial_columns(QUARTER_HEADER, '2025A')[0] == ['20251Q', '20252Q', '20253Q', '20254Q']
    # A bare month span is still a cumulative column.
    assert period_columns('2026年1-3月 2025年1-3月') == ['2026Q1', '2025Q1']


def test_interim_year_end_growth_column_is_a_placeholder():
    header = '本报告期末 上年度末\n本报告期末\n比上年度末\n增减(%)'
    assert financial_columns(header, '2026H1', True)[0] == ['2026H1', '2025A', None]


@pytest.mark.parametrize('report,current,previous', [('2026H1', '2026H1', '2025A'), ('2025A', '2025A', '2024A')])
def test_share_of_total_columns_are_placeholders(report, current, previous):
    assert financial_columns(SHARE_HEADER, report, True)[0] == [current, None, previous, None, None]


def test_existing_header_shapes_are_unchanged():
    cols, bases = financial_columns('2023年 2022年 本期比上年同期增减(%) 2021年 调整后 调整前 调整后 调整前', '2023A')
    assert cols == ['2023A', '2022A', '2022A', None, '2021A', '2021A']
    assert financial_columns('本期发生额 上期发生额 变动比例（%）', '2026H1')[0] == ['2026H1', '2025H1', None]
    assert financial_columns('项目 期末余额 期初余额', '2025A', True)[0] == ['2025A', '2024A']


@pytest.mark.parametrize('field,period,title,section,header,row,index,value', [
    ('income.revenue', '20252Q', '固定测试公司2025年年度报告', '分季度主要财务数据', QUARTER_HEADER,
     '营业收入 50,600.00 38,788.00 39,064.00 40,384.00', 1, '38,788.00'),
    ('balance.short_term_borrowings', '2026H1', '固定测试公司2026年半年度报告', '资产及负债状况', SHARE_HEADER,
     '短期借款 120.00 0.04 90.00 0.03 33.33', 0, '120.00'),
])
async def test_annotated_tables_accept_the_aligned_value(tmp_path, field, period, title, section, header, row, index, value):
    w, g, store, run = prepared(tmp_path, rows=[])
    c = await context(w)
    c['brief'].update(quarterly_collection=True, as_of='2026-10-15', interim_period='2026H1')
    source = SourceRecord(kind='upload', title=title, content=f'{title}\n{section}\n单位：元\n{header}\n{row}')
    p = SlotProposal(field_id=field, period=period, raw_value=value, raw_unit='元', quote=row,
                     header_quote=header, unit_quote='单位：元', column_index=index)
    assert not w.fixed_collection.accept(c, source, p.model_copy(update={'column_index': index + 1}))
    assert w.fixed_collection.accept(c, source, p), w.fixed_collection.last_reject


async def test_one_rejected_value_does_not_fail_every_open_field_of_the_period(tmp_path):
    w, g, store, run = prepared(tmp_path, rows=[])
    c = await context(w)
    source = SourceRecord(source_id='bad', kind='upload', title='固定测试公司2025年年报',
                          content='固定测试公司年报\n单位：百万元\n2025年 | 2024年\n营业收入 | 100 | 90', locator='p1')
    c['sources'].append(source.model_dump(mode='json'))
    g.values = [{'field_id': 'income.revenue', 'period': '2025A', 'raw_value': '90', 'raw_unit': '百万元',
                 'quote': '营业收入 | 100 | 90', 'header_quote': '2025年 | 2024年', 'column_index': 0}]
    c.update(await w.research_plan(c))
    slots = {(s['field_id'], s['period']): s for s in store.records(run.run_id, 'data_slot')
             if not s.get('segment_id') and not s.get('bond_id') and not s.get('detail_id')}
    assert slots[('income.revenue', '2025A')]['state'] == 'extraction_failed'
    goodwill = slots[('balance.goodwill', '2025A')]
    assert goodwill['state'] == 'not_disclosed', goodwill['reason']


async def test_repair_request_sees_the_whole_window(tmp_path):
    w, g, store, run = prepared(tmp_path, rows=[])
    c = await context(w)
    w.fixed_collection.initialize(c)
    title = '固定测试公司2025年年度报告'
    content = title + '\n资产及负债状况\n短期借款 5 0.01 4 0.01 25.00\n合并利润表\n单位：元\n2025年 2024年\n营业收入 100 90\n'
    source = SourceRecord(kind='upload', title=title, content=content)
    store.execution_put(run.run_id, 'execution_meta', 'fixed-source-manifest',
                        {'bindings': {p: [source.source_id] for p in input_periods(c['brief'])}})
    g.values = [dict(field_id='income.revenue', period='2025A', raw_value='100', raw_unit='元',
                     quote='营业收入 100 90', header_quote='2025年 2024年', column_index=1)]
    await w.fixed_collection.extract_document(c, source, True)
    repairs = [v for name, v in g.calls if name == 'SlotExtraction' and v.get('rejected_values')]
    assert repairs and '合并利润表' in repairs[0]['sources'][0]['content']
    assert repairs[0]['rejected_excerpts']


def test_analyzer_view_exposes_only_citable_ids():
    content = {
        'evidence': [{'evidence_id': 'ev-1', 'quote': 'q', 'locator': '; '.join(f'page:{i}' for i in range(300))}],
        'financial_facts': [{'fact_id': 'fact-1', 'evidence_id': 'ev-2', 'slot_id': 's', 'locator': 'page:1', 'value': '1'}],
        'calculations': [{'result_id': 'cmp-a-0'}],
        'comparisons': [{'comparison_id': 'cmp-a', 'current_fact_id': 'fact-1'}],
        'upstream': [{'block_id': 'C01', 'conclusions': ['c'], 'evidence_ids': ['ev-3'], 'calculation_ids': ['x'],
                      'counter_evidence_ids': ['ev-4']}],
    }
    data = analyzer_view(content)
    text = json.dumps(data, ensure_ascii=False)
    for hidden in ('ev-2', 'ev-3', 'ev-4', '"cmp-a"', 'page:'):
        assert hidden not in text
    assert data['facts'][0]['fact_id'] == 'fact-1' and data['upstream'][0]['conclusions'] == ['c']
    assert 'financial_facts' not in data and content['financial_facts'][0]['evidence_id'] == 'ev-2'


async def test_split_keeps_each_fact_with_its_evidence(monkeypatch):
    class Gateway:
        def request_size(self, role, messages, schema):
            data = json.loads(messages[1]['content'])
            return len(data['facts']), 1
    seen = []

    async def answer(gateway, role, schema, context):
        seen.append(context)
        return FinancialAnalysis(observations=['o'], evidence_ids=[], calculation_ids=[], limitations=[])
    monkeypatch.setattr('company_research.agents.ask', answer)
    facts = [{'fact_id': f'f{i}', 'evidence_id': f'e{i}'} for i in range(4)]
    evidence = [{'evidence_id': f'e{i}'} for i in reversed(range(4))]
    await ask_bounded(Gateway(), 'financial_analyzer', FinancialAnalysis, {'facts': facts, 'evidence': evidence})
    assert len(seen) == 4
    for part in seen:
        assert {f['evidence_id'] for f in part['facts']} <= {e['evidence_id'] for e in part['evidence']}


def test_one_character_citation_typo_resolves_to_the_unique_id():
    known = {'ev-4e4e3152b881f920d6c3d303', 'ev-000d57d42ba3748827e15342'}
    output = FinancialAnalysis(
        observations=['o'],
        evidence_ids=['ev-e4e3152b881f920d6c3d303'],
        counter_evidence_ids=['ev-000d57d42ba3748827e15343'],
        calculation_ids=['calc-unknown'],
        limitations=[],
    )
    unknown_evidence, unknown_calculations = resolve_citations(output, known, {'calc-1'})
    assert output.evidence_ids == ['ev-4e4e3152b881f920d6c3d303']
    assert output.counter_evidence_ids == ['ev-000d57d42ba3748827e15342']
    assert not unknown_evidence and unknown_calculations == {'calc-unknown'}


def test_ambiguous_or_distant_citations_stay_unresolved():
    assert near_id('ev-ab', {'ev-abc', 'ev-abd'}) is None
    assert near_id('ev-0000', {'ev-1111'}) is None
