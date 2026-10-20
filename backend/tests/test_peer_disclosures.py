"""Peer CNINFO filings as industry material and sample concentration, with AKShare and HTTP mocked offline."""
from datetime import date
from types import SimpleNamespace

import httpx
import pandas as pd

from company_research import peer_disclosures
from company_research.peer_disclosures import PeerDisclosures, concentration, excerpt, revenue, volume
from company_research.reporting_periods import financial_document
from company_research.schemas import SourceRecord
from company_research.storage import Store
from test_research_reports import collection

AS_OF = date(2026, 10, 14)

SSE = '''[page:1]
目录
第三节 管理层讨论与分析……………………12
[page:5]
{name}2025 年年度报告
七、 近三年主要会计数据和财务指标
(一) 主要会计数据
单位：元  币种：人民币
主要会计数据 2025年 2024年 本期比上年同期增减(%)
营业收入 {revenue} 147,693,604,994.14 15.71
[page:9]
{name}2025 年年度报告
二、报告期内公司所处行业情况
2025年全国规模以上白酒企业产量414.5万千升，行业集中度持续提升。
(2). 产销量情况分析表
主要产品 单位 生产量 销售量 库存量 生产量比上年增减（%）
酒类 吨 104,384.50 {sales} 310,008.02 4.24 13.73 5.52
[page:20]
(一) 行业格局和趋势
白酒消费向头部品牌集中。
'''

SZSE = '''[page:7]
{name} 2025 年度报告全文
六、主要会计数据和财务指标
 2025 年 2024 年 本年比上年增减
营业收入（元） {revenue} 83,272,067,317.19 7.09%
[page:9]
第三节 管理层讨论与分析
一、报告期内公司所处行业情况
报告期内，白酒产业处于深度调整期。
1、主要产品生产、销售和库存量
产品
期初库存量（吨） 生产量（吨） 销售量（吨） 期末库存量（吨）
本期数 同比变化 本期数 同比变化 本期数 同比变化 本期数 同比变化
合计 48,322 107.14% 146,461 -20.44% {sales} 1.81% 32,799 -32.12%
'''

PROSPECTUS = '''[page:3]
二、发行人所处行业的基本情况……………………120
[page:120]
二、发行人所处行业的基本情况
（一）行业市场规模
2025年我国白酒市场规模约8,000亿元。
'''

COMPANIES = [
    ('600519', '贵州茅台', 20000, SSE, '170,899,152,276.34', '83,332.76'),
    ('000858', '五粮液', 5000, SZSE, '89,175,178,322.70', '161,984'),
    ('000568', '泸州老窖', 2000, SZSE, '31,195,000,000.00', '60,000'),
    ('600809', '山西汾酒', 3000, SSE, '36,011,000,000.00', '70,000.00'),
    ('002304', '洋河股份', 1500, SZSE, '28,876,000,000.00', '150,000'),
    ('603369', '今世缘', 600, SSE, '11,544,000,000.00', '30,000.00'),
]


class FakeAk:
    def __init__(self, fail=()):
        self.fail, self.listings = set(fail), 0

    def stock_industry_change_cninfo(self, symbol, start_date, end_date):
        return pd.DataFrame([{'分类标准': '申银万国行业分类标准', '变更日期': '2021-07-30', '行业中类': '白酒Ⅲ'}])

    def sw_index_third_info(self):
        return pd.DataFrame([{'行业代码': '850111.SI', '行业名称': '白酒Ⅲ', '静态市盈率': 20, 'TTM(滚动)市盈率': 19, '市净率': 5}])

    def sw_index_third_cons(self, symbol):
        return pd.DataFrame([{'股票代码': code + '.SH', '股票简称': name, '市值': cap} for code, name, cap, *_ in COMPANIES])

    def stock_zh_a_disclosure_report_cninfo(self, symbol, market, end_date, start_date, category='', keyword=''):
        self.listings += 1
        if symbol in self.fail:
            raise ConnectionError('cninfo down')
        name = next(n for c, n, *_ in COMPANIES if c == symbol)
        link = 'http://www.cninfo.com.cn/new/disclosure/detail?stockCode={}&announcementId={}&orgId=x'
        if category == '年报':
            rows = [
                (f'2025年年度报告', '2026-04-02', symbol + '1'),
                (f'2025年年度报告摘要', '2026-04-02', symbol + '2'),
                (f'2025年年度报告（英文版）', '2026-05-02', symbol + '3'),
                (f'2026年第一季度报告', '2026-04-28', symbol + '4'),
            ]
        else:
            assert keyword == '招股说明书' and start_date == '20211014'
            rows = [('首次公开发行股票<em>招股说明书</em>摘要', '2023-03-01', symbol + '5'),
                    ('首次公开发行股票<em>招股说明书</em>', '2023-03-01', symbol + '6')] if symbol == '603369' else []
        return pd.DataFrame([{'代码': symbol, '简称': name, '公告标题': t, '公告时间': d, '公告链接': link.format(symbol, a)}
                             for t, d, a in rows])


