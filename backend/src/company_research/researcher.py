import asyncio
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from .agents import ask, ask_bounded, ResearchExtraction, CompressedResearch, bind_extraction
from .schemas import ResearchTask, SourceRecord, EvidenceRecord, FinancialFact
from .execution import unit, settle, bounded_schedule, optimized_run
from .datasources import quote_locator


class ResearcherState(TypedDict):
    task: dict
    brief: dict
    round: int
    sources: list[dict]
    evidence: list[dict]
    facts: list[dict]
    queries: list[str]
    gaps: list[str]
    warnings: list[str]
    summary: dict
    reference_only: bool
    reference_prepared: bool
    reference_context: bool


def researcher_graph(gateway, datasource, store, run_id: str, max_rounds: int, mock=False, settings=None):
    optimized = optimized_run(store, run_id)

    async def retrieve(state):
        if state['task']['role'] == 'business':
            store.emit(
                run_id,
                '业务研究',
                state['task']['task_id'] + '_business',
                'running',
                '业务与行业研究：' + state['task']['topic'],
            )
        store.emit(
            run_id,
            '数据收集',
            state['task']['task_id'],
            'running',
            f"检索资料：{state['task']['topic']}，轮次 {state['round'] + 1}",
        )

        async def query(q):
            async def invoke():
                found, issues = await datasource.retrieve(q)
                return {'sources': [s.model_dump(mode='json') for s in found], 'warnings': issues}

            value = await unit(
                store, run_id, 'search', state['task']['task_id'], [state['task'], state['round'], q], invoke
            )
            return [SourceRecord.model_validate(s) for s in value['sources']], value['warnings']

        queries = state['queries']
        if state.get('reference_only'):
            queries = []
        if state.get('reference_prepared') and len(queries) > 3:
            queries = ['；'.join(queries[i::3]) for i in range(3)]
        results = await settle(query(q) for q in queries[:3])
        sources = {s['source_id']: s for s in state['sources']}
        warnings = list(state['warnings'])
        for records, issues in results:
            sources.update({s.source_id: s.model_dump(mode='json') for s in records})
            warnings += issues
        sources = {key: store.record(run_id, 'source', key, source) for key, source in sources.items()}
        return {'sources': list(sources.values()), 'warnings': warnings, 'round': state['round'] + 1}

    async def extract(state):
        sources = [SourceRecord.model_validate(s) for s in state['sources']]
        if state.get('reference_prepared'):
            sources = [s for s in sources if s.kind != 'upload']
            if not sources:
                return {'queries': []}
        if mock:
            import hashlib

            evidence = [
                EvidenceRecord(
                    evidence_id='ev-' + hashlib.sha256(s.source_id.encode()).hexdigest()[:20],
                    source_id=s.source_id,
                    claim=s.content,
                    quote=s.content,
                    locator=s.locator,
                    validation_status='verified',
                )
                for s in sources
                if not s.content.startswith('{')
            ][:4]
            return {'evidence': [e.model_dump(mode='json') for e in evidence], 'queries': [], 'gaps': []}
        from .contexts import extraction_batches
        from .schemas import ExtractionBatch
        from .framework import digest, comparison_periods
        from .schemas import ResearchBrief
        from .llm import TruncatedOutput, IncompleteOutput, CapacityError

        capacity = min(
            settings.extraction_input_tokens if settings else 16000, gateway.limits('researcher').input_capacity - 3000
        )
        periods = sorted({p for pair in comparison_periods(ResearchBrief.model_validate(state['brief'])) for p in pair})

        def batch_context(batch_id, windows):
            # Send each excerpt once, with its complete headers/units/footnotes
            # separately. Keep the original window unchanged in the audit record.
            sent = (
                [
                    {k: v for k, v in w.items() if k not in {'content', 'original_content'}}
                    | {'content': w['original_content'], 'metadata': w['content'].removesuffix(w['original_content'])}
                    for w in windows
                ]
                if optimized
                else windows
            )
            return {
                'task': state['task'],
                'brief': state['brief'],
                'batch_id': batch_id,
                'instructions': (
                    (
                        ['用户上传资料具有最高优先级；仅从当前资料提取，不请求外部交叉核验。']
                        + (
                            [
                                '本次提取行业、产业链、政策、需求规模、价格、竞争、技术、经营等背景证据，不限于目标公司的资料。',
                                '行业统计、市场规模、同行数据与未来判断保存到 evidence，quote 保留数值、年份、地域、口径；facts 留空，不能改写为目标公司财务数据。',
                            ]
                            if state.get('reference_context')
                            else []
                        )
                    )
                    if state.get('reference_only')
                    else []
                ),
                'question_ids': state['task'].get('question_ids', []),
                'sources': sent,
            }

        def request_size(windows):
            from .agents import request_messages

            return gateway.request_size(
                'researcher',
                request_messages('researcher', batch_context('batch-' + '0' * 24, windows)),
                ResearchExtraction,
            )

        cache = {b['batch_id']: b for b in store.records(run_id, 'batch')}
        from .agents import request_messages

        # Input identity includes task, brief, prompt, schema and model output;
        # each reused batch must also match every selected source window exactly.
        identity = [
            state['task'],
            state['brief'],
            request_messages('researcher', {}),
            ResearchExtraction.model_json_schema(),
        ]
        if hasattr(gateway, 'models'):
            model = gateway.models[gateway.routes.get('researcher', gateway.routes.get('default'))]
            identity.append(model.model_dump(exclude={'api_key_env', 'api_key_file_env', 'max_tokens'}))
            # Increasing resume budgets or changing dispatch/timeout limits must
            # not invalidate previously verified extraction results.
            identity.append(gateway.limits('researcher').max_output_tokens or model.max_tokens)
        reuse_id = 'extraction-reuse-' + digest(identity)
        receipt = (
            (store.execution_get(run_id, 'execution_meta', reuse_id) or {'batch_ids': []})
            if optimized
            else {'batch_ids': []}
        )
        reusable = [ExtractionBatch.model_validate(cache[k]) for k in receipt['batch_ids'] if k in cache]
        batches = extraction_batches(
            sources,
            state['task'],
            periods,
            capacity,
            request_size=request_size if optimized and hasattr(gateway, 'request_size') else None,
            reusable=reusable,
            input_identity=reuse_id if optimized else None,
        )

        def remember(batch):
            value = batch.model_dump(mode='json')
            store.record(run_id, 'batch', batch.batch_id, value)
            cache[batch.batch_id] = value
            if optimized and batch.batch_id not in receipt['batch_ids']:
                receipt['batch_ids'].append(batch.batch_id)
                store.execution_put(run_id, 'execution_meta', reuse_id, receipt)

        def merge(outputs):
            return tuple([item for output in outputs for item in output[i]] for i in range(5))

        async def run_batch(batch, depth=0):
            old = cache.get(batch.batch_id) if not optimized or batch.batch_id in receipt['batch_ids'] else None
            if old and old['status'] == 'validated':
                output = ResearchExtraction.model_validate(old['result'])
            else:
                batch.status = 'running'
                remember(batch)
                try:
                    if old and old['status'] == 'split':
                        raise CapacityError('复用已知拆分结构，不重复调用父批次')
                    output = await ask(
                        gateway, 'researcher', ResearchExtraction, batch_context(batch.batch_id, batch.windows)
                    )
                except (TruncatedOutput, IncompleteOutput, CapacityError) as exc:
                    batch.status = 'split'
                    batch.failure = type(exc).__name__
                    remember(batch)
                    if depth >= (settings.max_batch_splits if settings else 2):
                        return [], [], ['批次拆分恢复耗尽：' + batch.batch_id], list(batch.question_ids), []
                    if len(batch.windows) > 1:
                        mid = len(batch.windows) // 2
                        parts = [batch.windows[:mid], batch.windows[mid:]]
                    else:
                        w = batch.windows[0]
                        content = w['original_content']
                        mid = len(content) // 2
                        if mid < 16:
                            return [], [], ['单证据窗口仍无法完整输出'], list(batch.question_ids), []
                        # Preserve table metadata in both children, but shrink source rows.
                        prefix = w['content'].removesuffix(content)
                        parts = [
                            [
                                w
                                | {
                                    'content': prefix + content[:mid],
                                    'original_content': content[:mid],
                                    'end': w['start'] + mid,
                                }
                            ],
                            [
                                w
                                | {
                                    'content': prefix + content[mid:],
                                    'original_content': content[mid:],
                                    'start': w['start'] + mid,
                                }
                            ],
                        ]
                    outputs = []
                    for i, part in enumerate(parts):
                        child = batch.model_copy(
                            update={
                                'batch_id': batch.batch_id + '-' + str(i),
                                'parent_id': batch.batch_id,
                                'windows': part,
                                'status': 'pending',
                                'failure': None,
                                'result': {},
                            }
                        )
                        outputs.append(await run_batch(child, depth + 1))
                    return merge(outputs)
            # Replaying a valid output must not overwrite its durable batch with
            # the newly generated pending/empty batch shell.
            batch.result = output.model_dump(mode='json')
            batch.status = 'validated'
            batch.failure = None
            proposals = (
                output.model_copy(update={'facts': [], 'rejected_facts': []})
                if state.get('reference_context')
                else output
            )
            evidence, extracted, problems = bind_extraction(proposals, sources, state['task']['company_id'])
            evidence_mapping = {}
            for e in evidence:
                src = next(s for s in sources if s.source_id == e.source_id)
                e.locator = quote_locator(src, e.quote)
                old_id = e.evidence_id
                e.evidence_id = 'ev-' + digest([e.source_id, e.quote, e.actual_or_forecast])[:24]
                evidence_mapping[old_id] = e
            # Rebind facts after deterministic evidence IDs.
            for f in extracted:
                e = evidence_mapping[f.evidence_id]
                f.evidence_id = e.evidence_id
                f.locator = e.locator
                f.fact_id = (
                    'fact-'
                    + digest(
                        [
                            f.company_id,
                            f.metric_code,
                            f.period,
                            f.scope,
                            f.segment_id,
                            f.value,
                            f.unit,
                            f.currency,
                            f.accounting_basis,
                            f.actual_or_forecast,
                            f.version,
                            f.supersedes,
                            f.evidence_id,
                        ]
                    )[:24]
                )
            if problems:
                batch.status = 'quarantined'
                batch.failure = '; '.join(problems)
                store.record(
                    run_id,
                    'quarantine',
                    batch.batch_id,
                    {'batch': batch.batch_id, 'proposals': batch.result, 'problems': problems},
                )
            remember(batch)
            from .work_products import preserve_materials

            preserve_materials(
                store,
                run_id,
                [('evidence', e.evidence_id, e.model_dump(mode='json')) for e in evidence]
                + [('fact', f.fact_id, f.model_dump(mode='json')) for f in extracted],
            )
            return evidence, extracted, problems, list(output.gaps), list(output.followup_queries)

        if optimized:
            concurrency = min(
                settings.concurrency if settings else getattr(gateway, 'concurrency', 3),
                gateway.limits('researcher').concurrency or getattr(gateway, 'concurrency', 3),
            )
            outputs = await bounded_schedule(range(len(batches)), lambda i: run_batch(batches[i]), concurrency)
        else:
            outputs = [await run_batch(batch) for batch in batches]
        ev, facts, warnings, gaps, queries = merge(outputs)
        if not batches:
            gaps.append('没有定位到问题相关资料窗口')
        if gaps and not queries and state['task']['queries']:
            queries = [state['task']['queries'][0] + ' ' + str(gaps[0])]
        if state.get('reference_only'):
            queries = []
        elif state.get('reference_prepared'):
            # Keep follow-up searches restricted to targets absent from references.
            queries = state['task']['queries'] if gaps else []
        return {
            'evidence': state['evidence'] + [e.model_dump(mode='json') for e in ev],
            'facts': state['facts'] + [f.model_dump(mode='json') for f in facts],
            'queries': list(dict.fromkeys(queries))[:2],
            'gaps': list(dict.fromkeys(gaps)),
            'warnings': state['warnings'] + warnings,
        }

    def gap(state):
        store.emit(
            run_id,
            '数据收集',
            state['task']['task_id'],
            'running',
            f"缺口检查：{state['task']['topic']}，已保留 {len(state['evidence'])} 项证据",
        )
        return {}

    async def compress(state):
        if mock:
            summary = CompressedResearch(
                summary='模拟任务证据已整理。数据为合成 Fixture。',
                evidence_ids=[e['evidence_id'] for e in state['evidence']],
                unresolved=state['gaps'],
            )
        else:
            uniq = list({e['evidence_id']: e for e in state['evidence']}.values())
            slim = [
                {
                    'evidence_id': e['evidence_id'],
                    'claim': (e.get('claim') or '')[:120],
                    'source_id': e.get('source_id'),
                    'actual_or_forecast': e.get('actual_or_forecast'),
                }
                for e in uniq
            ]
            summary = await ask_bounded(
                gateway,
                'compression',
                CompressedResearch,
                {'task': state['task'], 'evidence': slim, 'gaps': state['gaps']},
            )
            known_ids = {e['evidence_id'] for e in state['evidence']}
            dropped = [i for i in summary.evidence_ids if i not in known_ids]
            if dropped:
                store.emit(
                    run_id,
                    '数据收集',
                    state['task']['task_id'],
                    'running',
                    f"压缩输出含 {len(dropped)} 项未知证据引用，已剔除",
                )
                summary.evidence_ids = [i for i in summary.evidence_ids if i in known_ids]
        store.emit(run_id, '数据收集', state['task']['task_id'], 'completed', f"研究摘要完成：{state['task']['topic']}")
        if state['task']['role'] == 'business':
            store.emit(
                run_id,
                '业务研究',
                state['task']['task_id'] + '_business',
                'completed',
                '业务与行业研究已完成：' + state['task']['topic'],
            )
        if state['task']['role'] == 'business':
            store.emit(run_id, '业务研究', '业务研究', 'completed', '业务与行业研究已完成：' + state['task']['topic'])
        return {'summary': summary.model_dump(mode='json')}

    g = StateGraph(ResearcherState)
    for name, fn in [('retrieve', retrieve), ('extract', extract), ('gap', gap), ('compress', compress)]:

        def wrap(name, fn):
            async def execute(state):
                return await unit(
                    store, run_id, 'research_step', state['task']['task_id'] + ':' + name, state, lambda: fn(state)
                )

            return execute

        g.add_node(name, fn if name == 'gap' else wrap(name, fn))
    g.add_edge(START, 'retrieve')
    g.add_edge('retrieve', 'extract')
    g.add_edge('extract', 'gap')
    g.add_conditional_edges('gap', lambda s: 'retrieve' if s['queries'] and s['round'] < max_rounds else 'compress')
    g.add_edge('compress', END)
    return g.compile()
