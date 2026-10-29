"""Deterministic prose checks: direction words against the cited data, gap claims against inputs.

Direction is checked clause by clause, so a word about one metric is never matched with
another metric's numbers elsewhere in the sentence. Both checks stay silent whenever the
text is ambiguous (mixed directions, negation, a rate rather than a level as subject), so a
hit is a real contradiction rather than a style preference.
"""

import json
import re
from decimal import Decimal
from pathlib import Path

from .financials.formulas import FIELD_MAP

SENTENCE = re.compile(r'[^。！？；!?;\n]+[。！？；!?;]?')
CLAUSE = re.compile(r'[^，,。！？；!?;\n]+')
UP = '上升|上涨|增长|增加|提升|提高|走高|回升'
DOWN = '下降|下跌|减少|下滑|回落|降低|走低|下行|萎缩'
DIRECTION = re.compile(f'(?P<up>{UP})|(?P<down>{DOWN})')
# The word then describes a growth rate, margin or share, not the cited level.
RATE_SUBJECT = re.compile(r'(?:增速|增幅|降幅|速度|幅度|比率|率|占比|比重|弹性)[^\d，。；]{0,4}$')
NEGATION = re.compile(r'(?:未|不|没有|并未|并非|无|难以|能否|是否)\s*$')
GAP = re.compile(r'未提供|未披露|没有提供|没有披露|未给出|未列示|缺少|缺乏|缺失|无法获得|未获取')
# A breakdown, structure or basis may genuinely be missing while the total exists.
BREAKDOWN = re.compile(r'分项|明细|拆分|构成|结构|分部|分业务|分产品|分渠道|分地区|口径|单价|吨价|销量|产能')
GENERIC_GAP = re.compile(r'(?:未提供|没有提供|缺少|缺乏)[^。；]{0,8}(?:财务事实|财务数据)')
PERIOD = re.compile(r'(?:19|20)\d{2}(?:A|E|H[12]|Q[1-4]|[1-4]Q)')
# A data clause's subject is what precedes its first number or data token.
LEAD = re.compile(r'[^\d\[]*')
JOINER = re.compile(r'的同时|同时|而|但|且|则|并')
GENERIC = re.compile(r'同比|环比|绝对额|绝对值|合计|总额|金额|规模|水平|本期|当期|[的在亦也仍再更]')


def _labels():
    template = Path(__file__).parent / 'templates/fixed_data_slots.v1.json'
    fields = [f for g in json.loads(template.read_text(encoding='utf-8'))['groups'] for f in g['fields']]
    labels = {}
    for f in fields:
        if f.get('metric_code') and f.get('label'):
            label = re.sub(r'原表值$|^年报披露', '', f['label'])
            labels.setdefault(label, set()).add(f['metric_code'])
    for label, code in FIELD_MAP.items():
        labels.setdefault(label, set()).add(code)
    return {k: v for k, v in labels.items() if len(k) >= 3}


LABELS = _labels()
LABEL_PATTERN = re.compile('|'.join(sorted(map(re.escape, LABELS), key=len, reverse=True)))


def sentences(paragraph):
    return [m.group(0) for m in SENTENCE.finditer(paragraph) if m.group(0).strip()]


def _polarity(clause):
    """(sign, [(word, subject), ...]) of the clause's direction words, or None when absent or mixed."""
    signs = {}
    for m in DIRECTION.finditer(clause):
        before = clause[max(0, m.start() - 8) : m.start()]
        if NEGATION.search(before):
            return None
        if RATE_SUBJECT.search(before):
            continue
        subject = JOINER.split(clause[: m.start()])[-1][-8:]
        signs.setdefault(1 if m.group('up') else -1, []).append((m.group(0), subject))
    if len(signs) != 1:
        return None
    return next(iter(signs.items()))


def _same_subject(subject, clause):
    """Whether a direction word's subject names the metric that leads a data clause."""
    lead = GENERIC.sub('', LEAD.match(clause).group(0))
    subject = GENERIC.sub('', subject)
    return any(subject[i : i + 2] in lead for i in range(len(subject) - 1))


def _sign(value):
    return (value > 0) - (value < 0)


def _actual(refs, facts, comparisons):
    """Signs of change the cited data shows, with the periods each one covers."""
    fact_ids = {id for kind, id in refs if kind == 'fact'}
    calc_ids = {id for kind, id in refs if kind == 'calc'}
    found = []
    paired = set()
    for c in comparisons:
        if {c['current_fact_id'], c['previous_fact_id']} <= fact_ids or calc_ids & set(c['calculation_ids']):
            found.append((_sign(Decimal(str(c['delta']))), f"{c['previous_period']}→{c['current_period']}"))
            paired |= {c['current_fact_id'], c['previous_fact_id']}
    groups = {}
    for id in fact_ids - paired:
        f = facts.get(id)
        if f:
            key = (f['metric_code'], f.get('scope'), f.get('segment_id'), f['unit'], re.sub(r'^\d{4}', '', f['period']))
            groups.setdefault(key, []).append(f)
    for group in groups.values():
        if len(group) < 2 or len({f['period'] for f in group}) != len(group):
            continue
        group.sort(key=lambda f: f['period'])
        steps = {_sign(Decimal(str(b['value'])) - Decimal(str(a['value']))) for a, b in zip(group, group[1:])}
        if len(steps) == 1:
            found.append((steps.pop(), f"{group[0]['period']}→{group[-1]['period']}"))
    return found


