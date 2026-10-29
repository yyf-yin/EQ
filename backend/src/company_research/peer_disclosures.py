"""Peer filings from CNINFO, read as industry material, and concentration computed from them.

The peers are the largest Shenwan level-3 constituents (market_data). For the company and
each peer, the latest annual report and, when issued within a few years, the prospectus
are listed through AKShare (stock_zh_a_disclosure_report_cninfo) and downloaded from
static.cninfo.com.cn. Only the industry, competition and operating-data sections are kept,
each window prefixed with its page marker, so quotes keep page locators.

Revenue (and sales volume, when every filing states it in the same unit) parsed from the
same filings gives each company's share of the sample and CR3/CR5. These are shares of the
listed companies read here, never of the whole industry; every line says so.
Any failure only leaves fewer filings and a warning.
"""

import asyncio
import io
import re
from datetime import date, timedelta

import httpx

from .datasources import source_record
from .market_data import call, constituents, industry

PDF_URL = 'http://static.cninfo.com.cn/finalpage/{}/{}.PDF'
HEADERS = {'User-Agent': 'Mozilla/5.0 CompanyResearch/0.1', 'Referer': 'http://www.cninfo.com.cn/'}
TITLE = '同行公告节选'  # annual_reports.annual_document never treats these excerpts as financial reports.
MAX_BYTES = 60 * 1024 * 1024
ANNUAL_PAGES = 80  # The management discussion sits in the first third of an annual report.
PROSPECTUS_PAGES = 450
ANNUAL_TITLE = re.compile(r'(20\d{2})\s*年\s*(?:年度报告|年报)(?:全文)?(?:（(?:修订|更新)[^）]*）)?')
PROSPECTUS_TITLE = re.compile(r'招股(?:说明书|意向书)')
EXCLUDED = re.compile(r'摘要|英文|English|取消|提示性|附录|意见|更正公告|保荐|法律|问询|回复|鉴证|核查|审计报告|申报稿')
VOLUME_TABLE = r'产销量情况分析表|主要产品生产、销售和库存量|产销量情况|生产量、销售量、库存量'
# (pattern, window in characters) per kind of filing; windows are merged and capped.
SECTIONS = {
    'annual': [
        (r'所处(?:的)?行业(?:的)?(?:基本)?情况', 4000),
        (r'行业基本情况', 3000),
        (r'行业格局和趋势|行业竞争格局和发展趋势|所处行业(?:的)?发展前景', 4000),
        (r'行业经营性信息分析', 3500),
        (r'主要经营数据', 2500),
        (VOLUME_TABLE, 2000),
    ],
    'prospectus': [
        (r'发行人所处行业(?:的)?基本情况|所处行业(?:的)?基本情况', 16000),
        (r'(?:行业|市场)竞争(?:格局|状况|情况)', 6000),
    ],
}
PAGE = re.compile(r'^\[page:\d+\]$', re.M)
TOC_LINE = re.compile(r'(?:\.{4,}|…{2,}|·{4,})\s*\d*\s*$')
REVENUE = re.compile(r'营业(?:总)?收入\s*(?:（元）|\(元\))?\s+(-?[\d,]+\.\d{2})')
NUMBER = r'-?[\d,]+(?:\.\d+)?'
UNITS = r'万千升|千升|万吨|吨|万箱|箱|万瓶|瓶|万台|台|万辆|辆|万件|件|万平方米|平方米|万套|套|兆瓦|GWh|MWh|万片|片'


def clean(title: str) -> str:
    return re.sub(r'<[^>]+>|\s', '', str(title or ''))


def number(text: str) -> float:
    return float(text.replace(',', ''))


def choose(rows: list[dict], pattern: re.Pattern, as_of: str) -> dict | None:
    """Latest matching, non-excluded filing on or before as_of; final versions before drafts."""
    found = [r for r in rows if pattern.search(r['title']) and not EXCLUDED.search(r['title']) and r['date'] <= as_of]
    return max(found, key=lambda r: ('意向书' not in r['title'], r['date'], r['url']), default=None)


def pages_text(data: bytes, limit: int) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return '\n'.join(f'[page:{i + 1}]\n' + (p.extract_text() or '') for i, p in enumerate(reader.pages[:limit]))