def cninfo(missing=(), log=None):
    texts = {}
    for code, name, _, template, rev, sales in COMPANIES:
        texts[code + '1'] = template.format(name=name, revenue=rev, sales=sales)
        texts[code + '6'] = PROSPECTUS

    def handler(request):
        assert request.url.host == 'static.cninfo.com.cn'
        if log is not None:
            log.append(str(request.url))
        key = request.url.path.rsplit('/', 1)[-1].removesuffix('.PDF')
        if key in missing or key not in texts:
            return httpx.Response(404)
        return httpx.Response(200, content=texts[key].encode(), headers={'content-type': 'application/pdf'})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def plain_pages(monkeypatch):
    # The fixture "PDF" is the extracted text itself; real parsing is pypdf's job.
    monkeypatch.setattr(peer_disclosures, 'pages_text', lambda data, limit: data.decode())


def test_sections_figures_and_toc_lines():
    sse = SSE.format(name='贵州茅台', revenue='170,899,152,276.34', sales='83,332.76')
    value, span = revenue(sse)
    assert value == 170899152276.34
    assert volume(sse)[:2] == (83332.76, '吨')
    szse = SZSE.format(name='五粮液', revenue='89,175,178,322.70', sales='161,984')
    assert revenue(szse)[0] == 89175178322.70 and volume(szse)[:2] == (161984.0, '吨')
    text = excerpt(sse, 'annual', 12000)
    assert text.startswith('[page:9]') and '所处行业情况' in text and '[page:20]' in text and '目录' not in text
    assert len(excerpt(sse, 'annual', 60)) <= 80  # capped
    body = excerpt(PROSPECTUS, 'prospectus', 12000)
    assert body.startswith('[page:120]') and '8,000亿元' in body and '……120' not in body


def test_concentration_is_labelled_as_listed_company_sample():
    figures = [dict(name=n, revenue=r, revenue_page='5', volume=v, unit='吨', volume_page='9', title='2025年年度报告',
                    url='http://static.cninfo.com.cn/x.PDF') for n, r, v in
               [('甲', 60e8, 10), ('乙', 20e8, 30), ('丙', 10e8, 20), ('丁', 5e8, 20), ('戊', 3e8, 10), ('己', 2e8, 10)]]
    text, rows = concentration(figures, '白酒Ⅲ', '2025')
    assert '上市公司合计口径' in text and '不是全行业规模' in text
    assert '样本内营业收入集中度CR3（上市公司合计口径）：90.0%' in text
    assert '样本内营业收入集中度CR5（上市公司合计口径）：98.0%' in text
    assert '样本内销售量集中度CR3（上市公司合计口径）：70.0%' in text
    assert '甲占样本营业收入比重（上市公司合计口径）：60.0%' in text
    assert all(line in text and '上市公司合计口径' in line for _, _, line in rows)
    # CR5 of five companies is 100% by construction and is left out; volumes are never
    # converted, so a company reporting in another unit leaves the volume sample, by name.
    figures[0]['unit'] = '千升'
    text, rows = concentration(figures[:5], '白酒Ⅲ', '2025')
    assert 'CR5' not in text and 'CR3' in text
    assert '销售量样本：白酒Ⅲ上市公司样本（4家，以吨披露）' in text and '未计入销售量样本：甲' in text
    assert '样本内销售量集中度CR3（上市公司合计口径）：87.5%' in text  # (30+20+20)/80
    figures[1]['unit'], figures[2]['unit'] = '千升', '万箱'
    assert '销售量' not in concentration(figures[:5], '白酒Ⅲ', '2025')[0]  # no unit shared by three
    assert concentration(figures[:2], '白酒Ⅲ', '2025') is None


async def test_peer_filings_are_listed_excerpted_and_cached_per_run(tmp_path, monkeypatch):
    plain_pages(monkeypatch)
    store, ak, log = Store(tmp_path / 'db'), FakeAk(), []
    async with cninfo(log=log) as client:
        peers = PeerDisclosures(store, 'a', client, ak)
        result = await peers.fetch('000858', AS_OF, 5, 12000, 5)
        assert result['warnings'] == [] and result['industry'] == '白酒Ⅲ' and result['year'] == '2025'
        titles = [s['title'] for s in result['sources']]
        assert titles[0].startswith('同行公告节选：五粮液（000858）2025年年度报告')  # the company itself first
        assert len(titles) == 7 and sum('招股说明书' in t for t in titles) == 1
        assert all(s['source_url'].startswith('http://static.cninfo.com.cn/finalpage/') for s in result['sources'])
        assert all(not financial_document(SourceRecord.model_validate(s)) for s in result['sources'])
        text, rows = result['calculation']
        assert '上市公司样本（6家）' in text and '营业收入CR5（上市公司合计口径）' in {m for m, _, _ in rows}
        assert '贵州茅台 2025年营业收入 1,708.99亿元（2025年年度报告，第5页' in text
        listings, downloads = ak.listings, len(log)
        await peers.fetch('000858', AS_OF, 5, 12000, 5)
        assert len(log) == downloads  # same run: excerpts from cache


