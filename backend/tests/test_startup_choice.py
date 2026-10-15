import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from company_research.api import create_app
from company_research.config import Settings
from company_research.graphs import ResearchWorkflow
from company_research.isolation import ensure_isolation
from company_research.runner import Runner
from company_research.schemas import ResearchRun
from company_research.execution import ensure_manifest
from company_research.storage import Store
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


async def client_startup(client):
    state = (await client.get('/api/startup')).json()
    return state, {'session_id':state['session_id'], 'run_id':state['candidate']['run_id']}


async def test_latest_created_unfinished_only_and_n_keeps_old_materials(tmp_path, monkeypatch):
    settings, old = setup(tmp_path)
    store = old.state.store
    earlier = seed(store, 'earlier', '2026-10-10T00:00:00+00:00')
    latest = seed(store, 'latest', '2026-10-11T00:00:00+00:00')
    seed(store, 'completed', '2026-10-12T00:00:00+00:00', 'completed')
    store.record(earlier.run_id,'source','one',{'content':'earlier'})
    store.record(latest.run_id,'source','one',{'content':'latest'})
    store.save_run(store.run(earlier.run_id))  # Updated time must not change selection.
    app = create_app(settings)
    called = []
    async def pause_new(run_id):
        called.append(run_id)
        app.state.store.transition_run(run_id, {'queued'}, status='interrupted')
    monkeypatch.setattr(app.state.runner,'run',pause_new)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            state, body = await client_startup(client)
            assert state['candidate']['run_id'] == latest.run_id and not called
            first, repeat = await asyncio.gather(*(client.post('/api/startup/decision',json=body|{'answer':'N'}) for _ in range(2)))
            assert first.status_code == repeat.status_code == 200
            selected = first.json()['selected_run_id']
            assert selected is None and repeat.json() == first.json()
            assert first.json()['answer'] == 'N'
            await asyncio.sleep(.01)
            assert called == []
            assert app.state.store.active_runs() == []
            with app.state.store.connect() as db:
                assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 3
            assert app.state.store.run(latest.run_id).status == 'interrupted'
            assert not (await client.get(f'/api/research/{latest.run_id}/recovery')).json()['current_session']
            assert app.state.store.records(latest.run_id,'source') == [{'content':'latest'}]
            assert app.state.store.records(earlier.run_id,'source') == [{'content':'earlier'}]
            assert (await client.post('/api/startup/decision',json=body|{'answer':'Y'})).status_code == 409
            assert latest_unfinished(app.state.store).run_id == earlier.run_id  # N is never offered again.
            # Starting work still requires an explicit company submission.
            created = await client.post('/api/research',json={'company':'another company'})
            assert created.status_code == 202
            new_id = created.json()['run_id']
            await asyncio.sleep(.01)
            assert called == [new_id]
            assert app.state.store.run(new_id).company_input == 'another company'
            assert app.state.store.records(new_id,'source') == []


@pytest.mark.parametrize('status', ['queued','running','pausing','interrupted','failed','blocked'])
async def test_y_adopts_only_selected_run_once(tmp_path, monkeypatch, status):
    settings, old = setup(tmp_path)
    earlier = seed(old.state.store,'old','2026-10-10T00:00:00+00:00')
    latest = seed(old.state.store,'latest','2026-10-11T00:00:00+00:00',status,failure_code='execution')
    if status == 'blocked':
        old.state.store.transition_run(latest.run_id, {'blocked'}, failure_code='quality',
            error='已保存source的同一 ID 对应不同内容，拒绝覆盖：source-id/publication_date')
    app = create_app(settings)
    called = []
    async def pause_selected(run_id):
        called.append(run_id)
        app.state.store.transition_run(run_id, {'queued'}, status='interrupted')
    monkeypatch.setattr(app.state.runner,'run',pause_selected)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            state, body = await client_startup(client)
            assert state['candidate']['can_continue'] and not called
            assert (await client.post(f'/api/research/{latest.run_id}/resume')).status_code == 409
            replies = await asyncio.gather(*(client.post('/api/startup/decision',json=body|{'answer':'Y'}) for _ in range(2)))
            assert all(r.status_code == 200 and r.json()['selected_run_id'] == latest.run_id for r in replies)
            await asyncio.sleep(.01)
            assert called == [latest.run_id]
            assert (await client.get(f'/api/research/{latest.run_id}/recovery')).json()['current_session']
            assert not (await client.get(f'/api/research/{earlier.run_id}/recovery')).json()['current_session']


