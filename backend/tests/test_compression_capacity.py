"""Large research summaries keep every evidence and gap within the wire limit."""
import copy
import json

import httpx
import pytest

from company_research.agents import CompressedResearch, ask_bounded
from company_research.contexts import estimate_tokens
from company_research.llm import CapacityError, Gateway, LLMError, ModelConfig, TruncatedOutput
from company_research.researcher import researcher_graph
from company_research.schemas import ResearchTask
from company_research.storage import Store


def gateway(client, protocol='openai'):
    return Gateway(
        {'fixture': ModelConfig(protocol=protocol, base_url='http://fixture/v1',
            model='fixture', api_key_env='COMPRESSION_TEST_KEY', max_tokens=1000,
            structured_mode='json')},
        {'default': 'fixture'}, client=client,
        role_limits={'default': {'input_capacity': 6000, 'context_capacity': 8000,
                                'output_reserve': 1000}},
        global_token_budget=2000000)


def response(context, protocol='openai'):
    value={'summary': '已整理',
           'evidence_ids': [e['evidence_id'] for e in context.get('evidence', [])],
           'unresolved': context.get('gaps', [])}
    if protocol == 'anthropic':
        return httpx.Response(200, json={'content': [{'type': 'tool_use', 'id': 'out',
            'name': 'structured_output', 'input': value}], 'stop_reason': 'tool_use',
            'usage': {'input_tokens': 10, 'output_tokens': 10}})
    return httpx.Response(200, json={'choices': [{'message': {
        'content': json.dumps(value, ensure_ascii=False)}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 10}})


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
async def test_large_gaps_split_beyond_two_levels_and_resume_committed_parts(tmp_path, monkeypatch, protocol):
    monkeypatch.setenv('COMPRESSION_TEST_KEY', 'fixture-only')
    context={'task': {'task_id': 'large', 'block_id': 'F01'},
             'evidence': [{'evidence_id': f'e{i}', 'claim': '收入'} for i in range(5)],
             'gaps': [f'缺口{i}：' + '缺少明确口径的财务数据。'*20 for i in range(80)]}
    original=copy.deepcopy(context)
    successful=[]
    fail=True
    def handler(request):
        nonlocal fail
        payload=json.loads(request.content)
        assert estimate_tokens(payload)<=6000
        content=(payload['messages'][0]['content'][0]['text'] if protocol=='anthropic'
                 else payload['messages'][1]['content'])
        sent=json.loads(content)
        assert len(sent['instructions'])==1
        if successful and fail:
            fail=False
            return httpx.Response(400)
        successful.append(sent)
        return response(sent, protocol)
    store=Store(tmp_path/'db')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first=gateway(client, protocol);first.attach_store(store, 'r')
        with pytest.raises(LLMError):
            await ask_bounded(first, 'compression', CompressedResearch, context)
        saved=copy.deepcopy(successful[0])
        resumed=gateway(client, protocol);resumed.attach_store(store, 'r')
        result=await ask_bounded(resumed, 'compression', CompressedResearch, context)
    assert len(successful)>4
    assert successful.count(saved)==1
    assert result.evidence_ids==[e['evidence_id'] for e in context['evidence']]
    assert result.unresolved==context['gaps']
    assert context==original
    assert all(p['estimated_tokens']<6000 for p in store.records('r', 'sent_context'))


async def test_researcher_compresses_evidence_after_first_600(tmp_path, monkeypatch):
    monkeypatch.setenv('COMPRESSION_TEST_KEY', 'fixture-only')
    sent_ids=[]
    def handler(request):
        payload=json.loads(request.content)
        assert estimate_tokens(payload)<=6000
        context=json.loads(payload['messages'][1]['content'])
        sent_ids.extend(e['evidence_id'] for e in context['evidence'])
        return response(context)
    class Datasource:
        async def retrieve(self, query):
            raise AssertionError('prepared references require no retrieval')
    task=ResearchTask(company_id='D', topic='上传资料', role='company', queries=[]).model_dump(mode='json')
    evidence=[{'evidence_id': f'e{i}', 'claim': '有原文依据的经营情况',
               'source_id': 's', 'actual_or_forecast': 'actual'} for i in range(701)]
    state={'task': task, 'brief': {}, 'round': 0, 'sources': [], 'evidence': evidence,
           'facts': [], 'queries': [], 'gaps': ['仍待补充资料'], 'warnings': [],
           'summary': {}, 'reference_prepared': True}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        output=await researcher_graph(gateway(client), Datasource(), Store(tmp_path/'db'),
                                      'r', 1).ainvoke(state)
    expected=[e['evidence_id'] for e in evidence]
    assert sent_ids==expected
    assert output['summary']['evidence_ids']==expected
    assert output['summary']['unresolved']==state['gaps']


async def test_unsplittable_gap_fails_without_sending_or_dropping_it(monkeypatch):
    monkeypatch.setenv('COMPRESSION_TEST_KEY', 'fixture-only')
    def handler(request):
        raise AssertionError('oversized request must not be sent')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CapacityError):
            await ask_bounded(gateway(client), 'compression', CompressedResearch,
                              {'evidence': [], 'gaps': ['超长单条缺口'*2000]})


async def test_output_truncation_still_has_a_bounded_repair_limit():
    class Model:
        calls=0
        async def structured(self, role, messages, schema):
            self.calls+=1
            raise TruncatedOutput('fixture output truncated')
    model=Model()
    with pytest.raises(TruncatedOutput):
        await ask_bounded(model, 'compression', CompressedResearch,
                          {'evidence': [], 'gaps': [str(i) for i in range(80)]})
    assert model.calls==3