def direction_problems(paragraphs, refs_in, facts, comparisons):
    """Clauses whose single direction word contradicts every change the cited data shows: data
    in the same clause, or else in the nearest earlier data clause of the sentence when that
    clause leads with the same metric the direction word is about."""
    facts = {f['fact_id']: f for f in facts}
    problems = []
    for index, paragraph in enumerate(paragraphs):
        for sentence in sentences(paragraph):
            clauses = CLAUSE.findall(sentence)
            data = [_actual(refs_in(c), facts, comparisons) for c in clauses]
            for position, clause in enumerate(clauses):
                polarity = _polarity(clause)
                if not polarity:
                    continue
                sign, words = polarity
                actual = data[position]
                if not actual:
                    earlier = next((j for j in range(position - 1, -1, -1) if data[j]), None)
                    words = [w for w in words if earlier is not None and _same_subject(w[1], clauses[earlier])]
                    if not words:
                        continue
                    actual, clause = data[earlier], clauses[earlier] + '，' + clause
                problems += _contradiction(index, clause, sign, words[0][0], actual)
    return problems


def _contradiction(index, clause, sign, word, actual):
    signs = {s for s, _ in actual}
    if len(signs) != 1 or 0 in signs or sign in signs:
        return []
    periods = '、'.join(p for _, p in actual)
    truth = '上升' if signs.pop() > 0 else '下降'
    text = f'第{index + 1}段“{clause.strip()[:80]}”写为“{word}”，但所引数据（{periods}）实际{truth}；'
    return [(index, text + '请按数据改正方向或删除该判断')]


def gap_problems(paragraphs, refs_in, facts, segments=()):
    """Sentences that call a metric missing although the writer's own input holds it.

    Only meaningful against the exact context the writer saw, so it runs at drafting time;
    a claim about a named segment is checked against that segment's facts only."""
    by_code = {}
    for f in facts:
        by_code.setdefault(f['metric_code'], []).append(f)
    problems = []
    for index, paragraph in enumerate(paragraphs):
        for sentence in sentences(paragraph):
            if not GAP.search(sentence):
                continue
            if GENERIC_GAP.search(sentence) and facts:
                problems.append(
                    (
                        index,
                        f'第{index + 1}段“{sentence.strip()[:60]}”称输入没有财务数据，但输入含 {len(facts)} 条 financial_facts；'
                        '请引用相关数据或改为说明具体缺少哪一项',
                    )
                )
                continue
            if BREAKDOWN.search(sentence):
                continue
            named = [s for s in segments if s and s in sentence]
            cited = {id for kind, id in refs_in(sentence) if kind == 'fact'}
            periods = set(PERIOD.findall(sentence))
            for label in dict.fromkeys(LABEL_PATTERN.findall(sentence)):
                present = [
                    f
                    for code in LABELS[label]
                    for f in by_code.get(code, [])
                    if (f.get('segment_id') in named if named else f.get('scope', 'consolidated') != 'segment')
                    and (not periods or f['period'] in periods)
                ]
                if present and not cited & {f['fact_id'] for f in present}:
                    listed = '、'.join(sorted({f['period'] for f in present})[-6:])
                    problems.append(
                        (
                            index,
                            f'第{index + 1}段“{sentence.strip()[:60]}”称{label}缺失，但输入已有{label}（{listed}）；'
                            '请引用该数据，或写明真正缺少的具体口径',
                        )
                    )
    return problems


# Internal audit wording talks about the pipeline (inputs, sections, evidence sets,
# bound data) rather than the company. Broker reports state the judgement and the
# data; a sentence that only describes what this run could or could not use is cut.
DATA_TOKEN = re.compile(r'\[\[[a-z]+:[^\]]+\]\]')
META_HARD = re.compile(
    r'本块|本轮(?:证据|新增|资料|输入)|证据集|资料包|结构化事实|占位|写作缺口|未绑定|未取数|未进入本|待证假设|口径混同'
    r'|financial_facts|calculations?|comparisons?|evidence|\bfacts?\b|consistency_checks'
    r'|输入(?:中|里|数据|资料|证据|未|没有|给出|显示|仅|只)'
    r'|(?:本章|本节|本段)(?:不|只|仅|未|无法|没有)'
)
META_LABEL = re.compile(r'^\s*(?:本章|本节)?(?:统一)?(?:结论|小结)[：:]\s*')
META_SOFT = re.compile(r'本章|本节|成立条件|推翻条件|反证[：:]|不确定性[：:]|限制[：:]|依据[：:]|机制[：:]|含义[：:]')


def meta_terms(paragraph):
    text = DATA_TOKEN.sub(' ', paragraph)
    return list(dict.fromkeys(m.group(0) for p in (META_HARD, META_LABEL, META_SOFT) for m in p.finditer(text)))


def meta_problems(paragraphs):
    return [
        f'第{i + 1}段含内部审核措辞“{"、".join(terms[:4])}”：按研报正文写法直接陈述判断与数据，'
        '不描述输入、本章范围、证据或成立/推翻条件；确需提示的不确定性用“若……则……”融入正文'
        for i, terms in ((i, meta_terms(p)) for i, p in enumerate(paragraphs))
        if terms
    ]


def strip_meta(paragraph):
    """Final cleanup: drop a leading “本章结论：” label and sentences that only talk about the run."""
    text = META_LABEL.sub('', paragraph)
    kept = [s for s in sentences(text) if not META_HARD.search(DATA_TOKEN.sub(' ', s))]
    return ''.join(kept).strip()
