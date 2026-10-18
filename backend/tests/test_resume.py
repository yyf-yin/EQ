import asyncio
import copy
import json
import os
import subprocess
import sys

import httpx
import pytest
from pydantic import BaseModel

from company_research.api import create_app
from company_research.config import Settings
from company_research.execution import unit, recovery_info, RecoveryError, ensure_manifest
from company_research.graphs import ResearchWorkflow
from company_research.llm import Gateway, ModelConfig, BudgetError, RoleLimits
from company_research.runner import Runner
from company_research.schemas import ResearchRun, ResearchTask, ResearchBrief, SourceRecord
from company_research.storage import Store


def settings(tmp_path, **kwargs):
    return Settings(mode='mock', database=tmp_path/'runs.sqlite', artifacts=tmp_path/'out',
                    local_sources=tmp_path/'local', mock_delay=0, **kwargs)


async def wait_status(store, run_id, statuses):
    for _ in range(5000):
        run = store.run(run_id)
        if run.status in statuses:
            return run
        await asyncio.sleep(.01)
    raise AssertionError(store.run(run_id))


async def test_result_committed_before_graph_checkpoint_is_replayed(tmp_path, monkeypatch):
    config = settings(tmp_path)
    store = Store(config.database)
    run = ResearchRun(company_input='恢复', mode='mock')
    store.save_run(run)
    real_checkpoint = store.checkpoint
    real_brief = ResearchWorkflow.research_brief
    count = 0
    failed = False
    async def brief(self, context):
        nonlocal count
        count += 1
        return await real_brief(self, context)
    def checkpoint(run_id, node, context):
        nonlocal failed
        if node == 'research_brief' and not failed:
            failed = True
            raise RuntimeError('fault between business commit and graph commit')
        real_checkpoint(run_id, node, context)
    monkeypatch.setattr(ResearchWorkflow, 'research_brief', brief)
    monkeypatch.setattr(store, 'checkpoint', checkpoint)
    runner = Runner(config, store)
    await runner.run(run.run_id)
    assert store.run(run.run_id).status == 'failed'
    assert count == 1
    await runner.run(run.run_id)
    assert store.run(run.run_id).status == 'limited'
    assert count == 1
    assert store.run(run.run_id).resume_count == 1


async def test_supervisor_keeps_successful_peers_and_waits_for_entire_block(tmp_path, monkeypatch):
    config = settings(tmp_path, concurrency=3)
    store = Store(config.database)
    run = ResearchRun(company_input='测试', mode='mock')
    store.save_run(run)
    tasks = [ResearchTask(task_id=f't{i}', company_id='D', block_id='C01' if i < 3 else 'F01',
                          topic='测试', role='company', queries=['q']).model_dump(mode='json') for i in range(4)]
    calls = []
    class Subgraph:
        async def ainvoke(self, state, config):
            name = state['task']['task_id']
            calls.append(name)
            if name == 't1' and calls.count(name) == 1:
                raise RuntimeError('one peer failed')
            if name == 't3':
                assert all(t in calls for t in ('t0', 't1', 't2'))
            await asyncio.sleep(.005)
            return state | {'summary': {'summary': name}}
    monkeypatch.setattr('company_research.graphs.researcher_graph', lambda *a, **kw: Subgraph())
    context = {'pending': [t['task_id'] for t in tasks], 'plan': {'tasks': tasks, 'blocks': [
        {'block_id': 'C01', 'dependencies': []}, {'block_id': 'F01', 'dependencies': ['C01']}]},
        'brief': {}, 'summaries': [], 'sources': [], 'evidence': [], 'facts': [], 'limitations': []}
    workflow = ResearchWorkflow(config, store, run.run_id)
    with pytest.raises(RuntimeError):
        await workflow.supervisor(copy.deepcopy(context))
    assert 't3' not in calls
    result = await workflow.supervisor(copy.deepcopy(context))
    assert calls.count('t0') == calls.count('t2') == calls.count('t3') == 1
    assert calls.count('t1') == 2
    assert result['pending'] == [] and len(result['summaries']) == 4


