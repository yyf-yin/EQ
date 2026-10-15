"""Quarter/current-year gates tested with local synthetic disclosures only."""
import json
from decimal import Decimal

import pytest

from company_research.comparisons import build_comparisons
from company_research.fixed_collection import SlotProposal, financial_source
from company_research.financials.formulas import FinancialError
from company_research.reporting_periods import (canonical_period, period_metadata, report_period, financial_document,
    period_columns, latest_interim, supports_period)
from company_research.schemas import SourceRecord, ResearchBrief, FinancialFact
from company_research.annual_reports import annual_document
from test_fixed_collection import prepared, context


def report(period, *, kind='upload', publication_date=None):
    title={'Q1':'第一季度报告','H1':'半年度报告','Q3':'第三季度报告'}[period[4:]]
    return SourceRecord(kind=kind,title=f'固定测试公司{period[:4]}年{title}',
        content=f'固定测试公司{period[:4]}年{title}\n合并利润表\n单位：百万元',publication_date=publication_date)


def test_report_identification_latest_disclosed_and_dates():
    company=dict(company_id='FIX',name='固定测试公司',ticker='000123')
    sources=[report('2026Q1'),report('2026H1'),report('2026Q3',publication_date='2026-10-20'),report('2025Q3')]
    assert latest_interim(sources,'2026-10-15')=='2026H1'
    assert latest_interim(sources+[report('2026Q3')],'2026-10-15')=='2026Q3'
    assert latest_interim([report('2026Q3')],'2026-08-01') is None
    assert latest_interim([report('2026H1',kind='web')],'2026-10-15') is None
    assert financial_source(sources[1],company)
    assert not financial_source(report('2026H1',kind='local'),company)
    assert not financial_source(sources[1],dict(company_id='OTHER',name='其他公司',ticker='999999'))
    assert canonical_period('2026Q2')=='2026H1'
    assert canonical_period('20262Q')=='20262Q'
    assert period_metadata('2026H1')['period_start']=='2026-01-01'
    assert period_metadata('20262Q')['period_start']=='2026-04-01'
    assert period_metadata('2026H1','year_end_stock')['period_start']=='2026-06-30'
    assert report_period(sources[2])=='2026Q3'
    assert not annual_document(sources[1],company)
    industry=SourceRecord(kind='web',title='半导体行业统计半年报',content='半导体行业统计半年报，市场统计口径。')
    assert not financial_document(industry)
    for label in ('2026年半年报','2026年中报','2026年中期报告'):
        alternative=sources[1].model_copy(update={'title':'固定测试公司'+label,'content':'固定测试公司'+label})
        assert report_period(alternative)=='2026H1'


def test_quarterly_headers_and_comparative_scope():
    assert period_columns('2025年 第一季度 | 第二季度 | 第三季度 | 第四季度')==['20251Q','20252Q','20253Q','20254Q']
    assert period_columns('2026年1-9月 | 2025年1-9月')==['2026Q3','2025Q3']
    assert supports_period(report('2026H1'),'2025H1')
    assert not supports_period(report('2026H1'),'2025Q1')
    assert not supports_period(report('2026H1'),'2025A')


