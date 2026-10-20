"""Eastmoney broker reports as industry material, with AKShare and HTTP mocked offline."""
import io
from datetime import date
from types import SimpleNamespace

import httpx
import pandas as pd
from reportlab.pdfgen import canvas

from company_research.datasources import WebAdapter
from company_research.research_reports import ResearchReports, select
from company_research.schemas import SourceRecord
from company_research.storage import Store
from test_material_collection import setup

AS_OF = date(2026, 10, 14)


def pdf(text):
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer)
    page.drawString(50, 700, text)
    page.save()
    return buffer.getvalue()


class FakeAk:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def stock_research_report_em(self, symbol):
        self.calls += 1
        if self.fail:
            raise ConnectionError('akshare down')
        return pd.DataFrame([
            {'报告名称': '公司深度报告：渠道改革', '机构': '甲证券', '日期': date(2026, 9, 1),
             '报告PDF链接': 'https://pdf.dfcfw.com/pdf/H3_C1_1.pdf', '行业': '白酒Ⅱ'},
            {'报告名称': '2026年中报点评', '机构': '乙证券', '日期': date(2026, 8, 30),
             '报告PDF链接': 'https://pdf.dfcfw.com/pdf/H3_C2_1.pdf', '行业': '白酒Ⅱ'},
            {'报告名称': '旧深度报告', '机构': '丙证券', '日期': date(2024, 1, 5),
             '报告PDF链接': 'https://pdf.dfcfw.com/pdf/H3_C3_1.pdf', '行业': '白酒Ⅱ'},
        ])


def eastmoney(listing=200, pdf_status=None, log=None):
    def handler(request):
        if log is not None:
            log.append(str(request.url))
        if request.url.host == 'reportapi.eastmoney.com':
            if listing != 200:
                return httpx.Response(listing)
            q = request.url.params
            assert q['beginTime'] == '2025-07-14' and q['endTime'] == '2026-10-14'
            if q['qType'] == '0':
                assert q['code'] == '600519'
                return httpx.Response(200, json={'data': [
                    {'infoCode': 'J1', 'title': '公司跟踪：动销平稳', 'orgSName': '丁证券',
                     'publishDate': '2026-09-20 00:00:00.000', 'indvInduCode': '1277', 'indvInduName': '白酒Ⅱ'}]})
            assert q['qType'] == '1' and q['industryCode'] == '1277'
            return httpx.Response(200, json={'data': [
                {'infoCode': 'I1', 'title': '白酒行业深度：周期复盘与展望', 'orgSName': '戊证券',
                 'publishDate': '2026-06-30 00:00:00.000', 'attachPages': 40, 'indvInduName': '白酒Ⅱ'},
                {'infoCode': 'I2', 'title': '食品饮料行业周报：双节动销', 'orgSName': '己证券',
                 'publishDate': '2026-10-12 00:00:00.000', 'attachPages': 12, 'indvInduName': '白酒Ⅱ'}]})
        assert request.url.host == 'pdf.dfcfw.com'
        if pdf_status:
            return httpx.Response(pdf_status)
        return httpx.Response(200, content=pdf('Report ' + request.url.path), headers={'content-type': 'application/pdf'})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def public(url):
    return None


def test_deep_industry_reports_rank_before_weekly_notes_and_reviews():
    reports = [
        dict(kind='industry', title='行业周报', url='a', date='2026-10-12', pages=12),
        dict(kind='company', title='公司深度报告', url='b', date='2026-09-01', pages=0),
        dict(kind='industry', title='行业深度：复盘', url='c', date='2026-06-30', pages=40),
        dict(kind='company', title='中报点评', url='d', date='2026-08-30', pages=0),
        dict(kind='industry', title='行业深度：复盘', url='c', date='2026-06-30', pages=40),
    ]
    assert [r['url'] for r in select(reports, 3)] == ['c', 'b', 'a']


async def test_reports_are_listed_filtered_read_and_cached_per_run(tmp_path, monkeypatch):
    monkeypatch.setattr('company_research.datasources.validate_public_url', public)
    store, ak, log = Store(tmp_path / 'db'), FakeAk(), []
    async with eastmoney(log=log) as client:
        reports = ResearchReports(WebAdapter(None, store, client, run_id='a'), client, ak)
        sources, warnings = await reports.fetch('600519', AS_OF, 15, 3)
        assert not warnings
        assert [s.title for s in sources] == [
            '戊证券行业研报：白酒行业深度：周期复盘与展望', '甲证券公司研报：公司深度报告：渠道改革',
            '己证券行业研报：食品饮料行业周报：双节动销']
        assert all(s.kind == 'web' and s.source_url.startswith('https://pdf.dfcfw.com/') for s in sources)
        assert sources[0].publication_date == '2026-06-30' and sources[0].locator == 'page:1'
        listed, _ = await reports.listing('600519', AS_OF, 15)
        assert 'https://pdf.dfcfw.com/pdf/H3_C3_1.pdf' not in {r['url'] for r in listed}  # outside the window
        calls, requests = ak.calls, len(log)
        await reports.fetch('600519', AS_OF, 15, 3)
        assert ak.calls == calls and len(log) == requests  # same run: listing and PDFs from cache
        other = ResearchReports(WebAdapter(None, store, client, run_id='b'), client, ak)
        await other.fetch('600519', AS_OF, 15, 3)
        assert ak.calls == calls + 1 and len(log) > requests