async def test_researcher_resumes_after_extraction_without_search_or_extraction(tmp_path):
    from company_research.researcher import researcher_graph
    from company_research.agents import ResearchExtraction, CompressedResearch
    store = Store(tmp_path/'db')
    source = SourceRecord(kind='local', title='资料', content='营业收入 100 百万元\n'*10)
    queries = []
    class Datasource:
        async def retrieve(self, q):
            queries.append(q)
            return [source], []
    class Model:
        def __init__(self): self.calls = []
        def limits(self, role): return RoleLimits()
        async def structured(self, role, messages, schema):
            self.calls.append(role)
            if role == 'researcher':
                return ResearchExtraction(evidence=[], facts=[], followup_queries=[], gaps=[])
            if self.calls.count('compression') == 1:
                raise RuntimeError('compression fault')
            return CompressedResearch(summary='已整理', evidence_ids=[], unresolved=[])
    model = Model()
    task = ResearchTask(company_id='D', block_id='F01', topic='收入', role='financial', queries=['收入']).model_dump(mode='json')
    brief = ResearchBrief(company_id='D', scope='测试', segments=['设备'], historical_periods=['2024A','2025A'], forecast_periods=['2026E']).model_dump(mode='json')
    state = {'task':task,'brief':brief,'round':0,'sources':[],'evidence':[],'facts':[],
             'queries':task['queries'],'gaps':[],'warnings':[],'summary':{}}
    graph = researcher_graph(model, Datasource(), store, 'r', 1)
    with pytest.raises(RuntimeError): await graph.ainvoke(state)
    before = model.calls.count('researcher')
    output = await graph.ainvoke(state)
    assert len(queries) == 1 and model.calls.count('researcher') == before
    assert output['summary']['summary'] == '已整理'


class Answer(BaseModel):
    answer: str


async def test_structured_steps_reuse_after_restart_and_budget_is_actual_usage(tmp_path, monkeypatch):
    monkeypatch.setenv('RESUME_TEST_KEY', 'test-only')
    store = Store(tmp_path/'db')
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'choices':[{'message':{'content':'{"answer":"ok"}'},'finish_reason':'stop'}],
                                       'usage':{'prompt_tokens':10,'completion_tokens':5}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        def model():
            g = Gateway({'m':ModelConfig(protocol='openai',base_url='http://fixture/v1',model='m',api_key_env='RESUME_TEST_KEY')},
                        {'default':'m'},client=client,global_call_budget=1,enforce_call_budgets=True)
            g.attach_store(store,'r')
            return g
        messages = [{'role':'user','content':'draft'}]
        first = model()
        assert (await first.structured('writer', messages, Answer)).answer == 'ok'
        assert first.reserved_tokens == 15
        resumed = model()
        assert resumed.calls == 1 and resumed.reserved_tokens == 15
        assert (await resumed.structured('writer', messages, Answer)).answer == 'ok'
        assert len(requests) == 1
        with pytest.raises(BudgetError):
            await resumed.structured('reflection', [{'role':'user','content':'next'}], Answer)
        assert len(requests) == 1


async def test_api_pause_same_session_resume_duplicate_clicks_and_restart_rejection(tmp_path, monkeypatch):
    config = settings(tmp_path)
    app = create_app(config)
    entered, release = asyncio.Event(), asyncio.Event()
    original = ResearchWorkflow.research_brief
    count = 0
    async def brief(self, context):
        nonlocal count
        count += 1
        entered.set()
        await release.wait()
        return await original(self, context)
    monkeypatch.setattr(ResearchWorkflow,'research_brief',brief)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            run_id = (await client.post('/api/research',json={'company':'暂停'})).json()['run_id']
            await asyncio.wait_for(entered.wait(),30)
            response = await client.post(f'/api/research/{run_id}/pause')
            assert response.status_code == 202 and response.json()['status'] == 'pausing'
            release.set()
            paused = await wait_status(app.state.store,run_id,{'interrupted'})
            assert paused.stop_reason == 'user'
            responses = await asyncio.gather(*(client.post(f'/api/research/{run_id}/resume') for _ in range(2)))
            assert all(r.status_code == 202 for r in responses)
            final = await wait_status(app.state.store,run_id,{'limited','failed'})
            assert final.status == 'limited' and final.resume_count == 1
            assert count == 1
    restarted = create_app(config)
    async with restarted.router.lifespan_context(restarted):
        await asyncio.sleep(.03)
        assert restarted.state.store.run(run_id).status == 'limited'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted),base_url='http://test') as client:
            responses = await asyncio.gather(*(client.post(f'/api/research/{run_id}/resume') for _ in range(2)))
            assert all(r.status_code == 409 for r in responses)
            info = (await client.get(f'/api/research/{run_id}/recovery')).json()
            assert not info['current_session'] and not info['can_resume']
            assert count == 1


