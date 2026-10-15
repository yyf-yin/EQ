"""Explicit reporting periods: cumulative flows and single quarters never alias."""
import json
import re
from calendar import monthrange
from datetime import date

POLICY = 'uploaded-quarterly-periods-1'
INTERIM = r'季报|季度报告|半年度报告|半年报|中报|中期报告|quarterly[\s_-]*report|interim[\s_-]*report|semi[\s_-]*annual[\s_-]*report'
REPORT_TYPES = {'quarterly_report', 'interim_report', 'semiannual_report'}


def canonical_period(period):
    value = str(period or '').upper().replace(' ', '')
    if not re.fullmatch(r'20\d{2}(?:A|H1|Q[1-4]|[1-4]Q)', value):
        return None
    return value[:4] + {'Q2': 'H1', 'Q4': 'A'}.get(value[4:], value[4:])


def previous_period(period):
    return str(int(period[:4])-1) + period[4:]


def period_metadata(period, field_kind='annual_flow'):
    year = int(period[:4]); suffix = period[4:]
    quarter = {'A':4, 'Q1':1, 'H1':2, 'Q3':3}.get(suffix)
    single = bool(re.fullmatch(r'[1-4]Q', suffix))
    if single: quarter = int(suffix[0])
    if quarter is None: raise ValueError('未知财务期间')
    month = quarter*3
    end = date(year, month, monthrange(year, month)[1]).isoformat()
    stock = field_kind == 'year_end_stock'
    start = end if stock else date(year, (quarter-1)*3+1 if single else 1, 1).isoformat()
    kind = 'period_end_stock' if stock and suffix != 'A' else 'year_end_stock' if stock else 'quarter_flow' if single else 'annual_flow' if suffix=='A' else 'interim_flow'
    label = f'{year}年' + ({'A':'全年', 'Q1':'一季度累计', 'H1':'上半年累计', 'Q3':'前三季度累计'}.get(suffix) or f'第{suffix[0]}季度单季')
    if stock: label = f'{end}期末'
    return dict(period_start=start, period_end=end, period_kind=kind, period_label=label)


def period_columns(text, default_year=None, default_suffix=None):
    """Read ordered, explicitly labelled columns; support year-only interim headers."""
    token = (r'(?P<date_year>20\d{2})(?:年(?P<cn_month>\d{1,2})月(?P<cn_day>\d{1,2})日|[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2}))|'
             r'(?P<code>20\d{2}\s*(?:H1|Q[1-4]|[1-4]Q|A))|'
             r'(?:(?P<year>20\d{2})\s*年?\s*)?(?P<name>前三季度|半年度|上半年|半年|中期|中报|全年|年度|'
             r'第?[一二三四1234]季度|1\s*[-—–至]\s*[369]\s*月|1月\s*[-—–至]\s*[369]月)')
    result=[]; year=default_year; cursor=0
    for match in re.finditer(token, text, re.I):
        preceding=re.findall(r'(20\d{2})\s*年',text[cursor:match.start()])
        if preceding:year=preceding[-1]
        cursor=match.end()
        if match['date_year']:
            year=match['date_year']
            month=int(match['month'] or match['cn_month']);day=int(match['day'] or match['cn_day'])
            if month in (3,6,9,12) and day==monthrange(int(year),month)[1]:
                result.append(year+{3:'Q1',6:'H1',9:'Q3',12:'A'}[month])
            continue
        if match['code']:
            result.append(canonical_period(match['code']));year=match['code'][:4];continue
        if match['year']:year=match['year']
        if not year:continue
        name=match['name']
        if name in {'半年度','上半年','半年','中期','中报'} or re.search(r'6\s*月',name):suffix='H1'
        elif name=='前三季度' or re.search(r'9\s*月',name):suffix='Q3'
        elif name in {'全年','年度'}:suffix='A'
        elif re.search(r'3\s*月',name):suffix='Q1'
        else:
            n=re.search(r'[一二三四1234]',name)[0]
            n={'一':'1','二':'2','三':'3','四':'4'}.get(n,n)
            suffix=n+'Q'
        result.append(str(year)+suffix)
    if not result and default_suffix:
        result=[year+default_suffix for year in re.findall(r'20\d{2}',text)]
    return result


