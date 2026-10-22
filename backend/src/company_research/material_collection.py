"""Neutral, bounded qualitative collection. All reuse belongs to this run only."""

import re
from datetime import date
from typing import Literal

from pydantic import Field

from .agents import ask, request_messages
from .contexts import estimate_tokens
from .datasources import DatasourceError
from .execution import check_pause, unit
from .framework import digest
from .schemas import Schema, SourceRecord
from .reporting_periods import financial_document

VERSION = 'materials-2'
# These are coverage categories, never one retrieval task per category.
PRESETS = {
    'company': [
        ('identity', '公司身份与业务构成', '主体、业务构成、业务边界及关联关系', True),
        ('changes', '经营变化与布局', '已披露的经营变化、发展布局与重要事项', True),
        ('governance', '治理与经营约束', '治理、控制关系及已披露的经营约束', False),
    ],
    'business': [
        ('model', '产品与经营模式', '产品服务、客户、渠道、采购及生产方式', True),
        ('changes', '经营变化与布局', '产品、客户、产能、地域和组织的实际变化', True),
        ('drivers', '经营驱动与约束', '实际披露的经营影响因素、依赖条件与风险', True),
    ],
    'industry': [
        ('boundary', '行业边界与口径', '细分市场、地域、期间和产业链范围', True),
        ('technology', '产品与工艺', '产品定义、性能、用途与应用领域，生产工艺路线及其对比、替代关系', True),
        ('market', '市场规模与结构', '市场规模、细分构成、历史变化与机构预测，保留统计口径', True),
        ('supply_demand', '需求与供给', '下游需求、供给能力、产能与供需变化', True),
        ('competition', '竞争与产业链', '主要参与者、竞争方式、上下游关系及各环节的毛利与议价能力', True),
        ('producers', '主要厂商与产能', '国内外主要生产企业逐家的产能、产量、份额、技术路线及在建与拟建产能，保留口径', True),
        ('upstream', '上游原料与成本', '主要原材料、能源与包材的价格走势、供应是否紧缺或集中，及其占生产成本的比重', True),
        ('downstream', '下游需求与渠道', '下游客户或消费场景的结构与景气、渠道库存与终端价格、客户集中度', True),
        ('price', '价格与周期', '产品价格走势、周期位置与驱动因素，保留价格口径', False),
        ('policy', '政策与监管变化', '近期相关政策、实施时间、适用范围与变化', False),
        ('constraints', '行业约束与风险', '行业经营条件、依赖因素及风险', False),
    ],
}
# After the broad first search, each open industry direction gets its own query
# built from these neutral search terms (model-added directions use their label).
DIRECTION_TERMS = {
    'boundary': '定义 分类 产业链 细分市场',
    'market': '市场规模 增速 预测',
    'supply_demand': '产能 产量 需求量 供需 进出口',
    'competition': '竞争格局 市场份额 主要企业 产能分布',
    'producers': '主要生产企业 产能 扩产 在建 拟建 产能对比',
    'upstream': '原材料 价格 供应 成本占比',
    'downstream': '下游需求 渠道库存 终端价格 客户结构',
    'price': '价格走势 均价 周期',
    'policy': '政策 规划 监管 标准',
    'technology': '性能 用途 应用领域 生产工艺 技术路线',
    'constraints': '原料 成本 环保 风险',
}
STATUS_LABELS = {
    'pending': '待收集',
    'found': '已取得适用资料',
    'partial': '部分取得',
    'not_found': '限定检索后未找到',
    'no_change': '有证据支持无变化',
    'not_applicable': '不适用',
    'retrieval_failed': '获取失败',
}


class ExtraDirection(Schema):
    label: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=240)
    reason: str = Field(min_length=1, max_length=240)


class SlotDirections(Schema):
    slot_id: str
    directions: list[ExtraDirection] = Field(default_factory=list)
    # Industry slots only: the narrower industry carrying most of the company's revenue.
    refined_subject: str = Field(default='', max_length=40)


class MaterialDirectionPlan(Schema):
    slots: list[SlotDirections] = Field(default_factory=list)


class DirectionFinding(Schema):
    status: Literal['pending', 'found', 'partial', 'not_found', 'no_change', 'not_applicable', 'retrieval_failed']
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ''


class MaterialAssessment(Schema):
    sufficient: bool
    covered_dimensions: dict[str, list[str]] = Field(default_factory=dict)
    direction_findings: dict[str, DirectionFinding] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


def kind(task):
    return (
        'industry'
        if task['topic'].startswith('行业')
        else 'business'
        if task['topic'].startswith('业务')
        else 'company'
    )


