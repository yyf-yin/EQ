"""The most recently created unfinished run is the one the page may continue after a restart."""

import re

from .schemas import ResearchRun

UNFINISHED = ('queued', 'running', 'pausing', 'interrupted', 'failed', 'blocked', 'waiting_human')


def latest_unfinished(store):
    with store.connect() as db:
        row = db.execute(
            f"""SELECT payload FROM runs WHERE json_extract(payload,'$.status') IN ({','.join('?' * len(UNFINISHED))})
            ORDER BY json_extract(payload,'$.created_at') DESC, rowid DESC LIMIT 1""",
            UNFINISHED,
        ).fetchone()
    return ResearchRun.model_validate_json(row[0]) if row else None


def owns_run(store, run_id):
    """This service may control runs it started, plus the latest unfinished one."""
    session_id = getattr(store, 'service_session_id', None)
    if session_id is None or store.execution_get(run_id, 'execution_meta', 'service-session') == {
        'session_id': session_id
    }:
        return True
    latest = latest_unfinished(store)
    return bool(latest and latest.run_id == run_id)


def claim_run(store, run_id):
    store.execution_put(run_id, 'execution_meta', 'service-session', {'session_id': store.service_session_id})


def release_retired_guard(store):
    """A retired guard checked search metadata rather than document identity; its blocks may continue."""
    run = latest_unfinished(store)
    if (
        run
        and run.status == 'blocked'
        and run.failure_code == 'quality'
        and re.fullmatch(r'已保存source的同一 ID 对应不同内容，拒绝覆盖：[^/]+/publication_date', run.error or '')
    ):
        store.transition_run(run.run_id, {'blocked'}, status='interrupted', failure_code=None)
