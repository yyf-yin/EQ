"""Question-directed source windows and auditable, bounded block contexts."""

import json
import math
import os
import re
from .framework import digest, CORE
from .schemas import ExtractionBatch, ContextPackage

METRICS = {
    'F01': set(CORE) - {'operating_cashflow'}
    | {'gross_margin', 'net_margin', 'operating_margin', 'ebit', 'opex', 'tax_rate', 'net_income'},
    'F02': {
        'cash',
        'assets',
        'liabilities',
        'equity',
        'debt',
        'receivables',
        'inventory',
        'current_assets',
        'current_liabilities',
        'payables',
    },
    'F03': {
        'operating_cashflow',
        'net_income',
        'parent_net_income',
        'receivables',
        'inventory',
        'payables',
        'capex',
        'fcf',
        'depreciation',
    },
    'F05': {
        'roe',
        'roic',
        'equity',
        'average_equity',
        'average_invested_capital',
        'ebit',
        'tax_rate',
        'capex',
        'dividends',
        'payout_ratio',
        'debt',
        'shares',
        'research_expense',
    },
}


# Token estimate by character class instead of UTF-8 bytes. Bytes over-count
# Chinese about 3x (one CJK char = 3 bytes, but roughly 0.6-1.3 tokens across
# common tokenizers), which made every batch ~3x smaller than the model allows
# and multiplied request counts. Defaults are calibrated slightly above the
# DeepSeek usage observed in real runs (see docs/LLM_CONFIGURATION.md); tune
# per model with CDR_TOKENS_PER_CJK / CDR_CHARS_PER_TOKEN when switching
# providers. The gateway logs the provider's real count next to this estimate.
_CJK = re.compile(
    r'[\u2e80-\u2fff\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]'
)


def _ratio(name, default):
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


def tokens_per_cjk():
    return _ratio('CDR_TOKENS_PER_CJK', 1.0)


def chars_per_token():
    return _ratio('CDR_CHARS_PER_TOKEN', 3.0)


def estimate_text_tokens(text: str) -> int:
    other = len(_CJK.sub('', text))
    cjk = len(text) - other
    return math.ceil(cjk * tokens_per_cjk() + other / chars_per_token())


