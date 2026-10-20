"""Personal-tool annual inputs: explicit user uploads, no report discovery."""

import json
import re

POLICY = 'user-annual-reports-1'
ANNUAL = r'年报|年度报告|annual[\s_-]*reports?'
SECONDARY = r'研报|证券研究|研究报告|行业报告|点评'


def industry_annual_title(title):
    return bool(re.search(r'行业|产业|协会|统计|市场', title) and not re.search(r'公司|股份|证券代码|股票代码', title))


def peer_excerpt(source):
    """Industry sections cut from CNINFO filings, and the sample shares computed from them
    (peer_disclosures): industry material, not a financial report."""
    url = source.source_url or ''
    return (source.title.startswith('同行公告节选：') and url.startswith('http://static.cninfo.com.cn/')) or (
        source.title.startswith('同行公告汇总计算：') and not url
    )


def annual_document(source, company=None):
    """Identify document type/subject, without scoring source quality."""
    if peer_excerpt(source):
        return False
    try:
        row = json.loads(source.content)
    except (ValueError, TypeError):
        row = None
    if isinstance(row, dict):
        return row.get('document_type') == 'annual_report' and (
            company is None or row.get('company_id') == company['company_id']
        )
    title = source.title
    from .reporting_periods import INTERIM

    if re.search(INTERIM, title, re.I):
        return False
    if re.search(SECONDARY, title, re.I):
        return False
    if company is None and industry_annual_title(title):
        return False
    if not re.search(ANNUAL, title, re.I) and re.search(SECONDARY, source.content[:120], re.I):
        return False
    text = title + ' ' + source.content[:1200]
    if not re.search(ANNUAL, title, re.I) and re.search(INTERIM, source.content[:1200], re.I):
        return False
    return bool(re.search(ANNUAL, text, re.I)) and (
        company is None or company['name'] in text or (company.get('ticker') and company['ticker'] in text)
    )


def annual_filename(name):
    return (
        bool(re.search(ANNUAL, name, re.I)) and not re.search(SECONDARY, name, re.I) and not industry_annual_title(name)
    )


def annual_search_result(result):
    if industry_annual_title(result.get('title', '')):
        return False
    text = ' '.join(str(result.get(k) or '') for k in ('title', 'description', 'snippet', 'content'))
    if re.search(SECONDARY, text, re.I):
        return False
    return bool(re.search(ANNUAL, text, re.I) or re.search(r'annual[\s_/-]*reports?', result.get('url', ''), re.I))
