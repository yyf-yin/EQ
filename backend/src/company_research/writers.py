import re
from decimal import Decimal
from .agents import ask, ask_bounded, WriterDraft, Reflection, DRAFT_ID_FIELDS
from .schemas import (
    ChartSeries,
    ChartSpec,
    SectionChart,
    ReportDocument,
    ReportSection,
    Table,
    SourceRecord,
    EvidenceRecord,
    FinancialFact,
    IndustryDatum,
    CalculationResult,
    ForecastAssumption,
    FinancialForecast,
)
from .reports import TITLES
from .financials.formulas import FinancialDataProcessor, FinancialError
from .comparisons import FINANCIAL_TITLES, bind_financial_sections, supplemental_financial_tables
from .contexts import block_context
from .framework import digest
from .text_checks import direction_problems, gap_problems, meta_problems, strip_meta

TOKEN = re.compile(r'\[\[(fact|calc|assumption|ind):([a-zA-Z0-9_-]+)\]\]')
# Dates, reporting periods and structural ordinals are not financial quantities and
# may be written directly; every other digit must come from a bound data token.
ALLOWED_NUMERALS = re.compile(
    r'(?:19|20)\d{2}\s*(?:[-–—~至到]\s*(?:19|20)?\d{2,4}\s*)?(?:年度?|财年|A|E|H[12]|Q[1-4]|[1-4]Q)?(?![\d.%])'
    r'|\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?|\d{1,2}\s*日'
    r'|(?<![A-Za-z0-9])(?:[HQ][1-4]|[1-4]Q)(?![A-Za-z0-9])'
    r'|第\s*\d{1,2}\s*(?:季度|季|章|节|部分|条|项|点|阶段)'
    r'|(?:^|(?<=[。；\s]))[（(]?\d{1,2}[)）、.](?!\d)'
    r'|[（(]\d{1,2}[)）]'
)


# Internal record IDs (ev-…, fact-slot-…, cmp-…) are provenance, not prose. Their hex
# digits used to read as raw numbers, which forced repair rounds and dropped sentences.
RECORD_ID = re.compile(r'(?<![A-Za-z0-9-])(?:[a-z]+-)+[0-9a-f]{8,}(?![0-9A-Za-z])')
ID_LIST = re.compile(RECORD_ID.pattern + r'(?:\s*[、，,和及/]\s*' + RECORD_ID.pattern + ')*')
ID_GROUP = re.compile(r'[（(\[【][^（()）\[\]【】]*[)）\]】]')
ID_LEAD = re.compile(r'(?:证据|来源|参见|详见|见)?[：:]?\s*$')
ID_FILLER = re.compile(r'[\s、，,；;：:/]|证据|来源|参见|详见|比较|证券代码|见')
# “归母净利润”/“归母净利” followed closely by the value it names.
PARENT_LABEL = re.compile(r'归母净利(?:润)?(?:分别)?(?:为|达|约|是)?\s*\[\[(fact|calc):([a-zA-Z0-9_-]+)\]\]')


def blank(pattern, text):
    return pattern.sub(lambda m: ' ' * len(m.group(0)), text)


def raw_numbers(paragraph: str) -> list[str]:
    """Return snippets containing digits that are neither data tokens nor dates/periods."""
    text = blank(ALLOWED_NUMERALS, blank(RECORD_ID, blank(TOKEN, paragraph)))
    return [paragraph[max(0, m.start() - 12) : m.end() + 12] for m in re.finditer(r'\d+(?:[.,]\d+)*\s*%?', text)]


def strip_record_ids(text: str, bare_ids=True) -> tuple[str, list[str]]:
    """Remove record IDs written into prose; returns the text and the IDs removed.
    Bracketed citations always go; with bare_ids=False an ID used as a noun stays
    for the writer to rephrase. Data tokens such as [[fact:ID]] are kept untouched."""
    found = []

    def ids(part):
        out, last = [], 0
        for m in ID_LIST.finditer(part):
            found.extend(RECORD_ID.findall(m.group(0)))
            out.append(ID_LEAD.sub('', part[last : m.start()]))
            last = m.end()
        return ''.join(out) + part[last:]

    bare = ids if bare_ids else (lambda part: part)

    def group(m):
        if not RECORD_ID.search(m.group(0)):
            return m.group(0)
        inner = re.sub(r'([、，,；;])(?:\s*[、，,；;])+', r'\1', ids(m.group(0)[1:-1]))
        if len(ID_FILLER.sub('', inner)) <= 6:
            return ''
        return m.group(0)[0] + re.sub(r'^[\s、，,；;]+|[\s、，,；;]+$', '', inner) + m.group(0)[-1]

    pieces, last = [], 0
    for m in TOKEN.finditer(text):
        pieces += [bare(ID_GROUP.sub(group, text[last : m.start()])), m.group(0)]
        last = m.end()
    pieces.append(bare(ID_GROUP.sub(group, text[last:])))
    cleaned = re.sub(r'\s+([，。；、）)])', r'\1', ''.join(pieces))
    cleaned = re.sub(r'([，、；])\s*([。；])', r'\2', re.sub(r'[ \t]{2,}', ' ', cleaned))
    return cleaned.strip(), found


def canonical_ids(draft: WriterDraft, context: dict) -> WriterDraft:
    """Writers often drop the record prefix the token kind already names ([[ind:509f…]]
    for ind-509f…). Such an ID is mapped back to the one record it denotes instead of
    being reported as unknown, which made the repair round delete every industry number."""
    aliases = {}
    for kind, items in citable(context).items():
        short = {}
        for id in items:
            for i, ch in enumerate(id):
                if ch == '-':
                    short.setdefault(id[i + 1 :], set()).add(id)
        aliases[kind] = {s: next(iter(ids)) for s, ids in short.items() if len(ids) == 1 and s not in items}

    def fix(kind, id):
        return aliases[kind].get(id, id)

    def fix_ref(ref):
        match = CHART_REF.fullmatch(ref.strip())
        return f'{match.group(1)}:{fix(*match.groups())}' if match and match.group(1) in aliases else ref

    paragraphs = [TOKEN.sub(lambda m: f'[[{m.group(1)}:{fix(*m.groups())}]]', p) for p in draft.paragraphs]
    fields = {field: list(dict.fromkeys(fix(kind, id) for id in getattr(draft, field))) for kind, field in DRAFT_ID_FIELDS.items()}
    charts = [
        c.model_copy(update={'series': [s.model_copy(update={'refs': [fix_ref(r) for r in s.refs]}) for s in c.series]})
        for c in draft.charts
    ]
    if paragraphs == draft.paragraphs and charts == draft.charts and all(fields[f] == getattr(draft, f) for f in fields):
        return draft
    return draft.model_copy(update={'paragraphs': paragraphs, 'charts': charts, **fields})


def without_record_ids(draft: WriterDraft, context: dict) -> WriterDraft:
    """Prose never carries record IDs; valid evidence IDs move to evidence_ids instead."""
    draft = canonical_ids(draft, context)
    known = {e['evidence_id'] for e in context['evidence']}
    paragraphs, removed = [], []
    for paragraph in draft.paragraphs:
        text, ids = strip_record_ids(paragraph, bare_ids=False)
        paragraphs.append(text)
        removed += ids
    if not removed:
        return draft
    extra = [id for id in dict.fromkeys(removed) if id in known and id not in draft.evidence_ids]
    # Empty paragraphs are kept so a paragraph-for-paragraph patch stays aligned.
    return draft.model_copy(update={'paragraphs': paragraphs, 'evidence_ids': draft.evidence_ids + extra})


