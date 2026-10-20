"""Rewind a stopped run to just before a node so it can be resumed with new code.

Developer tool, run with the backend stopped:
    .venv\\Scripts\\python.exe scripts\\rewind_run.py <run_id> [--to assumptions] [--token-budget N] [--dry-run]

Both databases are backed up first (sqlite online backup) into data/runs/backups/.
The graph thread is forked from the last checkpoint whose next node is --to, so
collected sources, evidence and facts are kept. Saved node results from --to
onward and cached section drafts are dropped so they really run again; model
calls with unchanged prompts and inputs still replay from cache.
"""
import argparse
import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from company_research.config import Settings
from company_research.execution import budget_limits
from company_research.graphs import ResearchWorkflow, STAGES
from company_research.storage import Store

TAIL = [
    'financial_analysis',
    'assumptions',
    'calculate',
    'validate',
    'analyze_blocks',
    'write_sections',
    'core_conclusion',
    'assemble',
    'final_review',
    'revise',
    'render',
    'deliver',
]


def backup(path: Path, folder: Path):
    target = folder / path.name
    with sqlite3.connect(path) as src, sqlite3.connect(target) as dst:
        src.backup(dst, pages=4096)
    print('backup', path.name, '->', target)


async def find_snapshot(settings, store, run_id, node):
    async with AsyncSqliteSaver.from_conn_string(str(settings.database.parent / 'graph.sqlite')) as saver:
        graph = ResearchWorkflow(settings, store, run_id).build(saver)
        config = {'configurable': {'thread_id': run_id}}
        async for snapshot in graph.aget_state_history(config):
            if snapshot.next == (node,):
                return snapshot
    return None


async def fork(settings, store, run_id, snapshot, previous):
    async with AsyncSqliteSaver.from_conn_string(str(settings.database.parent / 'graph.sqlite')) as saver:
        graph = ResearchWorkflow(settings, store, run_id).build(saver)
        await graph.aupdate_state(snapshot.config, snapshot.values, as_node=previous)
        state = await graph.aget_state({'configurable': {'thread_id': run_id}})
        return state.next


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run_id')
    parser.add_argument('--to', default='assumptions', choices=TAIL[1:-2])
    parser.add_argument('--token-budget', type=int, help='raise the run token budget (only increases)')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    settings = Settings()
    store = Store(settings.database)
    run = store.run(args.run_id)
    if not run:
        raise SystemExit('run not found')
    if run.status not in {'blocked', 'failed', 'interrupted'}:
        raise SystemExit(f'run is {run.status}; stop the backend and only rewind a stopped run')
    previous = TAIL[TAIL.index(args.to) - 1]
    dropped = set(TAIL[TAIL.index(args.to) :])

    snapshot = await find_snapshot(settings, store, args.run_id, args.to)
    if not snapshot:
        raise SystemExit(f'no graph checkpoint before {args.to}')
    with store.connect() as db:
        units = [
            (key, json.loads(payload))
            for key, payload in db.execute(
                'SELECT id,payload FROM execution_units WHERE run_id=?', (args.run_id,)
            ).fetchall()
        ]
        units = [key for key, u in units if u.get('kind') == 'node' and u.get('name') in dropped]
        sections = db.execute(
            "SELECT count(*) FROM records WHERE run_id=? AND kind IN ('section','review_issue')", (args.run_id,)
        ).fetchone()[0]
    limits = budget_limits(settings, store, args.run_id)
    print(f'run {run.run_id} {run.status}: {run.error}')
    print(f'fork from checkpoint {snapshot.config["configurable"].get("checkpoint_id")} (next={snapshot.next})')
    print(f'drop {len(units)} saved node results, {sections} section/review records')
    print(f'token budget {limits["global_token_budget"]} -> {args.token_budget or "unchanged"}')
    if args.dry_run:
        return

    folder = settings.database.parent / 'backups' / f'{args.run_id}-rewind-{datetime.now():%Y%m%d-%H%M%S}'
    folder.mkdir(parents=True)
    backup(settings.database, folder)
    backup(settings.database.parent / 'graph.sqlite', folder)

    print('graph next ->', await fork(settings, store, args.run_id, snapshot, previous))
    with store.lock, store.connect() as db:
        db.executemany(
            'DELETE FROM execution_units WHERE run_id=? AND id=?', [(args.run_id, key) for key in units]
        )
        db.execute("DELETE FROM records WHERE run_id=? AND kind IN ('section','review_issue')", (args.run_id,))
        db.execute(
            "DELETE FROM execution_meta WHERE run_id=? AND id='startup-decision' AND json_extract(payload,'$.answer')='N'",
            (args.run_id,),
        )
    store.checkpoint(args.run_id, previous, snapshot.values['context'])
    run.status, run.error, run.failure_code, run.stop_reason = 'interrupted', None, None, 'shutdown'
    run.stage = STAGES[args.to]
    store.save_run(run)
    if args.token_budget:
        store.adjust_budget(args.run_id, limits | {'global_token_budget': args.token_budget}, limits)
    store.emit(args.run_id, run.stage, 'run', 'interrupted', f'开发回退：已退回到{run.stage}之前，可从断点继续')
    print('done; start the backend and choose to continue this run')


if __name__ == '__main__':
    asyncio.run(main())
