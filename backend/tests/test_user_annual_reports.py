"""User-provided annual reports are the only annual input in fixed mode."""
import json
from types import SimpleNamespace

import httpx
import pytest

from company_research.annual_reports import annual_document, POLICY
from company_research.config import Settings
from company_research.datasources import LocalDatasource, UnifiedDatasource
from company_research.execution import manifest
from company_research.fixed_collection import annual_source
from company_research.financials.formulas import FinancialError
from company_research.graphs import ResearchWorkflow
from company_research.schemas import SourceRecord
from test_fixed_collection import prepared, context, FullGateway


def test_local_and_web_reports_are_not_financial_inputs():
    company=dict(company_id='FIX',name='固定测试公司',ticker='000123')
    report=SourceRecord(kind='upload',title='固定测试公司2025年年度报告',content='固定测试公司2025年年度报告\n主营业务设备。')
    assert annual_source(report,company)
    assert not annual_source(report.model_copy(update={'kind':'local'}),company)
    assert not annual_source(report.model_copy(update={'kind':'web'}),company)
    structured=report.model_copy(update={'title':'data.json','content':json.dumps({'document_type':'annual_report','company_id':'FIX'})})
    assert annual_source(structured,company)


def test_local_index_skips_named_reports_before_parsing_and_filters_structured_reports(tmp_path,monkeypatch):
    from company_research import datasources
    (tmp_path/'2025年度报告.pdf').write_bytes(b'not read by the annual-input path')
    (tmp_path/'archive.json').write_text(json.dumps([{'document_type':'annual_report','company_id':'FIX','period':'2025A','value':'999'}]),encoding='utf-8')
    (tmp_path/'security.json').write_text(json.dumps({'company_id':'FIX','ticker':'000123','company_name':'固定测试公司'}),encoding='utf-8')
    calls=[];original=datasources.parse_material
    def parse(data,suffix):
        calls.append(suffix)
        return original(data,suffix)
    monkeypatch.setattr(datasources,'parse_material',parse)
    local=LocalDatasource(tmp_path);local.build_index(exclude_annual_reports=True)
    assert '.pdf' not in calls and not local.errors
    assert [s.title for s in local.index]==['security.json']


async def test_web_report_candidates_are_skipped_before_reading_and_hidden_reports_are_discarded():
    reads=[]
    async def search(query):return [
        {'title':'固定测试公司2025年年度报告','url':'https://fixture.invalid/annual.pdf'},
        {'title':'制造业供需研究','url':'https://fixture.invalid/industry'},
        {'title':'公告','url':'https://fixture.invalid/notice'},
        {'title':'固定测试公司2025年报点评研报','url':'https://fixture.invalid/review'}]
    async def read(result):
        reads.append(result['url'])
        content='固定测试公司2025年年度报告' if result['title']=='公告' else result['title']
        return [SourceRecord(kind='web',title=result['title'],content=content)]
    local=SimpleNamespace(search=lambda query:[],errors=[])
    datasource=UnifiedDatasource(local,SimpleNamespace(search=search,read=read))
    datasource.exclude_annual_reports=True
    sources,warnings=await datasource.retrieve('制造业 供需')
    assert not warnings and 'https://fixture.invalid/annual.pdf' not in reads
    assert {s.title for s in sources}=={'制造业供需研究','固定测试公司2025年报点评研报'}


async def test_industry_annual_statistics_remain_available_for_qualitative_search():
    from company_research.annual_reports import annual_search_result
    title='中国半导体产业发展年度报告'
    report=SourceRecord(kind='web',title=title,content=title+'\n市场规模与统计口径。')
    assert not annual_document(report)
    result={'title':title,'url':'https://fixture.invalid/annual-report.pdf'}
    assert not annual_search_result(result)
    async def search(query):return [result]
    async def read(result):return [report]
    datasource=UnifiedDatasource(SimpleNamespace(search=lambda query:[],errors=[]),SimpleNamespace(search=search,read=read))
    datasource.exclude_annual_reports=True
    sources,_=await datasource.retrieve('半导体 市场规模')
    assert sources==[report]