async def ask_draft(gateway, role, data, local):
    return without_record_ids(await ask_bounded(gateway, role, WriterDraft, data), local)


def citable(context: dict) -> dict:
    """Objects a draft may cite, by data-token kind."""
    return {
        'fact': {f['fact_id']: f for f in context['facts']},
        'calc': {r['result_id']: r for r in context['calculations']},
        'assumption': {a['assumption_id']: a for a in context['assumptions']},
        'ind': {d['data_id']: d for d in context.get('industry_data', [])},
    }


def declared_ids(draft: WriterDraft) -> dict:
    return {kind: set(getattr(draft, field)) for kind, field in DRAFT_ID_FIELDS.items()}


def draft_problems(draft: WriterDraft, context: dict) -> list[str]:
    """Describe every contract violation so one targeted repair round can fix them."""
    objects = {kind: set(items) for kind, items in citable(context).items()}
    declared = declared_ids(draft)
    parent_periods = {
        (item.get('period'), item.get('scenario'))
        for items in citable(context).values()
        for item in items.values()
        if (item.get('metric_code') or item.get('output_metric')) == 'parent_net_income'
    }
    problems = []
    unknown = sorted(set(draft.evidence_ids) - {e['evidence_id'] for e in context['evidence']})
    if unknown:
        problems.append('evidence_ids 含输入中不存在的证据：' + '、'.join(unknown[:10]))
    for kind, ids in declared.items():
        bad = sorted(ids - objects[kind])
        if bad:
            problems.append(f'{kind} 引用了输入中不存在的 ID：' + '、'.join(bad[:10]))
    for i, paragraph in enumerate(draft.paragraphs):
        for kind, id in TOKEN.findall(paragraph):
            if id not in objects[kind]:
                problems.append(f'第{i + 1}段的 [[{kind}:{id}]] 不在输入数据中，请删除或换成存在的 ID')
            elif id not in declared[kind]:
                problems.append(f'第{i + 1}段使用了 [[{kind}:{id}]] 但未在对应 ID 列表中声明')
        named = RECORD_ID.findall(blank(TOKEN, paragraph))
        if named:
            problems.append(
                f'第{i + 1}段正文写了记录 ID“{"、".join(named[:3])}”：正文不写任何 ID，'
                '改为说明资料名称或直接陈述内容，证据只列入 evidence_ids'
            )
        for kind, id in PARENT_LABEL.findall(paragraph):
            item = citable(context)[kind].get(id) or {}
            # Without minority interests net_income is the owners' income itself.
            if (item.get('metric_code') or item.get('output_metric')) == 'net_income' and (
                item.get('period'),
                item.get('scenario'),
            ) in parent_periods:
                problems.append(
                    f'第{i + 1}段把 [[{kind}:{id}]] 写成归母净利润，但它是合并净利润（net_income）：'
                    '归母净利润改引 parent_net_income，或改称“合并净利润”'
                )
        for snippet in raw_numbers(paragraph):
            problems.append(
                f'第{i + 1}段直接写了数字“{snippet.strip()}”：财务/经营数值必须改用 [[fact:ID]]/[[calc:ID]]/[[assumption:ID]]，'
                '行业与第三方数字改用 industry_data 的 [[ind:ID]]，没有对应数据时改为定性表述'
            )
    checks = direction_problems(draft.paragraphs, TOKEN.findall, context['facts'], context.get('comparisons', []))
    segments = (context.get('brief') or {}).get('segments') or []
    checks += gap_problems(draft.paragraphs, TOKEN.findall, context['facts'], segments)
    problems += meta_problems(draft.paragraphs)
    problems += short_problems(draft.paragraphs)
    problems += chart_problems(draft, context)
    if len(clean_heading(draft.heading)) > 30:
        problems.append('heading 过长：观点式标题控制在 30 字以内，一句话说清本节判断')
    problems += part_problems(draft, context.get('part_topics') or {})
    return list(dict.fromkeys(problems + [text for _, text in checks]))


# A broker paragraph argues one point with data, cause and comparison; a run of one- or
# two-sentence paragraphs reads as a list of facts. Tokens count as a short rendered value.
SHORT_PARAGRAPH = 120


def short_problems(paragraphs: list[str]) -> list[str]:
    lengths = [len(TOKEN.sub('数值数值', p)) for p in paragraphs]
    short = [i + 1 for i, n in enumerate(lengths) if 0 < n < SHORT_PARAGRAPH]
    if len(short) < 3 or len(short) * 3 <= len(paragraphs):
        return []
    return [
        f'第{"、".join(map(str, short[:8]))}段过短（不足 {SHORT_PARAGRAPH} 字）：同一主题的相邻段落合并为一段，'
        '每段按“判断→数据→原因→与历史或同行对比→对公司的影响”写完整，不要一个数据一段'
    ]


# Each business's industry section is written as these subsections, in this order,
# after the two Guangfa deep reports. Policy is written only when material supports it.
INDUSTRY_PARTS = {
    'process': '产品与工艺',
    'supply': '供给格局',
    'demand': '需求与规模',
    'price': '价格驱动',
    'policy': '政策事件',
}


def part_problems(draft: WriterDraft, topics: dict) -> list[str]:
    if not draft.parts:
        return []
    if not topics:
        return ['本章不分小节：parts 必须为空']
    order = list(topics)
    problems = []
    if any(p.topic not in topics for p in draft.parts):
        problems.append('parts.topic 只能取：' + '、'.join(order))
    ranks = [order.index(p.topic) for p in draft.parts if p.topic in topics]
    starts = [p.start for p in draft.parts]
    if ranks != sorted(set(ranks)):
        problems.append('parts 按 ' + '→'.join(order) + ' 的顺序排列，每个 topic 至多一次')
    if starts[0] != 0 or starts != sorted(set(starts)) or starts[-1] >= len(draft.paragraphs):
        problems.append('parts.start 是该小节第一段的序号（从 0 开始）：首个为 0，严格递增，且小于段落数')
    if any(len(clean_heading(p.heading)) > 30 for p in draft.parts):
        problems.append('parts.heading 过长：小节观点式标题控制在 30 字以内')
    return problems


# Writer-proposed charts carry data tokens, not numbers: each value is read from the
# cited record, so a chart can only show what the text could cite.
CHART_REF = re.compile(r'(fact|calc|assumption|ind):([a-zA-Z0-9_-]+)')
IND_VALUE = re.compile(r'\s*([-+]?\d[\d,，]*(?:\.\d+)?)\s*(.*?)\s*')
CHART_SCALES = {'CNY_million': (Decimal('0.01'), '亿元'), 'ratio': (Decimal(100), '%'), 'percentage_points': (Decimal(1), 'pct')}
MAX_CHARTS = 3


def chart_value(kind: str, item: dict) -> tuple[float, str] | None:
    if kind == 'ind':
        match = IND_VALUE.fullmatch(item['value_text'])
        return (float(re.sub('[,，]', '', match.group(1))), match.group(2)) if match else None
    if item.get('value') is None:
        return None
    scale, unit = CHART_SCALES.get(item['unit'], (Decimal(1), UNITS.get(item['unit'], item['unit'])))
    return float(Decimal(str(item['value'])) * scale), unit


