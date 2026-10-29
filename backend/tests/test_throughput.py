"""Throughput changes must preserve bounds, dependencies, recovery and evidence."""
import asyncio
import json
from collections import Counter

import httpx
import pytest

from company_research.agents import ResearchExtraction, CompressedResearch, request_messages
from company_research.config import Settings
from company_research.contexts import extraction_batches, locate_windows
from company_research.execution import bounded_schedule, optimized_run, unit, DependencySchedulingError
from company_research.llm import Gateway, ModelConfig, RoleLimits
from company_research.researcher import researcher_graph
from company_research.schemas import SourceRecord, ResearchTask, ResearchBrief
from company_research.storage import Store


async def test_refills_slots_without_waiting_for_slow_peer_and_keeps_order():
    release = asyncio.Event()
    active = peak = 0
    finished = []
    async def work(key):
        nonlocal active, peak
        active += 1; peak = max(peak, active)
        try:
            if key == 'slow':
                await release.wait()
            elif key == 'refill':
                assert 'slow' not in finished
                release.set()
            finished.append(key)
            return key
        finally:
            active -= 1
    keys = ['slow', 'fast', 'refill']
    result = await asyncio.wait_for(bounded_schedule(keys, work, 2), 2)
    assert result == keys and peak == 2


async def test_dependencies_wait_for_all_tasks_in_upstream_block():
    release = asyncio.Event()
    finished = set()
    async def work(key):
        if key == 'a1': await release.wait()
        if key == 'a2': release.set()
        if key == 'b': assert {'a1', 'a2'} <= finished
        finished.add(key)
        return key
    ready = lambda key, done: key != 'b' or {'a1','a2'} <= done
    assert await bounded_schedule(['a1','a2','b'], work, 2, ready) == ['a1','a2','b']
    with pytest.raises(DependencySchedulingError):
        await bounded_schedule(['cycle'], work, 2, lambda key, done: False)


async def test_failure_drains_started_units_and_does_not_dispatch_more(tmp_path):
    store = Store(tmp_path/'db')
    started, committed = [], []
    async def work(key):
        started.append(key)
        async def invoke():
            if key == 'fail': raise RuntimeError('injected')
            await asyncio.sleep(.01)
            committed.append(key)
            return {'saved':key}
        return await unit(store, 'r', 'test', key, {}, invoke)
    with pytest.raises(RuntimeError, match='injected'):
        await bounded_schedule(['fail','peer','later'], work, 2)
    assert started == ['fail','peer'] and committed == ['peer']
    assert await work('peer') == {'saved':'peer'} and committed == ['peer']


async def test_failure_precedence_is_stable_when_later_task_fails_first():
    async def work(key):
        if key=='first':
            await asyncio.sleep(.01)
            raise ValueError('first input failure')
        raise RuntimeError('faster second failure')
    with pytest.raises(ValueError,match='first input failure'):
        await bounded_schedule(['first','second'],work,2)


async def test_strategy_is_pinned_for_old_checkpoints_and_new_runs(tmp_path):
    store = Store(tmp_path/'db')
    store.checkpoint('old', 'supervisor', {})
    assert not optimized_run(store, 'old')
    assert optimized_run(store, 'new')
    store.checkpoint('new', 'supervisor', {})
    assert optimized_run(store, 'new')
    await unit(store, 'unit-only', 'test', 'saved', {}, lambda: asyncio.sleep(0, result={}))
    assert not optimized_run(store, 'unit-only')


def slim(windows):
    return [{k:v for k,v in w.items() if k not in {'content','original_content'}}|
            {'content':w['original_content'],'metadata':w['content'].removesuffix(w['original_content'])}
            for w in windows]


@pytest.mark.parametrize('protocol,mode',[('openai','json'),('openai','tool'),('openai','native'),('anthropic','tool')])
async def test_batches_fit_full_wire_payload_and_keep_every_excerpt(tmp_path, monkeypatch, protocol, mode):
    monkeypatch.setenv('THROUGHPUT_KEY','fixture-only')
    task=ResearchTask(task_id='F01', company_id='D',block_id='F01',topic='收入',role='financial',queries=['营业收入']).model_dump(mode='json')
    brief=ResearchBrief(company_id='D',scope='fixture',segments=['设备'],historical_periods=['2023A','2024A','2025A'],forecast_periods=['2026E','2027E','2028E']).model_dump(mode='json')
    source=SourceRecord(kind='local',title='年报',locator='page 20',content='单位：人民币百万元 合并\n| 指标 | 2025A | 2024A |\n'+'营业收入 '+('披露的收入资料 '*2000)+'\n注：同期数据已重述。\n')
    calls=[]
    def respond(request):
        calls.append(json.loads(request.content))
        value={'evidence':[],'facts':[],'gaps':[],'followup_queries':[]}
        if protocol=='anthropic':
            return httpx.Response(200,json={'content':[{'type':'tool_use','id':'o','name':'structured_output','input':value}],'stop_reason':'tool_use','usage':{'input_tokens':1,'output_tokens':1}})
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value)},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        gateway=Gateway({'m':ModelConfig(protocol=protocol,base_url='https://fixture.test',model='m',api_key_env='THROUGHPUT_KEY',structured_mode=mode)}, {'default':'m'},client=client,
                        role_limits={'default':{'input_capacity':20000,'context_capacity':28000}},global_token_budget=1000000,block_call_budget=200)
        def context(batch_id,windows):
            return {'task':task,'brief':brief,'batch_id':batch_id,'question_ids':[],'sources':slim(windows)}
        def size(windows):
            return gateway.request_size('researcher',request_messages('researcher',context('batch-'+'0'*24,windows)),ResearchExtraction)
        batches=extraction_batches([source],task,[],16000,request_size=size)
        before=''.join(w['original_content'] for w in locate_windows([source],task,16000))
        after=''.join(w['original_content'] for b in batches for w in b.windows)
        assert before == after and len(batches)>1
        for b in batches:
            messages=request_messages('researcher',context(b.batch_id,b.windows))
            estimated, capacity=gateway.request_size('researcher',messages,ResearchExtraction)
            assert estimated <= capacity
            assert all('百万元' in w['content'] and '重述' in w['content'] for w in b.windows)
            await gateway.structured('researcher',messages,ResearchExtraction)
        assert len(calls)==len(batches)


