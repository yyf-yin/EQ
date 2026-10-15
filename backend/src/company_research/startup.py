"""Explicit launcher choice for the most recently created unfinished run."""
import re

from .schemas import ResearchRun
from .execution import recovery_info


def latest_unfinished(store):
    with store.connect() as db:
        row = db.execute("""SELECT payload FROM runs
            WHERE json_extract(payload,'$.status') IN ('queued','running','pausing','interrupted','failed','blocked','waiting_human')
            AND NOT EXISTS (SELECT 1 FROM execution_meta d WHERE d.run_id=runs.id AND d.id='startup-decision'
                            AND json_extract(d.payload,'$.answer')='N')
            ORDER BY json_extract(payload,'$.created_at') DESC, rowid DESC LIMIT 1""").fetchone()
    return ResearchRun.model_validate_json(row[0]) if row else None


def continuation_view(settings, store, run):
    candidate = run.model_copy(deep=True)
    if candidate.status in {'queued','running','pausing'}:
        candidate.status = 'interrupted'
    # This retired guard checked search metadata rather than document identity.
    if candidate.status == 'blocked' and candidate.failure_code == 'quality' and re.fullmatch(
        r'已保存source的同一 ID 对应不同内容，拒绝覆盖：[^/]+/publication_date', candidate.error or ''):
        candidate.status = 'interrupted'
        candidate.failure_code = None
    class View:
        service_session_id = None
        def run(self, run_id):return candidate if run_id == candidate.run_id else store.run(run_id)
        def __getattr__(self, name):return getattr(store, name)
    return candidate, recovery_info(settings, View(), candidate.run_id)
