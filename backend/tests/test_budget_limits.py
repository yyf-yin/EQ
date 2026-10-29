"""Budget boundaries use HTTP fixtures and isolated databases, never paid calls."""
import asyncio

import httpx
import pytest

from company_research.config import Settings
from company_research.execution import recovery_info
from company_research.isolation import ensure_isolation
from company_research.llm import BudgetError, CALL_CONTEXT, Gateway, ModelConfig
from company_research.runner import Runner
from company_research.schemas import ResearchBrief, ResearchRun
from company_research.storage import Store


def config(tmp_path):
    return Settings(_env_file=None, mode='mock', database=tmp_path/'runs.sqlite',
                    artifacts=tmp_path/'out', local_sources=tmp_path/'sources',
                    global_call_budget=2000, global_token_budget=20000000,
                    block_call_budget=250, enforce_call_budgets=True, mock_delay=0)


def saved_run(tmp_path, status='failed', failure_code='budget'):
    settings = config(tmp_path)
    store = Store(settings.database)
    run = ResearchRun(company_input='budget fixture', mode='real', status=status, failure_code=failure_code)
    store.save_run(run)
    ensure_isolation(store, run.run_id)
    return settings, store, run


def gateway(client, monkeypatch, **limits):
    limits.setdefault('enforce_call_budgets', True)
    monkeypatch.setenv('BUDGET_FIXTURE_KEY', 'test-only')
    model = ModelConfig(protocol='openai', base_url='http://fixture/v1',
                        model='fixture', api_key_env='BUDGET_FIXTURE_KEY')
    return Gateway({'m':model}, {'default':'m'}, client=client, **limits)


def response(request):
    return httpx.Response(200, json={'choices':[{'message':{'content':'ok'}, 'finish_reason':'stop'}],
                                    'usage':{'prompt_tokens':10, 'completion_tokens':5}})


async def test_global_requests_cross_block_cap_after_restart(tmp_path, monkeypatch):
    settings, store, run = saved_run(tmp_path, status='blocked')
    run.error = '调用/全局 token 预算耗尽：global'
    store.save_run(run)
    for i in range(250):
        store.record(run.run_id, 'call', str(i), {'call_id':str(i), 'role':'researcher',
            'block_id':'global', 'result':'ok', 'usage_source':'provider',
            'input_tokens':10000, 'output_tokens':4000})
    info = recovery_info(settings, store, run.run_id)
    assert info['can_resume'] and info['budget']['tokens_used'] == 3500000
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        g = gateway(client, monkeypatch, global_call_budget=2000, global_token_budget=20000000,
                    block_call_budget=250, role_limits={'default':{'block_call_budget':250}})
        g.attach_store(store, run.run_id)
        await asyncio.gather(*(g.complete('researcher', []) for _ in range(3)))
        assert g.calls == 253 and g.reserved_tokens == 3500045
        restarted = gateway(client, monkeypatch, global_call_budget=2000,
                            global_token_budget=20000000, block_call_budget=250)
        restarted.attach_store(store, run.run_id)
        assert restarted.calls == 253 and restarted.reserved_tokens == g.reserved_tokens