def interim_document(source, company=None):
    from .annual_reports import SECONDARY, industry_annual_title
    try:row=json.loads(source.content)
    except (ValueError,TypeError):row=None
    if isinstance(row,dict):
        return row.get('document_type') in REPORT_TYPES and (company is None or row.get('company_id')==company['company_id'])
    text=source.title+' '+source.content[:1200]
    if re.search(SECONDARY,source.title,re.I):return False
    if company is None and industry_annual_title(source.title):return False
    return bool(re.search(INTERIM,text,re.I)) and (company is None or company['name'] in text or bool(company.get('ticker') and company['ticker'] in text))


def financial_document(source, company=None):
    from .annual_reports import annual_document
    return annual_document(source,company) or interim_document(source,company)


def report_period(source):
    """Report cover/structured metadata identifies the reporting scope, not every fact."""
    try:row=json.loads(source.content)
    except (ValueError,TypeError):row=None
    if isinstance(row,dict):
        return canonical_period(row.get('report_period') or row.get('period'))
    text=source.title+' '+source.content[:500]
    columns=period_columns(text)
    if not columns:
        from .annual_reports import annual_document
        years=re.findall(r'20\d{2}',text)
        return years[0]+'A' if years and annual_document(source) else None
    period=columns[0]
    # A third-quarter report contains January–September cumulative statements.
    if interim_document(source):
        period=period[:4]+{'1Q':'Q1','2Q':'H1','3Q':'Q3','4Q':'A'}.get(period[4:],period[4:])
    return period


def available_source(source, as_of):
    try:row=json.loads(source.content)
    except (ValueError,TypeError):row=None
    publication=source.publication_date or (row.get('publication_date') if isinstance(row,dict) else None)
    if publication:
        try:
            if date.fromisoformat(publication[:10])>date.fromisoformat(as_of[:10]):return False
        except ValueError:pass
    period=report_period(source)
    return not period or period_metadata(period)['period_end']<=as_of[:10]


def latest_interim(sources, as_of):
    year=as_of[:4]
    candidates=[report_period(s) for s in sources if s.kind=='upload' and interim_document(s) and available_source(s,as_of)]
    candidates=[p for p in candidates if p and p[:4]==year and p[4:] in {'Q1','H1','Q3'}]
    return max(candidates,key=lambda p:period_metadata(p)['period_end']) if candidates else None


def quarterly_periods(brief):
    if not brief.get('quarterly_collection'):return []
    as_of=brief['as_of'][:10]
    years=sorted({p[:4] for p in brief['historical_periods']} | {str(int(min(brief['historical_periods'])[:4])-1),as_of[:4],str(int(as_of[:4])-1)})
    return [p for year in years for suffix in ('Q1','H1','Q3','1Q','2Q','3Q','4Q')
            for p in [year+suffix] if period_metadata(p)['period_end']<=as_of]


def required_interim_periods(brief):
    latest=brief.get('interim_period')
    return {latest,previous_period(latest)} if brief.get('quarterly_collection') and latest else set()


def supports_period(source, period):
    """Bind optional historical quarters only where that period is actually described."""
    rp=report_period(source)
    if rp and rp[4:]!='A':
        allowed={rp,previous_period(rp)}
        # Single quarter values can occur alongside the cumulative report.
        q={'Q1':'1Q','H1':'2Q','Q3':'3Q'}.get(rp[4:])
        if q:allowed|={rp[:4]+q,previous_period(rp[:4]+q)}
        return period in allowed
    if period.endswith('A'):return period[:4] in source.title+' '+source.content
    columns=period_columns(source.content, default_year=rp[:4] if rp else None)
    if period[4:] in {'1Q','Q1'}:
        return period in columns or period[:4]+('1Q' if period[4:]=='Q1' else 'Q1') in columns
    return period in columns
