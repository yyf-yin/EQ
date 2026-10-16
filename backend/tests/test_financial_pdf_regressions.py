"""Regressions for real PDF layout/capacity failure shapes; all amounts synthetic."""
import json

import pytest

from company_research.agents import request_messages
from company_research.execution import PauseRequested
from company_research.fixed_collection import (
    ANNUAL_QUARTER_FIELDS, BASE_YEAR_FIELDS, SlotProposal, SlotExtraction, periods as input_periods, uncertain_number)
from company_research.llm import TruncatedOutput
from company_research.reporting_periods import supports_period
from company_research.llm import Gateway as WireGateway, ModelConfig
from company_research.reconciliation import metric_before
from company_research.schemas import SourceRecord
from company_research.table_columns import financial_columns
from test_fixed_collection import prepared, context


def test_wrapped_metric_names_keep_parent_and_adjusted_profit_distinct():
    text = '归属于上市公\n司股东的扣除\n非经常性损益\n的净利润 100'
    assert metric_before(text, text.index('100'), 'adjusted_parent_net_income')
    assert not metric_before(text, text.index('100'), 'parent_net_income')
    assert not metric_before(text, text.index('100'), 'net_income')


def test_complete_headers_preserve_growth_and_restatement_columns():
    assert financial_columns('本报告期（1－6月） 上年同期 本报告期比\n上年同期增\n减(%)', '2026H1')[0] == ['2026H1', '2025H1', None]
    cols, bases = financial_columns('2025年 2024年 本期比上年同期增减(%) 2023年\n调整后 调整前 调整后 调整前', '2025A')
    assert cols == ['2025A', '2024A', '2024A', None, '2023A', '2023A']
    assert bases == ['reported', 'restated', 'reported', 'reported', 'restated', 'reported']
    assert financial_columns('本报告期末 上年度末', '2026H1', True)[0] == ['2026H1', '2025A']


@pytest.mark.parametrize('field,row,header,period,index,value,basis', [
    ('income.revenue', '其中：营业收入 43 100.00 90.00', '项目 附注 2026年半年度 2025年半年度', '2026H1', 0, '100.00', 'reported'),
    ('income.parent_net_income', '1.归属于母公司股东的净利润 30.00 25.00', '项目 附注 2026年半年度 2025年半年度', '2026H1', 0, '30.00', 'reported'),
    ('income.adjusted_parent_net_income', '归属于上市公司股东的扣除非经\n常性损益的净利润 28.00 24.00 16.67', '本报告期（1－6月） 上年同期 本报告期比上年同期增减(%)', '2026H1', 0, '28.00', 'reported'),
    ('income.adjusted_parent_net_income', '归属于上市公\n司股东的扣除\n非经常性损益\n的净利润 30 25 24 20 18 17', '2025年 2024年 本期比上年同期增减(%) 2023年\n调整后 调整前 调整后 调整前', '2024A', 1, '25', 'restated'),
])
async def test_real_table_shapes_accept_only_correct_value_columns(tmp_path, field, row, header, period, index, value, basis):
    w, g, store, run = prepared(tmp_path, rows=[])
    c = await context(w)
    c['brief'].update(quarterly_collection=True, as_of='2026-10-15', interim_period='2026H1')
    title = '固定测试公司2026年半年度报告' if period.endswith('H1') else '固定测试公司2025年年度报告'
    source = SourceRecord(kind='upload', title=title, content=title+'\n合并利润表\n单位：元\n'+header+'\n'+row)
    p = SlotProposal(field_id=field, period=period, raw_value=value, raw_unit='元', quote=row,
                     header_quote=header, unit_quote='单位：元', column_index=index, accounting_basis=basis)
    assert not w.fixed_collection.accept(c, source, p.model_copy(update={'raw_value': '999'}))
    assert not w.fixed_collection.accept(c, source, p.model_copy(update={'column_index': index + 1}))
    assert w.fixed_collection.accept(c, source, p)


