"""Conservative alignment of quoted financial rows, including non-value columns."""

import re
import unicodedata

from .reporting_periods import period_columns, previous_period


def financial_columns(header, report, stock=False):
    text = re.sub(r'\s+', '', unicodedata.normalize('NFKC', header))
    # Preserve the position of growth columns; they are never financial inputs.
    # Growth/change and share-of-total columns are kept as None placeholders.
    # A share column restates its period label ("本期期末数占总资产的比例"),
    # so it is matched whole before period labels are read.
    own = r'(?:本(?:报告)?期(?:期末|末)?|本年(?:末)?|上年(?:度)?(?:同期|期末|末)?|上期(?:期末|末)?)(?:金额|数|余额)?'
    growth = (
        r'(?:本(?:报告)?期|本年)(?:末)?比上年(?:度)?(?:同期)?(?:期)?(?:末)?(?:增减|增长|变动)(?:\(%\))?'
        r'|(?:' + own + r'较' + own + r')?(?:变动|增减|增长)(?:比例|幅度)(?:\(%\))?'
        r'|' + own + r'占[一-鿿]{1,8}?比例(?:\(%\))?'
    )
    parts = re.split('(' + growth + ')', text)
    columns = []
    for part in parts:
        if re.fullmatch(growth, part):
            columns.append(None)
            continue
        explicit = period_columns(part, default_year=report[:4] if report else None,
                                  default_suffix='A' if stock else report[4:] if report else 'A')
        relative = (
            r'上年同期(?:发生额|金额|数)?|上年(?:度)?期末(?:余额|金额|数)?|上年(?:度)?末|上年度|上期(?:发生额|金额|数)?'
            r'|本(?:报告)?期期末(?:余额|金额|数)?|本报告期(?:末)?'
            r'|本期(?:发生额|金额|数|末)?|期末(?:余额|数)|期初(?:余额|数)'
        )
        if explicit and not (re.search(relative, part) and not re.search(r'20\d{2}', part)):
            columns.extend(explicit)
        elif report:
            for match in re.finditer(relative, part):
                label = match[0]
                if label.startswith(('本', '期末')):
                    columns.append(report)
                elif re.match(r'上年(?:度)?(?:期)?末|上年度$', label) or label.startswith('期初'):
                    columns.append(str(int(report[:4]) - 1) + 'A')
                else:
                    columns.append(previous_period(report))
    bases = ['reported'] * len(columns)
    adjustments = re.findall(r'调整后|调整前', text)
    # Standard three-year summary: current year, two comparative years,
    # each comparative year has adjusted/unadjusted subcolumns.
    if adjustments:
        years = [p for p in columns if p]
        if len(years) < 2 or adjustments != ['调整后', '调整前'] * (len(years) - 1):
            return [], []  # Ambiguous multi-level header: do not guess.
        expanded, bases = [], []
        for p in columns:
            if p and p != years[0]:
                expanded.extend([p, p]); bases.extend(['restated', 'reported'])
            else:
                expanded.append(p); bases.append('reported')
        columns = expanded
    return columns, bases


# An empty cell still occupies its column: "不适用", or a dash standing alone.
PLACEHOLDER = r'(?<!\S)(?:不适用|[-—－–]+)(?!\S)'


def row_numbers(quote, header, number_pattern, column_count, growth_column=True):
    # Item enumeration belongs to the label, not to the value columns.
    row = re.sub(r'^\s*\d+[.、]\s*(?=[^\d\s])', '', quote)
    numbers = re.findall('(?:' + number_pattern + ')|' + PLACEHOLDER, row)
    if len(numbers) == column_count + 1 and re.search(r'附注|注释', header):
        # Only an explicit, single integer note reference may be skipped.
        if re.fullmatch(r'\d{1,3}', numbers[0]):
            numbers = numbers[1:]
    if len(numbers) == column_count + 1 and not growth_column:
        # The quoted header stops before an unlabelled trailing change column.
        numbers = numbers[:-1]
    return numbers
