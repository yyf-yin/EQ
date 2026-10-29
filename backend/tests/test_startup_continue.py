"""After a restart nothing runs by itself; only the latest unfinished run can be continued from the page."""
import asyncio

import httpx
import pytest

from company_research.api import create_app
from company_research.config import Settings
from company_research.graphs import ResearchWorkflow
from company_research.isolation import ensure_isolation
from company_research.runner import Runner
from company_research.schemas import ResearchRun
from company_research.execution import ensure_manifest
from company_research.startup import latest_unfinished


def setup(tmp_path):
    settings = Settings(mode='mock', database=tmp_path/'db', artifacts=tmp_path/'out',
                        local_sources=tmp_path/'local', mock_delay=0)
    return settings, create_app(settings)


def seed(store, name, date, status='interrupted', **kwargs):
    run = ResearchRun(company_input=name, mode='mock', status=status, created_at=date, **kwargs)
    store.save_run(run)
    ensure_isolation(store, run.run_id)
    return run


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')


async def test_restart_runs_nothing_and_only_latest_unfinished_can_continue(tmp_path, monkeypatch):
    settings, old = setup(tmp_path)
    store = old.state.store
    earlier = seed(store, 'earlier', '2026-10-10T00:00:00+00:00')
    latest = seed(store, 'latest', '2026-10-11T00:00:00+00:00', 'running')
    seed(store, 'completed', '2026-10-12T00:00:00+00:00', 'completed')
    store.record(earlier.run_id, 'source', 'one', {'content': 'earlier'})
    store.save_run(store.run(earlier.run_id))  # Updated time must not change selection.
    app = create_app(settings)
    called = []

    async def pause_selected(run_id):
        called.append(run_id)
        app.state.store.transition_run(run_id, {'queued'}, status='interrupted')

    monkeypatch.setattr(app.state.runner, 'run', pause_selected)
    async with app.router.lifespan_context(app):
        async with client(app) as http:
            state = (await http.get('/api/startup')).json()
            assert state['candidate']['run_id'] == latest.run_id and state['candidate']['can_continue']
            assert 'answer' not in state and 'selected_run_id' not in state
            await asyncio.sleep(.01)
            assert called == [] and app.state.store.active_runs() == []
            assert app.state.store.run(latest.run_id).stop_reason == 'restart'
            assert (await http.post('/api/startup/decision', json={})).status_code in {404, 405}
            info = (await http.get(f'/api/research/{earlier.run_id}/recovery')).json()
            assert not info['current_session'] and not info['can_resume'] and '成果包' in info['reason']
            assert (await http.post(f'/api/research/{earlier.run_id}/resume')).status_code == 409
            replies = await asyncio.gather(*(http.post(f'/api/research/{latest.run_id}/resume') for _ in range(2)))
            assert all(r.status_code == 202 for r in replies)
            await asyncio.sleep(.01)
            assert called == [latest.run_id]
            assert app.state.store.records(earlier.run_id, 'source') == [{'content': 'earlier'}]
            # A new run becomes the latest; the continued one stays owned by this service.
            created = await http.post('/api/research', json={'company': 'another company'})
            assert created.status_code == 202
            assert latest_unfinished(app.state.store).run_id == created.json()['run_id']
            assert (await http.get(f'/api/research/{latest.run_id}/recovery')).json()['current_session']


@pytest.mark.parametrize('status', ['queued', 'running', 'pausing', 'interrupted', 'failed', 'waiting_human'])
async def test_latest_run_in_each_unfinished_status_is_the_candidate(tmp_path, status):
    settings, old = setup(tmp_path)
    latest = seed(old.state.store, 'latest', '2026-10-11T00:00:00+00:00', status, failure_code='execution')
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with client(app) as http:
            candidate = (await http.get('/api/startup')).json()['candidate']
            assert candidate['run_id'] == latest.run_id and candidate['can_continue']
            assert app.state.store.run(latest.run_id).status not in {'queued', 'running', 'pausing'}


