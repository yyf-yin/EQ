"""Where the company's money goes and comes from, read from its own annual reports.

The annual report's 成本分析表 gives each cost item's share of operating cost (直接材料、
直接人工、制造费用…) and its change, and 主要销售客户及主要供应商情况 gives the top-five
supplier and customer shares. Those lines are copied into one derived source per report
and admitted as industry data like any located quote, so the industry and company
sections can cite upstream cost and downstream concentration as [[ind:ID]]."""

import re

from .annual_reports import annual_document
from .datasources import source_record
from .industry_data import IndustryDataProposal, admit
from .reporting_periods import report_period
from .schemas import SourceRecord

PUBLISHER = '公司年报'
TABLE_END = re.compile(r'[（(]\s*5\s*[)）]|主要销售客户|前五名客户')
ROW = re.compile(
    r'^(?:(?P<product>[一-鿿A-Za-z0-9（）()·]{1,12})\s+)?(?P<item>[一-鿿（）()、]{2,12})\s+'
    r'(?P<amount>-?[\d,]+\.\d{2})\s+(?P<share>\d{1,3}(?:\.\d+)?)\s+-?[\d,]+\.\d{2}\s+\d{1,3}(?:\.\d+)?\s+'
    r'(?P<change>-?\d+(?:\.\d+)?)'
)
PRODUCT = re.compile(r'^[一-鿿]{2,10}$')
HEADER = re.compile(r'本期|上年|比例|金额|变动|情况|说明|构成|分产|分行|单位|成本分析')
TOTALS = {'合计', '小计', '总计'}
CONCENTRATION = re.compile(
    r'前五名(?P<who>客户|供应商)(?:销售|采购)额\s*[\d,.]+\s*万元\s*[，,]\s*占年度(?:销售|采购)总额\s*(?P<share>\d+(?:\.\d+)?)\s*%'
)


def cost_rows(text: str) -> list[dict]:
    """Cost items of the 成本分析表, by product when the table lists products."""
    start = text.find('成本分析表')
    if start < 0:
        return []
    end = TABLE_END.search(text, start)
    table = text[start : end.start() if end else start + 6000]
    by_product = table.find('分产品情况')
    rows = []
    for part in ([table[by_product:]] if by_product >= 0 else []) + [table]:
        product = ''
        for line in (l.strip() for l in part.splitlines()):
            if PRODUCT.fullmatch(line) and not HEADER.search(line):
                product = line
                continue
            match = ROW.match(line)
            if not match or match.group('item') in TOTALS or float(match.group('share')) >= 100:
                continue
            # “燃料及动力” one year, “燃料动力” the next: one item, one series.
            item = re.sub('[及与和]', '', match.group('item'))
            rows.append(match.groupdict() | {'item': item, 'product': match.group('product') or product})
        if rows:
            return rows
    return rows


def derived_lines(source: SourceRecord) -> tuple[str, list[tuple[str, str, str, str]]]:
    """The period label and (subject, metric, value, line) for one annual report."""
    period = report_period(source) or ''
    if not period.endswith('A'):
        return '', []
    label = period[:4] + '年'
    out = []
    for row in cost_rows(source.content):
        subject = '公司' + row['product']
        out.append((subject, f"{row['item']}占营业成本比重", row['share'] + '%',
                    f"{label}{row['product']}营业成本中{row['item']}占比：{row['share']}%"))
        out.append((subject, f"{row['item']}成本同比", row['change'] + '%',
                    f"{label}{row['product']}{row['item']}成本同比变动：{row['change']}%"))
    seen = set()
    for match in CONCENTRATION.finditer(source.content):
        who = match.group('who')
        if who in seen:
            continue
        seen.add(who)
        metric = '前五名供应商采购占比' if who == '供应商' else '前五名客户销售占比'
        total = '年度采购总额' if who == '供应商' else '年度销售总额'
        out.append(('公司', metric, match.group('share') + '%',
                    f"{label}前五名{who}{'采购' if who == '供应商' else '销售'}额占{total}：{match.group('share')}%"))
    return label, out


def chain_data(c: dict) -> tuple[list, list, list]:
    """Derived sources, evidence and industry data for the company's own annual reports."""
    company = c.get('company') or {}
    sources, evidence, data = [], [], []
    for raw in c.get('sources', []):
        original = SourceRecord.model_validate(raw)
        if not annual_document(original, company if company.get('company_id') else None):
            continue
        label, lines = derived_lines(original)
        if not lines:
            continue
        intro = f'据公司{label}年度报告“成本分析表”及“主要销售客户及主要供应商情况”整理：'
        derived = source_record(
            original.kind,
            f'{original.title}：成本构成与前五名客户供应商',
            '\n'.join([intro] + [line for *_, line in lines]),
            '全文',
            publication_date=original.publication_date,
            local_path=original.local_path,
            attachment_id=original.attachment_id,
        )
        admitted = [
            admit(
                IndustryDataProposal(
                    source_id=derived.source_id, subject=subject[:60], metric=metric[:30], period=label,
                    value_text=value, quote=line, publisher=PUBLISHER,
                ),
                derived,
            )
            for subject, metric, value, line in lines
        ]
        admitted = [a for a in admitted if a]
        if admitted:
            sources.append(derived)
            evidence += [e for e, _ in admitted]
            data += [d for _, d in admitted]
    return sources, evidence, data