def estimate_tokens(value):
    """Approximate token count of the JSON-serialized value (not an exact tokenizer)."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return estimate_text_tokens(text)


def chars_for_tokens(tokens):
    """Conservative character allowance for a token budget (assumes CJK-dense text)."""
    return int(max(0, tokens) / max(tokens_per_cjk(), 1 / chars_per_token()))


def locate_windows(sources, task, capacity):
    terms = list(
        dict.fromkeys(
            re.findall(r'[a-zA-Z_]+|[\u4e00-\u9fff]{2}', ' '.join(task.get('queries', [])) + task.get('topic', ''))
        )
    )
    if task.get('role') == 'financial':
        terms += list(CORE) + list(CORE.values())
    windows = []
    for source in sources:
        lines = source.content.splitlines(keepends=True)
        offsets = []
        offset = 0
        for line in lines:
            offsets.append(offset)
            offset += len(line)
        hits = [i for i, line in enumerate(lines) if any(t.lower() in line.lower() for t in terms)]
        if task.get('task_id') in {'uploaded_reference_extract', 'uploaded_reference_context_extract'}:
            hits = list(range(len(lines)))
        if not hits:
            continue
        # Keep original headers, units, reporting scope and footnotes with every row group.
        metadata = [
            i
            for i, line in enumerate(lines)
            if re.search(
                r'单位|百万元|人民币|合并|母公司|重述|注[:：]|注\d|footnote|unit|period|scope|\|.*(?:项目|指标|本期|同期|20\d{2}.*20\d{2}).*\||^#|^\|[- :|]+\|$',
                line,
                re.I,
            )
        ]
        header = ''.join(lines[i] for i in metadata if i <= hits[0])
        footnotes = ''.join(lines[i] for i in metadata if re.search(r'注[:：]|注\d|footnote|重述', lines[i], re.I))
        groups = []
        for i in hits:
            start = max(0, i - 2)
            end = min(len(lines), i + 3)
            if groups and start <= groups[-1][1]:
                groups[-1] = (groups[-1][0], end)
            else:
                groups.append((start, end))
        for start, end in groups:
            # Split at rows first; oversized single rows retain explicit character offsets.
            content = ''.join(lines[start:end])
            prefix = header + '\n' + footnotes
            # Metadata itself must not grow to include all table rows.
            preceding = [
                i
                for i in metadata
                if i <= max(start, hits[0]) and not re.search(r'注[:：]|注\d|footnote', lines[i], re.I)
            ]
            prefix = ''.join(lines[i] for i in preceding[-6:]) + '\n' + footnotes
            max_chars = max(32, chars_for_tokens(capacity - estimate_tokens(prefix) - 800))
            for pos in range(0, len(content), max_chars):
                excerpt = prefix + content[pos : pos + max_chars]
                windows.append(
                    {
                        'source_id': source.source_id,
                        'title': source.title,
                        'locator': source.locator,
                        'start': offsets[start] + pos,
                        'end': offsets[start] + min(pos + max_chars, len(content)),
                        'content': excerpt,
                        'selection_reason': 'question terms; neighboring rows, headers, units and footnotes',
                        'original_content': content[pos : pos + max_chars],
                    }
                )
    return windows


def extraction_batches(sources, task, periods, capacity, request_size=None, reusable=(), input_identity=None):
    windows = locate_windows(sources, task, capacity)
    groups = []
    group = []

    def fits(items):
        if estimate_tokens(items) + 2000 > capacity:
            return False
        if request_size is None:
            return True
        size, limit = request_size(items)
        return size <= limit

    def shrink(w):
        if fits([w]):
            return [w]
        content = w['original_content']
        mid = len(content) // 2
        # Metadata cannot be discarded to make a request fit. The ordinary
        # bounded recovery path still reports an unsplittable window as a gap.
        prefix = w['content'].removesuffix(content)
        if mid < 16 or not fits([w | {'content': prefix, 'original_content': ''}]):
            return [w]
        left = w | {'content': prefix + content[:mid], 'original_content': content[:mid], 'end': w['start'] + mid}
        right = w | {'content': prefix + content[mid:], 'original_content': content[mid:], 'start': w['start'] + mid}
        return shrink(left) + shrink(right)

    if request_size is not None:
        windows = [part for w in windows for part in shrink(w)]
    positions = {digest(w): i for i, w in enumerate(windows)}
    available = set(positions)
    covered = set()
    reused = []
    order = lambda batch: (
        min((positions.get(digest(w), len(positions)) for w in batch.windows), default=len(positions)),
        batch.batch_id,
    )
    for batch in sorted(reusable, key=order):
        selected = {digest(w) for w in batch.windows}
        if batch.status == 'validated' and selected and selected <= available and not selected & covered:
            reused.append(batch)
            covered |= selected
    windows = [w for w in windows if digest(w) not in covered]
    for w in windows:
        if group and not fits(group + [w]):
            groups.append(group)
            group = []
        group.append(w)
    if group:
        groups.append(group)
    batches = reused + [
        ExtractionBatch(
            batch_id='batch-'
            + digest([task['task_id'], periods, g] + ([input_identity] if input_identity else []))[:24],
            block_id=task.get('block_id') or task['task_id'],
            company_id=task['company_id'],
            segment_id=task.get('segment_id'),
            scope_hint='segment' if task.get('segment_id') else 'consolidated',
            metric_codes=sorted(
                METRICS.get(task.get('block_id'), set(CORE) if task.get('role') == 'financial' else set())
            ),
            question_ids=task.get('question_ids', []),
            periods=periods,
            windows=g,
            estimated_input_tokens=estimate_tokens(g) + 2000,
        )
        for g in groups
    ]
    return sorted(batches, key=order) if reusable else batches


INDUSTRY_DATA_FIELDS = (
    'data_id', 'evidence_id', 'subject', 'metric', 'period', 'value_text', 'actual_or_forecast', 'publisher'
)


def block_context(c, block_id, purpose, store=None, run_id=None, capacity=120000):
    blocks = {b['block_id']: b for b in c.get('plan', {}).get('blocks', [])}
    b = blocks.get(block_id, {'template_id': block_id, 'segment_id': None, 'dependencies': [], 'questions': {}})
    template = b['template_id']
    segment = b['segment_id']
    metrics = METRICS.get(template)
    facts = (
        [
            f
            for f in c.get('facts', [])
            if (f['segment_id'] == segment if segment else f['segment_id'] is None)
            and (not metrics or f['metric_code'] in metrics)
        ]
        if template != 'C01'
        else []
    )
    if template == 'I01':
        facts = []
    if template == 'F04':
        facts = [f for f in c.get('facts', []) if f['metric_code'] in {'revenue', 'cost'}]
    if template in {'V01', 'R01', 'X01'}:
        latest = max(c['brief']['historical_periods'])
        display = set(c['brief']['historical_periods'])
        if c['brief'].get('interim_period'):
            interim = c['brief']['interim_period']
            display |= {interim, str(int(interim[:4]) - 1) + interim[4:]}
        facts = [
            f
            for f in c.get('facts', [])
            if (f['metric_code'] in CORE and f['period'] in display and f['scope'] == 'consolidated')
            or (
                f['period'] == latest
                and f['metric_code']
                in {'revenue', 'cost', 'cash', 'debt', 'equity', 'shares', 'price', 'net_income', 'parent_net_income'}
            )
            or (
                c.get('data_template_version')
                and f.get('slot_id')
                and f['metric_code'] in {'shares', 'price'}
                and not f['period'].endswith('A')
            )
        ]
    facts = [
        f
        for f in facts
        if f['actual_or_forecast'] == 'actual' and f['scope'] == ('segment' if f['segment_id'] else 'consolidated')
    ]
    fact_ids = {f['fact_id'] for f in facts}
    calculations = [
        r
        for r in c.get('calculations', [])
        if (set(r['input_refs'].values()) & fact_ids or (template in {'V01', 'X01'} and r['scenario'] != 'historical'))
        and (not template.startswith('F') or r['scenario'] == 'historical')
    ]
    if template in {'V01', 'R01', 'X01'}:
        calculations = [
            r
            for r in calculations
            if r['output_metric']
            in {'revenue', 'net_income', 'parent_net_income', 'eps', 'target_price', 'cfo', 'fcf', 'cash', 'pe', 'roe', 'roic'}
            or r['output_metric'].endswith(('.yoy', '.delta'))
        ]
        # Tables retain all detailed calculation chains. Analysis sees key final results and latest comparisons.
        latest = max(c['brief']['historical_periods'])
        calculations = [
            r
            for r in calculations
            if r['period'] == latest
            or (
                r['scenario'] != 'historical'
                and r['output_metric'] in {'revenue', 'net_income', 'parent_net_income', 'eps', 'target_price', 'cfo', 'cash'}
            )
        ]
    comparisons = [r for r in c.get('comparisons', []) if r['current_fact_id'] in fact_ids]
    if template in {'V01', 'R01', 'X01'}:
        comparisons = [
            r
            for r in comparisons
            if r['current_period'] == max(c['brief']['historical_periods'])
            or r['current_period'] == c['brief'].get('interim_period')
        ]
    # A comparison is cited through its own delta/rate results, so those stay citable
    # even where the calculation list above is narrowed to key metrics.
    listed = {r['result_id'] for r in calculations}
    cited = {id for r in comparisons for id in r['calculation_ids']} - listed
    calculations += [r for r in c.get('calculations', []) if r['result_id'] in cited]
    # C01/I01/B01 need actual excerpts. Finance sees only its own evidence and topic matches.
    evidence_ids = {f['evidence_id'] for f in facts}
    from .references import reference_question_support

    support = reference_question_support(c, store, run_id)
    reference_ids = {id for q in b['questions'] for id in support.get(q, [])}
    # Material collected for this business or its industry follows the block even when a
    # quote does not name the business itself (e.g. 维生素E market data for 营养品).
    material_ids = {
        id
        for s in c.get('material_collections', [])
        if template in {'I01', 'B01'}
        and (s.get('block_id') == block_id or segment in s.get('scope', {}).get('linked_segments', []))
        for status in s.get('direction_statuses', {}).values()
        for id in status.get('evidence_ids', [])
    }
    # The company's own cost structure and top-five shares (cost_structure.py) are the
    # upstream and downstream facts every industry and position block may cite.
    from .cost_structure import PUBLISHER as ANNUAL_CHAIN

    chain_ids = (
        {d['evidence_id'] for d in c.get('industry_data', []) if d.get('publisher') == ANNUAL_CHAIN}
        if template in {'I01', 'B01'}
        else set()
    )
    material_ids |= chain_ids
    numeric_evidence = {f['evidence_id'] for f in c.get('fact_candidates', c.get('facts', [])) + c.get('facts', [])}
    words = re.findall(r'[\u4e00-\u9fff]{2}', ' '.join(b['questions'].values()))
    evidence = [
        e
        for e in c.get('evidence', [])
        if e['evidence_id'] in evidence_ids
        or e['evidence_id'] in reference_ids
        or e['evidence_id'] in material_ids
        or (
            e['evidence_id'] not in numeric_evidence
            and not e['quote'].startswith('{')
            and (segment in e['quote'] if segment else any(w in e['quote'] for w in words))
        )
    ]
    if template == 'C01':
        evidence = [e for e in c.get('evidence', []) if e['source_id'] in c['company']['source_ids'] or e in evidence]
    evidence = [e for e in evidence if e['evidence_id'] not in c.get('excluded_fact_evidence', [])]
    if segment:
        # Select paragraphs mentioning this business rather than the entire shared company note.
        evidence = [
            e | {'quote': '\n'.join(p for p in e['quote'].split('\n\n') if segment in p)}
            if not e['quote'].startswith('{') and e['evidence_id'] not in reference_ids | material_ids
            else e
            for e in evidence
        ]
    upstream = [a for id, a in c.get('block_analyses', {}).items() if id in b['dependencies']]
    assumptions = (
        [a for a in c.get('assumptions', []) if a['period'] == c['brief']['forecast_periods'][0]]
        if template == 'V01'
        else []
    )
    forecasts = (
        [{k: v for k, v in f.items() if k not in {'result_ids', 'assumption_ids'}} for f in c.get('forecasts', [])]
        if template in {'V01', 'R01', 'X01'}
        else []
    )
    content = {
        'company': c['company'],
        'brief': c['brief'],
        'block': b,
        'evidence': evidence,
        'financial_facts': facts,
        'calculations': calculations,
        'comparisons': comparisons,
        'assumptions': assumptions,
        'forecasts': forecasts,
        'research': [],
        'analysis': c.get('block_analyses', {}).get(block_id, {}),
        'upstream': upstream,
        'limitations': [g for g in c.get('coverage', []) if g['block_id'] == block_id and g['gaps']],
        'financial_conflicts': [
            d
            for d in c.get('fact_decisions', [])
            if d['status'] == 'unresolved'
            and (
                template in {'V01', 'R01', 'X01'}
                or (template == 'F04' and d['identity'].get('segment_id'))
                or (
                    metrics
                    and d['identity'].get('metric_code') in metrics
                    and d['identity'].get('segment_id') == segment
                )
            )
        ],
    }
    if template in {'I01', 'B01'}:
        # Industry numbers travel with the evidence they were read from; only business
        # and industry sections cite them.
        selected_evidence = {e['evidence_id'] for e in evidence}
        content['industry_data'] = [
            {k: d[k] for k in INDUSTRY_DATA_FIELDS}
            for d in c.get('industry_data', [])
            if d['evidence_id'] in selected_evidence
        ]
    if template in {'V01', 'X01'} and (c.get('market') or c.get('forecast_model')):
        from .market_data import summary

        content['valuation_reference'] = {
            'market': summary(c['market']) if c.get('market') else '',
            'forecast_model': '历史趋势通用模型' if c.get('forecast_model') == 'generic' else '有据假设模型',
            'note': '股价、可比公司估值与一致预期在报告的估值表中列示；正文可作定性比较（如估值高于或低于可比公司），不要手写其中的数字。',
        }
    # Shared industry packets follow every linked business; gaps remain visible in analysis and writing.
    materials = c.get('material_collections', [])
    if materials:
        selected_materials = [
            s
            for s in materials
            if s.get('block_id') == block_id
            or (template in {'B01', 'I01'} and segment in s.get('scope', {}).get('linked_segments', []))
            or template in {'R01', 'X01', 'V01'}
        ]
        content['material_collections'] = [
            {
                k: s[k]
                for k in ('topic', 'scope', 'directions', 'direction_statuses', 'limitations', 'state', 'stop_reason')
                if k in s
            }
            for s in selected_materials
        ]
    # Do not silently truncate numeric inputs. Callers must split or configure a larger role.
    from .llm import CapacityError

    if estimate_tokens(content) > capacity:
        raise CapacityError('块上下文超出配置输入容量：' + block_id)
    versions = (
        {f['fact_id']: digest(f) for f in facts}
        | {e['evidence_id']: digest(e) for e in evidence}
        | {r['result_id']: digest(r) for r in calculations}
        | {a['block_id']: a['version'] for a in upstream}
    )
    versions.update(
        {
            '@scope': digest(
                [c['company'], c['brief'], {k: v for k, v in b.items() if k not in {'status', 'version'}}]
            ),
            '@assumptions': digest(assumptions),
            '@forecasts': digest(forecasts),
            '@comparisons': digest(comparisons),
            '@gaps': digest([(g['question_id'], g['gaps']) for g in content['limitations']]),
        }
    )
    versions['@financial_conflicts'] = digest(content['financial_conflicts'])
    if materials:
        versions['@material_collections'] = digest(content['material_collections'])
    package = ContextPackage(
        package_id='ctx-' + digest([purpose, block_id, versions])[:24],
        purpose=purpose,
        block_id=block_id,
        snapshot_id=digest(versions),
        selected_versions=versions,
        selection_reason='block metric, business, evidence and DAG dependencies',
        content=content,
        estimated_tokens=estimate_tokens(content),
    )
    if store:
        store.record(run_id, 'context', package.package_id, package.model_dump(mode='json'))
    return package


def source_context(sources, topic, capacity):
    """Identity/brief calls also receive located disclosure windows, not document beginnings."""
    task = {'topic': topic, 'queries': [topic], 'role': 'company'}
    selected = []
    for source in sources:
        try:
            row = json.loads(source.content)
            if isinstance(row, dict) and row.get('metric_code') and row['metric_code'] not in {'revenue', '营业收入'}:
                continue
        except ValueError:
            pass
        selected.append(source)
    windows = locate_windows(
        sorted(selected, key=lambda s: s.publication_date or '', reverse=True), task, capacity // 2
    )
    from .llm import CapacityError

    if not windows:
        raise CapacityError('没有定位到公司身份/披露范围的来源窗口')
    result = []
    for w in windows:
        source = next(s for s in sources if s.source_id == w['source_id'])
        item = {k: v for k, v in source.model_dump(mode='json').items() if k != 'content'} | {
            'content': w['content'],
            'window_start': w['start'],
            'window_end': w['end'],
        }
        if estimate_tokens(result + [item]) > capacity:
            if result:
                break
            continue
        result.append(item)
    if not result:
        raise CapacityError('身份/范围资料超出容量，需定向缩小检索范围')
    return result