async def test_large_target_list_is_counted_in_complete_wire_request(tmp_path):
    w, g, store, run = prepared(tmp_path, rows=[])
    c = await context(w)
    c['brief'].update(quarterly_collection=True, as_of='2026-10-15', interim_period='2026H1')
    w.fixed_collection.initialize(c)
    source = SourceRecord(kind='upload', title='固定测试公司2025年年度报告',
        content='固定测试公司2025年年度报告\n' + ('2025年 2024年 单位：元\n营业收入 100 90\n' * 1800))
    periods = ['2025A', '2024A', '2023A', '2022A', '20251Q', '20252Q', '20253Q', '20254Q']
    store.execution_put(run.run_id, 'execution_meta', 'fixed-source-manifest', {'bindings': {p: [source.source_id] if p in periods else [] for p in input_periods(c['brief'])}})
    wire = WireGateway({'test': ModelConfig(protocol='openai', api_key_env='UNUSED_TEST_KEY', base_url='https://fixture.invalid', model='fixture', max_tokens=32000, structured_mode='json')},
        {'default': 'test'}, role_limits={'default': {'input_capacity': 36000, 'context_capacity': 68000, 'max_output_tokens': 32000}})
    g.request_size = wire.request_size
    g.values = [dict(field_id='income.revenue', period='2025A', raw_value='100', raw_unit='元',
                     quote='营业收入 100 90', header_quote='2025年 2024年 单位：元', column_index=0)]
    original_call = g.structured

    async def pause_after_first(*args):
        output = await original_call(*args)
        if len(g.calls) == 1:
            run.status = 'pausing'
            store.save_run(run)
        return output

    g.structured = pause_after_first
    with pytest.raises(PauseRequested):
        await w.fixed_collection.extract_document(c, source, True)
    assert any(s['state'] == 'locked' for s in store.records(run.run_id, 'data_slot'))
    run.status = 'running'
    store.save_run(run)
    await w.fixed_collection.extract_document(c, source, True)
    requests = [v for name, v in g.calls if name == 'SlotExtraction']
    assert len(requests) > 1
    targets = requests[0]['open_targets']
    # Compact per-period map; an annual report's quarters ask only for the
    # quarterly-table metrics and the comparison year only for core fields.
    assert targets['2025A']['consolidated'] == '*'
    assert targets['20251Q']['consolidated'] == sorted(ANNUAL_QUARTER_FIELDS)
    assert set(targets['2022A']['consolidated']) <= BASE_YEAR_FIELDS
    assert 'income.taxes_surcharges' not in targets['2022A']['consolidated']
    for request in requests:
        size, limit = wire.request_size('researcher', request_messages('researcher', request), SlotExtraction)
        assert size <= limit
    # All original text survives the smaller windows, with no extra model calls on replay.
    assert ''.join(r['sources'][0]['content'] for r in requests) == source.content
    count = len(g.calls)
    await w.fixed_collection.extract_document(c, source, True)
    assert len(g.calls) == count


def test_negative_table_columns_are_not_ranges():
    import re
    from company_research.fixed_collection import NUMBER
    row = '财务费用 49 -243.00 -486.00'
    assert not any(uncertain_number(row, m) for m in re.finditer(NUMBER, row))
    for text in ('预计100-200万元', '100至200', '100~200', '100—200'):
        assert all(uncertain_number(text, m) for m in re.finditer(NUMBER, text)), text
    # A spaced dash is an empty column placeholder, not a range.
    row = '投资收益 — 120.00'
    assert not any(uncertain_number(row, m) for m in re.finditer(NUMBER, row))


async def test_negative_cashflow_row_is_accepted(tmp_path):
    w, g, store, run = prepared(tmp_path, rows=[])
    c = await context(w)
    header = '项目 附注 2025年度 2024年度'
    row = '投资活动产生的现金流量净额 49 -243.00 -486.00'
    title = '固定测试公司2025年年度报告'
    source = SourceRecord(kind='upload', title=title, content=title + '\n合并现金流量表\n单位：元\n' + header + '\n' + row)
    p = SlotProposal(field_id='cashflow.investing_cashflow', period='2025A', raw_value='-243.00', raw_unit='元',
                     quote=row, header_quote=header, unit_quote='单位：元', column_index=0)
    assert w.fixed_collection.accept(c, source, p)


def test_annual_report_supports_only_own_year_scope():
    title = '固定测试公司2025年年度报告'
    source = SourceRecord(kind='upload', title=title,
                          content=title + '\n公司成立于2020年，2026年第一季度计划……\n2025年 第一季度 第二季度 第三季度 第四季度')
    assert supports_period(source, '2025A') and supports_period(source, '2024A') and supports_period(source, '2023A')
    assert not supports_period(source, '2022A') and not supports_period(source, '2020A')
    assert all(supports_period(source, '2025' + q) for q in ('1Q', '2Q', '3Q', '4Q'))
    for period in ('2025Q1', '2025H1', '2025Q3', '20261Q', '2026Q1', '20241Q', '2024H1'):
        assert not supports_period(source, period), period