def resolve_chart(spec: ChartSpec, objects: dict) -> tuple[SectionChart | None, list[str]]:
    """The chart with values read from its cited records, or the reasons it cannot be drawn."""
    name = f'图表“{spec.title}”'
    n = len(spec.categories)
    if not 2 <= n <= 12 or not 1 <= len(spec.series) <= 5:
        return None, [f'{name}：categories 需 2—12 项，series 需 1—5 个']
    if spec.kind == 'pie' and len(spec.series) != 1:
        return None, [f'{name}：饼图只能有一个序列']
    problems, series, units, refs, sources = [], [], {}, [], set()
    for s in spec.series:
        if len(s.refs) != n:
            problems.append(f'{name}：序列“{s.name}”的 refs 必须与 categories 一一对应（{n} 项，缺值写空字符串）')
            continue
        values, origins = [], set()
        for ref in s.refs:
            if not ref.strip():
                values.append(None)
                continue
            match = CHART_REF.fullmatch(ref.strip())
            item = objects.get(match.group(1), {}).get(match.group(2)) if match else None
            value = chart_value(match.group(1), item) if item else None
            if value is None:
                problems.append(f'{name}：序列“{s.name}”的“{ref}”不是输入中可取值的 fact/calc/assumption/ind 记录')
                values.append(None)
                continue
            kind = match.group(1)
            units.setdefault(s.axis, set()).add(value[1])
            values.append(value[0])
            refs.append(f'{kind}:{match.group(2)}')
            if kind == 'ind':
                origins.add((item['metric'], item.get('publisher', '')))
                sources.add(item.get('publisher') or '行业资料')
            else:
                sources.add('研究预测' if kind == 'assumption' or item.get('scenario') not in (None, 'historical') else '公司公告')
        if len(origins) > 1:
            problems.append(f'{name}：序列“{s.name}”混用了不同指标或来源的行业数据，不同口径不能放进同一序列')
        if sum(v is not None for v in values) < 2:
            problems.append(f'{name}：序列“{s.name}”至少需要两个有值的数据点')
        if spec.kind == 'pie' and any(v is not None and v <= 0 for v in values):
            problems.append(f'{name}：饼图各项必须为正数')
        series.append(ChartSeries(name=s.name, values=values, kind=s.kind, axis=s.axis))
    for axis, found in units.items():
        if len(found) > 1:
            problems.append(f'{name}：{"右" if axis == "right" else "左"}轴混用了单位（{"、".join(sorted(found))}），不同单位的序列放到另一侧坐标轴或拆成两张图')
    if spec.kind == 'combo' and len(spec.series) == 1 and n < 3:
        problems.append(f'{name}：单序列图至少需要三个期间')
    if problems:
        return None, problems
    return SectionChart(
        title=spec.title,
        kind=spec.kind,
        categories=spec.categories,
        series=series,
        unit=next(iter(units.get('left', {''}))),
        right_unit=next(iter(units.get('right', {''}))),
        source='、'.join(sorted(sources, key=lambda s: (s != '公司公告', s))),
        refs=list(dict.fromkeys(refs)),
    ), []


def chart_problems(draft: WriterDraft, context: dict) -> list[str]:
    objects = citable(context)
    cited = {f'{k}:{i}' for p in draft.paragraphs for k, i in TOKEN.findall(p)}
    problems = [] if len(draft.charts) <= MAX_CHARTS else [f'每节至多 {MAX_CHARTS} 张图表，只保留最能说明论点的']
    for spec in draft.charts:
        chart, found = resolve_chart(spec, objects)
        problems += found
        if chart and not cited & set(chart.refs):
            problems.append(f'图表“{spec.title}”的数据没有在正文中引用：图表跟在讨论它的段落之后，请在该段引用其中至少一项')
    return problems


def chart_after(chart: SectionChart, paragraphs: list[str]) -> int:
    """Index of the first paragraph citing the chart's data (tokens, before rendering)."""
    refs = set(chart.refs)
    return next(
        (i for i, p in enumerate(paragraphs) if refs & {f'{k}:{id}' for k, id in TOKEN.findall(p)}),
        max(len(paragraphs) - 1, 0),
    )


def remap_charts(charts, mapping):
    """Charts after paragraphs were dropped; a chart whose paragraph went follows the one before."""
    out = []
    for chart in charts:
        kept = [m for m in mapping[: chart.after + 1] if m is not None]
        out.append(chart.model_copy(update={'after': kept[-1] if kept else 0}))
    return out


def remap_parts(parts, mapping):
    """Parts after paragraphs were dropped or merged; mapping[i] is paragraph i's new
    index, or None when it is gone. A part left without paragraphs disappears."""
    out = []
    for k, part in enumerate(parts):
        end = parts[k + 1].start if k + 1 < len(parts) else len(mapping)
        kept = [mapping[i] for i in range(part.start, min(end, len(mapping))) if mapping[i] is not None]
        if kept:
            out.append(part.model_copy(update={'start': kept[0]}))
    return out


def clean_heading(heading: str) -> str:
    """A viewpoint title carries no numbering, data tokens, IDs or trailing punctuation."""
    text, _ = strip_record_ids(TOKEN.sub('', heading or ''))
    text = re.sub(r'^\s*(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[.、．])\s*', '', text)
    return text.strip().rstrip('。；;，,')


def sanitize_draft(draft: WriterDraft, context: dict) -> tuple[WriterDraft, list[str]]:
    """Last resort after a failed repair: drop unverifiable sentences and unknown IDs
    instead of failing the whole section. Returns the cleaned draft and what was removed."""
    objects = {kind: set(items) for kind, items in citable(context).items()}
    evidence = {e['evidence_id'] for e in context['evidence']}
    removed = []
    paragraphs = []
    mapping = []
    for paragraph in draft.paragraphs:
        kept = []
        for sentence in re.split(r'(?<=[。！？；])', paragraph):
            if not sentence:
                continue
            bad_token = any(id not in objects[kind] for kind, id in TOKEN.findall(sentence))
            if bad_token or raw_numbers(sentence):
                removed.append(sentence.strip())
                continue
            kept.append(sentence)
        mapping.append(len(paragraphs) if ''.join(kept).strip() else None)
        if ''.join(kept).strip():
            paragraphs.append(''.join(kept))
    # Malformed parts are dropped rather than guessed; the section then reads unsplit.
    valid = not part_problems(draft, context.get('part_topics') or {})
    used = {kind: set() for kind in DRAFT_ID_FIELDS}
    for paragraph in paragraphs:
        for kind, id in TOKEN.findall(paragraph):
            used[kind].add(id)
    declared = declared_ids(draft)
    cited = {f'{k}:{i}' for p in paragraphs for k, i in TOKEN.findall(p)}
    charts = []
    for spec in draft.charts[:MAX_CHARTS]:
        chart, problems = resolve_chart(spec, citable(context))
        if chart and cited & set(chart.refs):
            charts.append(spec)
        else:
            removed.append(f'图表“{spec.title}”')
    clean = draft.model_copy(
        update={
            'paragraphs': paragraphs,
            'charts': charts,
            'parts': remap_parts(draft.parts, mapping) if valid else [],
            'evidence_ids': [e for e in draft.evidence_ids if e in evidence],
            **{
                field: sorted((declared[kind] & objects[kind]) | used[kind])
                for kind, field in DRAFT_ID_FIELDS.items()
            },
        }
    )
    return clean, removed


UNITS = {
    'CNY_million': '百万元',
    'CNY/share': '元/股',
    'CNY/unit': '元/件',
    'million_shares': '百万股',
    'times': '倍',
    'million_units': '百万件',
    'million_users': '百万用户',
    'CNY/user': '元/用户',
    'years': '年',
}