def neutral(text):
    return not re.search(
        r'[?？]|是否|能否|会不会|为什么|如何|利好|利空|证明|增长点|必然|看涨|看跌|'
        r'股价|证券代码|财务三表|资产负债表|利润表|现金流量表|财务取数|盈利预测|估值',
        text,
        re.I,
    )


def search_subject(scope):
    # Saved scopes from earlier runs have no refinement and keep the original subject.
    return scope.get('refined_subject') or scope['subject']


def subject_terms(scope):
    return list(dict.fromkeys(t for t in (scope.get('refined_subject'), scope['subject']) if t))


def source_key(source):
    # Canonical whitespace catches mirrored copies without building a library.
    return digest(' '.join(source.content.split()))


def future_source(source, as_of):
    publication = source.get('publication_date') if isinstance(source, dict) else source.publication_date
    if not publication:
        return False
    try:
        return date.fromisoformat(publication[:10]) > date.fromisoformat(as_of)
    except ValueError:
        return False  # Ambiguous dates stay explicit for the assessor, never guessed.


class MaterialCollector:
    def __init__(self, fixed):
        self.fixed = fixed
        self.w, self.store, self.run_id = fixed.w, fixed.store, fixed.run_id
        self.settings = self.w.settings

    def search_budget(self, task):
        industry = kind(task) == 'industry'
        return self.settings.material_industry_search_budget if industry else self.settings.material_search_budget

    def document_budget(self, task):
        industry = kind(task) == 'industry'
        return self.settings.material_industry_document_budget if industry else self.settings.material_document_budget

    def slot(self, task):
        return next(s for s in self.store.records(self.run_id, 'collection_slot') if s['slot_id'] == task['task_id'])

    async def configure(self, c, tasks):
        """One persisted planning call for all slots; replay ignores later evidence."""
        identity = digest(
            [
                VERSION,
                c['brief'],
                [t.task_id for t in tasks],
                self.settings.material_extra_direction_limit,
                self.settings.material_policy_years,
            ]
        )
        saved = self.store.execution_get(self.run_id, 'execution_meta', 'material-plan')
        if saved:
            if saved['identity'] != identity:
                raise DatasourceError('业务行业资料范围已冻结，请新建研究使用不同范围')
            for task in tasks:
                task.material_scope = saved['tasks'][task.task_id]['scope']
                task.material_directions = saved['tasks'][task.task_id]['directions']
            return
        as_of = (c['brief'].get('as_of') or self.store.run(self.run_id).created_at)[:10]
        snapshot = date.fromisoformat(as_of)
        definitions = []
        for task in tasks:
            task_kind = kind(task.model_dump())
            scope = {
                'kind': task_kind,
                'subject': task.topic.split('：', 1)[-1],
                'linked_segments': task.linked_segments,
                'start_date': min(c['brief']['historical_periods'])[:4] + '-01-01',
                'as_of': as_of,
                'region': '以实际资料披露为准，未明确则保留限制',
                'policy_start_date': snapshot.replace(
                    year=snapshot.year - self.settings.material_policy_years,
                    day=28 if snapshot.month == 2 and snapshot.day == 29 else snapshot.day,
                ).isoformat(),
            }
            directions = [
                dict(
                    direction_id=key,
                    label=label,
                    description=description,
                    required=required,
                    origin='preset',
                    reason='通用资料覆盖方向',
                )
                for key, label, description, required in PRESETS[task_kind]
            ]
            definitions.append(dict(slot_id=task.task_id, scope=scope, preset_directions=directions))
        evidence = []
        size = 0
        for e in self.store.records(self.run_id, 'evidence'):
            if e['actual_or_forecast'] != 'context':
                continue
            item = {k: e[k] for k in ('evidence_id', 'claim', 'quote')}
            item['quote'] = item['quote'][:1500]
            size += estimate_tokens(item)
            if size > min(
                6000, max(0, self.w.gateway.limits('researcher').input_capacity - 8000 - estimate_tokens(definitions))
            ):
                break
            evidence.append(item)
        context = dict(
            company=c['company'],
            brief=c['brief'],
            slots=definitions,
            evidence=evidence,
            extra_direction_limit=self.settings.material_extra_direction_limit,
            material_plan_contract=True,
        )
        # Industry slots always get one planning call so the subject can be refined.
        if self.settings.material_extra_direction_limit or any(d['scope']['kind'] == 'industry' for d in definitions):
            capacity = self.w.gateway.limits('researcher').input_capacity

            def fits(part):
                return (
                    estimate_tokens(request_messages('researcher', part))
                    + estimate_tokens(MaterialDirectionPlan.model_json_schema())
                    + 1000
                    <= capacity
                )

            # Batch many business slots only when the configured input capacity requires it.
            pending, outputs = [], []

            async def plan_batch(batch):
                part = context | {'slots': batch, 'evidence': evidence[:]}
                while not fits(part) and part['evidence']:
                    part['evidence'].pop()
                if not fits(part):
                    from .llm import CapacityError

                    raise CapacityError('单个资料范围超过 researcher 输入容量，请提高容量')

                async def invoke():
                    return (await ask(self.w.gateway, 'researcher', MaterialDirectionPlan, part)).model_dump(
                        mode='json'
                    )

                result = await unit(
                    self.store, self.run_id, 'material_plan', identity + ':' + str(len(outputs)), part, invoke
                )
                outputs.append(MaterialDirectionPlan.model_validate(result))

            for definition in definitions:
                if pending and not fits(context | {'slots': pending + [definition], 'evidence': []}):
                    await plan_batch(pending)
                    pending = []
                pending.append(definition)
            if pending:
                await plan_batch(pending)
            output = MaterialDirectionPlan(slots=[s for result in outputs for s in result.slots])
        else:
            output = MaterialDirectionPlan()
        extras, refined = {}, {}
        for proposal in output.slots:
            extras.setdefault(proposal.slot_id, []).extend(proposal.directions)
            if proposal.refined_subject.strip():
                refined.setdefault(proposal.slot_id, proposal.refined_subject.strip())
        corpus = ' '.join([s.get('content', '') for s in c.get('sources', [])] + [e['quote'] for e in evidence])
        configured = {}
        for task, definition in zip(tasks, definitions):
            scope = definition['scope']
            candidate = refined.get(task.task_id, '')
            # Only a disclosed, neutral name narrower than the original enters search terms;
            # the original subject is kept as the reporting boundary.
            if (
                scope['kind'] == 'industry'
                and candidate
                and candidate != scope['subject']
                and len(candidate) <= 20
                and neutral(candidate)
                and not re.search(r'[：:，,；;\s]', candidate)
                and c['company']['name'] not in candidate
                and candidate in corpus
            ):
                scope['refined_subject'] = candidate
            directions = definition['preset_directions'][:]
            labels = {d['label'] for d in directions}
            for extra in extras.get(task.task_id, []):
                label = extra.label.strip()
                if (
                    len(directions) - len(definition['preset_directions'])
                    >= self.settings.material_extra_direction_limit
                    or not label
                    or not extra.description.strip()
                    or label in labels
                    or not extra.reason.strip()
                    or not neutral(label + ' ' + extra.description)
                ):
                    continue
                directions.append(
                    dict(
                        direction_id='extra-' + digest(label)[:12],
                        label=label,
                        description=extra.description,
                        required=False,
                        origin='model',
                        reason=extra.reason,
                    )
                )
                labels.add(label)
            task.material_scope, task.material_directions = definition['scope'], directions
            configured[task.task_id] = dict(scope=task.material_scope, directions=directions)
            slot = self.slot(task.model_dump())
            slot.update(
                contract_version=VERSION,
                scope=task.material_scope,
                directions=directions,
                direction_statuses={
                    d['direction_id']: dict(status='pending', evidence_ids=[], reason='尚未检查适用资料')
                    for d in directions
                },
                search_history=[],
                document_hashes=[],
                stop_reason='',
                search_budget=self.search_budget(task.model_dump()),
            )
            self.store.record(self.run_id, 'collection_slot', task.task_id, slot)
        self.store.execution_put(
            self.run_id, 'execution_meta', 'material-plan', dict(identity=identity, tasks=configured)
        )

    def ready(self, slot, sufficient):
        statuses = slot['direction_statuses']
        return sufficient and all(
            statuses[d['direction_id']]['status'] in {'found', 'partial', 'no_change'}
            and statuses[d['direction_id']]['evidence_ids']
            for d in slot['directions']
            if d['required']
        )

    def complete(self, slot):
        return all(v['status'] in {'found', 'no_change', 'not_applicable'} for v in slot['direction_statuses'].values())

    def candidates(self, c, task):
        sources = {s['source_id']: s for s in self.store.records(self.run_id, 'source')}
        terms = task.get('linked_segments', []) + [task.get('segment_id') or ''] + subject_terms(task['material_scope'])
        if kind(task) != 'industry':
            terms.append(c['company']['name'])
        slot = self.slot(task)
        found = slot['search_history'] + [slot.get('reports', {}), slot.get('peers', {})]
        discovered = {i for h in found for i in h.get('source_ids', [])}
        candidates = []
        for e in self.store.records(self.run_id, 'evidence'):
            if e['actual_or_forecast'] != 'context' or e.get('validation_status') == 'conflict':
                continue
            s = sources.get(e['source_id'], {})
            if s.get('kind') != 'upload' and s and financial_document(SourceRecord.model_validate(s)):
                continue
            if future_source(s, task['material_scope']['as_of']):
                continue
            text = e['quote'] + ' ' + e['claim'] + ' ' + s.get('title', '')
            score = sum(bool(t) and t in text for t in terms)
            if not score and e['source_id'] not in discovered:
                continue
            candidates.append((score, e, s))
        return sorted(candidates, key=lambda entry: (-entry[0], entry[1]['evidence_id']))

    async def assess(self, c, task):
        slot = self.slot(task)
        key = 'material-state-' + task['task_id']
        previous = self.store.execution_get(self.run_id, 'execution_meta', key) or {}
        assessed = set(previous.get('assessed_ids', []))
        last = (
            MaterialAssessment.model_validate(previous['output']) if previous else MaterialAssessment(sufficient=False)
        )
        candidates = self.candidates(c, task)
        evidence_by_id = {e['evidence_id']: e for _, e, _ in candidates}
        # Include source/date/scope in every assessment and account for overhead.
        base = dict(
            task=task,
            dimensions=[d['label'] for d in slot['directions']],
            directions=slot['directions'],
            scope=slot['scope'],
            material_contract=True,
            previous_coverage={},
            evidence=[],
        )
        available = self.w.gateway.limits('researcher').input_capacity
        from .llm import IncompleteOutput, TruncatedOutput

        # Malformed or truncated output halves the batch; a different batch is a
        # different unit, so a recorded failure never replays on resume.
        limit = len(candidates)
        for _ in range(2 * len(candidates) + 2):
            context = base | {'previous_coverage': last.model_dump(mode='json')}
            capacity = (
                available
                - estimate_tokens(request_messages('researcher', context))
                - estimate_tokens(MaterialAssessment.model_json_schema())
                - 3000
            )
            selected, size = [], 0
            for _, e, s in candidates:
                if e['evidence_id'] in assessed:
                    continue
                item = {k: e[k] for k in ('evidence_id', 'claim', 'quote')}
                item.update(
                    source_id=e['source_id'],
                    title=s.get('title', ''),
                    publication_date=s.get('publication_date'),
                    source_url=s.get('source_url'),
                    locator=e.get('locator'),
                )
                weight = estimate_tokens(item)
                if weight > capacity and capacity > 1000:
                    # The full quotation remains in the evidence store. Never let one
                    # large quotation prevent smaller applicable excerpts being checked.
                    item['claim'] = item['claim'][:240]
                    item['excerpt_truncated'] = True
                    while estimate_tokens(item) > capacity and len(item['quote']) > 100:
                        item['quote'] = item['quote'][: len(item['quote']) // 2]
                    weight = estimate_tokens(item)
                if size + weight > capacity:
                    # An oversized excerpt must not hide the following candidates.
                    continue
                selected.append(item)
                size += weight
                if len(selected) >= limit:
                    break
            if not selected:
                if any(e['evidence_id'] not in assessed for _, e, _ in candidates):
                    from .llm import CapacityError

                    raise CapacityError('资料覆盖评估上下文超过 researcher 输入容量；原证据已保留，不能记为未找到')
                break
            context['evidence'] = selected

            async def invoke():
                return (await ask(self.w.gateway, 'researcher', MaterialAssessment, context)).model_dump(mode='json')

            try:
                output = MaterialAssessment.model_validate(
                    await unit(self.store, self.run_id, 'material_assessment', task['task_id'], context, invoke)
                )
            except (IncompleteOutput, TruncatedOutput):
                if len(selected) > 1:
                    limit = len(selected) // 2
                else:
                    # A single excerpt that still cannot be assessed is skipped, not fatal.
                    assessed = assessed | {selected[0]['evidence_id']}
                continue
            known = assessed | {e['evidence_id'] for e in selected}
            findings = output.direction_findings.copy()
            for d in slot['directions']:
                direction_id = d['direction_id']
                # Accept the old coverage representation, preserving compatibility.
                if direction_id not in findings and output.covered_dimensions.get(d['label']):
                    findings[direction_id] = DirectionFinding(
                        status='found', evidence_ids=output.covered_dimensions[d['label']]
                    )
                finding = findings.get(direction_id)
                if finding is None:
                    continue
                refs = list(dict.fromkeys(i for i in finding.evidence_ids if i in known and i in evidence_by_id))
                status = finding.status
                if status in {'found', 'partial', 'no_change'} and not refs:
                    status = 'pending'
                if status == 'no_change' and not any(
                    re.search(
                        r'无(?:重大)?变化|未发生.{0,5}变化|未(?:发生)?变[更动]|维持.{0,4}(?:原状|不变)|保持.{0,4}不变|未修[订改]|unchanged',
                        evidence_by_id[i]['quote'],
                        re.I,
                    )
                    for i in refs
                ):
                    status = 'partial'
                if status == 'no_change' and not finding.reason.strip():
                    status = 'partial'
                if status == 'not_applicable' and not finding.reason.strip():
                    status = 'pending'
                # Only the collector can attribute transport failure or conclude a bounded search.
                if status in {'not_found', 'retrieval_failed'}:
                    status = 'pending'
                old = slot['direction_statuses'][direction_id]
                if (
                    old['status'] in {'found', 'no_change'}
                    and status not in {'found', 'no_change'}
                    and not (status == 'partial' and refs and finding.reason.strip())
                ):
                    continue
                if old['evidence_ids'] and not refs and status != 'not_applicable':
                    continue
                slot['direction_statuses'][direction_id] = dict(
                    status=status,
                    evidence_ids=list(dict.fromkeys(old['evidence_ids'] + refs))
                    if status in {'found', 'partial', 'no_change'}
                    else [],
                    reason=finding.reason or ('有适用原文证据' if refs else '尚未取得适用证据'),
                )
            last = MaterialAssessment(
                sufficient=output.sufficient,
                covered_dimensions={
                    d['label']: slot['direction_statuses'][d['direction_id']]['evidence_ids']
                    for d in slot['directions']
                    if slot['direction_statuses'][d['direction_id']]['evidence_ids']
                },
                direction_findings={
                    i: DirectionFinding.model_validate(v) for i, v in slot['direction_statuses'].items()
                },
                limitations=output.limitations,
            )
            assessed = known
            # Save merged statuses with the receipt before advancing to another document.
            self.store.record(self.run_id, 'collection_slot', task['task_id'], slot)
            self.store.execution_put(
                self.run_id,
                'execution_meta',
                key,
                dict(assessed_ids=sorted(assessed), output=last.model_dump(mode='json')),
            )
        last.sufficient = self.ready(slot, last.sufficient)
        return last

    def targets(self, slot):
        return sorted(
            [
                d
                for d in slot['directions']
                if slot['direction_statuses'][d['direction_id']]['status']
                in {'pending', 'partial', 'not_found', 'retrieval_failed'}
            ],
            key=lambda d: not d['required'],
        )

    def query(self, c, task, targets, broad):
        scope = task['material_scope']
        subject = search_subject(scope) if kind(task) == 'industry' else c['company']['name'] + ' ' + scope['subject']
        window = (
            scope['policy_start_date'] if any(d['direction_id'] == 'policy' for d in targets) else scope['start_date']
        )
        period = window[:4] + '-' + scope['as_of'][:4]
        if kind(task) == 'industry' and not broad:
            # One direction per query; no analytical question enters it.
            words = [subject, period, *(DIRECTION_TERMS.get(d['direction_id'], d['label']) for d in targets)]
            site = getattr(getattr(self.w.datasource, 'policy', None), 'policy_site', '')
            if site and [d['direction_id'] for d in targets] == ['policy']:
                words.append('site:' + site)
            return ' '.join(words)
        # Business categories remain grouped in one query.
        labels = [d['label'] for d in targets]
        discovery = '行业报告 市场规模 供需 竞争 政策' if kind(task) == 'industry' else '公司报告 业务构成 经营情况'
        return ' '.join([subject, period, discovery if broad else '资料 ' + ' '.join(labels)])

    async def read_sources(self, c, task, sources):
        from .fixed_collection import material_priority, row_data, periods, VERSION as fixed_version

        slot = self.slot(task)
        seen = set(slot['document_hashes'])
        terms = task.get('linked_segments', []) + subject_terms(task['material_scope'])
        sources = sorted(
            sources, key=lambda s: (-sum(t in s.title + ' ' + s.content for t in terms if t), material_priority(s))
        )
        for source in sources:
            check_pause(self.store, self.run_id)
            if source.kind != 'upload' and financial_document(source):
                continue
            if future_source(source, task['material_scope']['as_of']):
                continue
            row = row_data(source)
            if row and (
                row.get('ticker')
                or row.get('document_type') == 'security'
                or (row.get('document_type') == 'annual_report' and (row.get('field_id') or row.get('metric_code')))
            ):
                continue  # Already locked financial/security rows contain no qualitative material.
            fingerprint = source_key(source)
            if fingerprint in seen or len(seen) >= self.document_budget(task):
                continue
            shared_key = 'material-document-' + fingerprint
            shared = self.store.execution_get(self.run_id, 'execution_meta', shared_key)
            if not shared:
                await self.fixed.extract_document(c, source, quantitative=False)
                document_id = (
                    'document-'
                    + digest(
                        [
                            fixed_version,
                            digest(source.content),
                            c['company']['company_id'],
                            periods(c['brief']),
                            c['brief']['segments'],
                        ]
                    )[:24]
                )
                receipt = self.store.execution_get(self.run_id, 'execution_meta', document_id) or {}
                shared = dict(
                    source_id=receipt.get('source_id', source.source_id), state=receipt.get('state', 'complete')
                )
                self.store.execution_put(self.run_id, 'execution_meta', shared_key, shared)
            seen.add(fingerprint)
            # Reload because assessments persist their own copy of the slot.
            slot = self.slot(task)
            slot['document_hashes'] = sorted(seen)
            if shared['state'] == 'failed':
                slot.setdefault('read_failures', []).append(shared['source_id'])
            for history in slot['search_history'] + [slot[k] for k in ('reports', 'peers') if slot.get(k)]:
                if source.source_id in history['source_ids'] and shared['source_id'] not in history['source_ids']:
                    history['source_ids'].append(shared['source_id'])
            self.store.record(self.run_id, 'collection_slot', task['task_id'], slot)
            # Check after a small batch, or the last document, rather than every source.
            if len(seen) % 2 == 0:
                assessment = await self.assess(c, task)
                if self.complete(self.slot(task)):
                    return assessment
        return await self.assess(c, task)

    async def read_reports(self, c, task):
        """Broker reports on the company's industry are read before any web search; a
        failed fetch leaves only a warning on the slot and web search goes on as before."""
        reports = getattr(self.w, 'reports', None)
        ticker = str(c['company'].get('ticker') or '')
        if not reports or not re.fullmatch(r'\d{6}', ticker) or self.slot(task).get('reports', {}).get('processed'):
            return None
        as_of = task['material_scope']['as_of']
        months, limit = self.settings.research_report_months, self.settings.research_report_limit
        inputs = [VERSION, ticker, as_of, months, limit]

        async def fetch():
            try:
                found, warnings = await reports.fetch(ticker, date.fromisoformat(as_of), months, limit)
            except Exception as exc:  # Any failure degrades to web search, never stops the run.
                found, warnings = [], [f'券商研报获取失败：{type(exc).__name__}']
            found = [s for s in found if not financial_document(s)]
            return dict(sources=[s.model_dump(mode='json') for s in found], warnings=warnings)

        result = await unit(self.store, self.run_id, 'material_reports', digest(inputs), inputs, fetch)
        sources = [SourceRecord.model_validate(raw) for raw in result['sources']]
        for source in sources:
            self.store.record(self.run_id, 'source', source.source_id, source.model_dump(mode='json'))
        slot = self.slot(task)
        slot['reports'] = dict(source_ids=[s.source_id for s in sources], warnings=result['warnings'], processed=False)
        self.store.record(self.run_id, 'collection_slot', task['task_id'], slot)
        self.store.emit(
            self.run_id, '数据收集', task['task_id'], 'running', f"{task['topic']}：取得券商研报 {len(sources)} 份"
        )
        assessment = await self.read_sources(c, task, sources) if sources else None
        slot = self.slot(task)
        slot['reports']['processed'] = True
        self.store.record(self.run_id, 'collection_slot', task['task_id'], slot)
        return assessment

    async def read_peers(self, c, task):
        """Industry sections of the company's and its peers' CNINFO filings, read like any
        material, plus sample shares and CR3/CR5 computed from their revenue and sales
        volume, admitted as industry data on the listed-company-sample basis. Any failure
        leaves a warning and web search goes on."""
        from .industry_data import IndustryDataProposal, admit

        peers = getattr(self.w, 'peers', None)
        ticker = str(c['company'].get('ticker') or '')
        if not peers or not re.fullmatch(r'\d{6}', ticker) or self.slot(task).get('peers', {}).get('processed'):
            return None
        as_of = task['material_scope']['as_of']
        options = [self.settings.peer_disclosure_peers, self.settings.peer_disclosure_chars]
        options.append(self.settings.peer_prospectus_years)
        inputs = [VERSION, ticker, as_of, *options]

        async def fetch():
            try:
                return await peers.fetch(ticker, date.fromisoformat(as_of), *options)
            except Exception as exc:  # Any failure degrades to web search, never stops the run.
                failed = [f'同行公告获取失败：{type(exc).__name__}']
                return dict(sources=[], industry=None, year=None, calculation=None, warnings=failed)

        result = await unit(self.store, self.run_id, 'material_peers', digest(inputs), inputs, fetch)
        sources = [SourceRecord.model_validate(raw) for raw in result['sources']]
        for source in sources:
            self.store.record(self.run_id, 'source', source.source_id, source.model_dump(mode='json'))
        computed = []
        if result.get('calculation'):
            from .datasources import source_record

            text, rows = result['calculation']
            title = f"同行公告汇总计算：{result['industry']}上市公司样本（{result['year']}年）"
            calc = source_record('web', title, text, '全文', publication_date=as_of)
            self.store.record(self.run_id, 'source', calc.source_id, calc.model_dump(mode='json'))
            computed.append(calc.source_id)
            for metric, subject, line in rows:
                proposal = IndustryDataProposal(
                    source_id=calc.source_id,
                    subject=subject[:60],
                    metric=metric[:30],
                    period=result['year'] + '年',
                    value_text=line.rsplit('：', 1)[-1],
                    quote=line,
                    publisher='根据同行年报计算（上市公司合计口径）',
                )
                admitted = admit(proposal, calc)
                if admitted:
                    evidence, datum = admitted
                    self.store.record(self.run_id, 'evidence', evidence.evidence_id, evidence.model_dump(mode='json'))
                    self.store.record(self.run_id, 'industry_data', datum.data_id, datum.model_dump(mode='json'))
        slot = self.slot(task)
        ids = [source.source_id for source in sources] + computed
        slot['peers'] = dict(source_ids=ids, warnings=result['warnings'], processed=False)
        self.store.record(self.run_id, 'collection_slot', task['task_id'], slot)
        note = f"{task['topic']}：取得同行公告 {len(sources)} 份" + ('，已计算样本集中度' if computed else '')
        self.store.emit(self.run_id, '数据收集', task['task_id'], 'running', note)
        assessment = await self.read_sources(c, task, sources) if sources else None
        slot = self.slot(task)
        slot['peers']['processed'] = True
        self.store.record(self.run_id, 'collection_slot', task['task_id'], slot)
        return assessment

    async def search(self, c, task, query, targets):
        normalized = ' '.join(query.split())
        identity = digest([VERSION, normalized])
        # Only industry searches drop document-sharing previews and forum posts.
        options = {'filter_sources': True} if kind(task) == 'industry' else {}

        async def retrieve():
            try:
                found, warnings = await self.w.datasource.retrieve(normalized, **options)
                found = [s for s in found if s.kind == 'upload' or not financial_document(s)]
                return dict(sources=[s.model_dump(mode='json') for s in found], warnings=warnings)
            except DatasourceError as exc:
                return dict(sources=[], warnings=[str(exc)])

        result = await unit(self.store, self.run_id, 'material_search', identity, [VERSION, normalized], retrieve)
        for raw in result['sources']:
            source = SourceRecord.model_validate(raw)
            self.store.record(self.run_id, 'source', source.source_id, source.model_dump(mode='json'))
        slot = self.slot(task)
        if not any(h['query'] == normalized for h in slot['search_history']):
            slot['search_history'].append(
                dict(
                    query=normalized,
                    direction_ids=[d['direction_id'] for d in targets],
                    source_ids=[s['source_id'] for s in result['sources']],
                    warnings=result['warnings'],
                    state='retrieval_failed' if result['warnings'] else 'completed',
                    processed=False,
                    before_coverage=slot['direction_statuses'],
                )
            )
        slot['search_count'] = len(slot['search_history'])
        self.store.record(self.run_id, 'collection_slot', task['task_id'], slot)
        return result

    async def process_search(self, c, task, history):
        sources = {s['source_id']: s for s in self.store.records(self.run_id, 'source')}
        assessment = await self.read_sources(
            c, task, [SourceRecord.model_validate(sources[i]) for i in history['source_ids'] if i in sources]
        )
        slot = self.slot(task)
        entry = next(h for h in slot['search_history'] if h['query'] == history['query'])
        before = history['before_coverage']
        gain = any(
            set(f['evidence_ids']) - set(before[i]['evidence_ids'])
            or (f['status'] in {'found', 'no_change', 'not_applicable'} and f['status'] != before[i]['status'])
            for i, f in slot['direction_statuses'].items()
        )
        entry.update(processed=True, gained_evidence=gain)
        self.store.record(self.run_id, 'collection_slot', task['task_id'], slot)
        return assessment

    def finish(self, task, assessment, stop_reason):
        slot = self.slot(task)
        for d in slot['directions']:
            finding = slot['direction_statuses'][d['direction_id']]
            if finding['status'] != 'pending':
                continue
            searches = [h for h in slot['search_history'] if d['direction_id'] in h['direction_ids']]
            if searches or slot.get('read_failures'):
                failed = all(h['state'] == 'retrieval_failed' for h in searches) or bool(slot.get('read_failures'))
                finding.update(
                    status='retrieval_failed' if failed else 'not_found',
                    reason=(
                        '相关来源请求、读取或提取失败，不能据此认定没有资料'
                        if failed
                        else f"在{slot['scope']['policy_start_date'] if d['direction_id'] == 'policy' else slot['scope']['start_date']}至{slot['scope']['as_of']}的限定检索来源中，未取得适用证据；不代表不存在或无变化"
                    ),
                )
        refs = list(
            dict.fromkeys(i for finding in slot['direction_statuses'].values() for i in finding['evidence_ids'])
        )
        slot.update(
            state='ready' if assessment.sufficient else 'limited',
            stop_reason=stop_reason,
            evidence_ids=refs,
            source_ids=list(
                dict.fromkeys(
                    e['source_id'] for e in self.store.records(self.run_id, 'evidence') if e['evidence_id'] in refs
                )
            ),
        )
        # An optional direction searched without result (e.g. no recent policy) is simply
        # left out of the report; only required gaps and failed retrievals are limitations.
        limits = [
            f"{d['label']}：{STATUS_LABELS[slot['direction_statuses'][d['direction_id']]['status']]}；{slot['direction_statuses'][d['direction_id']]['reason']}"
            for d in slot['directions']
            if slot['direction_statuses'][d['direction_id']]['status'] not in {'found', 'no_change', 'not_applicable'}
            and (d['required'] or slot['direction_statuses'][d['direction_id']]['status'] != 'not_found')
        ]
        warnings = [v for h in slot['search_history'] for v in h['warnings']]
        if slot.get('read_failures'):
            warnings.append('部分资料提取失败，成功证据保留，缺口不能解释为未披露或不存在')
        slot['limitations'] = list(dict.fromkeys(assessment.limitations + limits + warnings))
        self.store.record(self.run_id, 'collection_slot', task['task_id'], slot)
        self.store.record(
            self.run_id,
            'reference_coverage',
            task['task_id'],
            dict(
                task_id=task['task_id'],
                fields=[],
                covered_questions={q: refs for q in task['question_ids']} if refs else {},
                missing_questions=[],
                external_queries=[h['query'] for h in slot['search_history']],
                status=slot['state'],
            ),
        )
        self.store.emit(
            self.run_id,
            '数据收集',
            task['task_id'],
            'completed',
            task['topic'] + '：' + ('资料就绪，缺口保留' if assessment.sufficient else '资料受限，结束取证'),
        )

    async def collect(self, c):
        pool = [
            SourceRecord.model_validate(s) for s in c['sources'] if s['source_id'] in c.get('material_source_ids', [])
        ]
        for task in c['plan']['tasks']:
            check_pause(self.store, self.run_id)
            slot = self.slot(task)
            if slot['state'] in {'ready', 'limited'}:
                continue
            assessment = await self.assess(c, task)
            if not self.complete(self.slot(task)):
                assessment = await self.read_sources(c, task, pool)
            if kind(task) == 'industry' and not self.complete(self.slot(task)):
                assessment = await self.read_reports(c, task) or assessment
            if kind(task) == 'industry' and not self.complete(self.slot(task)):
                assessment = await self.read_peers(c, task) or assessment
            for history in self.slot(task)['search_history']:
                if not history.get('processed'):
                    assessment = await self.process_search(c, task, history)
            stop_reason = 'coverage_complete'
            # Industry directions are searched one by one, so a fruitless policy search
            # does not end the search for market size; each gets one dedicated query.
            by_direction = kind(task) == 'industry'
            while not self.complete(self.slot(task)):
                slot = self.slot(task)
                if (
                    not by_direction
                    and len(slot['search_history']) >= 2
                    and all(not h.get('gained_evidence') for h in slot['search_history'][-2:])
                ):
                    stop_reason = 'no_new_evidence'
                    break
                if len(slot['document_hashes']) >= self.document_budget(task):
                    stop_reason = 'document_budget'
                    break
                if slot['search_count'] >= self.search_budget(task):
                    stop_reason = 'search_budget'
                    break
                if not self.w.datasource.web or not self.settings.search_url:
                    stop_reason = 'search_unavailable'
                    break
                broad = slot['search_count'] == 0
                targets = self.targets(slot)
                if by_direction and not broad:
                    used = {h['query'] for h in slot['search_history']}
                    targets = [d for d in targets if self.query(c, task, [d], False) not in used][:1]
                    if not targets:
                        stop_reason = 'directions_exhausted'
                        break
                elif not broad:
                    targets = targets[:3]
                query = self.query(c, task, targets, broad)
                if any(h['query'] == query for h in slot['search_history']):
                    stop_reason = 'duplicate_query'
                    break
                await self.search(c, task, query, targets)
                assessment = await self.process_search(c, task, self.slot(task)['search_history'][-1])
            self.finish(task, assessment, stop_reason)
        bound = self.fixed.load_bound(c)
        slots = self.store.records(self.run_id, 'collection_slot')
        limitations = list(dict.fromkeys(c.get('limitations', []) + [v for s in slots for v in s['limitations']]))
        return bound | dict(facts=self.fixed.facts(c), pending=[], limitations=limitations, material_collections=slots)
