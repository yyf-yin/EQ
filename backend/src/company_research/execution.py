"""Durable, run-scoped work units. Internal outputs never enter evaluation exports."""

import asyncio
import copy
import hashlib
from contextvars import ContextVar
from pathlib import Path

from .framework import digest, VERSION
from .schemas import now

SCOPE = ContextVar('execution_scope', default='')
EXECUTION_VERSION = 'resume-1'


class PauseRequested(Exception):
    pass


class RecoveryError(Exception):
    pass


class DependencySchedulingError(RuntimeError):
    pass


def unit_key(kind, name, inputs):
    return digest([EXECUTION_VERSION, kind, name, inputs])


def check_pause(store, run_id):
    run = store.run(run_id)
    if run and run.status == 'pausing':
        raise PauseRequested()


async def unit(store, run_id, kind, name, inputs, action):
    """Commit complete results before the parent graph advances; replay by exact input."""
    check_pause(store, run_id)
    key = unit_key(kind, name, inputs)
    old = store.execution_get(run_id, 'execution_units', key)
    if (
        old
        and kind == 'model'
        and old['state'] == 'failed'
        and old.get('error_type') in {'TruncatedOutput', 'IncompleteOutput'}
    ):
        from . import llm

        raise getattr(llm, old['error_type'])('复用已知容量/截断诊断，继续执行拆分恢复。')
    if old and old['state'] == 'succeeded':
        if digest(old['output']) != old['output_hash']:
            raise RecoveryError('已保存执行结果校验失败，原成果保留，请检查数据库。')
        return copy.deepcopy(old['output'])
    record = {
        'id': key,
        'kind': kind,
        'name': name,
        'state': 'running',
        'attempts': (old or {}).get('attempts', 0) + 1,
        'started_at': now(),
    }
    store.execution_put(run_id, 'execution_units', key, record)
    token = SCOPE.set(key)
    try:
        result = await action()
        # A successful call already in flight is committed even after pause was requested.
        record.update(state='succeeded', output=result, output_hash=digest(result), completed_at=now())
        store.execution_put(run_id, 'execution_units', key, record)
        return copy.deepcopy(result)
    except (asyncio.CancelledError, PauseRequested):
        record.update(state='uncertain', error_type='Interrupted')
        store.execution_put(run_id, 'execution_units', key, record)
        raise
    except Exception as exc:
        record.update(state='failed', error_type=type(exc).__name__)
        store.execution_put(run_id, 'execution_units', key, record)
        raise
    finally:
        SCOPE.reset(token)