def number(value: Decimal, unit: str) -> str:
    if unit == 'ratio':
        return f'{value * 100:.2f}%'
    if unit == 'percentage_points':
        return f'{value:.2f}个百分点'
    return f'{value:.2f}' + UNITS.get(unit, unit)


def resolve_draft(draft: WriterDraft, context: dict, section_id: str, title: str) -> ReportSection:
    objects = citable(context)
    evidence = {e['evidence_id'] for e in context['evidence']}
    if not set(draft.evidence_ids).issubset(evidence):
        raise FinancialError('Writer 引用未知证据')
    declarations = declared_ids(draft)
    for kind, ids in declarations.items():
        if not ids.issubset(objects[kind]):
            raise FinancialError('Writer 引用未知数据 ID')
    bindings = {}
    used_evidence = set(draft.evidence_ids)

    def replace(match):
        kind, id = match.groups()
        if id not in declarations[kind]:
            raise FinancialError('数值引用未在章节引用字段声明')
        item = objects[kind][id]
        # Industry numbers keep the source's own wording and unit.
        text = item['value_text'] if kind == 'ind' else number(Decimal(item['value']), item['unit'])
        bindings[f'{kind}:{id}'] = text
        if kind in {'fact', 'ind'}:
            used_evidence.add(item['evidence_id'])
        if kind == 'assumption':
            used_evidence.update(item['evidence_ids'])
        return text

    paragraphs = []
    for paragraph in draft.paragraphs:
        if raw_numbers(paragraph):
            raise FinancialError('Writer 直接生成数字，必须改用数据或计算引用')
        paragraph, named = strip_record_ids(paragraph)
        used_evidence.update(id for id in named if id in evidence)
        paragraph = strip_meta(paragraph)
        paragraphs.append(TOKEN.sub(replace, paragraph))
    charts = []
    for spec in draft.charts[:MAX_CHARTS]:
        chart, _ = resolve_chart(spec, objects)
        if chart:
            charts.append(chart.model_copy(update={'after': chart_after(chart, draft.paragraphs)}))
            for ref in chart.refs:
                kind, id = ref.split(':', 1)
                if kind in {'fact', 'ind'}:
                    used_evidence.add(objects[kind][id]['evidence_id'])
    return ReportSection(
        section_id=section_id,
        title=title,
        heading=clean_heading(draft.heading),
        paragraphs=paragraphs,
        parts=[p.model_copy(update={'heading': clean_heading(p.heading)}) for p in draft.parts],
        charts=charts,
        evidence_ids=sorted(used_evidence),
        calculation_ids=draft.calculation_ids,
        number_bindings=bindings,
        consistency_checks=draft.consistency_checks,
    )


def payload(c: dict) -> dict:
    # Evidence is the factual context; compressed summaries do not replace sources.
    return {
        'company': c['company'],
        'brief': c['brief'],
        'evidence': c['evidence'],
        'financial_facts': c['facts'],
        'calculations': c['calculations'],
        'assumptions': c['assumptions'],
        'forecasts': c['forecasts'],
        'research': c['summaries'],
        'analysis': c['analysis'],
        'limitations': c['limitations'],
    }


def section_block(section_id):
    if section_id in FINANCIAL_TITLES:
        return section_id
    if section_id.startswith('industry-'):
        return 'I01-' + section_id.split('-')[-1]
    if section_id.startswith('position-'):
        return 'B01-' + section_id.split('-')[-1]
    return {
        'company': 'C01',
        'financial': 'F01',
        'business': 'F04',
        'forecast': 'V01',
        'risk': 'R01',
        'core': 'X01',
    }.get(section_id, 'C01')


def section_parts(section_id):
    return INDUSTRY_PARTS if section_id.startswith('industry-') else {}


def imported_section(c, section_id, instructions=None):
    """A section accepted from a resume package; rework instructions always redraft."""
    value = (c.get('imported_sections') or {}).get(section_id)
    return ReportSection.model_validate(value) if value and not instructions else None


async def write_one(gateway, c, section_id, title, goal, core=False, instructions=None, store=None, run_id=None):
    imported = imported_section(c, section_id, instructions)
    if imported:
        return imported
    role = 'core_writer' if core else 'writer'
    package = block_context(c, section_block(section_id), 'writing', store, run_id, 1000000)
    selected = package.content
    local = c | {
        'facts': selected['financial_facts'],
        'evidence': selected['evidence'],
        'calculations': selected['calculations'],
        'assumptions': selected['assumptions'],
        'industry_data': selected.get('industry_data', []),
        'part_topics': section_parts(section_id),
    }
    data = selected | {
        'section': {'section_id': section_id, 'block_id': section_block(section_id), 'title': title, 'goal': goal},
        'instructions': instructions or [],
    }
    if local['part_topics']:
        data['parts_contract'] = {'topics': local['part_topics'], 'optional': ['policy']}
    if core:
        data['consistency_checks'] = [
            '收入增长与现金流匹配',
            '分业务预测与总量约束',
            '估值证据支持',
            '业务资源竞争与集中度',
        ]
        data['final_sections'] = [
            {
                'section_id': s['section_id'],
                'conclusions': s['paragraphs'][:2],
                'children': [
                    {'section_id': ch['section_id'], 'conclusions': ch['paragraphs'][:2]} for ch in s['children']
                ],
            }
            for s in c['report']['sections'][2:]
        ]
    version = digest(data)
    if store and not instructions:
        cached = next(
            (r for r in store.records(run_id, 'section') if r['section_id'] == section_id and r['version'] == version),
            None,
        )
        if cached:
            return ReportSection.model_validate(cached['content'])
    draft = await ask_draft(gateway, role, data, local)
    # Depth is judged by reflection against the block's questions, not by character
    # count. A clearly thin draft still gets one expansion request, never a hard fail.
    # The industry section carries four to five subsections, so it needs more substance.
    minimum = (
        800
        if section_id.startswith('industry-')
        else 300
        if core or section_id in FINANCIAL_TITLES or section_id.startswith('position-')
        else 500
    )
    if sum(len(p) for p in draft.paragraphs) < minimum:
        draft = await ask_draft(
            gateway,
            role,
            data
            | {
                'instructions': (instructions or [])
                + ['上一稿过于单薄：请逐一回答本章必需问题，补充有来源的机制分析、反证与限制。']
            },
            local,
        )
    reflection = await ask_bounded(
        gateway,
        'reflection',
        Reflection,
        {
            'section': data['section'],
            'draft': draft.model_dump(mode='json'),
            'evidence': selected['evidence'],
            'calculations': selected['calculations'],
        },
    )
    problems = draft_problems(draft, local)
    if reflection.needs_revision or problems:
        fixes = reflection.instructions if reflection.needs_revision else []
        draft = await ask_draft(
            gateway,
            role,
            data | {'draft': draft.model_dump(mode='json'), 'instructions': problems + fixes + (instructions or [])},
            local,
        )
        problems = draft_problems(draft, local)
    if problems:
        draft, removed = sanitize_draft(draft, local)
        if removed:
            import logging

            logging.getLogger(__name__).warning(
                'section %s: dropped %d unverifiable sentences after repair', section_id, len(removed)
            )
    section = resolve_draft(draft, local, section_id, title)
    if store:
        from .schemas import now

        store.record(
            run_id,
            'section',
            section_id,
            {
                'section_id': section_id,
                'version': version,
                'content': section.model_dump(mode='json'),
                'block_id': section_block(section_id),
                'input_snapshot_id': package.snapshot_id,
                'selected_versions': package.selected_versions,
                'generated_at': now(),
            },
        )
    return section