def anchors(text: str, pattern: str):
    """Heading occurrences in the body; table-of-contents lines ('……12') are skipped."""
    for m in re.finditer(pattern, text):
        end = text.find('\n', m.end())
        line = text[text.rfind('\n', 0, m.start()) + 1 : end if end >= 0 else len(text)]
        if not TOC_LINE.search(line):
            yield m.start()


def excerpt(text: str, kind: str, limit: int, extra: list[tuple[int, int]] = ()) -> str:
    """The industry sections of a filing, each window starting with its page marker."""
    spans = []
    for pattern, size in SECTIONS[kind]:
        start = next(anchors(text, pattern), None)
        if start is not None:
            spans.append((text.rfind('\n', 0, start) + 1, min(len(text), start + size)))
    spans = sorted(spans + list(extra))
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    parts, size = [], 0
    for start, end in merged:
        end = min(end, start + limit - size)
        if end <= start:
            break
        markers = [m for m in PAGE.finditer(text, 0, start + 1)]
        body = text[start:end]
        if markers and not body.startswith('[page:'):
            # Begin at the line start so the page marker precedes whole lines.
            line = text.rfind('\n', markers[-1].end(), start) + 1
            body = markers[-1].group(0) + '\n' + text[max(line, markers[-1].end() + 1) : end]
        parts.append(body.strip())
        size += end - start
    return '\n……\n'.join(parts)


def page_of(text: str, offset: int) -> str:
    markers = PAGE.findall(text, 0, offset + 1)
    return markers[-1][6:-1] if markers else '?'


def revenue(text: str):
    """Operating revenue in yuan from the key accounting data table, with its span."""
    head = text.find('主要会计数据')
    m = REVENUE.search(text, max(head, 0))
    if not m:
        return None
    scale = 1e4 if '万元' in text[max(0, m.start() - 400) : m.start()] else 1
    return number(m.group(1)) * scale, (m.start(), m.end())


def volume(text: str):
    """Total sales volume and unit from the production and sales table, when unambiguous."""
    # SZSE industry table: "行业分类 项目 单位 2025 年 2024 年" then "销售量 吨 119,370.77 128,301.64 -6.96%";
    # its first row is the whole industry category of the company.
    m = re.search(rf'^销售量\s+({UNITS})\s+({NUMBER})\s', text, re.M)
    if m:
        return number(m.group(2)), m.group(1), (text.rfind('\n', 0, max(0, m.start() - 200)) + 1, m.end() + 300)
    start = next(anchors(text, VOLUME_TABLE), None)
    if start is None:
        return None
    region = text[start : start + 2500]
    span = (start, start + min(len(region), 1500))
    # SSE template: "主要产品 单位 生产量 销售量 库存量 ..." then "酒类 吨 104,384.50 83,332.76 ..."
    if re.search(r'单位\s+生产量\s+销售量', region):
        rows = re.findall(rf'^(\S+)\s+({UNITS})\s+({NUMBER})\s+({NUMBER})\s', region, re.M)
        row = next((r for r in rows if r[0] == '合计'), rows[0] if len(rows) == 1 else None)
        if row:
            return number(row[3]), row[1], span
    # Quantity columns with the unit in the header: "期初库存量（吨） 生产量（吨） 销售量（吨） 期末库存量（吨）"
    header = re.search(rf'((?:\S*量（(?:{UNITS})）\s*){{3,}})', region)
    total = re.search(r'^合计\s+(.+)$', region, re.M)
    if header and total:
        columns = re.findall(rf'(\S*量)（({UNITS})）', header.group(1))
        values = [v for v in total.group(1).split() if not v.endswith('%') and re.fullmatch(NUMBER, v)]
        names = [c[0] for c in columns]
        if '销售量' in names and len(values) == len(names):
            i = names.index('销售量')
            return number(values[i]), columns[i][1], span
    return None


def percent(value: float) -> str:
    return f'{value * 100:.1f}%'


