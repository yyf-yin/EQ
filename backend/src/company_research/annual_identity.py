"""Resolve the reporting issuer from this run's uploaded annual reports."""

import json
import re

from .agents import ask
from .contexts import source_context
from .datasources import DatasourceError
from .schemas import Company


def compact(value):
    return re.sub(r'\s+', '', str(value))


async def resolve_annual_identity(reports, user_input, gateway, local_rows):
    query = compact(user_input)
    candidates = []
    for source in reports:
        try:
            row = json.loads(source.content)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        name = row.get('company_name') or row.get('name')
        ticker = str(row.get('ticker', ''))
        names = [compact(row.get(k, '')) for k in ('company_name', 'name', 'security_name', 'ticker', 'company_id')]
        if name and re.fullmatch(r'\d{6}', ticker) and query in names:
            candidates.append((source, row, name, ticker))
    if len({(name, ticker) for _, _, name, ticker in candidates}) > 1:
        raise DatasourceError('上传年报存在多个证券主体，请使用证券代码明确研究公司')
    if candidates:
        source, row, name, ticker = candidates[0]
        company = Company(
            company_id=str(row.get('company_id') or f"{row.get('market', 'A股')}:{ticker}"),
            name=name,
            ticker=ticker,
            market=row.get('market', 'A股'),
            financial_company=row.get('financial_company', False),
            source_ids=[source.source_id],
        )
    else:
        selected = source_context(
            reports,
            user_input + ' 公司信息 公司简介 中文名称 公司全称 股票简称 股票代码 证券简称 证券代码 上市交易所',
            gateway.limits('resolver').input_capacity - 4000,
        )
        company = await ask(gateway, 'resolver', Company, {
            'input': user_input,
            'sources': selected,
            'instructions': [
                '从本次上传年报的封面、公司简介、股票简况确认报告发行人身份。',
                '只选择与用户输入的公司全称、证券简称或证券代码一致的主体；不得采用股东、子公司或同行的身份。',
                '公司全称和六位证券代码必须在引用的同一份年报正文中出现；保留代码前导零。',
                '引用实际年报 source_id；不得使用网页、记忆或推测补充；无法确认或存在歧义时返回空 ticker 或 source_ids。',
            ],
        })
        known = {s.source_id: s for s in reports}
        if (
            not company.name.strip()
            or not re.fullmatch(r'\d{6}', company.ticker)
            or not company.source_ids
            or not set(company.source_ids) <= known.keys()
            or (re.fullmatch(r'\d{6}', query) and query != company.ticker)
            or not all(
                compact(company.name) in compact(known[k].content)
                and re.search(r'(?<!\d)' + re.escape(company.ticker) + r'(?!\d)', compact(known[k].content))
                and (query == company.ticker or query in compact(known[k].content))
                for k in company.source_ids
            )
        ):
            raise DatasourceError('上传年报不足以确认本公司全称及证券代码，请检查研究名称或补充含公司简介、股票简况的完整年报')
        # Use a stable identifier, never an identifier invented by the model.
        company.company_id = f'{company.market}:{company.ticker}'

    # Preserve existing structured-data joins when a matching local record exists.
    ids = {
        str(r['company_id']) for r in local_rows
        if r and r.get('company_id') and str(r.get('ticker', '')) == company.ticker
    }
    if len(ids) == 1 and (not candidates or not candidates[0][1].get('company_id')):
        company.company_id = ids.pop()
    return company