async def settle(actions):
    """Let already-started peers commit before propagating one failure."""
    results = await asyncio.gather(*actions, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return results


def optimized_run(store, run_id):
    """Pin scheduling/input strategy; existing checkpoints retain their exact inputs."""
    profile = store.execution_get(run_id, 'execution_meta', 'performance')
    if profile is None:
        legacy = bool(store.load_checkpoint(run_id) or store.execution_states(run_id))
        profile = {'version': 'legacy' if legacy else 'throughput-1'}
        store.execution_put(run_id, 'execution_meta', 'performance', profile)
    return profile['version'] == 'throughput-1'


async def bounded_schedule(keys, action, concurrency, ready=None):
    """Refill free slots; stop dispatch on failure and let in-flight work commit.

    Dependency readiness sees completed work only. Results retain input order so
    completion timing cannot change downstream prompts or checkpoint identities.
    """
    keys = list(keys)
    order = {key: i for i, key in enumerate(keys)}
    pending = list(keys)
    completed, results, running = set(), {}, {}
    try:
        while pending or running:
            for key in list(pending):
                if len(running) >= concurrency:
                    break
                if ready is None or ready(key, completed):
                    running[asyncio.create_task(action(key))] = key
                    pending.remove(key)
            if not running:
                raise DependencySchedulingError('任务依赖无法满足')
            finished, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            failures = {}
            for task in finished:
                key = running.pop(task)
                try:
                    results[key] = task.result()
                    completed.add(key)
                except BaseException as exc:
                    failures[key] = exc
            if failures:
                peers = list(running)
                settled = await asyncio.gather(*peers, return_exceptions=True)
                for task, result in zip(peers, settled):
                    if isinstance(result, BaseException):
                        failures[running[task]] = result
                # Preserve the old input-order exception precedence, including
                # quality vs execution failures, regardless of response timing.
                raise failures[min(failures, key=order.__getitem__)]
        return [results[key] for key in keys]
    finally:
        for task in running:
            if not task.done():
                task.cancel()
        await asyncio.gather(*running, return_exceptions=True)


def manifest(settings, gateway=None, mode='real'):
    from .config import ROOT
    from .datasources import EXTENSIONS

    root = ROOT / 'examples/fixtures' if mode == 'mock' else settings.local_sources
    sources = []
    admitted_paths = None
    if mode == 'real' and settings.data_collection_mode == 'fixed':
        from .datasources import LocalDatasource

        local = LocalDatasource(root)
        local.build_index(exclude_annual_reports=True)
        admitted_paths = {Path(s.local_path).as_posix() for s in local.index if s.local_path}
    if root.is_dir():
        for path in sorted(root.rglob('*')):
            if path.is_file() and path.suffix.lower() in EXTENSIONS:
                if admitted_paths is not None and path.relative_to(root).as_posix() not in admitted_paths:
                    continue
                sources.append([path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()])
    prompts = sorted((Path(__file__).parent / 'prompts').glob('*.txt'))
    models = {}
    if gateway:
        for role, route in gateway.routes.items():
            model = gateway.models[route]
            models[role] = {
                'model': model.model,
                'protocol': model.protocol,
                'base_url': model.base_url,
                'structured_mode': model.structured_mode,
                'max_tokens': gateway.limits(role).max_output_tokens or model.max_tokens,
            }
    from .reconciliation import POLICY as reconciliation_policy

    result = {
        'version': EXECUTION_VERSION,
        'rules_version': VERSION,
        'financial_reconciliation': reconciliation_policy,
        'human_intervention': 'human-data-1',
        'mode': mode,
        'sources': digest(sources),
        'prompts': digest([p.read_text(encoding='utf-8') for p in prompts]),
        'models': digest(models),
        'research_limits': digest(
            {
                k: getattr(settings, k)
                for k in (
                    'max_research_rounds',
                    'max_replans',
                    'max_conflict_checks',
                    'max_revisions',
                    'max_batch_splits',
                    'plan_repairs',
                    'extraction_input_tokens',
                    'material_search_budget',
                    'material_document_budget',
                    'material_industry_search_budget',
                    'material_industry_document_budget',
                    'material_extra_direction_limit',
                    'material_policy_years',
                )
            }
        ),
        'retrieval': digest([settings.search_provider, settings.search_url, settings.search_auth_header]),
    }
    if mode == 'real':
        from .fixed_collection import TEMPLATE, VERSION as slot_version
        from .material_collection import VERSION as material_version, PRESETS
        from .annual_reports import POLICY as annual_input_policy
        from .reporting_periods import POLICY as period_policy

        result['data_collection'] = digest(
            [
                settings.data_collection_mode,
                slot_version,
                TEMPLATE,
                material_version,
                PRESETS,
                annual_input_policy,
                period_policy,
            ]
        )
    return result


def human_upgrade_safe(store, run_id):
    """Retain compatible old progress without letting dirty inputs bypass the gate."""
    checkpoint = store.load_checkpoint(run_id)
    if not checkpoint or checkpoint[0] in {
        'resolve_company',
        'research_brief',
        'research_plan',
        'calculation_plan',
        'dependencies',
        'supervisor',
        'data_gaps',
        'replan',
    }:
        return True  # The new uncached calculation entry will run the human gate.
    from .human_intervention import blocking, matches

    context = checkpoint[1]
    required = context.get('required_data')
    decisions = context.get('fact_decisions')
    if required is None or decisions is None:
        return False
    critical = [r for r in required if blocking(r)]
    if any(r.get('source_status') != 'found' for r in critical):
        return False
    return not any(d['status'] == 'unresolved' and any(matches(d['identity'], r) for r in critical) for d in decisions)


def ensure_manifest(settings, store, run_id, gateway=None):
    from .isolation import ensure_isolation

    ensure_isolation(store, run_id)
    run = store.run(run_id)
    current = manifest(settings, gateway, run.mode)
    from .references import reference_fingerprint

    reference = reference_fingerprint(store, run_id)
    if reference:
        current['uploaded_references'] = reference
    previous = store.execution_get(run_id, 'execution_meta', 'manifest')
    compatible_previous = previous
    # Mock runs never retrieve web data; adding its fingerprint need not break
    # an otherwise unchanged, isolated mock checkpoint from the earlier version.
    if previous and run.mode == 'mock' and 'retrieval' not in previous:
        compatible_previous = previous | {'retrieval': current['retrieval']}
    if (
        compatible_previous
        and 'human_intervention' not in compatible_previous
        and (run.mode == 'mock' or human_upgrade_safe(store, run_id))
    ):
        compatible_previous = compatible_previous | {'human_intervention': current['human_intervention']}
    if compatible_previous and compatible_previous != current:
        raise RecoveryError(
            '资料、模型、提示或流程规则已改变，无法安全沿用原断点。请恢复原配置后继续，或保留阶段成果并新建研究。'
        )
    if previous != current:
        store.execution_put(run_id, 'execution_meta', 'manifest', current)


def budget_limits(settings, store, run_id):
    return store.execution_get(run_id, 'execution_meta', 'budget') or {
        'global_call_budget': settings.global_call_budget,
        'global_token_budget': settings.global_token_budget,
        'block_call_budget': settings.block_call_budget,
    }


def load_gateway(settings, store, run_id):
    from .llm import Gateway

    gateway = Gateway.from_file(
        settings.models_config,
        concurrency=settings.concurrency,
        timeout=settings.request_timeout,
        enforce_call_budgets=settings.enforce_call_budgets,
        **budget_limits(settings, store, run_id),
    )
    if store.execution_get(run_id, 'execution_meta', 'budget_override'):
        # The explicit run-level block limit applies across all roles for this run.
        for limits in gateway.role_limits.values():
            if limits.block_call_budget is not None:
                limits.block_call_budget = gateway.block_call_budget
    return gateway


def accounted_tokens(record):
    if record.get('usage_source') == 'provider':
        return (record.get('input_tokens') or 0) + (record.get('output_tokens') or 0)
    return record.get('budget_tokens', 0)


def recovery_info(settings, store, run_id):
    from .isolation import isolation_info

    isolation = isolation_info(store, run_id)
    run = store.run(run_id)
    checkpoint = store.checkpoint_info(run_id)
    units = store.execution_states(run_id)
    calls = store.records(run_id, 'call')
    limits = budget_limits(settings, store, run_id)
    compatible = not checkpoint or checkpoint['rules_version'] == VERSION
    budget_failure = run.failure_code == 'budget' or (
        not run.failure_code and (run.error or '').startswith('调用/全局 token 预算耗尽：')
    )
    from .startup import owns_run

    current_session = owns_run(store, run_id)
    allowed = (
        run.status in {'interrupted', 'waiting_human'}
        or (run.status == 'failed' and run.failure_code in {None, 'execution', 'budget'})
        or (run.status == 'blocked' and budget_failure)
    )
    reason = '保留已保存成果，从未完成的步骤继续。'
    if not compatible:
        allowed = False
        reason = '旧规则检查点不能恢复到当前流程；可导出阶段成果。'
    elif checkpoint and not (settings.database.parent / 'graph.sqlite').is_file():
        allowed = False
        reason = '图检查点文件缺失，请恢复 graph.sqlite；原阶段成果仍保留。'
    elif run.failure_code == 'incompatible':
        allowed = False
        reason = '资料或配置与已保存输入不兼容，不能继续；请新建研究，原成果仍保留。'
    elif (run.status == 'blocked' and not budget_failure) or run.failure_code == 'quality':
        reason = '数据或审核质量阻断，需要修复研究输入并新建研究；不能通过继续操作跳过审核。'
    if run.status == 'waiting_human':
        reason = '等待人工数据反馈；提交后可继续核验，关键问题解决前不进入计算。'
    usage = sum(accounted_tokens(c) for c in calls)
    blocks = {}
    for c in calls:
        block = c.get('block_id') or 'global'
        blocks[block] = blocks.get(block, 0) + 1
    failure = (store.execution_get(run_id, 'execution_meta', 'budget_failure') or {}) if budget_failure else {}
    block_caps = {b: limits['block_call_budget'] for b in blocks if b != 'global'}
    if failure.get('kind') == 'block' and not store.execution_get(run_id, 'execution_meta', 'budget_override'):
        block_caps[failure['block_id']] = min(limits['block_call_budget'], failure['limit'])
    exhausted_blocks = [
        b
        for b, cap in block_caps.items()
        if settings.enforce_call_budgets and budget_failure and blocks.get(b, 0) >= cap
    ]
    calls_exhausted = settings.enforce_call_budgets and len(calls) >= limits['global_call_budget']
    tokens_exhausted = (
        usage >= limits['global_token_budget']
        or usage + failure.get('request_tokens', 0) > limits['global_token_budget']
    )
    exhausted = calls_exhausted or tokens_exhausted or bool(exhausted_blocks)
    if exhausted and allowed:
        if calls_exhausted:
            reason = f"总调用预算耗尽：{len(calls)} / {limits['global_call_budget']} 次，请提高总调用上限后继续。"
        elif tokens_exhausted:
            reason = f"总 token 预算不足：已记账 {usage} / {limits['global_token_budget']}，下一请求需预留 {failure.get('request_tokens', 0)}，请提高总 token 上限后继续。"
        else:
            block = exhausted_blocks[0]
            reason = (
                f'分析块 {block} 调用预算耗尽：{blocks[block]} / {block_caps[block]} 次，请提高每块调用上限后继续。'
            )
    elif budget_failure and allowed:
        reason = '当前预算可继续，已保存成果和累计用量保留。'
    if isolation['reason']:
        allowed = False
        reason = isolation['reason']
    if not current_session:
        allowed = False
        reason = '只有最近一个未完成的任务可以在页面继续；此任务可导出成果包后在首页上传继续，原成果可查看。'
    elif run.failure_code == 'configuration':
        reason = '配置错误需要修复后新建研究；原成果可查看或导出。'
    counts = {}
    for u in units:
        if u['state'] == 'succeeded':
            counts[u['kind']] = counts.get(u['kind'], 0) + 1
    return {
        'can_resume': allowed and not exhausted,
        'can_increase_budget': allowed,
        'current_session': current_session,
        'can_pause': current_session and run.status in {'queued', 'running'},
        'data_isolation': isolation,
        'reason': reason,
        'checkpoint_node': checkpoint['node'] if checkpoint else None,
        'saved_units': counts,
        'unfinished_units': sum(u['state'] != 'succeeded' for u in units),
        'resume_count': run.resume_count,
        'budget': limits
        | {
            'calls_used': len(calls),
            'tokens_used': usage,
            'enforce_call_budgets': settings.enforce_call_budgets,
            'unknown_calls': sum(c.get('result') in {'running', 'interrupted', 'uncertain'} for c in calls),
        },
        'legacy': bool(checkpoint and not store.execution_get(run_id, 'execution_meta', 'manifest')),
    }