def concentration(figures: list[dict], industry_name: str, year: str):
    """Sample shares and CR3/CR5 text plus (metric, subject, line) rows to cite, or None.

    figures: [{name, revenue, revenue_page, volume, unit, volume_page, title, url}] for one
    fiscal year. Volumes are never converted between units: only the companies reporting
    in the most common unit form the volume sample, and the others are named."""
    revenue_rows = [f for f in figures if f.get('revenue')]
    if len(revenue_rows) < 3:
        return None
    sample = f'{industry_name}上市公司样本（{len(revenue_rows)}家）'
    lines = [
        f'同行公告汇总计算：{sample}，{year}年度',
        f'口径说明：分母为本表所列上市公司{year}年合计，是上市公司合计口径，'
        '不是全行业规模，不代表全行业市场份额或集中度。',
    ]
    rows = []
    volumes = [f for f in figures if f.get('volume')]
    unit = max(sorted({f['unit'] for f in volumes}), key=lambda u: sum(f['unit'] == u for f in volumes), default='')
    same = [f for f in volumes if f['unit'] == unit]
    bases = [('营业收入', 'revenue', revenue_rows, '亿元', 1e8, sample)]
    if len(same) >= 3:
        bases.append(('销售量', 'volume', same, unit, 1, f'{industry_name}上市公司样本（{len(same)}家，以{unit}披露）'))
    for basis, key, items, unit_name, scale, group in bases:
        lines.append(f'{basis}样本：{group}')
        others = [f['name'] for f in figures if f not in items]
        if others:
            lines.append(f'未计入{basis}样本：' + '、'.join(others) + '（未披露或计量单位不同，不作换算）')
        for f in items:
            amount = f'{f[key] / scale:,.2f}{unit_name}'
            lines.append(f'{f["name"]} {year}年{basis} {amount}（{f["title"]}，第{f[key + "_page"]}页，{f["url"]}）')
        total = sum(f[key] for f in items)
        lines.append(f'样本合计{basis} {total / scale:,.2f}{unit_name}（上市公司合计口径）')
        ranked = sorted(items, key=lambda f: -f[key])
        for f in ranked:
            line = f'{f["name"]}占样本{basis}比重（上市公司合计口径）：{percent(f[key] / total)}'
            lines.append(line)
            rows.append((f'占样本{basis}比重', f'{f["name"]}（{group}）', line))
        for k in (3, 5):
            # CR5 of five companies is 100% by construction.
            if len(ranked) > k:
                line = f'样本内{basis}集中度CR{k}（上市公司合计口径）：{percent(sum(f[key] for f in ranked[:k]) / total)}'
                lines.append(line)
                rows.append((f'{basis}CR{k}（上市公司合计口径）', group, line))
    return '\n'.join(lines), rows