async def test_failed_api_resume_quality_block_and_budget_adjustment(tmp_path):
    config = settings(tmp_path, global_call_budget=2, global_token_budget=1000, block_call_budget=2)
    app = create_app(config)
    store = app.state.store
    failed = ResearchRun(company_input='恢复失败任务',mode='mock',status='failed',rules_version='1.1')
    blocked = ResearchRun(company_input='质量阻断',mode='mock',status='blocked',failure_code='quality')
    budget = ResearchRun(company_input='预算',mode='mock',status='failed',failure_code='budget')
    for run in (failed,blocked,budget):
        store.save_run(run)
        store.execution_put(run.run_id, 'execution_meta', 'service-session', {'session_id':store.service_session_id})
    for i in range(2): store.record(budget.run_id,'call',str(i),{'call_id':str(i),'budget_tokens':500,'block_id':'F01','result':'uncertain'})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.post(f'/api/research/{blocked.run_id}/resume')).status_code == 409
            assert (await client.post(f'/api/research/{budget.run_id}/resume')).status_code == 409
            before = await client.get(f'/api/research/{budget.run_id}/recovery')
            assert before.json()['budget']['calls_used'] == 2
            updated = await client.post(f'/api/research/{budget.run_id}/budget',json={
                'global_call_budget':4,'global_token_budget':2000,'block_call_budget':4})
            assert updated.status_code == 200 and updated.json()['can_resume']
            assert updated.json()['budget']['calls_used'] == 2 and updated.json()['budget']['tokens_used'] == 1000
            response = await client.post(f'/api/research/{failed.run_id}/resume')
            assert response.status_code == 202 and response.json()['run_id'] == failed.run_id
            assert (await wait_status(store,failed.run_id,{'limited','failed'})).status == 'limited'


async def test_resume_rejects_changed_sources_and_preserves_result(tmp_path):
    config = settings(tmp_path)
    config.local_sources.mkdir()
    store = Store(config.database)
    run = ResearchRun(company_input='版本',mode='real',status='interrupted')
    store.save_run(run)
    path = config.local_sources/'source.md'
    path.write_text('first',encoding='utf-8')
    ensure_manifest(config,store,run.run_id)
    path.write_text('changed',encoding='utf-8')
    with pytest.raises(RecoveryError): ensure_manifest(config,store,run.run_id)
    assert store.run(run.run_id).status == 'interrupted'


@pytest.mark.parametrize('status', ['queued','running','pausing','interrupted','failed','blocked'])
async def test_restart_never_runs_older_tasks_or_allows_controls(tmp_path, monkeypatch, status):
    config = settings(tmp_path)
    old_app = create_app(config)
    store = old_app.state.store
    run = ResearchRun(company_input='old session', mode='mock', status=status, failure_code='execution',
                      created_at='2026-01-01T00:00:00+00:00')
    store.save_run(run)
    # Only the latest unfinished run may be continued from the page after a restart.
    store.save_run(ResearchRun(company_input='newer', mode='mock', status='interrupted'))
    store.execution_put(run.run_id, 'execution_meta', 'service-session', {'session_id':store.service_session_id})
    store.record(run.run_id, 'source', 'own', {'content':'preserved source'})
    before = store.records(run.run_id, 'source')
    restarted = create_app(config)
    async def forbidden(*args):raise AssertionError('Restart must never run old work')
    monkeypatch.setattr(restarted.state.runner, 'run', forbidden)
    async with restarted.router.lifespan_context(restarted):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url='http://test') as client:
            result = (await client.get(f'/api/research/{run.run_id}')).json()
            assert not result['recovery']['current_session']
            assert not result['recovery']['can_resume'] and not result['recovery']['can_pause']
            assert result['status'] == ('interrupted' if status in {'queued','running','pausing'} else status)
            assert (await client.post(f'/api/research/{run.run_id}/resume')).status_code == 409
            assert (await client.post(f'/api/research/{run.run_id}/pause')).status_code == 409
            assert (await client.post(f'/api/research/{run.run_id}/budget', json={
                'global_call_budget':3000,'global_token_budget':30000000,'block_call_budget':300})).status_code == 409
            snapshot = (await client.get(f'/api/research/{run.run_id}/work-product')).json()
            assert snapshot['counts']['source'] == 1
    assert restarted.state.store.records(run.run_id, 'source') == before


async def test_explicit_block_budget_increase_applies_to_role_caps(tmp_path,monkeypatch):
    from company_research.execution import load_gateway
    monkeypatch.setenv('RESUME_TEST_KEY','test-only')
    models=tmp_path/'models.yaml'
    models.write_text('''models:
  m:
    protocol: openai
    base_url: http://fixture/v1
    model: fixture
    api_key_env: RESUME_TEST_KEY
routes:
  default: m
role_limits:
  default:
    block_call_budget: 1
''',encoding='utf-8')
    config=settings(tmp_path,models_config=models,block_call_budget=1)
    store=Store(config.database)
    run=ResearchRun(company_input='预算',mode='real',status='interrupted')
    store.save_run(run)
    before={'block_call_budget':1,'global_call_budget':10,'global_token_budget':100000}
    assert load_gateway(config,store,run.run_id).limits('writer').block_call_budget==1
    store.adjust_budget(run.run_id,before|{'block_call_budget':3},before)
    gateway=load_gateway(config,store,run.run_id)
    assert gateway.block_call_budget==gateway.limits('writer').block_call_budget==3
    assert store.records(run.run_id,'budget_adjustment')[0]['before']['block_call_budget']==1
    assert 'block_call_budget: 1' in models.read_text(encoding='utf-8')


