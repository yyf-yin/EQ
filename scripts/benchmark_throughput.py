"""Compare extraction strategies with fixed HTTP latency and identical evidence.

No real provider/search requests. Each invocation uses a fresh isolated database.
This measures a research subgraph, not real company end-to-end performance.
"""
import asyncio
import json
import os
import time
from collections import Counter
from uuid import uuid4

import httpx

from company_research.config import ROOT, Settings
from company_research.framework import digest
from company_research.llm import Gateway, ModelConfig
from company_research.researcher import researcher_graph
from company_research.schemas import ResearchBrief, ResearchRun, ResearchTask, SourceRecord
from company_research.storage import Store


async def measure(profile, directory, source, latency):
    store=Store(directory/'research.sqlite')
    run=ResearchRun(company_input='合成提速基准',mode='real');store.save_run(run)
    store.execution_put(run.run_id,'execution_meta','performance',{'version':profile})
    settings=Settings(mode='real',database=store.path,local_sources=directory/'sources',artifacts=directory/'out',concurrency=3)
    calls=Counter()
    async def respond(request):
        body=json.loads(request.content)
        schema=body['tools'][0]['function']['parameters']['title']
        data=json.loads(body['messages'][-1]['content']);calls[schema]+=1
        await asyncio.sleep(latency)
        if schema=='ResearchExtraction':
            quote='营业收入 2025A 550'
            found=next((s for s in data['sources'] if quote in s['content']),None)
            facts=[{'source_id':found['source_id'],'quote':quote,'metric_code':'revenue','period':'2025A',
                    'unit':'CNY_million','value':'550','actual_or_forecast':'actual'}] if found else []
            value={'evidence':[],'facts':facts,'followup_queries':[],'gaps':[]}
        else:
            assert schema=='CompressedResearch'
            value={'summary':'合成基准摘要','evidence_ids':[e['evidence_id'] for e in data['evidence']],'unresolved':[]}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value,ensure_ascii=False)},'finish_reason':'stop'}],
                                       'usage':{'prompt_tokens':100,'completion_tokens':100}})
    class Datasource:
        async def retrieve(self,query):return [source],[]
    brief=ResearchBrief(company_id='D',scope='合成基准',segments=['设备'],historical_periods=['2023A','2024A','2025A'],forecast_periods=['2026E','2027E','2028E'])
    task=ResearchTask(task_id='F01',company_id='D',block_id='F01',topic='营业收入',role='financial',queries=['营业收入'])
    state={'task':task.model_dump(mode='json'),'brief':brief.model_dump(mode='json'),'round':0,'sources':[],'evidence':[],
           'facts':[],'queries':task.queries,'gaps':[],'warnings':[],'summary':{}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        gateway=Gateway({'fixture':ModelConfig(protocol='openai',base_url='https://fixture.test/v1',model='fixture',api_key_env='THROUGHPUT_BENCH_KEY')},
                        {'default':'fixture'},client=client,concurrency=3,role_limits={'researcher':{'input_capacity':20000,'context_capacity':68000,'concurrency':2}},
                        global_call_budget=10000,global_token_budget=20000000,block_call_budget=10000)
        gateway.attach_store(store,run.run_id)
        graph=researcher_graph(gateway,Datasource(),store,run.run_id,1,settings=settings)
        started=time.perf_counter();result=await graph.ainvoke(state,{'recursion_limit':20});elapsed=time.perf_counter()-started
    facts={f['fact_id']:f for f in result['facts']};evidence={e['evidence_id']:e for e in result['evidence']}
    return {'seconds':round(elapsed,3),'http_calls':dict(calls),'unique_facts':len(facts),'unique_evidence':len(evidence),
            'facts_digest':digest(sorted(facts.values(),key=lambda f:f['fact_id'])),
            'evidence_digest':digest(sorted(evidence.values(),key=lambda e:e['evidence_id'])),
            'warnings':result['warnings'],'gaps':result['gaps']}


async def main():
    os.environ['THROUGHPUT_BENCH_KEY']='fixture-only'
    directory=ROOT/'work/throughput-benchmark'/uuid4().hex
    source=SourceRecord(source_id='benchmark-source',kind='local',title='合成披露',locator='table 1',
                        content='单位：人民币百万元 合并\n| 指标 | 2025A | 2024A |\n'+
                                '营业收入 2025A 550；同行对照资料、业务边界和现金流变化均需查证。\n'*1000)
    latency=.1
    before=await measure('legacy',directory/'legacy',source,latency)
    after=await measure('throughput-1',directory/'optimized',source,latency)
    assert before['facts_digest']==after['facts_digest'] and before['evidence_digest']==after['evidence_digest']
    assert before['warnings']==after['warnings']==[] and before['gaps']==after['gaps']==[]
    result={'scope':'合成取证子图；固定 Mock HTTP 延迟，不代表真实完整研报耗时',
            'http_latency_seconds':latency,'legacy':before,'optimized':after,
            'reduction_percent':round(100*(1-after['seconds']/before['seconds']),2)}
    path=directory/'result.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));print(path)


if __name__=='__main__':asyncio.run(main())