def test_explicit_user_report_title_is_not_rejected_for_business_words_in_its_body():
    company=dict(company_id='FIX',name='固定测试公司',ticker='000123')
    source=SourceRecord(kind='upload',title='固定测试公司2025年年度报告',content='固定测试公司2025年年度报告\n公司提供研究报告软件与设备服务。')
    assert annual_source(source,company)


async def test_no_user_report_stops_before_any_brief_or_download_request(tmp_path):
    w,g,store,run=prepared(tmp_path,rows=[])
    (w.settings.local_sources/'固定测试公司2025年年度报告.md').write_text('固定测试公司2025年年度报告\n设备与服务\n营业收入999百万元',encoding='utf-8')
    w=ResearchWorkflow(w.settings,store,run.run_id,g)
    c=await context(w)
    assert not any(annual_document(SourceRecord.model_validate(s)) for s in c['sources'])
    async def forbidden(*args):raise AssertionError('cannot discover a missing annual report')
    w.datasource.retrieve=forbidden
    with pytest.raises(FinancialError,match='请上传本次使用的公司年报'):
        await w.research_brief(c)
    assert not g.calls and not store.records(run.run_id,'human_issue')


async def test_uploaded_inputs_are_frozen_and_ignored_local_reports_do_not_override_or_invalidate(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    assert not any(annual_document(s) for s in w.datasource.local.index)
    before=manifest(w.settings,mode='real')
    (w.settings.local_sources/'固定测试公司2025年年度报告.md').write_text('固定测试公司2025年年度报告\n营业收入999百万元',encoding='utf-8')
    assert manifest(w.settings,mode='real')['sources']==before['sources']
    c.update(await w.research_plan(c))
    financial=[s for s in store.records(run.run_id,'data_slot') if s['field_id']=='income.revenue' and s['state']=='locked']
    assert all(s['raw_value']=='100' for s in financial)
    sources={s['source_id']:s for s in store.records(run.run_id,'source')}
    assert all(sources[s['source_id']]['kind']=='upload' for s in financial)
    saved=store.execution_get(run.run_id,'execution_meta','fixed-source-manifest')
    assert saved['annual_input_policy']==POLICY
    calls=len(g.calls)
    c.update(await w.research_plan(c))
    assert len(g.calls)==calls


async def test_brief_receives_only_user_reports_not_unrelated_local_business_notes(tmp_path):
    w,_,store,run=prepared(tmp_path)
    g=FullGateway();w=ResearchWorkflow(w.settings,store,run.run_id,g)
    c=await context(w)
    c.update(await w.research_brief(c))
    supplied=next(v['sources'] for name,v in g.calls if name=='ResearchBrief')
    reference_ids={s.source_id for s in w.references}
    assert supplied and all(s['source_id'] in reference_ids for s in supplied)
    assert c['brief']['segments']==['设备','服务']


async def test_raw_document_extract_never_reads_unprovided_years_or_creates_human_checks(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    before=len(g.calls)
    report=SourceRecord(kind='web',title='固定测试公司2025年年度报告',content='固定测试公司2025年年度报告\n营业收入999百万元')
    await w.fixed_collection.extract_document(c,report,quantitative=False)
    await w.fixed_collection.extract_document(c,report,quantitative=True)
    assert len(g.calls)==before and not store.records(run.run_id,'human_issue')


async def test_real_start_requires_user_attachment_and_does_not_queue_search(tmp_path,monkeypatch):
    from company_research.api import create_app
    called=[]
    async def run(self,run_id):called.append(run_id)
    monkeypatch.setattr('company_research.runner.Runner.run',run)
    settings=Settings(_env_file=None,mode='real',database=tmp_path/'db',local_sources=tmp_path/'local',artifacts=tmp_path/'out')
    app=create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        startup=(await client.get('/api/startup')).json()
        assert startup['reference_limits']['annual_reports_required']
        response=await client.post('/api/research',json={'company':'固定测试公司'})
        assert response.status_code==422 and '年报' in response.json()['detail']
    assert not called and not app.state.store.active_runs()