@pytest.mark.parametrize('problem', ['reuse','quality','missing_graph','changed_manifest','wrong_session','wrong_run'])
async def test_y_never_bypasses_safety_or_falls_back_to_earlier_task(tmp_path, monkeypatch, problem):
    settings, old = setup(tmp_path)
    earlier = seed(old.state.store,'earlier','2026-10-10T00:00:00+00:00')
    latest = seed(old.state.store,'latest','2026-10-11T00:00:00+00:00')
    store = old.state.store
    if problem == 'reuse':store.record(latest.run_id,'reuse','one',{'fact_id':'one'})
    if problem == 'quality':store.transition_run(latest.run_id,{'interrupted'},status='blocked',failure_code='quality',error='real conflict')
    if problem == 'missing_graph':store.checkpoint(latest.run_id,'resolve_company',{'rules_version':'1.1','run_id':latest.run_id})
    if problem == 'changed_manifest':
        ensure_manifest(settings,store,latest.run_id)
        settings.max_research_rounds += 1
    app = create_app(settings)
    async def forbidden(*args):raise AssertionError('Unsafe startup must not execute work')
    monkeypatch.setattr(app.state.runner,'run',forbidden)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            _, body = await client_startup(client)
            if problem == 'wrong_session':body['session_id']='previous service'
            if problem == 'wrong_run':body['run_id']=earlier.run_id
            assert (await client.post('/api/startup/decision',json=body|{'answer':'Y'})).status_code == 409
            assert (await client.get('/api/startup')).json()['selected_run_id'] is None
            assert not (await client.get(f'/api/research/{latest.run_id}/recovery')).json()['current_session']


async def test_y_replays_original_checkpoint_and_successful_nodes(tmp_path, monkeypatch):
    settings, old = setup(tmp_path)
    store = old.state.store
    run = seed(store,'resume original','2026-10-11T00:00:00+00:00','queued')
    store.execution_put(run.run_id,'execution_meta','service-session',{'session_id':store.service_session_id})
    original_resolve, original_brief = ResearchWorkflow.resolve_company, ResearchWorkflow.research_brief
    calls = {'resolve':0,'brief':0}
    async def resolve(self, context):
        calls['resolve'] += 1
        return await original_resolve(self,context)
    async def brief(self, context):
        calls['brief'] += 1
        if calls['brief'] == 1:raise RuntimeError('offline')
        return await original_brief(self,context)
    monkeypatch.setattr(ResearchWorkflow,'resolve_company',resolve)
    monkeypatch.setattr(ResearchWorkflow,'research_brief',brief)
    await Runner(settings,store).run(run.run_id)
    assert store.run(run.run_id).status == 'failed'
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            _, body = await client_startup(client)
            assert (await client.post('/api/startup/decision',json=body|{'answer':'Y'})).status_code == 200
            for _ in range(3000):
                result = app.state.store.run(run.run_id)
                if result.status not in {'queued','running'}:break
                await asyncio.sleep(.01)
            assert result.status == 'limited' and result.resume_count == 1
    assert calls == {'resolve':1,'brief':2}


async def test_no_unfinished_task_has_no_prompt_candidate(tmp_path):
    settings, app = setup(tmp_path)
    seed(app.state.store,'done','2026-10-11T00:00:00+00:00','limited')
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/api/startup')).json()['candidate'] is None


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows CMD launcher integration')
@pytest.mark.parametrize('answer', ['y','n'])
def test_actual_powershell_prompt_accepts_stdin_y_n(tmp_path, answer):
    settings = Settings(mode='mock',database=tmp_path/'db',artifacts=tmp_path/'out',local_sources=tmp_path/'local',mock_delay=.5)
    store = Store(settings.database)
    old = seed(store,'console test','2026-10-11T00:00:00+00:00')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        port = listener.getsockname()[1]
    env = os.environ | {'CDR_MODE':'mock','CDR_DATABASE':str(settings.database),
                        'CDR_ARTIFACTS':str(settings.artifacts),'CDR_LOCAL_SOURCES':str(settings.local_sources),'CDR_MOCK_DELAY':'.5'}
    log = (tmp_path/'server.log').open('w',encoding='utf-8')
    process = subprocess.Popen([sys.executable,'-m','uvicorn','company_research.api:app','--host','127.0.0.1','--port',str(port)],
                               env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    base = f'http://127.0.0.1:{port}'
    try:
        with httpx.Client(base_url=base,timeout=5) as client:
            for _ in range(100):
                try:
                    if client.get('/api/health').status_code == 200:break
                except httpx.HTTPError:pass
                if process.poll() is not None:raise AssertionError('Test backend failed to start')
                time.sleep(.1)
            script = Path(__file__).resolve().parents[2]/'scripts/startup_choice.ps1'
            command = ". '"+str(script).replace("'","''")+f"'; Select-StartupResearch -BackendPort {port}"
            result = subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-Command',command],input='wrong\n'+answer+'\n',
                                    text=True,capture_output=True,timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
            assert result.returncode == 0, result.stderr
            assert 'Please enter Y or N.' in result.stdout
            assert ('Selected research task:' if answer == 'y' else 'Opening the research home page.') in result.stdout
            state = client.get('/api/startup').json()
            assert state['answer'] == answer.upper()
            selected = state['selected_run_id']
            assert (selected == old.run_id) is (answer == 'y')
            assert store.run(old.run_id).company_input == 'console test'
            if answer == 'y':
                assert client.get(f'/api/research/{selected}/recovery').json()['current_session']
            else:
                assert selected is None
                assert store.active_runs() == []
                with store.connect() as db:
                    assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 1
                repeat = subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-Command',command],
                    text=True,capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
                assert repeat.returncode == 0 and 'Opening the research home page.' in repeat.stdout
    finally:
        try:httpx.post(base+'/api/research/pause-active',timeout=65)
        except httpx.HTTPError:pass
        process.terminate()
        process.wait(timeout=10)
        log.close()