async def patch_one(gateway, c, section: ReportSection, targets: dict[int, list[str]], store=None, run_id=None):
    """Redraft only the flagged paragraphs (0-based index -> review notes); the rest keep their
    text and bindings. Returns None when the model does not answer paragraph-for-paragraph."""
    package = block_context(c, section_block(section.section_id), 'writing', store, run_id, 1000000)
    selected = package.content
    local = c | {
        'facts': selected['financial_facts'],
        'evidence': selected['evidence'],
        'calculations': selected['calculations'],
        'assumptions': selected['assumptions'],
        'industry_data': selected.get('industry_data', []),
    }
    order = sorted(targets)
    data = selected | {
        'section': {
            'section_id': section.section_id,
            'block_id': section_block(section.section_id),
            'title': section.title,
            'goal': '只改写终审指出问题的段落',
            'current_paragraphs': section.paragraphs,
        },
        'patch_contract': {'targets': [{'paragraph': i + 1, 'problems': targets[i]} for i in order]},
    }
    draft = await ask_draft(gateway, 'writer', data, local)
    problems = draft_problems(draft, local)
    if len(draft.paragraphs) != len(order):
        problems.append(f'paragraphs 必须恰好 {len(order)} 项，与 targets 一一对应')
    if problems:
        draft = await ask_draft(
            gateway, 'writer', data | {'draft': draft.model_dump(mode='json'), 'instructions': problems}, local
        )
        if len(draft.paragraphs) != len(order):
            return None
        if draft_problems(draft, local):
            # Clean paragraph by paragraph so a dropped sentence never shifts the alignment.
            single = [sanitize_draft(draft.model_copy(update={'paragraphs': [p]}), local)[0] for p in draft.paragraphs]
            paragraphs = [s.paragraphs[0] if s.paragraphs else '' for s in single]
            draft = sanitize_draft(draft, local)[0].model_copy(update={'paragraphs': paragraphs})
    fresh = resolve_draft(draft, local, section.section_id, section.title)
    replaced = dict(zip(order, fresh.paragraphs))
    paragraphs = [replaced.get(i, p) for i, p in enumerate(section.paragraphs)]
    # A paragraph emptied by the patch is deleted; subsections keep their own paragraphs.
    mapping, count = [], 0
    for p in paragraphs:
        mapping.append(count if p.strip() else None)
        count += bool(p.strip())
    paragraphs = [p for p in paragraphs if p.strip()]
    kept = {k: v for k, v in section.number_bindings.items() if any(v in p for p in paragraphs)}
    return section.model_copy(
        update={
            'paragraphs': paragraphs,
            'parts': remap_parts(section.parts, mapping),
            'charts': remap_charts(section.charts, mapping),
            'evidence_ids': sorted(set(section.evidence_ids) | set(fresh.evidence_ids)),
            'calculation_ids': list(dict.fromkeys(section.calculation_ids + fresh.calculation_ids)),
            'number_bindings': kept | fresh.number_bindings,
        }
    )


MOCK_TEXT = {
    'company': [
        '输入公司名称仅用于演示界面。本次映射至虚构的示例制造公司，经营设备与服务两项业务。程序从本地合成材料读取经营说明与财务字段；未检索该输入公司的实际公告，也未调用真实模型。所有后续判断用于检验研究方法，不能作为对输入公司的事实描述。',
        '公司研究应首先核对上市主体、并表范围、核心子公司与实际经营业务，区分集团介绍与上市公司的资产边界。产品销量和行业规模不能直接当作上市公司收入；客户合同、交付验收和收入确认政策共同决定经营数据能否进入财务报表。',
        '制造企业的竞争力通常需要从产品性能、交付能力、成本控制、客户关系及售后保障寻找证据。在本示例中，设备交付与服务维护构成研究对象，但材料没有真实客户名单、专利、市场份额或认证记录。因此报告不把演示中的经营机制写成已证实的护城河。',
        '业务结构分析还需要区分一次性交付收入与持续服务收入。设备业务的增长可能依赖客户投资，而服务业务可能依赖存量设备与续约。两者对销售投入、应收占用和现金回收速度的要求不同，不能简单使用同一行业增速得出公司收入预测。',
        '后续真实研究应补充最新年报与中期公告、分部口径、重大合同及项目进度，再与历史数字交叉验证。身份、范围和资料时点核对不足时，即使财务公式正确，也无法保证研究结论有效。本报告始终保留这种资料层面的限制。',
    ],
    'financial': [
        '历史财务材料由合成 Fixture 提供，财务指标使用 Python Decimal 注册公式计算。分析的重点是收入增长如何传导到利润、营运资本与现金创造。毛利率、净利率和资本回报必须结合会计口径及平均资产基础理解，不能单凭单一比率推断经营改善。',
        '收入与成本按相同业务边界比较，毛利变化可以来自价格、产品组合、单位成本或产能利用率。材料没有真实销量、产品售价和原料采购证据，因此这些只是待检验的解释路径，不能把利润率变化直接归因于某个未经验证的经营因素。',
        '应收账款与库存构成现金占用的重要部分。利润表中的收入增长不保证现金已经收回；如果客户回款延迟或库存周转放缓，经营现金流可能弱于利润。研究需要结合账龄、减值、预付款和应付政策判断，避免将暂时资金占用误判为永久损失。',
        '偿债能力既取决于债务规模，也取决于期限、利率和现金来源。流动比率与速动比率属于静态指标；实际支付能力还受现金可用性、担保、抵押以及资本开支承诺影响。本模型采用明确的借款与还款假设，禁止通过自动新增债务掩盖现金缺口。',
        '自由现金流由经营现金流减资本开支计算，代表本模型中投资后的现金余额变化来源。扩产期的自由现金流下降不必然意味着经营恶化，但项目回报、投产节奏和需求兑现必须有依据。公司金融资产、少数股东及复杂税务事项不在简化预测模型中自动处理。',
    ],
    'business': [
        '业务研究分别讨论设备与服务的行业机制及公司经营情况。分部历史数字通过精确字段读取；预测分部收入和成本先独立计算，再汇总到公司口径。只有业务边界与会计分类一致，分部预测才适合进入三表。',
        '不同业务在需求周期、确认时点和现金回收上可能存在差异。设备研究关注客户资本开支、产品替代和交付能力，服务研究关注存量客户、续约和响应效率。示例资料未提供真实市场份额或竞争排名，研究不产生这些事实。',
    ],
    'forecast': [
        '预测使用历史增速模板作为合成演示，不代表真实业务应优先选择该模板。真实模式可选择产销量与单价、产能利用率、用户与每用户收入、市场规模与份额等注册模型。选择应由业务机制和资料可得性共同决定，缺少驱动输入时应补查或说明预测缺失。',
        '每个情景、年度和业务均保存预测假设与证据引用。基础情景描述需求温和增长，悲观情景描述需求偏弱与成本压力，乐观情景描述需求改善。情景只是条件推演，并非概率分布或收益保证；合成参数不能用作现实市场估值。',
        '利润表从分部收入成本汇总，扣除期间费用、借款利息和税费。折旧作为费用中的非现金部分，现金流中加回；固定资产根据资本开支与折旧滚动。营运资本由应收、库存和应付变化形成。假设变化因此同时影响利润、资产负债和现金，而非单独调整净利润。',
        '估值示例采用预测每股收益与明确的目标市盈率相乘。倍数由合成情景设定，没有真实可比公司或市场价格依据，因此只能检验估值计算链。真实研究需要在同一价格时点、股本范围和盈利口径下比较估值，并说明负利润时市盈率不适用。',
        '模型不自动生成融资来补足负现金，也不设置其他资产、权益等任意平衡项。预测输出需要通过资产负债、现金与分部合计校验。宏观冲击、汇率、少数股东权益、递延所得税以及复杂租赁安排需要增加有来源的模型输入，不能由语言模型补写数字。',
    ],
    'risk': [
        '需求低于假设可能导致设备订单、交付和验收延后，从而影响收入及成本吸收。应监测客户投资计划、订单可执行性及产品替代，而不是只看收入增速。示例没有真实订单来源，需求逻辑属于研究路径。',
        '客户回款延迟和库存积压会增加营运资本占用，使现金弱于利润。风险监测应关注账龄、坏账准备、库存结构及现金回收；如果周转假设发生变化，必须重算现金流和资产负债表，而非只修改风险文字。',
        '原材料、人工及竞争价格变化可能压缩毛利。费用刚性又会扩大收入下降对经营利润的影响。分部成本比例变化在三个情景中体现，但真实预测需要采购、产品组合和规模效应证据。',
        '资本开支超支或项目延迟会减少自由现金流，并可能增加融资需求。融资假设须与债务期限、利率及可得性一致。如果现金不足，系统将明确提示，不能假设公司必然获得借款。',
        '估值倍数下调可以抵消盈利增长，预测价格不等于可实现交易价格。最重要的限制是合成数据与缺少真实市场联调：本报告不能反映输入公司的实际经营或估值。研究人员需要在真实配置完成后重新核查所有依据。',
    ],
}