async def test_latest_pair_required_historical_quarters_optional_and_yoy(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    c.update(await w.research_plan(c));c.update(await w.dependencies(c));c.update(await w.data_gaps(c))
    slots=store.records(run.run_id,'data_slot')
    assert c['brief']['interim_period']=='2026H1'
    mandatory=[s for s in slots if s['requirement']=='C' and not s['period'].endswith('A')]
    assert {s['period'] for s in mandatory}=={'2026H1','2025H1'}
    assert len(mandatory)==10 and all(s['state']=='locked' for s in mandatory)
    old=next(s for s in slots if s['field_id']=='income.revenue' and s['period']=='20232Q')
    assert old['normalized_value'] is None and old['requirement']=='O'
    assert any(s['segment_id']=='设备' and s['period']=='2026H1' for s in slots)
    await w.human_gate(c)
    comparisons,calculations,gaps=build_comparisons(ResearchBrief.model_validate(c['brief']),[FinancialFact.model_validate(f) for f in c['facts']])
    assert not gaps
    interim=[cmp for cmp in comparisons if cmp.current_period=='2026H1']
    assert len(interim)==5 and all(cmp.previous_period=='2025H1' for cmp in interim)
    assert all(cmp.rate==Decimal(0) for cmp in interim)
    before=len(g.calls);saved=[s for s in mandatory]
    c.update(await w.research_plan(c))
    assert len(g.calls)==before
    assert [s for s in store.records(run.run_id,'data_slot') if s['slot_id'] in {v['slot_id'] for v in saved}]==saved


async def test_missing_current_year_cannot_pass_gate(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    c['sources']=[s for s in c['sources'] if s['title']!='interim.json']
    c.update(await w.research_plan(c));c.update(await w.dependencies(c));c.update(await w.data_gaps(c))
    assert c['brief']['interim_period'] is None
    assert all(s['state']=='locked' for s in store.records(run.run_id,'data_slot') if s['requirement']=='C')
    with pytest.raises(FinancialError,match='研究当年最新'):await w.human_gate(c)


async def test_missing_comparative_cannot_pass_gate(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    c['sources']=[s for s in c['sources'] if s['title']!='interim.json' or json.loads(s['content'])['period']=='2026H1']
    c.update(await w.research_plan(c));c.update(await w.dependencies(c));c.update(await w.data_gaps(c))
    assert any(d['period']=='2025H1' and d['priority']=='critical' for d in c['missing'])
    with pytest.raises(FinancialError,match='2025H1'):await w.human_gate(c)


async def test_annual_quarter_table_is_single_quarter_not_cumulative(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    c['brief'].update(quarterly_collection=True,as_of='2026-10-15',interim_period='2026H1')
    w.fixed_collection.initialize(c)
    source=SourceRecord(source_id='quarters',kind='upload',title='固定测试公司2025年年度报告',
        content='固定测试公司2025年年度报告\n分季度主要财务数据\n单位：百万元\n2025年 第一季度 | 第二季度 | 第三季度 | 第四季度\n营业收入 | 10 | 20 | 30 | 40')
    p=SlotProposal(field_id='income.revenue',period='20252Q',raw_value='20',raw_unit='百万元',
        quote='营业收入 | 10 | 20 | 30 | 40',header_quote='2025年 第一季度 | 第二季度 | 第三季度 | 第四季度',unit_quote='单位：百万元',column_index=1)
    assert w.fixed_collection.accept(c,source,p)
    assert not w.fixed_collection.accept(c,source,p.model_copy(update={'period':'2025H1'}))
    assert not w.fixed_collection.accept(c,source,p.model_copy(update={'period':'2025A'}))
    assert not w.fixed_collection.accept(c,source,p.model_copy(update={'period':'20253Q','column_index':2}))


async def test_interim_numeric_column_check_and_cumulative_not_single(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    c['brief'].update(quarterly_collection=True,as_of='2026-10-15',interim_period='2026H1')
    w.fixed_collection.initialize(c)
    source=report('2026H1').model_copy(update={'content':report('2026H1').content+'\n2026年1-6月 | 2025年1-6月\n营业收入 | 120 | 100'})
    p=SlotProposal(field_id='income.revenue',period='2026H1',raw_value='100',raw_unit='百万元',
        quote='营业收入 | 120 | 100',header_quote='2026年1-6月 | 2025年1-6月',unit_quote='单位：百万元',column_index=0)
    assert not w.fixed_collection.accept(c,source,p)
    assert not w.fixed_collection.accept(c,source,p.model_copy(update={'period':'20262Q','raw_value':'120'}))
    assert w.fixed_collection.accept(c,source,p.model_copy(update={'raw_value':'120'}))
    assert w.fixed_collection.accept(c,source,p.model_copy(update={'period':'2025H1','column_index':1}))
    brief=ResearchBrief.model_validate(c['brief'])
    comparisons,_,_=build_comparisons(brief,[FinancialFact.model_validate(f) for f in w.fixed_collection.facts(c)])
    cmp=next(v for v in comparisons if v.metric_code=='revenue' and v.current_period=='2026H1')
    assert cmp.delta==Decimal('20') and cmp.rate==Decimal('.2')


async def test_structured_quarter_cannot_masquerade_as_annual(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    c['brief'].update(quarterly_collection=True,as_of='2026-10-15',interim_period='2026H1')
    w.fixed_collection.initialize(c)
    source=SourceRecord(kind='upload',title='data.json',content=json.dumps(dict(document_type='interim_report',company_id='FIX',
        report_period='2026H1',period='2025A',period_kind='quarter_flow',field_id='income.revenue',value='999',unit='CNY_million')))
    await w.fixed_collection.extract_document(c,source,quantitative=True)
    assert not [s for s in store.records(run.run_id,'data_slot') if s['state']=='locked' and s['field_id']=='income.revenue']


async def test_balance_previous_year_end_is_not_previous_same_quarter(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    c['brief'].update(quarterly_collection=True,as_of='2026-10-15',interim_period='2026H1')
    w.fixed_collection.initialize(c)
    source=report('2026H1').model_copy(update={'content':report('2026H1').content+'\n合并资产负债表\n2026年6月30日 | 2025年12月31日\n货币资金 | 120 | 100'})
    p=SlotProposal(field_id='balance.cash',period='2025H1',raw_value='100',raw_unit='百万元',
        quote='货币资金 | 120 | 100',header_quote='2026年6月30日 | 2025年12月31日',unit_quote='单位：百万元',column_index=1)
    assert not w.fixed_collection.accept(c,source,p)
    assert w.fixed_collection.accept(c,source,p.model_copy(update={'period':'2026H1','raw_value':'120','column_index':0}))
    # Year-only balances have ambiguous as-of dates and cannot be assumed to be June.
    ambiguous=source.model_copy(update={'content':source.content+'\n2026年 | 2025年'})
    assert not w.fixed_collection.accept(c,ambiguous,p.model_copy(update={'header_quote':'2026年 | 2025年'}))


async def test_first_quarter_report_and_latest_report_not_downgraded(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    c['brief'].update(quarterly_collection=True,as_of='2026-10-15',interim_period='2026Q1')
    w.fixed_collection.initialize(c)
    source=report('2026Q1').model_copy(update={'content':report('2026Q1').content+'\n2026年第一季度 | 2025年第一季度\n营业收入 | 30 | 20'})
    p=SlotProposal(field_id='income.revenue',period='2026Q1',raw_value='30',raw_unit='百万元',quote='营业收入 | 30 | 20',
        header_quote='2026年第一季度 | 2025年第一季度',unit_quote='单位：百万元',column_index=0)
    assert w.fixed_collection.accept(c,source,p)
    # A later report without extracted figures must not silently fall back to H1.
    (tmp_path/'later').mkdir()
    w2,g2,store2,run2=prepared(tmp_path/'later');c2=await context(w2)
    c2['sources'].append(report('2026Q3').model_dump(mode='json'))
    c2.update(await w2.research_plan(c2));c2.update(await w2.dependencies(c2));c2.update(await w2.data_gaps(c2))
    assert c2['brief']['interim_period']=='2026Q3'
    with pytest.raises(FinancialError,match='2026Q3'):await w2.human_gate(c2)