class PeerDisclosures:
    def __init__(self, store, run_id, client=None, ak=None):
        self.store, self.scope, self.client, self.ak = store, run_id, client, ak

    def akshare(self):
        if self.ak is None:
            import akshare

            self.ak = akshare
        return self.ak

    def companies(self, code: str, limit: int) -> tuple[str | None, list[dict]]:
        """The company first, then its largest Shenwan level-3 peers by market cap."""
        ak = self.akshare()
        name = industry(ak, code)
        if not name:
            return None, [{'code': code, 'name': ''}]
        _, _, rows = constituents(ak, name)
        own = next((r for r in rows if r['code'] == code), {'code': code, 'name': ''})
        others = sorted((r for r in rows if r['code'] != code and r.get('market_cap')), key=lambda r: -r['market_cap'])
        return name, [own] + others[:limit]

    def filings(self, code: str, as_of: date, years: int) -> list[dict]:
        ak = self.akshare()
        start = as_of.replace(year=as_of.year - years, day=min(as_of.day, 28)).strftime('%Y%m%d')
        end = as_of.strftime('%Y%m%d')
        rows = []
        annual = dict(category='年报', start_date=(as_of - timedelta(days=500)).strftime('%Y%m%d'))
        for options in (annual, dict(keyword='招股说明书', start_date=start)):
            df = call(ak.stock_zh_a_disclosure_report_cninfo, symbol=code, market='沪深京', end_date=end, **options)
            for _, r in df.iterrows() if df is not None else []:
                link = str(r.get('公告链接') or '')
                found = re.search(r'announcementId=(\d+)', link)
                day = str(r.get('公告时间') or '')[:10]
                if found and re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
                    rows.append(
                        dict(
                            title=clean(r.get('公告标题')),
                            name=clean(r.get('简称')),
                            date=day,
                            url=PDF_URL.format(day, found.group(1)),
                            page=link,
                        )
                    )
        return rows

    async def download(self, url: str) -> bytes:
        async def get(client):
            async with client.stream('GET', url, headers=HEADERS) as response:
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError('公告文件超过下载上限')
                    chunks.append(chunk)
                return b''.join(chunks)

        if self.client:
            return await get(self.client)
        async with httpx.AsyncClient(timeout=90, trust_env=False, follow_redirects=False) as client:
            return await get(client)

    async def read(self, company: dict, filing: dict, kind: str, chars: int):
        """(SourceRecord, figures) for one filing; cached for the run by URL."""
        key = f'run:{self.scope}:peer-filing:{filing["url"]}:{kind}:{chars}'
        cached = self.store.cached(key)
        if cached is not None:
            from .schemas import SourceRecord

            return SourceRecord.model_validate(cached['source']), cached['figures']
        data = await self.download(filing['url'])
        text = await asyncio.to_thread(pages_text, data, ANNUAL_PAGES if kind == 'annual' else PROSPECTUS_PAGES)
        figures, extra = {}, []
        if kind == 'annual':
            found = revenue(text)
            if found:
                figures.update(revenue=found[0], revenue_page=page_of(text, found[1][0]))
                extra.append((max(0, found[1][0] - 120), found[1][1] + 100))
            found = volume(text)
            if found:
                figures.update(volume=found[0], unit=found[1], volume_page=page_of(text, found[2][0]))
                extra.append(found[2])
        content = excerpt(text, kind, chars, extra)
        if not content.strip():
            raise ValueError('未找到行业相关章节')
        name = company.get('name') or filing['name']
        label = '招股说明书' if kind == 'prospectus' else '年度披露'
        source = source_record(
            'web',
            f'{TITLE}：{name}（{company["code"]}）{filing["title"]}·{label}行业章节',
            content,
            '全文',
            source_url=filing['url'],
            publication_date=filing['date'],
        )
        result = dict(source=source.model_dump(mode='json'), figures=figures)
        self.store.cache(key, result)
        return source, figures

    async def fetch(self, code: str, as_of: date, peers: int, chars: int, prospectus_years: int):
        """Excerpt sources, a concentration source with the rows to cite, and warnings."""
        warnings = []
        name, companies = await asyncio.to_thread(self.companies, code, peers)
        if not name:
            warnings.append('未取得申万三级行业，未读取同行公告')
            return dict(sources=[], industry=None, year=None, calculation=None, warnings=warnings)
        if len(companies) < 2:
            warnings.append('未取得同行名单')
        listings = await asyncio.gather(
            *(asyncio.to_thread(self.filings, c['code'], as_of, prospectus_years) for c in companies),
            return_exceptions=True,
        )
        jobs = []
        for company, rows in zip(companies, listings):
            if isinstance(rows, BaseException) or not rows:
                warnings.append(f'{company.get("name") or company["code"]} 公告列表获取失败')
                continue
            company['name'] = company.get('name') or rows[0]['name']
            for kind, pattern in (('annual', ANNUAL_TITLE), ('prospectus', PROSPECTUS_TITLE)):
                chosen = choose(rows, pattern, as_of.isoformat())
                if chosen:
                    jobs.append((company, chosen, kind))
        limit = asyncio.Semaphore(3)

        async def one(job):
            async with limit:
                company, filing, kind = job
                return await self.read(company, filing, kind, chars * (2 if kind == 'prospectus' else 1))

        read = await asyncio.gather(*(one(j) for j in jobs), return_exceptions=True)
        sources, figures = [], []
        for (company, filing, kind), result in zip(jobs, read):
            if isinstance(result, BaseException):
                warnings.append(f'{company["name"]}{filing["title"]} 读取失败：{type(result).__name__}')
                continue
            source, values = result
            sources.append(source)
            if kind == 'annual' and values:
                year = ANNUAL_TITLE.search(filing['title']).group(1)
                figures.append(values | dict(name=company['name'], year=year, title=filing['title'], url=filing['url']))
        years = sorted({f['year'] for f in figures}, key=lambda y: (sum(f['year'] == y for f in figures), y))
        year = years[-1] if years else None
        calculation = concentration([f for f in figures if f['year'] == year], name, year) if year else None
        if not calculation:
            warnings.append('可用同行营业收入不足 3 家，未计算样本集中度')
        return dict(
            sources=[s.model_dump(mode='json') for s in sources],
            industry=name,
            year=year,
            calculation=calculation,
            figures=figures,
            warnings=warnings,
        )
