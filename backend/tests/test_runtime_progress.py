import asyncio
import json

import httpx
import pytest

from company_research.api import create_app
from company_research.config import Settings
from company_research.llm import Gateway, ModelConfig
from company_research.schemas import ResearchRun
from company_research.storage import Store


async def test_status_counts_partial_materials_once_and_does_not_expose_call_bodies(tmp_path):
    app = create_app(Settings(mode='mock', database=tmp_path/'runs.sqlite',
                              artifacts=tmp_path/'out', local_sources=tmp_path/'sources'))
    store = app.state.store
    run = ResearchRun(company_input='测试', mode='real', status='running')
    store.save_run(run)
    store.record(run.run_id, 'fact', 'f1', {'fact_id': 'f1'})
    store.save_work_product_materials(run.run_id, [
        ('fact', 'f1', {'fact_id': 'f1'}), ('fact', 'f2', {'fact_id': 'f2'}),
        ('evidence', 'e1', {'evidence_id': 'e1'}),
    ])
    store.record(run.run_id, 'call', 'c1', {'call_id': 'c1', 'role': 'writer', 'result': 'ok',
                 'input_tokens': 12, 'output_tokens': 4, 'usage_source': 'provider',
                 'prompt': 'private-prompt', 'api_key': 'private-key'})
    store.record(run.run_id, 'call', 'c2', {'call_id': 'c2', 'role': 'researcher', 'result': 'running'})
    store.record(run.run_id, 'call', 'c3', {'call_id': 'c3', 'result': 'transport_or_protocol_failure'})
    before = store.run(run.run_id).model_dump()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get(f'/api/research/{run.run_id}')
    assert response.status_code == 200
    summary = response.json()['runtime']
    assert summary['artifact_counts'] == {'source': 0, 'evidence': 1, 'fact': 2, 'calculation': 0, 'section': 0}
    assert summary['usage'] == {'calls': 3, 'running_calls': 1, 'succeeded_calls': 1, 'failed_calls': 1,
                                'provider_input_tokens': 12, 'provider_output_tokens': 4, 'usage_missing_calls': 1,
                                'cache_reported_calls': 0, 'cache_reported_input_tokens': 0,
                                'cache_hit_tokens': 0, 'cache_hit_ratio': None}
    assert 'private' not in json.dumps(summary)
    assert store.run(run.run_id).model_dump() == before


@pytest.mark.parametrize('cancel', [False, True])
async def test_model_request_visible_while_waiting_and_updated_in_place(tmp_path, monkeypatch, cancel):
    monkeypatch.setenv('RUNTIME_TEST_KEY', 'test-key')
    store = Store(tmp_path/'runs.sqlite')
    run = ResearchRun(company_input='测试', mode='real', status='running')
    store.save_run(run)
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}],
                                        'usage': {'prompt_tokens': 10, 'completion_tokens': 5}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        gateway = Gateway({'m': ModelConfig(protocol='openai', base_url='http://test/v1',
                                           model='test-model', api_key_env='RUNTIME_TEST_KEY')},
                          {'default': 'm'}, client=client)
        gateway.attach_store(store, run.run_id)
        task = asyncio.create_task(gateway.complete('writer', [{'role': 'user', 'content': 'test'}]))
        await asyncio.wait_for(entered.wait(), 3)
        running = store.runtime_summary(run.run_id)
        assert running['usage']['running_calls'] == 1
        assert running['usage']['usage_missing_calls'] == 0
        call = running['recent_calls'][0]
        assert call['result'] == 'running' and call['started_at'] and call['model'] == 'test-model'
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            assert (await task).content == 'ok'
    final = store.runtime_summary(run.run_id)
    assert final['usage']['calls'] == 1 and final['usage']['running_calls'] == 0
    assert final['recent_calls'][0]['call_id'] == call['call_id']
    assert final['recent_calls'][0]['result'] == ('interrupted' if cancel else 'ok')
    assert final['usage']['provider_input_tokens'] == (0 if cancel else 10)
    assert gateway.calls == len(gateway.call_records) == 1


def test_cache_ratio_is_token_weighted_and_excludes_legacy_unknown_requests(tmp_path):
    store=Store(tmp_path/'usage.sqlite')
    for id,input_tokens,cache in [('hit',100,{'cache_hit_tokens':80,'cache_miss_tokens':20}),
                                  ('miss',900,{'cache_hit_tokens':0,'cache_miss_tokens':900}),
                                  ('legacy',5000,{})]:
        store.record('r','call',id,{'call_id':id,'result':'ok','input_tokens':input_tokens,
                                  'output_tokens':10,'usage_source':'provider',**cache})
    usage=store.runtime_summary('r')['usage']
    assert usage['provider_input_tokens']==6000
    assert usage['cache_reported_calls']==2 and usage['cache_reported_input_tokens']==1000
    assert usage['cache_hit_tokens']==80 and usage['cache_hit_ratio']==.08
