"""Deterministic readers for tables whose layout the CSRC disclosure rules fix.

The A-share periodic report's "主营业务分产品情况" table always lists, per product,
revenue, cost and gross margin for the report's own period, with no year in the
header. Model extraction struggles with it (header split across lines, no year
column), while a direct read is exact and self-checking: the printed margin must
equal (revenue − cost) / revenue.
"""

import re
from decimal import Decimal, InvalidOperation

HEADINGS = ('主营业务分产品情况', '分产品情况')
END = re.compile(r'主营业务分(?:地区|销售模式|行业)情况|产销量情况|成本分析表|^\s*\(\d+\)', re.M)
UNIT = re.compile(r'单位[：:]\s*(元|千元|万元|百万元|亿元)')
NUMBER = r'-?[\d,]+(?:\.\d+)?'
VALUES = rf'(?P<revenue>{NUMBER})\s+(?P<cost>{NUMBER})\s+(?P<margin>-?\d+(?:\.\d+)?)(?![\d,])'
ROW = re.compile(rf'^\s*(?P<name>[^\d\s\-—][^\d]*?)\s+{VALUES}')
VALUES_ONLY = re.compile(rf'^\s*{VALUES}')
# A product name the PDF wrapped onto several lines ("其他系列" / "酒"); header words never are names.
FRAGMENT = re.compile(r'^[一-鿿]{1,10}$')
HEADER_WORD = re.compile(r'百分点|分点|个百|增减|比上|营业|毛利|分产品|增加|减少')
SKIP = re.compile(r'合计|小计|总计|其中|分产品|营业收入')


def number(text):
    try:
        return Decimal(text.replace(',', ''))
    except InvalidOperation:
        return None


def product_rows(content: str):
    """Rows of the main-business-by-product table: name, revenue, cost, unit, the row text."""
    for heading in HEADINGS:
        start = content.find(heading)
        if start < 0:
            continue
        unit = UNIT.findall(content[max(0, start - 600) : start])
        if not unit:
            continue
        end = END.search(content, start + len(heading))
        block = content[start + len(heading) : end.start() if end else start + 3000]
        rows, pending = [], ''
        for line in block.splitlines():
            text = line.strip()
            m = ROW.match(text) or VALUES_ONLY.match(text)
            if not m:
                pending = pending + text if FRAGMENT.match(text) and not HEADER_WORD.search(text) else ''
                continue
            name = pending + (m.groupdict().get('name') or '').strip()
            pending = ''
            revenue, cost, margin = number(m.group('revenue')), number(m.group('cost')), number(m.group('margin'))
            if not name or SKIP.search(name) or not revenue or revenue <= 0 or cost is None or margin is None:
                continue
            # The table prints margin in percent; a misread column fails this check.
            if abs((revenue - cost) / revenue * 100 - margin) > Decimal('0.06'):
                continue
            rows.append({'name': name, 'revenue': m.group('revenue'), 'cost': m.group('cost'), 'unit': unit[-1], 'quote': text})
        if rows:
            return rows
    return []


def match_segment(name: str, segments: list[str]):
    """The brief segment a product row reports, by exact or contained name; None when ambiguous."""
    exact = [s for s in segments if s == name]
    if exact:
        return exact[0]
    contained = [s for s in segments if s in name or name in s]
    return contained[0] if len(contained) == 1 else None
