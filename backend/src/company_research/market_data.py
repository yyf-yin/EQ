"""Market data for valuation: the company's price, its Shenwan level-3 peers and consensus EPS.

Fetched once per run through AKShare and stored, so a resumed run values the company
on the same snapshot. Every call is bounded by a timeout and may fail on its own; a
missing piece leaves that cell empty rather than stopping the research. Sources that
answer from this network: CNINFO (industry), legulegu (Shenwan constituents with market
cap and PE), Sina (daily close) and THS (consensus and historical EPS).
"""

import concurrent.futures
import math
import re
from datetime import date, timedelta

SOURCE = 'AKShare：巨潮资讯行业分类、乐咕乐股申万行业成份、新浪行情、同花顺一致预期'
TIMEOUT = 30
PEERS = 5


def call(fn, *args, **kwargs):
    """Run one AKShare call with a hard timeout; None when it fails or hangs."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn, *args, **kwargs).result(timeout=TIMEOUT)
    except Exception:
        return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def number(value):
    try:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.replace(',', '').strip()
            scale = 1e8 if text.endswith('亿') else 1e4 if text.endswith('万') else 1
            value = float(text.rstrip('亿万%')) * scale
        value = float(value)
        return None if math.isnan(value) or math.isinf(value) else value
    except (TypeError, ValueError):
        return None


def exchange(code: str) -> str:
    return 'sh' if code[0] in '569' else 'bj' if code[0] in '48' else 'sz'


def industry(ak, code: str):
    """Latest Shenwan level-3 industry name from CNINFO, e.g. 白酒Ⅲ."""
    end = date.today().strftime('%Y%m%d')
    df = call(ak.stock_industry_change_cninfo, symbol=code, start_date='20100101', end_date=end)
    if df is None or df.empty:
        return None
    rows = df[df['分类标准'].astype(str).str.contains('申银万国')]
    if rows.empty:
        return None
    row = rows.sort_values('变更日期').iloc[-1]
    return str(row.get('行业中类') or row.get('行业大类') or '').strip() or None


def constituents(ak, name: str):
    """Shenwan level-3 index code, industry PE and constituent rows with market cap and PE."""
    info = call(ak.sw_index_third_info)
    if info is None or info.empty:
        return None, {}, []
    match = info[info['行业名称'] == name]
    if match.empty:
        return None, {}, []
    row = match.iloc[0]
    code = str(row['行业代码'])
    summary = {'pe': number(row.get('静态市盈率')), 'pe_ttm': number(row.get('TTM(滚动)市盈率')), 'pb': number(row.get('市净率'))}
    df = call(ak.sw_index_third_cons, symbol=code)
    rows = []
    for _, r in (df.iterrows() if df is not None else []):
        ticker = str(r.get('股票代码', '')).split('.')[0]
        if not re.fullmatch(r'\d{6}', ticker):
            continue
        rows.append(
            {
                'code': ticker,
                'name': str(r.get('股票简称', '')).strip(),
                'market_cap': number(r.get('市值')),  # 亿元
                'pe': number(r.get('市盈率')),
                'pe_ttm': number(r.get('市盈率ttm')),
                'pb': number(r.get('市净率')),
                'roe': number(r.get('ROE(%)')),
            }
        )
    return code, summary, rows


def close_price(ak, code: str, as_of: date):
    start = (as_of - timedelta(days=20)).strftime('%Y%m%d')
    df = call(ak.stock_zh_a_daily, symbol=exchange(code) + code, start_date=start, end_date=as_of.strftime('%Y%m%d'))
    if df is None or df.empty:
        return None, None
    last = df.iloc[-1]
    return number(last['close']), str(last['date'])[:10]


def eps(ak, code: str, history_year: str, forecast_years: list[str]):
    """Historical basic EPS for the latest annual report and the consensus mean for forecast years."""
    out = {}
    abstract = call(ak.stock_financial_abstract_ths, symbol=code, indicator='按年度')
    if abstract is not None and not abstract.empty:
        row = abstract[abstract['报告期'].astype(str) == history_year]
        if not row.empty:
            out[history_year + 'A'] = number(row.iloc[-1].get('基本每股收益'))
    forecast = call(ak.stock_profit_forecast_ths, symbol=code, indicator='预测年报每股收益')
    if forecast is not None and not forecast.empty:
        for _, r in forecast.iterrows():
            year = str(r.get('年度', ''))[:4]
            if year in forecast_years:
                out[year + 'E'] = number(r.get('均值'))
                out[year + 'E_count'] = number(r.get('预测机构数'))
    return {k: v for k, v in out.items() if v is not None}


def snapshot(code: str, as_of: date, history_year: str, forecast_years: list[str], peers: int = PEERS) -> dict:
    """Valuation inputs for the company and its largest same-industry peers."""
    import akshare as ak

    data = {'source': SOURCE, 'requested_as_of': as_of.isoformat(), 'company': {'code': code}, 'peers': [], 'errors': []}
    name = industry(ak, code)
    if not name:
        data['errors'].append('未取得申万行业分类')
    index_code, summary, rows = constituents(ak, name) if name else (None, {}, [])
    data.update(industry=name, industry_code=index_code, industry_valuation=summary)
    own = next((r for r in rows if r['code'] == code), {'code': code})
    others = sorted((r for r in rows if r['code'] != code and r.get('market_cap')), key=lambda r: -r['market_cap'])[:peers]
    for item in [own] + others:
        item['price'], item['price_date'] = close_price(ak, item['code'], as_of)
        item['eps'] = eps(ak, item['code'], history_year, forecast_years)
    data['company'] = own
    data['peers'] = others
    dates = [i['price_date'] for i in [own] + others if i.get('price_date')]
    data['as_of'] = max(dates) if dates else None
    if not others:
        data['errors'].append('未取得可比公司')
    return data


def summary(data: dict) -> str:
    """One readable paragraph of the snapshot, used as the evidence quote."""
    company = data.get('company') or {}
    parts = [f'数据日期 {data.get("as_of") or "未知"}']
    if company.get('price'):
        parts.append(f'{company.get("name") or company.get("code")} 收盘价 {company["price"]:.2f} 元')
    for key, value in sorted((company.get('eps') or {}).items()):
        if not key.endswith('_count'):
            parts.append(f'EPS {key} {value:.2f} 元')
    if data.get('industry'):
        valuation = data.get('industry_valuation') or {}
        parts.append(f'申万行业 {data["industry"]} 静态市盈率 {valuation.get("pe")}、TTM 市盈率 {valuation.get("pe_ttm")}')
    peers = '、'.join(p.get('name') or p['code'] for p in data.get('peers') or [])
    if peers:
        parts.append('可比公司 ' + peers)
    return '；'.join(parts) + '。'


HISTORY_SOURCE = '东方财富个股估值（经 AKShare）'


def valuation_history(code: str, as_of: date, years: int = 3) -> dict | None:
    """The company's own daily PE(TTM) over the last `years` years: median and band.
    None when the series is unavailable or covers fewer than about six months."""
    import akshare as ak
    import pandas as pd

    df = call(ak.stock_value_em, symbol=code)
    if df is None or df.empty or 'PE(TTM)' not in df.columns:
        return None
    dates = pd.to_datetime(df.iloc[:, 0], errors='coerce')
    values = pd.to_numeric(df['PE(TTM)'], errors='coerce')
    end = pd.Timestamp(as_of)
    window = (dates <= end) & (dates > end - pd.DateOffset(years=years)) & (values > 0)
    series, days = values[window], dates[window]
    if len(series) < 120:
        return None
    return {
        'source': HISTORY_SOURCE,
        'metric': 'PE(TTM)',
        'years': years,
        'start': days.min().date().isoformat(),
        'end': days.max().date().isoformat(),
        'days': int(len(series)),
        **{k: round(float(v), 2) for k, v in {
            'median': series.median(), 'p25': series.quantile(0.25), 'p75': series.quantile(0.75),
            'min': series.min(), 'max': series.max(),
        }.items()},
    }


def history_summary(code: str, history: dict) -> str:
    return (
        f'{code} 近{history["years"]}年{history["metric"]}（{history["start"]}至{history["end"]}，'
        f'{history["days"]}个交易日）：中位数 {history["median"]:.2f} 倍，25%—75%分位 {history["p25"]:.2f}—{history["p75"]:.2f} 倍，'
        f'区间 {history["min"]:.2f}—{history["max"]:.2f} 倍。'
    )


def pe(price, earnings):
    return price / earnings if price and earnings and earnings > 0 else None


def peer_forward_pe(data: dict, year: str):
    """Median forward PE of peers for a forecast year (e.g. 2026E); None without at least two."""
    values = sorted(v for p in data.get('peers', []) if (v := pe(p.get('price'), (p.get('eps') or {}).get(year))))
    if len(values) < 2:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