def mock_sections(c):
    evidence = [e['evidence_id'] for e in c['evidence'] if not e['quote'].startswith('{')]
    ids = ['core', 'toc', 'company', 'financial', 'business', 'forecast', 'risk', 'statements', 'disclaimer']
    sections = [
        ReportSection(
            section_id=id,
            title=t,
            paragraphs=MOCK_TEXT.get(id, []),
            evidence_ids=evidence[:3] if id in MOCK_TEXT else [],
        )
        for id, t in zip(ids, TITLES)
    ]
    for i, segment in enumerate(c['brief']['segments']):
        if segment == '设备':
            industry = [
                '设备需求与客户投资周期相关。客户扩产、技术更新与融资条件会影响采购时点，交付和验收又影响收入确认。需求周期不能仅由行业增长率概括，研究需要拆分新增产能、替换需求与产品升级。',
                '竞争分析应比较性能、可靠性、交付周期、售后和全生命周期成本。标准化产品可能受到价格竞争，定制化产品可能受到工程能力与客户认证约束；这些机制需要合同、客户反馈和同行公告支持。',
                '行业规模必须明确产品边界、地域和计价口径。公开行业材料可能采用产值、销量或设备存量，公司财务采用营业收入；不同指标不能直接相乘或替换。材料缺口会影响份额模型的适用性。',
                '本示例行业描述为合成研究假设。没有真实行业规模、价格或订单数据，因此不提供市场份额排名和需求增速事实。真实研究需要将行业资料与公司产品边界匹配后再预测。',
            ]
            position = [
                '设备是演示公司的一个分部，合成收入成本分别读取，不与服务口径混合。分部的经营质量应从交付验收、回款与库存共同判断；收入增长可能同时带来更多资金占用。',
                '设备业务的优势需要客观证据。真实研究应检验产品认证、客户重复采购、交付履约和售后表现，不应把公司宣传直接当成竞争优势。示例没有这些证据，所以不输出确定护城河结论。',
                '模型演示采用历史增长驱动收入和成本比例，适用于缺少销量售价的测试材料。真实资料充分时，更合适的量价或产能模型可以展示增长来源，并把产能约束引入预测。',
                '研究需要持续追踪客户资本开支和项目节点。假设与事实之间可能出现差异，应将差异转化为新增检索与计算需求，而不是由模型补充未经验证的数字。',
            ]
        else:
            industry = [
                '服务需求可能与设备存量及维护周期相关。研究应识别付费主体、服务合同、响应标准与续约机制，区分一次性维修、持续维护和软件服务等不同模式。',
                '竞争可能体现在服务覆盖、响应速度、人员能力和价格。不能因为服务收入持续发生就假设客户永不流失；续约率、客户集中度及替代服务都需要来源支持。',
                '服务市场规模与设备销售市场的统计边界通常不同。将设备行业增速直接用于服务预测可能遗漏存量客户的影响，因此应根据客户数、付费率或服务单价寻找适用驱动。',
                '示例未提供真实用户、续约率和服务单价。行业机制仅用于演示研究结构，不能当成实际行业结论。真实运行需要补充可靠行业来源和公司披露。',
            ]
            position = [
                '服务分部在演示中与设备存量存在经营联系，但这种联系并不保证稳定增长或高利润。公司是否具备客户留存和交叉销售能力，需要合同与续约证据支持。',
                '应将服务收入与服务成本口径一致地分析。人员、备件、交付支持及渠道费用可能影响利润，真实研究不能把服务业务简单视为轻资产或高毛利。',
                '示例预测独立计算服务收入与成本，再汇入公司利润表。历史增速模型用于测试；获得用户数和每用户收入等驱动后，可以替换模型，并保留假设和公式版本。',
                '经营跟踪应关注合同续约、服务履约及收款。若服务增长依赖设备新增销售，两个分部情景应在经济逻辑上协调，避免同时假设设备需求下降与无依据的服务高速增长。',
            ]
        sections[4].children.append(
            ReportSection(
                section_id=f'segment-{i}',
                title=segment,
                children=[
                    ReportSection(
                        section_id=f'industry-{i}',
                        title='（一）行业情况',
                        paragraphs=industry,
                        evidence_ids=evidence[:2],
                    ),
                    ReportSection(
                        section_id=f'position-{i}',
                        title='（二）公司情况',
                        paragraphs=position,
                        evidence_ids=evidence[:2],
                    ),
                ],
            )
        )
    sections[7].paragraphs = [
        '以下三表由 Python 从合成历史事实与已验证预测模型生成。A 表示实际口径测试值，E 表示模型预测。除每股指标外，金额单位为百万元。预测采用简化合并口径，不含少数股东、递延税及复杂租赁。'
    ]
    sections[8].paragraphs = [
        '本报告为研究辅助材料，不构成投资建议、证券交易指令或收益承诺。合成材料仅供系统测试，不代表用户输入公司的实际情况。',
        '预测依赖所列假设，估值仅为条件推演。实际经营、市场价格及融资条件可能与假设不同。使用者应核查原始来源、会计口径、时点及模型边界，并承担独立判断责任。',
    ]
    sections[3].paragraphs = ['各小节以同一有效快照说明财务数值与比较。驱动未有披露证据时保持未确认。']
    introductions = {
        'F01': '本小节核对合成资料中的收入、成本、归母及扣非归母净利润，按同期间和同口径比较金额、同比与盈利能力。驱动原因需要披露证据，数值变化本身不能证明经营原因。',
        'F02': '资产负债分析结合现金、有息债务、应收账款与存货判断偿债和资金占用。同日期期末同比与较上年末变化分别命名；合成数值只验证计算流程。',
        'F03': '经营现金流与利润可能因营运资本、折旧和资本开支产生差异。结合应收、库存、应付及自由现金流解释利润质量，未有披露依据的原因保持未确认。',
        'F04': '按披露业务边界分别比较收入、成本、毛利和收入占比，再检查分部与总量的关系。缺少销量、售价或结构证据时不编造量价贡献，也不分摊未披露业务利润。',
        'F05': '资本配置结合 ROE、ROIC、投资、研发、分红、回购与融资评价资金使用。平均资本不能由期末值替代；未披露或不适用的项目明确保留限制。',
    }
    sections[3].children = [
        ReportSection(section_id=id, title=title, paragraphs=[introductions[id]], evidence_ids=evidence[:3])
        for id, title in FINANCIAL_TITLES.items()
    ]
    return sections