async def test_truncated_window_is_split_not_resent(tmp_path):
    w, g, store, run = prepared(tmp_path, rows=[])
    c = await context(w)
    w.fixed_collection.initialize(c)
    title = '固定测试公司2025年年度报告'
    source = SourceRecord(kind='upload', title=title, content=title + '\n' + ('2025年 2024年 单位：元\n营业收入 100 90\n' * 400))
    store.execution_put(run.run_id, 'execution_meta', 'fixed-source-manifest',
                        {'bindings': {p: [source.source_id] for p in input_periods(c['brief'])}})
    original = g.structured
    seen = []

    async def truncate_large(role, messages, schema):
        if schema is SlotExtraction:
            size = len(json.loads(messages[-1]['content'])['sources'][0]['content'])
            seen.append(size)
            if size > 6000:
                raise TruncatedOutput('fixture output truncated')
        return await original(role, messages, schema)

    g.structured = truncate_large
    await w.fixed_collection.extract_document(c, source, True)
    windows = [v['sources'][0]['content'] for name, v in g.calls if name == 'SlotExtraction']
    # Every oversized window was sent exactly once, then halved until it fit;
    # the halves cover all original text without overlap.
    assert max(seen) > 6000 and seen.count(max(seen)) == 1
    assert ''.join(windows) == source.content
    assert all(len(text) <= 6000 for text in windows)
    receipts = [r for r in store.execution_list(run.run_id, 'execution_meta')
                if isinstance(r, dict) and r.get('source_id') == source.source_id and 'checked_window' in r]
    assert any(r['state'] == 'split' for r in receipts)
    assert not any(r['state'] == 'failed' for r in receipts)
    count = len(seen)
    await w.fixed_collection.extract_document(c, source, True)
    assert len(seen) == count


@pytest.mark.parametrize('field,row,header,period,index,value', [
    # An unlabelled trailing change column after a complete two-column header.
    ('cashflow.operating_cashflow', '经营活动产生的现金流量净额 120.00 100.00 20.00', '本报告期 上年同期', '2026H1', 0, '120.00'),
    # Empty cells still occupy their columns.
    ('income.investment_income', '投资收益 — 12.00', '项目 本期发生额 上期发生额', '2025H1', 1, '12.00'),
    ('income.other_income', '其他收益 不适用 8.00', '项目 本期数 上年同期数', '2025H1', 1, '8.00'),
    ('balance.inventory', '存货 300.00 280.00', '项目 期末余额 期初余额', '2026H1', 0, '300.00'),
])
async def test_p1_row_shapes_are_aligned(tmp_path, field, row, header, period, index, value):
    w, g, store, run = prepared(tmp_path, rows=[])
    c = await context(w)
    c['brief'].update(quarterly_collection=True, as_of='2026-10-15', interim_period='2026H1')
    title = '固定测试公司2026年半年度报告'
    statement = '合并资产负债表' if field.startswith('balance.') else '合并利润表'
    source = SourceRecord(kind='upload', title=title, content=title + '\n' + statement + '\n单位：元\n' + header + '\n' + row)
    p = SlotProposal(field_id=field, period=period, raw_value=value, raw_unit='元', quote=row,
                     header_quote=header, unit_quote='单位：元', column_index=index)
    assert not w.fixed_collection.accept(c, source, p.model_copy(update={'column_index': 1 - index}))
    assert w.fixed_collection.accept(c, source, p)


async def test_repair_request_carries_rejection_reason(tmp_path):
    w, g, store, run = prepared(tmp_path, rows=[])
    c = await context(w)
    w.fixed_collection.initialize(c)
    title = '固定测试公司2025年年度报告'
    source = SourceRecord(kind='upload', title=title, content=title + '\n合并利润表\n单位：元\n2025年 2024年\n营业收入 100 90\n')
    store.execution_put(run.run_id, 'execution_meta', 'fixed-source-manifest',
                        {'bindings': {p: [source.source_id] for p in input_periods(c['brief'])}})
    g.values = [dict(field_id='income.revenue', period='2025A', raw_value='100', raw_unit='元',
                     quote='营业收入 100 90', header_quote='2025年 2024年', column_index=1)]
    await w.fixed_collection.extract_document(c, source, True)
    repairs = [v for name, v in g.calls if name == 'SlotExtraction' and v.get('rejected_values')]
    assert repairs and 'column_index' in repairs[0]['rejected_values'][0]['reject_reason']
