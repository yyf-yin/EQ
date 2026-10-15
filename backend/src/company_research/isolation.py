"""Fail closed when saved research predates run-scoped data isolation."""

POLICY = 'run-isolated-1'


def isolation_info(store, run_id):
    state = store.isolation_state(run_id)
    run = store.run(run_id)
    policy = state['policy']
    reason = None
    if state['has_reuse']:
        reason = '该任务曾导入其他任务的历史财务资料，无法安全续跑或作为正式报告交付；请导出阶段成果并新建研究。'
    elif policy is not None and policy != {'version': POLICY, 'run_id': run_id}:
        reason = '任务的数据隔离标记不匹配，无法安全恢复；请保留阶段成果并新建研究。'
    elif policy is None and run and run.mode == 'real' and state['has_progress']:
        reason = '旧真实任务的已保存成果缺少数据隔离记录，无法确认未混入历史资料；请导出阶段成果并新建研究。'
    return {
        'policy': POLICY,
        'status': 'blocked' if reason else 'isolated' if policy else 'uninitialized',
        'reason': reason,
    }


def ensure_isolation(store, run_id):
    from .execution import RecoveryError

    info = isolation_info(store, run_id)
    if info['reason']:
        raise RecoveryError(info['reason'])
    if info['status'] == 'uninitialized':
        store.execution_put(run_id, 'execution_meta', 'data-isolation', {'version': POLICY, 'run_id': run_id})
