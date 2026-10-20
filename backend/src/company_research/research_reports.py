"""Broker research reports from Eastmoney's research centre, read as industry material.

Company reports are listed through AKShare (stock_research_report_em). AKShare has no
industry report list, so those come from the public JSON behind data.eastmoney.com/report,
filtered by the company's Eastmoney industry; the same JSON also lists company reports
when AKShare fails. PDFs are read through WebAdapter, so the public-URL, redirect and size
checks and the run-scoped cache are the same as for any web document. A failed listing or
download only returns fewer reports and a warning; the slot then relies on web search.
"""

import asyncio
import re
from datetime import date

import httpx

from .datasources import WebAdapter
from .market_data import call

LIST_URL = 'https://reportapi.eastmoney.com/report/list'
PAGE_SIZE, INDUSTRY_PAGES = 100, 3
PDF_URL = 'https://pdf.dfcfw.com/pdf/H3_{}_1.pdf'
HEADERS = {'User-Agent': 'Mozilla/5.0 CompanyResearch/0.1', 'Referer': 'https://data.eastmoney.com/report/'}
# Long-form reports carry industry analysis; weekly notes and result reviews rarely do.
DEPTH = re.compile(r'深度|专题|策略|框架|系列|首次覆盖|全景|产业链|行业研究|复盘|展望|白皮书')
BRIEF = re.compile(r'周报|日报|晨报|早报|周观点|月报|点评|快评|简评|速评|跟踪|纪要|季报|中报|年报|业绩')


def score(report: dict) -> float:
    title = report['title']
    # 白酒Ⅱ -> 白酒: a report naming the company's own industry beats a broader sector note.
    industry = re.sub(r'[ⅠⅡⅢⅣ]+$', '', report.get('industry') or '')
    value = 2 * bool(DEPTH.search(title)) - 2 * bool(BRIEF.search(title)) + (report['kind'] == 'industry')
    value += 2 * bool(industry and industry in title) + bool(re.search(r'证券|研究所', report.get('org') or ''))
    return value + min(report.get('pages') or 0, 40) / 20


def select(reports: list[dict], limit: int) -> list[dict]:
    """Deep industry reports first, newest first among equals; one report per PDF."""
    unique = {r['url']: r for r in reports}
    return sorted(unique.values(), key=lambda r: (score(r), r['date'], r['url']), reverse=True)[:limit]


class ResearchReports:
    def __init__(self, web: WebAdapter, client=None, ak=None):
        self.web, self.store, self.client, self.ak = web, web.store, client, ak

    def company_reports(self, code: str) -> list[dict] | None:
        ak = self.ak
        if ak is None:
            import akshare as ak
        df = call(ak.stock_research_report_em, symbol=code)
        if df is None:
            return None
        reports = []
        for _, row in df.iterrows():
            url = str(row.get('报告PDF链接') or '')
            if not url.startswith('http'):
                continue
            reports.append(
                dict(
                    kind='company',
                    title=str(row.get('报告名称') or '').strip(),
                    org=str(row.get('机构') or '').strip(),
                    date=str(row.get('日期') or '')[:10],
                    url=url,
                    industry=str(row.get('行业') or '').strip(),
                    pages=0,
                )
            )
        return reports

    async def listing_json(self, **params) -> list[dict]:
        query = dict(industryCode='*', industry='*', rating='*', ratingChange='*', fields='', orgCode='', rcode='')
        query.update({'pageNo': 1, **params})
        if self.client:
            response = await self.client.get(LIST_URL, params=query, headers=HEADERS, timeout=30)
        else:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                response = await client.get(LIST_URL, params=query, headers=HEADERS)
        response.raise_for_status()
        data = response.json().get('data')
        if not isinstance(data, list):
            raise ValueError('研报列表不符合预期格式')
        return [item for item in data if isinstance(item, dict) and item.get('infoCode')]

    @staticmethod
    def from_json(item: dict, kind: str) -> dict:
        return dict(
            kind=kind,
            title=str(item.get('title') or '').strip(),
            org=str(item.get('orgSName') or '').strip(),
            date=str(item.get('publishDate') or '')[:10],
            url=PDF_URL.format(item['infoCode']),
            industry=str(item.get('indvInduName') or item.get('industryName') or '').strip(),
            pages=int(item.get('attachPages') or 0),
        )

    async def listing(self, code: str, as_of: date, months: int) -> tuple[list[dict], list[str]]:
        key = f'run:{self.web.cache_scope}:reports:{code}:{as_of.isoformat()}:{months}'
        cached = self.store.cached(key)
        if cached is not None:
            return cached['reports'], cached['warnings']
        year, month = divmod(as_of.year * 12 + as_of.month - 1 - months, 12)
        start = date(year, month + 1, min(as_of.day, 28)).isoformat()
        window = dict(beginTime=start, endTime=as_of.isoformat())
        warnings, reports = [], []
        company = await asyncio.to_thread(self.company_reports, code)
        try:
            listed = await self.listing_json(qType=0, code=code, pageSize=50, **window)
            if company is None:
                company = [self.from_json(item, 'company') for item in listed]
            industry_code = next((str(i['indvInduCode']) for i in listed if i.get('indvInduCode')), '')
            if industry_code:
                # Newest first; a busy industry fills a page in weeks, so read a few pages.
                for page in range(1, INDUSTRY_PAGES + 1):
                    found = await self.listing_json(
                        qType=1, code='*', industryCode=industry_code, pageSize=PAGE_SIZE, pageNo=page, **window
                    )
                    reports += [self.from_json(item, 'industry') for item in found]
                    if len(found) < PAGE_SIZE:
                        break
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            warnings.append('东方财富行业研报列表获取失败')
        if company is None:
            warnings.append('东方财富个股研报列表获取失败')
        reports += company or []
        reports = [r for r in reports if r['title'] and start <= r['date'] <= as_of.isoformat()]
        if not warnings:
            self.store.cache(key, dict(reports=reports, warnings=warnings))
        return reports, warnings

    async def fetch(self, code: str, as_of: date, months: int, limit: int):
        """The selected reports as SourceRecords, plus warnings for what could not be obtained."""
        reports, warnings = await self.listing(code, as_of, months)
        chosen = select(reports, limit)
        read = await asyncio.gather(
            *(
                self.web.read(
                    dict(
                        url=r['url'],
                        title=f"{r['org']}{'行业' if r['kind'] == 'industry' else '公司'}研报：{r['title']}",
                        publication_date=r['date'],
                    )
                )
                for r in chosen
            ),
            return_exceptions=True,
        )
        sources = [s for result in read if not isinstance(result, BaseException) for s in result]
        failed = sum(isinstance(result, BaseException) for result in read)
        if failed:
            warnings = warnings + [f'{failed} 份券商研报 PDF 读取失败']
        return sources, warnings