async def test_real_block_limit_preserved_and_recoverable_with_override(tmp_path, monkeypatch):
    settings, store, run = saved_run(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        g = gateway(client, monkeypatch, block_call_budget=250,
                    role_limits={'default':{'block_call_budget':2}})
        g.attach_store(store, run.run_id)
        token = CALL_CONTEXT.set({'block_id':'C01'})
        try:
            await g.complete('researcher', [])
            await g.complete('researcher', [])
            with pytest.raises(BudgetError, match='分析块调用预算耗尽：C01.*2 / 2'):
                await g.complete('researcher', [])
        finally:
            CALL_CONTEXT.reset(token)
        assert g.calls == 2
        info = recovery_info(settings, store, run.run_id)
        assert not info['can_resume'] and 'C01' in info['reason']
        limits = info['budget']
        store.adjust_budget(run.run_id, {k:limits[k] for k in (
            'global_call_budget','global_token_budget','block_call_budget')} | {'block_call_budget':251},
            {k:limits[k] for k in ('global_call_budget','global_token_budget','block_call_budget')})
        assert recovery_info(settings, store, run.run_id)['can_resume']


async def test_global_call_budget_still_stops_unscoped_requests(tmp_path, monkeypatch):
    settings, store, run = saved_run(tmp_path)
    store.execution_put(run.run_id, 'execution_meta', 'budget', {
        'global_call_budget':2, 'global_token_budget':20000000, 'block_call_budget':1})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        g = gateway(client, monkeypatch, global_call_budget=2, block_call_budget=1)
        g.attach_store(store, run.run_id)
        await g.complete('resolver', [])
        await g.complete('brief', [])
        with pytest.raises(BudgetError, match='总调用预算耗尽：2 / 2'):
            await g.complete('researcher', [])
        info = recovery_info(settings, store, run.run_id)
        assert not info['can_resume'] and '总调用预算耗尽' in info['reason']
        assert info['budget']['calls_used'] == 2


async def test_token_budget_checks_next_request_reserve(tmp_path, monkeypatch):
    settings, store, run = saved_run(tmp_path)
    limits = {'global_call_budget':2000, 'global_token_budget':5000, 'block_call_budget':250}
    store.execution_put(run.run_id, 'execution_meta', 'budget', limits)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        g = gateway(client, monkeypatch, **limits)
        g.attach_store(store, run.run_id)
        with pytest.raises(BudgetError, match='总 token 预算不足.*下一请求需预留'):
            await g.complete('researcher', [])
        assert g.calls == 0
        info = recovery_info(settings, store, run.run_id)
        assert not info['can_resume'] and '下一请求需预留' in info['reason']
        required = store.execution_get(run.run_id, 'execution_meta', 'budget_failure')['request_tokens']
        store.adjust_budget(run.run_id, limits | {'global_token_budget':required}, limits)
        assert recovery_info(settings, store, run.run_id)['can_resume']


async def test_budget_stop_with_missing_facts_stays_resumable(tmp_path, monkeypatch):
    settings = config(tmp_path)
    store = Store(settings.database)
    run = ResearchRun(company_input='budget fixture', mode='mock')
    store.save_run(run)
    async def stop(self, context):
        brief = ResearchBrief(company_id='D', scope='fixture', segments=['设备'],
                              historical_periods=['2024A','2025A'], forecast_periods=['2026E'])
        store.checkpoint(run.run_id, 'research_brief', {'brief':brief.model_dump(mode='json'),
                                                      'facts':[], 'rules_version':'1.1'})
        raise BudgetError('总调用预算耗尽：2 / 2 次')
    monkeypatch.setattr('company_research.graphs.ResearchWorkflow.resolve_company', stop)
    await Runner(settings, store).run(run.run_id)
    assert store.run(run.run_id).status == 'failed'
    assert store.run(run.run_id).failure_code == 'budget'
    assert recovery_info(settings, store, run.run_id)['can_resume']


def test_quality_block_still_cannot_resume(tmp_path):
    settings, store, run = saved_run(tmp_path, status='blocked', failure_code='quality')
    info = recovery_info(settings, store, run.run_id)
    assert not info['can_resume'] and not info['can_increase_budget']


async def test_default_policy_ignores_call_caps_but_keeps_tokens_and_counts(tmp_path, monkeypatch):
    from company_research.execution import load_gateway
    settings, store, run = saved_run(tmp_path, status='blocked')
    settings.enforce_call_budgets = Settings(_env_file=None).enforce_call_budgets
    assert settings.enforce_call_budgets is False
    limits = {'global_call_budget':1, 'global_token_budget':20000000, 'block_call_budget':1}
    store.execution_put(run.run_id, 'execution_meta', 'budget', limits)
    store.execution_put(run.run_id, 'execution_meta', 'budget_failure', {
        'kind':'block', 'block_id':'C01', 'role':'researcher', 'used':1, 'limit':1})
    store.record(run.run_id, 'call', 'old', {'call_id':'old', 'role':'researcher',
        'block_id':'C01', 'result':'ok', 'usage_source':'provider', 'input_tokens':100, 'output_tokens':20})
    models = tmp_path/'models.yaml'
    models.write_text('''models:
  m:
    protocol: openai
    base_url: http://fixture/v1
    model: fixture
    api_key_env: BUDGET_FIXTURE_KEY
routes:
  default: m
role_limits:
  default:
    block_call_budget: 1
''', encoding='utf-8')
    settings.models_config = models
    monkeypatch.setenv('BUDGET_FIXTURE_KEY', 'test-only')
    g = load_gateway(settings, store, run.run_id)
    assert not g.enforce_call_budgets
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        g.client = client
        g.attach_store(store, run.run_id)
        token = CALL_CONTEXT.set({'block_id':'C01'})
        try:
            await asyncio.gather(*(g.complete('researcher', []) for _ in range(3)))
            assert g.calls == 4 and g.block_calls['C01'] == 4 and g.reserved_tokens == 165
            info = recovery_info(settings, store, run.run_id)
            assert info['can_resume'] and info['budget']['enforce_call_budgets'] is False
            g.global_token_budget = g.reserved_tokens
            with pytest.raises(BudgetError, match='总 token 预算不足'):
                await g.complete('researcher', [])
            assert g.calls == 4
        finally:
            CALL_CONTEXT.reset(token)


async def test_page_continue_adopts_legacy_global_budget_block(tmp_path, monkeypatch):
    from company_research.api import create_app
    settings = config(tmp_path)
    original = create_app(settings)
    store = original.state.store
    run = ResearchRun(company_input='legacy global stop', mode='mock', status='blocked',
                      failure_code='budget', error='调用/全局 token 预算耗尽：global')
    store.save_run(run)
    for i in range(250):
        store.record(run.run_id, 'call', str(i), {'call_id':str(i), 'role':'researcher',
                     'block_id':'global', 'budget_tokens':14000, 'result':'uncertain'})
    app = create_app(settings)
    called = []
    async def pause_selected(run_id):
        called.append(run_id)
        app.state.store.transition_run(run_id, {'queued'}, status='interrupted')
    monkeypatch.setattr(app.state.runner, 'run', pause_selected)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            state = (await client.get('/api/startup')).json()
            assert state['candidate']['run_id'] == run.run_id and state['candidate']['can_continue']
            assert not called
            reply = await client.post(f'/api/research/{run.run_id}/resume')
            assert reply.status_code == 202
            await asyncio.sleep(.01)
            assert called == [run.run_id]
            info = (await client.get(f'/api/research/{run.run_id}/recovery')).json()
            assert info['current_session'] and info['can_resume']
            assert info['budget']['calls_used'] == 250 and info['budget']['tokens_used'] == 3500000