async def test_failures_degrade_without_raising(tmp_path, monkeypatch):
    monkeypatch.setattr('company_research.datasources.validate_public_url', public)
    store = Store(tmp_path / 'db')
    # AKShare down: company reports come from the Eastmoney JSON instead.
    async with eastmoney() as client:
        reports = ResearchReports(WebAdapter(None, store, client, run_id='a'), client, FakeAk(fail=True))
        listed, warnings = await reports.listing('600519', AS_OF, 15)
        assert not warnings and {r['title'] for r in listed} >= {'公司跟踪：动销平稳', '白酒行业深度：周期复盘与展望'}
    # Both listings down: nothing, two warnings, no exception.
    async with eastmoney(listing=503) as client:
        reports = ResearchReports(WebAdapter(None, store, client, run_id='b'), client, FakeAk(fail=True))
        sources, warnings = await reports.fetch('600519', AS_OF, 15, 3)
        assert sources == [] and len(warnings) == 2
    # PDFs unavailable: listed but unread reports are reported, not raised.
    async with eastmoney(pdf_status=404) as client:
        reports = ResearchReports(WebAdapter(None, store, client, run_id='c'), client, FakeAk())
        sources, warnings = await reports.fetch('600519', AS_OF, 15, 2)
        assert sources == [] and warnings == ['2 份券商研报 PDF 读取失败']


async def collection(tmp_path, **options):
    collector, c, task, requests, reads, gateway = await setup(tmp_path, **options)
    c['company']['ticker'] = '600519'
    retrieve = collector.w.datasource.retrieve

    async def tolerant(query, **kwargs):  # source-filter options are not this test's concern
        return await retrieve(query)

    collector.w.datasource.retrieve = tolerant
    return collector, c, task, requests, reads


def report_source(i):
    return SourceRecord(source_id=f'report-{i}', kind='web', title=f'甲证券行业研报：制造业深度{i}',
        content=f'制造业市场规模第{i}份研报原文', source_url=f'https://pdf.dfcfw.com/pdf/H3_R{i}_1.pdf',
        publication_date='2026-06-30')


async def test_industry_slot_reads_reports_first_within_its_document_budget(tmp_path):
    collector, c, task, requests, reads = await collection(
        tmp_path, material_industry_document_budget=3, research_report_limit=4)
    calls = []

    async def fetch(code, as_of, months, limit):
        calls.append((code, as_of, months, limit))
        assert requests == []  # before any web search
        return [report_source(i) for i in range(4)], []

    collector.w.reports = SimpleNamespace(fetch=fetch)
    await collector.collect(c)
    slot = collector.slot(task)
    assert calls == [('600519', date(2026, 10, 14), 15, 4)]
    assert reads == ['report-0', 'report-1', 'report-2']  # the fourth exceeds the industry budget
    assert slot['reports']['processed'] and slot['reports']['source_ids'][:3] == reads
    assert slot['stop_reason'] == 'document_budget' and requests == []
    assert set(slot['evidence_ids']) >= {e['evidence_id'] for e in collector.store.records(collector.run_id, 'evidence')}
    # A resumed collection neither fetches nor reads the reports again.
    slot['state'] = 'pending'
    collector.store.record(collector.run_id, 'collection_slot', task['task_id'], slot)
    await collector.collect(c)
    assert len(calls) == 1 and len(reads) == 3


async def test_report_failure_falls_back_to_web_search(tmp_path):
    collector, c, task, requests, reads = await collection(tmp_path)

    async def fetch(*args):
        raise RuntimeError('eastmoney down')

    collector.w.reports = SimpleNamespace(fetch=fetch)
    result = await collector.collect(c)
    slot = collector.slot(task)
    assert slot['reports']['warnings'] == ['券商研报获取失败：RuntimeError'] and slot['reports']['processed']
    assert requests and reads == []  # web search ran as before
    assert not any('券商研报' in v for v in result['material_collections'][0]['limitations'])


async def test_reports_off_or_without_a_code_change_nothing(tmp_path):
    collector, c, task, requests, _ = await collection(tmp_path)
    c['company']['ticker'] = ''

    async def fetch(*args):
        raise AssertionError('not called')

    collector.w.reports = SimpleNamespace(fetch=fetch)  # fixture company has no six-digit code
    await collector.collect(c)
    assert 'reports' not in collector.slot(task) and requests