def append_tables(report: ReportDocument, c):
    processor = FinancialDataProcessor()
    facts = [FinancialFact.model_validate(f) for f in c['facts']]
    periods = c['brief']['historical_periods']
    company = c['company']['company_id']
    base = [FinancialForecast.model_validate(f) for f in c['forecasts'] if f['scenario'] == 'Base']
    columns = ['项目'] + periods + [f.period for f in base]
    maps = [
        (
            '利润表',
            'income',
            [('营业收入', 'revenue'), ('营业成本', 'cost'), ('经营利润 EBIT', 'ebit'), ('净利润', 'net_income')],
        ),
        (
            '资产负债表',
            'balance',
            [
                ('现金', 'cash'),
                ('应收账款', 'receivables'),
                ('存货', 'inventory'),
                ('固定资产', 'ppe'),
                ('其他资产', 'other_assets'),
                ('资产总计', 'assets'),
                ('应付账款', 'payables'),
                ('有息负债', 'debt'),
                ('其他负债', 'other_liabilities'),
                ('负债合计', 'liabilities'),
                ('股东权益', 'equity'),
            ],
        ),
        ('现金流量表', 'cashflow', [('经营现金流', 'operating_cashflow'), ('资本开支', 'capex')]),
    ]
    for title, kind, metrics in maps:
        rows = []
        for label, metric in metrics:
            row = [label]
            for period in periods:
                try:
                    row.append(f'{processor.get(facts, company, metric, period).value:.2f}')
                except FinancialError:
                    row.append('缺失')
            for f in base:
                key = 'cfo' if metric == 'operating_cashflow' else metric
                value = getattr(f, kind).get(key)
                row.append(f'{value:.2f}' if value is not None else '缺失')
            rows.append(row)
        if kind == 'income':
            for label, key in [
                ('期间费用', 'opex'),
                ('利息费用', 'interest'),
                ('所得税', 'tax'),
                ('折旧摊销', 'depreciation'),
            ]:
                rows.append([label] + ['缺失' for _ in periods] + [f'{f.income[key]:.2f}' for f in base])
        if kind == 'cashflow':
            for label, key in [
                ('营运资本增加', 'delta_working_capital'),
                ('投资现金流', 'cfi'),
                ('融资现金流', 'cff'),
                ('分红现金支出', 'dividends'),
                ('自由现金流', 'fcf'),
            ]:
                rows.append([label] + ['缺失' for _ in periods] + [f'{f.cashflow[key]:.2f}' for f in base])
        report.sections[7].tables.append(Table(title=title + ' 单位 百万元', columns=columns, rows=rows))
    historical = [
        r
        for r in report.calculations
        if r.scenario == 'historical'
        and r.formula_id not in {'comparison_delta', 'percentage_points'}
        and not r.output_metric.endswith('.yoy')
    ]
    report.sections[3].tables.append(
        Table(
            title='历史财务指标 Python 计算',
            columns=['指标', '期间', '结果', '计算 ID'],
            rows=[[r.output_metric, r.period, number(r.value, r.unit), r.result_id[:12]] for r in historical],
        )
    )
    report.sections[3].calculation_ids = [r.result_id for r in historical]
    report.sections[5].tables.append(
        Table(
            title='情景预测与估值 条件推演',
            columns=['情景', '期间', '收入 百万元', '净利润 百万元', 'EPS 元/股', '目标价格 元/股'],
            rows=[
                [
                    f.scenario,
                    f.period,
                    f'{f.income["revenue"]:.2f}',
                    f'{f.income["net_income"]:.2f}',
                    f'{f.income["eps"]:.2f}',
                    f'{f.income["target_price"]:.2f}',
                ]
                for f in report.forecasts
            ],
        )
    )
    report.sections[5].calculation_ids = [r.result_id for r in report.calculations if r.scenario != 'historical']
    report.sections[5].tables.append(
        Table(
            title='预测假设与依据',
            columns=['参数', '情景', '期间', '业务', '数值'],
            rows=[
                [a.metric_code, a.scenario, a.period, a.segment_id or '公司', number(a.value, a.unit)]
                for a in report.assumptions
                if a.period == c['brief']['forecast_periods'][0]
            ]
            if c['brief']['forecast_periods']
            else [],
        )
    )
    basis = {a.rationale: [] for a in report.assumptions}
    for a in report.assumptions:
        basis[a.rationale] = list(dict.fromkeys(basis[a.rationale] + a.evidence_ids))
    report.sections[5].paragraphs += [
        '假设依据：' + rationale + '。证据：' + ', '.join(ids) for rationale, ids in basis.items()
    ]
    report.charts = (
        [
            {
                'title': '基础情景收入与历史收入',
                'labels': periods + [f.period for f in base],
                'values': [str(processor.get(facts, company, 'revenue', p).value) for p in periods]
                + [str(f.income['revenue']) for f in base],
                'unit': '百万元',
            }
        ]
        if all(
            any(f.metric_code == 'revenue' and f.period == p and f.segment_id is None for f in facts) for p in periods
        )
        else []
    )