async def test_failures_degrade_to_warnings(tmp_path, monkeypatch):
    plain_pages(monkeypatch)
    store = Store(tmp_path / 'db')
    async with cninfo(missing={'0005681'}) as client:
        result = await PeerDisclosures(store, 'a', client, FakeAk(fail={'600809'})).fetch('000858', AS_OF, 5, 12000, 5)
        assert any('山西汾酒' in w and '公告列表获取失败' in w for w in result['warnings'])
        assert any(w.startswith('泸州老窖2025年年度报告 读取失败') for w in result['warnings'])
        assert len(result['sources']) == 5 and '上市公司样本（4家）' in result['calculation'][0]

    class NoIndustry(FakeAk):
        def stock_industry_change_cninfo(self, **kwargs):
            raise ConnectionError('down')

    async with cninfo() as client:
        result = await PeerDisclosures(store, 'b', client, NoIndustry()).fetch('000858', AS_OF, 5, 12000, 5)
        assert result['sources'] == [] and result['calculation'] is None and result['warnings']


def peer_source():
    return SourceRecord(
        source_id='peer-1', kind='web', title='同行公告节选：洋河股份（002304）2025年年度报告·年度披露行业章节',
        content='[page:9]\n五粮液 2025 年度报告全文\n制造业市场规模持续扩大，行业集中度提升。',
        source_url='http://static.cninfo.com.cn/finalpage/2026-04-02/0008581.PDF', publication_date='2026-04-02')


async def test_industry_slot_reads_peer_filings_and_admits_sample_concentration(tmp_path):
    collector, c, task, requests, reads = await collection(tmp_path, material_industry_document_budget=4)
    calls = []
    figures = [dict(name=n, revenue=r, revenue_page='5', title='2025年年度报告', url='http://static.cninfo.com.cn/x.PDF')
               for n, r in [('甲', 60e8), ('乙', 30e8), ('丙', 6e8), ('丁', 4e8)]]

    async def fetch(code, as_of, peers, chars, years):
        calls.append((code, as_of, peers, chars, years))
        assert requests == []  # before any web search
        return dict(sources=[peer_source().model_dump(mode='json')], industry='白酒Ⅲ', year='2025',
                    calculation=concentration(figures, '白酒Ⅲ', '2025'), warnings=['乙 公告列表获取失败'])

    collector.w.peers = SimpleNamespace(fetch=fetch)
    await collector.collect(c)
    slot = collector.slot(task)
    assert calls == [('600519', date(2026, 10, 14), 6, 12000, 5)]
    assert reads == ['peer-1']  # the excerpt is material although its pages say 年度报告
    assert slot['peers']['processed'] and slot['peers']['warnings'] == ['乙 公告列表获取失败']
    data = collector.store.records(collector.run_id, 'industry_data')
    cr3 = next(d for d in data if d['metric'] == '营业收入CR3（上市公司合计口径）')
    assert cr3['value_text'] == '96.0%' and cr3['subject'] == '白酒Ⅲ上市公司样本（4家）' and cr3['period'] == '2025年'
    assert cr3['publisher'] == '根据同行年报计算（上市公司合计口径）'
    assert {d['metric'] for d in data} == {'营业收入CR3（上市公司合计口径）', '占样本营业收入比重'}
    evidence = {e['evidence_id']: e for e in collector.store.records(collector.run_id, 'evidence')}
    assert evidence[cr3['evidence_id']]['quote'] == '样本内营业收入集中度CR3（上市公司合计口径）：96.0%'
    assert cr3['evidence_id'] in slot['evidence_ids']  # offered to the assessor with the slot's material
    # A resumed collection neither fetches nor reads again.
    slot['state'] = 'pending'
    collector.store.record(collector.run_id, 'collection_slot', task['task_id'], slot)
    await collector.collect(c)
    assert len(calls) == 1 and reads == ['peer-1']


async def test_peer_failure_or_switch_off_falls_back_to_web_search(tmp_path):
    collector, c, task, requests, reads = await collection(tmp_path)

    async def fetch(*args):
        raise RuntimeError('cninfo down')

    collector.w.peers = SimpleNamespace(fetch=fetch)
    await collector.collect(c)
    slot = collector.slot(task)
    assert slot['peers']['warnings'] == ['同行公告获取失败：RuntimeError'] and slot['peers']['processed']
    assert requests and reads == []
    assert collector.store.records(collector.run_id, 'industry_data') == []
    # peer_disclosures=false leaves w.peers unset: nothing is fetched.
    (tmp_path / 'off').mkdir()
    collector, c, task, requests, _ = await collection(tmp_path / 'off')
    await collector.collect(c)
    assert 'peers' not in collector.slot(task) and requests


def test_only_cninfo_excerpts_are_exempt_from_financial_report_filter():
    source = peer_source()
    assert not financial_document(source)
    assert financial_document(source.model_copy(update={'source_url': 'https://example.com/a.pdf'}))