async def test_retired_publication_date_block_can_be_continued(tmp_path, monkeypatch):
    settings, old = setup(tmp_path)
    latest = seed(old.state.store, 'latest', '2026-10-11T00:00:00+00:00', 'blocked', failure_code='quality',
                  error='已保存source的同一 ID 对应不同内容，拒绝覆盖：source-id/publication_date')
    app = create_app(settings)
    called = []

    async def record(run_id):
        called.append(run_id)

    monkeypatch.setattr(app.state.runner, 'run', record)
    async with app.router.lifespan_context(app):
        async with client(app) as http:
            assert app.state.store.run(latest.run_id).status == 'interrupted'
            assert (await http.post(f'/api/research/{latest.run_id}/resume')).status_code == 202
            await asyncio.sleep(.01)
            assert called == [latest.run_id]


@pytest.mark.parametrize('problem', ['reuse', 'quality', 'missing_graph', 'changed_manifest'])
async def test_page_continue_never_bypasses_safety(tmp_path, monkeypatch, problem):
    settings, old = setup(tmp_path)
    latest = seed(old.state.store, 'latest', '2026-10-11T00:00:00+00:00')
    store = old.state.store
    if problem == 'reuse':
        store.record(latest.run_id, 'reuse', 'one', {'fact_id': 'one'})
    if problem == 'quality':
        store.transition_run(latest.run_id, {'interrupted'}, status='blocked', failure_code='quality', error='real conflict')
    if problem == 'missing_graph':
        store.checkpoint(latest.run_id, 'resolve_company', {'rules_version': '1.1', 'run_id': latest.run_id})
    if problem == 'changed_manifest':
        ensure_manifest(settings, store, latest.run_id)
        settings.max_research_rounds += 1
    app = create_app(settings)

    async def forbidden(*args):
        raise AssertionError('Unsafe continue must not execute work')

    monkeypatch.setattr(app.state.runner, 'run', forbidden)
    async with app.router.lifespan_context(app):
        async with client(app) as http:
            assert (await http.post(f'/api/research/{latest.run_id}/resume')).status_code == 409
            await asyncio.sleep(.01)


async def test_page_continue_replays_original_checkpoint_and_successful_nodes(tmp_path, monkeypatch):
    settings, old = setup(tmp_path)
    store = old.state.store
    run = seed(store, 'resume original', '2026-10-11T00:00:00+00:00', 'queued')
    store.execution_put(run.run_id, 'execution_meta', 'service-session', {'session_id': store.service_session_id})
    original_resolve, original_brief = ResearchWorkflow.resolve_company, ResearchWorkflow.research_brief
    calls = {'resolve': 0, 'brief': 0}

    async def resolve(self, context):
        calls['resolve'] += 1
        return await original_resolve(self, context)

    async def brief(self, context):
        calls['brief'] += 1
        if calls['brief'] == 1:
            raise RuntimeError('offline')
        return await original_brief(self, context)

    monkeypatch.setattr(ResearchWorkflow, 'resolve_company', resolve)
    monkeypatch.setattr(ResearchWorkflow, 'research_brief', brief)
    await Runner(settings, store).run(run.run_id)
    assert store.run(run.run_id).status == 'failed'
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with client(app) as http:
            assert (await http.post(f'/api/research/{run.run_id}/resume')).status_code == 202
            for _ in range(3000):
                result = app.state.store.run(run.run_id)
                if result.status not in {'queued', 'running'}:
                    break
                await asyncio.sleep(.01)
            assert result.status == 'limited' and result.resume_count == 1
    assert calls == {'resolve': 1, 'brief': 2}


async def test_no_unfinished_task_has_no_candidate(tmp_path):
    settings, app = setup(tmp_path)
    seed(app.state.store, 'done', '2026-10-11T00:00:00+00:00', 'limited')
    app = create_app(settings)
    async with client(app) as http:
        assert (await http.get('/api/startup')).json()['candidate'] is None