async def test_hard_kill_preserves_committed_unit_and_inflight_budget(tmp_path):
    database, marker = tmp_path/'db.sqlite', tmp_path/'ready'
    script = '''
import asyncio,sys
from pathlib import Path
from company_research.storage import Store
from company_research.execution import unit
async def main():
    store=Store(Path(sys.argv[1]))
    async def work():return {'saved':'complete'}
    await unit(store,'r','research_task','one',{'input':1},work)
    store.record('r','call','inflight',{'call_id':'inflight','result':'running','budget_tokens':123,'block_id':'F01'})
    Path(sys.argv[2]).write_text('ready')
    await asyncio.Event().wait()
asyncio.run(main())
'''
    process = subprocess.Popen([sys.executable,'-c',script,str(database),str(marker)],
                               env=os.environ.copy(),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for _ in range(500):
            if marker.exists(): break
            if process.poll() is not None:
                raise AssertionError(process.stderr.read().decode())
            await asyncio.sleep(.01)
        assert marker.exists()
        process.kill()
        process.wait(timeout=5)
    finally:
        if process.poll() is None: process.kill();process.wait(timeout=5)
        process.stderr.close()
    store = Store(database)
    async def forbidden(): raise AssertionError('committed task must not execute again')
    assert await unit(store,'r','research_task','one',{'input':1},forbidden) == {'saved':'complete'}
    gateway = Gateway({},{});gateway.attach_store(store,'r')
    assert gateway.calls == 1 and gateway.reserved_tokens == 123


async def test_predict_and_writer_keep_partial_model_steps(tmp_path, monkeypatch):
    from company_research.planners import mock_assumptions
    from company_research.writers import write_one
    monkeypatch.setenv('RESUME_TEST_KEY','test-only')
    config = settings(tmp_path)
    store = Store(config.database)
    run = ResearchRun(company_input='步骤恢复',mode='mock')
    store.save_run(run)
    await Runner(config,store).run(run.run_id)
    context = store.load_checkpoint(run.run_id)[1]
    counts = {'assumptions':0,'writer':0,'reflection':0}
    def respond(request):
        payload=json.loads(request.content)
        schema=payload['tools'][0]['function']['parameters']['title']
        data=json.loads(payload['messages'][-1]['content'])
        if schema == 'AssumptionOutput':
            counts['assumptions']+=1
            if counts['assumptions']==8:return httpx.Response(400,json={'error':'injected'})
            evidence_id=context['assumptions'][0]['evidence_ids'][0]
            values=mock_assumptions(evidence_id,context['brief']['forecast_periods'])
            value={'assumptions':[a.model_dump(mode='json') for a in values if a.period==data['selected_period'] and a.scenario==data['selected_scenario']],
                   'segment_models':{'设备':'growth','服务':'growth'},'limitations':[]}
        elif schema == 'WriterDraft':
            counts['writer']+=1
            value={'paragraphs':['有来源的业务分析与限制说明。'*100], 'evidence_ids':[],'calculation_ids':[],'fact_ids':[],'assumption_ids':[],'consistency_checks':{}}
        else:
            assert schema == 'Reflection'
            counts['reflection']+=1
            if counts['reflection']==1:return httpx.Response(400,json={'error':'injected'})
            value={'needs_revision':False,'instructions':[]}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value,ensure_ascii=False)},'finish_reason':'stop'}],
                                       'usage':{'prompt_tokens':10,'completion_tokens':5}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        def model():
            gateway=Gateway({'m':ModelConfig(protocol='openai',base_url='http://fixture/v1',model='m',api_key_env='RESUME_TEST_KEY')},
                            {'default':'m'},client=client,role_limits={'default':{'input_capacity':1000000,'context_capacity':1100000}})
            gateway.attach_store(store,run.run_id)
            return gateway
        gateway=model()
        workflow=ResearchWorkflow(config,store,run.run_id,gateway);workflow.mock=False
        from company_research.llm import LLMError
        with pytest.raises(LLMError):await workflow.assumptions(context)
        workflow.gateway=model()
        result=await workflow.assumptions(context)
        assert counts['assumptions']==10  # 7 committed, one failure, only two remaining calls.
        assert len(result['assumptions'])==len(context['assumptions'])
        with pytest.raises(LLMError):await write_one(workflow.gateway,context,'company','公司','业务边界',store=store,run_id=run.run_id)
        section=await write_one(model(),context,'company','公司','业务边界',store=store,run_id=run.run_id)
        assert section.paragraphs and counts['writer']==1 and counts['reflection']==2