async def test_new_sources_do_not_reextract_validated_old_source(tmp_path):
    store=Store(tmp_path/'db')
    a=SourceRecord(kind='local',title='first',content='营业收入：原有披露。\n')
    b=SourceRecord(kind='local',title='second',content='营业收入：新增披露。\n')
    class Datasource:
        async def retrieve(self,q, **options): return ([a] if q=='first' else [b]),[]
    # Use Gateway's real wire size calculation with a deterministic model stub.
    class Model(Gateway):
        def __init__(self):
            super().__init__({'m':ModelConfig(protocol='openai',base_url='https://fixture.test',model='m',api_key_env='unused')},{'default':'m'})
            self.extracted=[]
        async def structured(self,role,messages,schema):
            data=json.loads(messages[-1]['content'])
            if role=='researcher':
                title=data['sources'][0]['title']; self.extracted.append(title)
                return ResearchExtraction(evidence=[],facts=[],followup_queries=['second'] if title=='first' else [],gaps=[])
            return CompressedResearch(summary='fixture',evidence_ids=[],unresolved=[])
    model=Model()
    task=ResearchTask(task_id='F01',company_id='D',block_id='F01',topic='营业收入',role='financial',queries=['first']).model_dump(mode='json')
    brief=ResearchBrief(company_id='D',scope='fixture',segments=['设备'],historical_periods=['2023A','2024A','2025A'],forecast_periods=['2026E','2027E','2028E']).model_dump(mode='json')
    state={'task':task,'brief':brief,'round':0,'sources':[],'evidence':[],'facts':[],'queries':['first'],'gaps':[],'warnings':[],'summary':{}}
    graph=researcher_graph(model,Datasource(),store,'r',3,settings=Settings())
    output=await graph.ainvoke(state)
    assert Counter(model.extracted)=={'first':1,'second':1}
    assert len(output['sources'])==2
    assert all(batch['status']=='validated' and batch['result'] for batch in store.records('r','batch'))
    changed=state|{'brief':brief|{'scope':'changed scope'}}
    await graph.ainvoke(changed)
    assert Counter(model.extracted)=={'first':2,'second':2}
    await graph.ainvoke(state)
    assert Counter(model.extracted)=={'first':2,'second':2}
    model.role_limits['default']=RoleLimits(concurrency=1,timeout=90,block_call_budget=999)
    await graph.ainvoke(state|{'queries':['second']})
    assert Counter(model.extracted)=={'first':2,'second':2}


async def test_parallel_batches_save_successful_peers_after_failure(tmp_path):
    store=Store(tmp_path/'db')
    source=SourceRecord(kind='local',title='年报',content='营业收入 '+('原始披露文字。'*1000))
    class Datasource:
        async def retrieve(self,q, **options): return [source],[]
    class Model(Gateway):
        def __init__(self):
            super().__init__({'m':ModelConfig(protocol='openai',base_url='https://fixture.test',model='m',api_key_env='unused')},
                             {'default':'m'},role_limits={'default':{'concurrency':2}})
            self.calls=Counter(); self.active=0; self.peak=0
            self.started=asyncio.Event(); self.fail=True
        async def structured(self,role,messages,schema):
            data=json.loads(messages[-1]['content'])
            if role!='researcher': return CompressedResearch(summary='fixture',evidence_ids=[],unresolved=[])
            key=data['batch_id'];self.calls[key]+=1;self.active+=1;self.peak=max(self.peak,self.active)
            if self.active==2:self.started.set()
            try:
                await asyncio.wait_for(self.started.wait(),2)
                if self.fail:
                    self.fail=False
                    raise RuntimeError('injected batch failure')
                await asyncio.sleep(.005)
                return ResearchExtraction(evidence=[],facts=[],followup_queries=[],gaps=[])
            finally:self.active-=1
    model=Model()
    task=ResearchTask(task_id='F01',company_id='D',block_id='F01',topic='营业收入',role='financial',queries=['营业收入']).model_dump(mode='json')
    brief=ResearchBrief(company_id='D',scope='fixture',segments=['设备'],historical_periods=['2023A','2024A','2025A'],forecast_periods=['2026E','2027E','2028E']).model_dump(mode='json')
    state={'task':task,'brief':brief,'round':0,'sources':[],'evidence':[],'facts':[],'queries':task['queries'],'gaps':[],'warnings':[],'summary':{}}
    graph=researcher_graph(model,Datasource(),store,'r',1,settings=Settings(extraction_input_tokens=6000))
    with pytest.raises(RuntimeError,match='injected batch failure'): await graph.ainvoke(state)
    successful=[b['batch_id'] for b in store.records('r','batch') if b['status']=='validated']
    assert len(successful)==1 and model.peak==2 and sum(model.calls.values())==2
    await graph.ainvoke(state)
    assert model.calls[successful[0]]==1
    assert all(b['status']=='validated' for b in store.records('r','batch'))