async def make_report(c, gateway, mock=False, store=None, run_id=None):
    if mock:
        sections = mock_sections(c)

        def accept(items):
            for index, s in enumerate(items):
                imported = imported_section(c, s.section_id)
                if imported:
                    items[index] = imported.model_copy(update={'children': s.children})
                accept(items[index].children)

        accept(sections)
    else:
        from .execution import bounded_schedule, optimized_run

        parallel = store is not None and optimized_run(store, run_id)
        top = [
            ('company', TITLES[2], '身份、发展、经营边界、竞争力'),
            ('financial', TITLES[3], '增长质量、利润、资本回报、现金与偿债'),
            ('business', TITLES[4], '业务结构及业务间关系'),
            ('forecast', TITLES[5], '预测模型、驱动、情景、估值依据与适用边界'),
            ('risk', TITLES[6], '风险机制、监测指标与假设影响'),
        ]
        financial = [
            (block, heading, '回答本块问题并解释已披露变化原因，原因无证据时明确未确认')
            for block, heading in FINANCIAL_TITLES.items()
        ]
        business = [
            [
                (
                    f'industry-{i}',
                    '（一）行业情况',
                    f'{segment}所在行业，按小节写：产品与工艺、供给格局、需求与规模、价格驱动；'
                    '近期有政策或贸易事件资料时加写政策事件，没有则不写',
                ),
                (
                    f'position-{i}',
                    '（二）公司情况',
                    f'公司{segment}业务的位置：产能与产业链配套、成本与份额、竞争优势及业务展望',
                ),
            ]
            for i, segment in enumerate(c['brief']['segments'])
        ]
        generated = {}
        if parallel:
            jobs = []
            for spec in top:
                jobs.extend(financial if spec[0] == 'financial' else [spec])
            jobs.extend(spec for children in business for spec in children)

            async def generate(i):
                return await write_one(gateway, c, *jobs[i], store=store, run_id=run_id)

            outputs = await bounded_schedule(range(len(jobs)), generate, gateway.concurrency)
            generated = {spec[0]: output for spec, output in zip(jobs, outputs)}

        async def section(spec):
            if parallel:
                return generated[spec[0]]
            return await write_one(gateway, c, *spec, store=store, run_id=run_id)

        sections = [ReportSection(section_id='core', title=TITLES[0]), ReportSection(section_id='toc', title=TITLES[1])]
        for spec in top:
            id, title, _ = spec
            if id == 'financial':
                sections.append(
                    ReportSection(section_id=id, title=title, children=[await section(s) for s in financial])
                )
            else:
                sections.append(await section(spec))
        for i, segment in enumerate(c['brief']['segments']):
            children = [await section(s) for s in business[i]]
            sections[4].children.append(ReportSection(section_id=f'segment-{i}', title=segment, children=children))
        sections.extend(
            [
                ReportSection(
                    section_id='statements',
                    title=TITLES[7],
                    paragraphs=[
                        '财务三表由确定性 Python 引擎生成。A 为已核对的历史完整年度，E 为假设条件下的预测。金额单位百万元，缺失项不以零替代。'
                    ],
                ),
                ReportSection(
                    section_id='disclaimer',
                    title=TITLES[8],
                    paragraphs=[
                        '本报告为自动化研究辅助材料，不构成投资建议或收益保证。预测为条件推演，使用者应核查来源、期间、口径及假设。模型不包含未显式输入的少数股东权益、递延税和复杂租赁。'
                    ],
                ),
            ]
        )
    report = ReportDocument(
        title=c['company']['name'] + ' 公司深度研究报告',
        company_id=c['company']['company_id'],
        mode='mock' if mock else 'real',
        sections=sections,
        sources=[SourceRecord.model_validate(s) for s in c['sources']],
        evidence=[EvidenceRecord.model_validate(e) for e in c['evidence']],
        financial_facts=[FinancialFact.model_validate(f) for f in c['facts']],
        industry_data=[IndustryDatum.model_validate(d) for d in c.get('industry_data', [])],
        calculations=[CalculationResult.model_validate(r) for r in c['calculations']],
        assumptions=[ForecastAssumption.model_validate(a) for a in c['assumptions']],
        forecasts=[FinancialForecast.model_validate(f) for f in c['forecasts']],
        limitations=list(
            dict.fromkeys(
                c['limitations']
                + (['模拟运行：全部资料与参数为合成 Fixture，未验证真实公司、模型或搜索。'] if mock else [])
            )
        ),
    )
    append_tables(report, c)
    report.market = c.get('market')
    report.forecast_model = c.get('forecast_model', '')
    report.data_template_version = c.get('data_template_version')
    if c.get('rules_version') == '1.1':
        from .schemas import ResearchBrief, ResearchBlock, CoverageEntry, ComparisonResult

        report.rules_version = '1.1'
        report.brief = ResearchBrief.model_validate(c['brief'])
        report.blocks = [ResearchBlock.model_validate(b) for b in c['plan']['blocks']]
        report.coverage = [CoverageEntry.model_validate(e) for e in c['coverage']]
        report.comparisons = [ComparisonResult.model_validate(r) for r in c.get('comparisons', [])]
        bind_financial_sections(report)
        supplemental_financial_tables(report)
        report.limitations += [
            '必需研究问题受限：' + e.question_id + '；' + '; '.join(e.gaps) for e in report.coverage if e.gaps
        ]
    if c.get('imported_sections'):
        from .reports import sections_flat

        # Imported sections already hold the deterministic paragraphs added above.
        for s in sections_flat(report.sections):
            if s.section_id in c['imported_sections']:
                s.paragraphs = list(dict.fromkeys(s.paragraphs))
                s.evidence_ids = list(dict.fromkeys(s.evidence_ids))
                s.calculation_ids = list(dict.fromkeys(s.calculation_ids))
    return report


async def write_core(c, gateway, mock, store=None, run_id=None):
    imported = imported_section(c, 'core', c.get('core_instructions'))
    if imported:
        return imported
    if mock:
        report = ReportDocument.model_validate(c['report'])
        base = next((f for f in report.forecasts if f.scenario == 'Base'), None)
        paragraphs = [
            '本报告使用虚构制造企业及合成财务数据，重点演示由来源、公式与情景假设形成研究结论的过程。输入名称不使模拟资料变为真实事实。所有结论均须在真实资料和模型配置完成后重新生成。',
            '设备与服务需要分别研究行业机制、客户需求及经营能力。设备交付和服务维护可能有关联，但材料没有真实订单、市占率、续约或客户数据。因此核心判断保持条件性，不将示例机制视为已验证竞争优势。',
            '财务分析必须同时关注收入、利润和现金。营运资本与资本开支使经营增长与可分配现金之间存在差异，借款、利息和分红进一步影响资金安排。三表模型以明确假设推导资产、负债与权益，不用任意平衡项隐藏缺口。',
        ]
        bindings = {}
        if base:
            r = next(
                r
                for r in report.calculations
                if r.scenario == 'Base' and r.period == base.period and r.output_metric == 'revenue'
            )
            value = number(r.value, r.unit)
            paragraphs.append(
                f'基础情景首年收入为{value}，由分部收入模型汇总而来。这只是合成需求假设的结果，不能代表输入公司的未来收入。悲观及乐观情景用于展示需求、成本和估值倍数变化的影响。'
            )
            bindings['calc:' + r.result_id] = value
        paragraphs += [
            '估值示例采用预测每股收益与合成目标市盈率，缺少真实可比公司及市场价格依据。需求兑现、成本控制、回款、资本开支和估值倍数均可能偏离假设，预测价格不代表可实现收益。',
            '研究限制与计算正确性必须分开判断：即使公式复算和三表勾稽通过，缺少真实证据仍使报告只能作为系统示例。本报告不提供投资评级，风险与资料边界是阅读结论的一部分。',
        ]
        return ReportSection(
            section_id='core',
            title=TITLES[0],
            paragraphs=paragraphs,
            evidence_ids=report.sections[6].evidence_ids,
            calculation_ids=[r.result_id] if base else [],
            number_bindings=bindings,
            consistency_checks={
                k: '合成模型确定性勾稽已检验；经营机制和估值没有真实市场证据，保持条件性。'
                for k in ['cash_growth', 'forecast_total', 'valuation_evidence', 'resource_concentration']
            },
        )
    return await write_one(
        gateway,
        c,
        'core',
        TITLES[0],
        '整体综合并显式检查四类跨块矛盾；重大矛盾列明责任块和修复要求',
        core=True,
        instructions=c.get('core_instructions'),
        store=store,
        run_id=run_id,
    )


def report_snapshot(report):
    data = report.model_dump(mode='json', exclude={'issues', 'snapshot_id', 'approved_snapshot_id'})

    def legacy(section):
        # Reports approved before viewpoint headings existed keep their snapshot.
        if section.get('heading') == '':
            del section['heading']
        if section.get('parts') == []:
            del section['parts']
        for child in section.get('children', []):
            legacy(child)

    for section in data['sections']:
        legacy(section)
    # Reports approved before industry data existed keep their snapshot.
    if not data.get('industry_data'):
        data.pop('industry_data', None)
    for key, empty in (('market', None), ('forecast_model', '')):
        if data.get(key) == empty:
            data.pop(key, None)
    return digest(data)
