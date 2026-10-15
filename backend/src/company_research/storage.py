import json
import sqlite3
import threading
from pathlib import Path
from typing import Any
from .schemas import ResearchRun, ResearchEvent, ReportDocument, now, uid

TERMINAL = {"completed", "limited", "blocked", "failed", "interrupted", "waiting_human"}


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_run ON events(run_id,id);
                CREATE TABLE IF NOT EXISTS reports(run_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS checkpoints(run_id TEXT PRIMARY KEY, node TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS records(run_id TEXT, kind TEXT, id TEXT, payload TEXT, PRIMARY KEY(run_id,kind,id));
                CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS work_product_snapshots(run_id TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(run_id,id));
                CREATE TABLE IF NOT EXISTS work_product_reviews(run_id TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(run_id,id));
                CREATE TABLE IF NOT EXISTS work_product_materials(run_id TEXT, kind TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(run_id,kind,id));
                CREATE TABLE IF NOT EXISTS execution_units(run_id TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(run_id,id));
                CREATE TABLE IF NOT EXISTS execution_meta(run_id TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(run_id,id));
                CREATE TABLE IF NOT EXISTS execution_attempts(run_id TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(run_id,id));
            ''')

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=20)

    def save_run(self, run: ResearchRun) -> None:
        run.updated_at = now()
        with self.lock, self.connect() as db:
            db.execute("INSERT OR REPLACE INTO runs VALUES(?,?)", (run.run_id, run.model_dump_json()))

    def run(self, run_id: str) -> ResearchRun | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        return ResearchRun.model_validate_json(row[0]) if row else None

    def active_runs(self) -> list[ResearchRun]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM runs").fetchall()
        return [
            r
            for row in rows
            if (r := ResearchRun.model_validate_json(row[0])).status in {"queued", "running", "pausing"}
        ]

    def transition_run(self, run_id: str, expected: set[str], **changes) -> ResearchRun | None:
        """Compare and update under a database write lock; never overwrite a newer run."""
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM runs WHERE id=?', (run_id,)).fetchone()
            if not row:
                return None
            run = ResearchRun.model_validate_json(row[0])
            if run.status not in expected:
                return None
            for key, value in changes.items():
                setattr(run, key, value)
            run.updated_at = now()
            db.execute('UPDATE runs SET payload=? WHERE id=?', (run.model_dump_json(), run_id))
        return run

    def execution_get(self, run_id: str, table: str, key: str) -> dict | None:
        if table not in {'execution_units', 'execution_meta', 'execution_attempts'}:
            raise ValueError('Invalid execution table')
        with self.connect() as db:
            row = db.execute(f'SELECT payload FROM {table} WHERE run_id=? AND id=?', (run_id, key)).fetchone()
        return json.loads(row[0]) if row else None

    def execution_put(self, run_id: str, table: str, key: str, value: dict) -> None:
        if table not in {'execution_units', 'execution_meta', 'execution_attempts'}:
            raise ValueError('Invalid execution table')
        with self.lock, self.connect() as db:
            db.execute(
                f'INSERT OR REPLACE INTO {table} VALUES(?,?,?)',
                (run_id, key, json.dumps(value, ensure_ascii=False, default=str)),
            )

    def execution_list(self, run_id: str, table: str = 'execution_units') -> list[dict]:
        if table not in {'execution_units', 'execution_meta', 'execution_attempts'}:
            raise ValueError('Invalid execution table')
        with self.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(f'SELECT payload FROM {table} WHERE run_id=? ORDER BY rowid', (run_id,))
            ]

    def execution_states(self, run_id: str) -> list[dict]:
        with self.connect() as db:
            return [
                {'kind': kind, 'state': state}
                for kind, state in db.execute(
                    "SELECT json_extract(payload,'$.kind'),json_extract(payload,'$.state') FROM execution_units WHERE run_id=?",
                    (run_id,),
                )
            ]

    def isolation_state(self, run_id: str) -> dict:
        with self.connect() as db:
            db.execute('BEGIN')
            row = db.execute(
                "SELECT payload FROM execution_meta WHERE run_id=? AND id='data-isolation'", (run_id,)
            ).fetchone()
            has_reuse = bool(
                db.execute("SELECT 1 FROM records WHERE run_id=? AND kind='reuse' LIMIT 1", (run_id,)).fetchone()
            )
            has_progress = any(
                db.execute(f'SELECT 1 FROM {table} WHERE {key}=? LIMIT 1', (run_id,)).fetchone()
                for table, key in [
                    ('records', 'run_id'),
                    ('checkpoints', 'run_id'),
                    ('execution_units', 'run_id'),
                    ('reports', 'run_id'),
                ]
            )
        return {'policy': json.loads(row[0]) if row else None, 'has_reuse': has_reuse, 'has_progress': has_progress}

    def checkpoint_info(self, run_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT node,json_extract(payload,'$.rules_version') FROM checkpoints WHERE run_id=?", (run_id,)
            ).fetchone()
        return {'node': row[0], 'rules_version': row[1]} if row else None

    def adjust_budget(self, run_id: str, value: dict, defaults: dict) -> None:
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM runs WHERE id=?', (run_id,)).fetchone()
            if not row or ResearchRun.model_validate_json(row[0]).status not in {'interrupted', 'failed', 'blocked'}:
                raise ValueError('任务已开始执行，无法调整预算')
            row = db.execute("SELECT payload FROM execution_meta WHERE run_id=? AND id='budget'", (run_id,)).fetchone()
            old = json.loads(row[0]) if row else defaults
            if any(value[k] < old[k] for k in old):
                raise ValueError('只能增加总预算，已有消耗不会清零')
            db.execute('INSERT OR REPLACE INTO execution_meta VALUES(?,?,?)', (run_id, 'budget', json.dumps(value)))
            if value['block_call_budget'] > old['block_call_budget']:
                db.execute(
                    'INSERT OR REPLACE INTO execution_meta VALUES(?,?,?)',
                    (run_id, 'budget_override', '{"enabled":true}'),
                )
            adjustment = {'before': old, 'after': value, 'updated_at': now()}
            db.execute(
                'INSERT INTO records VALUES(?,?,?,?)', (run_id, 'budget_adjustment', uid(), json.dumps(adjustment))
            )

    def emit(
        self, run_id: str, stage: str, task: str, status: str, message: str, once_key: str | None = None
    ) -> ResearchEvent:
        event = ResearchEvent(run_id=run_id, stage=stage, task_name=task, status=status, display_message=message)
        with self.lock, self.connect() as db:
            if once_key:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute(
                    'SELECT payload FROM execution_meta WHERE run_id=? AND id=?', (run_id, 'event-' + once_key)
                ).fetchone()
                if row:
                    return ResearchEvent.model_validate_json(row[0])
            cursor = db.execute("INSERT INTO events(run_id,payload) VALUES(?,?)", (run_id, event.model_dump_json()))
            event.event_id = cursor.lastrowid
            db.execute("UPDATE events SET payload=? WHERE id=?", (event.model_dump_json(), event.event_id))
            if once_key:
                db.execute(
                    'INSERT INTO execution_meta VALUES(?,?,?)', (run_id, 'event-' + once_key, event.model_dump_json())
                )
            row = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
            if row:
                run = ResearchRun.model_validate_json(row[0])
                run.stage, run.updated_at = stage, now()
                db.execute("UPDATE runs SET payload=? WHERE id=?", (run.model_dump_json(), run_id))
        return event

    def events(self, run_id: str, after: int = 0) -> list[ResearchEvent]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM events WHERE run_id=? AND id>? ORDER BY id", (run_id, after)
            ).fetchall()
        return [ResearchEvent.model_validate_json(row[0]) for row in rows]

    def save_report(self, run_id: str, report: ReportDocument) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO reports VALUES(?,?)", (run_id, report.model_dump_json()))

    def report(self, run_id: str) -> ReportDocument | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM reports WHERE run_id=?", (run_id,)).fetchone()
        return ReportDocument.model_validate_json(row[0]) if row else None

    def checkpoint(self, run_id: str, node: str, state: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)",
                (run_id, node, json.dumps(state, ensure_ascii=False, default=str)),
            )

    def load_checkpoint(self, run_id: str) -> tuple[str, dict] | None:
        with self.connect() as db:
            row = db.execute("SELECT node,payload FROM checkpoints WHERE run_id=?", (run_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def record(self, run_id: str, kind: str, record_id: str, payload: dict, *, identity_fields=None) -> dict:
        if identity_fields is None:
            identity_fields = {
                'source': ('content', 'kind', 'source_url', 'local_path', 'locator'),
                'evidence': ('source_id', 'quote', 'actual_or_forecast', 'locator'),
                'fact': (
                    'company_id',
                    'metric_code',
                    'period',
                    'unit',
                    'value',
                    'actual_or_forecast',
                    'scope',
                    'segment_id',
                    'currency',
                    'accounting_basis',
                    'source_id',
                    'evidence_id',
                    'locator',
                    'version',
                    'supersedes',
                    'slot_id',
                    'raw_value',
                    'raw_unit',
                    'locked_at',
                    'value_origin',
                    'derivation_id',
                ),
            }.get(kind, ())
        with self.lock, self.connect() as db:
            if kind == 'data_slot':
                row = db.execute(
                    'SELECT payload FROM records WHERE run_id=? AND kind=? AND id=?', (run_id, kind, record_id)
                ).fetchone()
                if row:
                    old = json.loads(row[0])
                    if old.get('state') in {'locked', 'not_disclosed', 'not_applicable', 'source_missing'}:
                        if old != payload:
                            from .financials.formulas import FinancialError

                            raise FinancialError('固定表终态槽只读，拒绝覆盖：' + record_id)
                        return old
            if identity_fields:
                from decimal import Decimal
                from .financials.formulas import FinancialError

                db.execute('BEGIN IMMEDIATE')
                row = db.execute(
                    'SELECT payload FROM records WHERE run_id=? AND kind=? AND id=?', (run_id, kind, record_id)
                ).fetchone()
                if row:
                    old = json.loads(row[0])
                    for field in identity_fields:
                        before, after = old.get(field), payload.get(field)
                        if field == 'value' and before is not None and after is not None:
                            before, after = Decimal(str(before)), Decimal(str(after))
                        if before != after:
                            raise FinancialError(f'已保存{kind}的同一 ID 对应不同内容，拒绝覆盖：{record_id}/{field}')
                    if kind == 'source':
                        # Search metadata is not document identity. Pin the first
                        # version used by this run and retain later observations.
                        from .framework import digest

                        differences = {
                            field: {'saved': old.get(field), 'observed': payload.get(field)}
                            for field in ('title', 'publication_date')
                            if old.get(field) != payload.get(field)
                        }
                        if differences:
                            observation = {'source_id': record_id, 'differences': differences}
                            db.execute(
                                'INSERT OR IGNORE INTO records VALUES(?,?,?,?)',
                                (
                                    run_id,
                                    'source_metadata',
                                    digest(observation),
                                    json.dumps(observation, ensure_ascii=False),
                                ),
                            )
                        return old
            db.execute(
                "INSERT OR REPLACE INTO records VALUES(?,?,?,?)",
                (run_id, kind, record_id, json.dumps(payload, ensure_ascii=False, default=str)),
            )
        return payload

    def cached(self, key: str) -> Any | None:
        with self.connect() as db:
            row = db.execute("SELECT payload,created_at FROM cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        from datetime import datetime, timezone, timedelta

        if datetime.now(timezone.utc) - datetime.fromisoformat(row[1]) > timedelta(
            hours=getattr(self, 'cache_ttl_hours', 6)
        ):
            return None
        return json.loads(row[0])

    def records(self, run_id: str, kind: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM records WHERE run_id=? AND kind=?', (run_id, kind)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def runtime_summary(self, run_id: str) -> dict:
        """Small, read-only status projection; never expose prompts or source bodies."""
        with self.connect() as db:
            db.execute('BEGIN')
            counts = dict(
                db.execute(
                    '''
                SELECT kind, COUNT(*) FROM (
                    SELECT kind,id FROM records WHERE run_id=?
                    UNION
                    SELECT kind,id FROM work_product_materials WHERE run_id=?
                ) GROUP BY kind
            ''',
                    (run_id, run_id),
                )
            )
            calls = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT payload FROM records WHERE run_id=? AND kind='call' ORDER BY rowid", (run_id,)
                )
            ]
        finished = [c for c in calls if c.get('result') != 'running']
        cache_calls = [
            c for c in calls if c.get('cache_hit_tokens') is not None and c.get('cache_miss_tokens') is not None
        ]
        cache_input = sum(c['cache_hit_tokens'] + c['cache_miss_tokens'] for c in cache_calls)
        cache_hits = sum(c['cache_hit_tokens'] for c in cache_calls)
        return {
            'artifact_counts': {k: counts.get(k, 0) for k in ('source', 'evidence', 'fact', 'calculation', 'section')},
            'usage': {
                'calls': len(calls),
                'running_calls': len(calls) - len(finished),
                'succeeded_calls': sum(c.get('result') == 'ok' for c in finished),
                'failed_calls': sum(c.get('result') not in (None, 'ok') for c in finished),
                'provider_input_tokens': sum(c.get('input_tokens') or 0 for c in calls),
                'provider_output_tokens': sum(c.get('output_tokens') or 0 for c in calls),
                'usage_missing_calls': sum(c.get('usage_source') != 'provider' for c in finished),
                'cache_reported_calls': len(cache_calls),
                'cache_reported_input_tokens': cache_input,
                'cache_hit_tokens': cache_hits,
                'cache_hit_ratio': cache_hits / cache_input if cache_input else None,
            },
            'recent_calls': [
                {
                    k: c[k]
                    for k in (
                        'call_id',
                        'role',
                        'model',
                        'block_id',
                        'attempt',
                        'result',
                        'started_at',
                        'duration_seconds',
                        'input_tokens',
                        'output_tokens',
                        'cache_hit_tokens',
                        'cache_miss_tokens',
                        'response_model',
                        'reasoning_tokens',
                    )
                    if k in c
                }
                for c in sorted(reversed(calls), key=lambda c: c.get('started_at', ''), reverse=True)[:8]
            ],
        }

    def work_product_state(self, run_id: str) -> dict:
        """Read all submitted materials on one SQLite WAL read boundary.

        A damaged individual record is reported, not silently omitted. This reader
        never changes the research run, checkpoint, report or approval records.
        """
        state = {'records': {}, 'reviews': [], 'events': [], 'unavailable': []}

        def read(payload, label):
            try:
                return json.loads(payload)
            except (ValueError, TypeError):
                state['unavailable'].append({'artifact': label, 'reason': '已保存记录无法解析'})
                return None

        with self.connect() as db:
            db.execute('BEGIN')
            row = db.execute('SELECT payload FROM runs WHERE id=?', (run_id,)).fetchone()
            if not row:
                return state
            state['run'] = read(row[0], 'run')
            row = db.execute('SELECT node,payload FROM checkpoints WHERE run_id=?', (run_id,)).fetchone()
            state['checkpoint_node'] = row[0] if row else None
            state['context'] = read(row[1], 'checkpoint') if row else {}
            row = db.execute('SELECT payload FROM reports WHERE run_id=?', (run_id,)).fetchone()
            state['report'] = read(row[0], 'report') if row else None
            for kind, record_id, payload in db.execute(
                'SELECT kind,id,payload FROM records WHERE run_id=? ORDER BY kind,id', (run_id,)
            ):
                value = read(payload, f'{kind}/{record_id}')
                if value is not None:
                    state['records'].setdefault(kind, []).append(value)
            for event_id, payload in db.execute('SELECT id,payload FROM events WHERE run_id=? ORDER BY id', (run_id,)):
                value = read(payload, f'event/{event_id}')
                if value is not None:
                    state['events'].append(value)
            for review_id, payload in db.execute(
                'SELECT id,payload FROM work_product_reviews WHERE run_id=? ORDER BY rowid', (run_id,)
            ):
                value = read(payload, f'review/{review_id}')
                if value is not None:
                    state['reviews'].append(value)
            state['partial'] = {}
            for kind, material_id, payload in db.execute(
                'SELECT kind,id,payload FROM work_product_materials WHERE run_id=? ORDER BY kind,id', (run_id,)
            ):
                value = read(payload, f'partial/{kind}/{material_id}')
                if value is not None:
                    state['partial'].setdefault(kind, []).append(value)
        return state

    def save_work_product_snapshot(self, run_id: str, snapshot_id: str, payload: dict) -> dict:
        with self.connect() as db:
            db.execute(
                'INSERT OR IGNORE INTO work_product_snapshots VALUES(?,?,?)',
                (run_id, snapshot_id, json.dumps(payload, ensure_ascii=False)),
            )
            row = db.execute(
                'SELECT payload FROM work_product_snapshots WHERE run_id=? AND id=?', (run_id, snapshot_id)
            ).fetchone()
        return json.loads(row[0])

    def work_product_snapshot(self, run_id: str, snapshot_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                'SELECT payload FROM work_product_snapshots WHERE run_id=? AND id=?', (run_id, snapshot_id)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def save_work_product_review(self, run_id: str, review_id: str, payload: dict) -> None:
        with self.connect() as db:
            db.execute(
                'INSERT OR REPLACE INTO work_product_reviews VALUES(?,?,?)',
                (run_id, review_id, json.dumps(payload, ensure_ascii=False)),
            )

    def save_work_product_materials(self, run_id: str, materials: list[tuple[str, str, dict]]) -> None:
        with self.connect() as db:
            db.executemany(
                'INSERT OR REPLACE INTO work_product_materials VALUES(?,?,?,?)',
                [
                    (run_id, kind, material_id, json.dumps(value, ensure_ascii=False))
                    for kind, material_id, value in materials
                ],
            )

    def cache(self, key: str, value: Any) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO cache VALUES(?,?,?)", (key, json.dumps(value, ensure_ascii=False), now())
            )
