import json
import os
import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from company_research.llm import Gateway,ModelConfig,ConfigurationError,LLMError


class Answer(BaseModel):
    answer: str


@pytest.mark.parametrize('protocol',['openai','anthropic'])
async def test_protocol_http_server(protocol,monkeypatch):
    monkeypatch.setenv('TEST_KEY','test-secret')
    app=FastAPI(); captured=[]
    @app.post('/v1/{endpoint:path}')
    async def respond(endpoint:str,request:Request):
        data=await request.json();captured.append((endpoint,data,dict(request.headers)))
        assert data['model']=='configured-model'
        if protocol=='openai':
            return {'choices':[{'message':{'content':None,'tool_calls':[{'id':'one','type':'function','function':{'name':'structured_output','arguments':'{"answer":"ok"}'}}]},'finish_reason':'tool_calls'}],'usage':{'prompt_tokens':12,'completion_tokens':4}}
        return {'content':[{'type':'tool_use','id':'one','name':'structured_output','input':{'answer':'ok'}}],'usage':{'input_tokens':12,'output_tokens':4},'stop_reason':'tool_use'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://mock') as c:
        g=Gateway({'m':ModelConfig(protocol=protocol,base_url='http://mock/v1',model='configured-model',api_key_env='TEST_KEY')},{'default':'m'},client=c)
        value=await g.structured('planner',[{'role':'system','content':'instructions'},{'role':'user','content':'query'}],Answer)
        assert value.answer=='ok'
        endpoint,data,headers=captured[0]
        assert endpoint==('chat/completions' if protocol=='openai' else 'messages')
        if protocol=='anthropic':
            assert headers['x-api-key']=='test-secret'
            assert headers['anthropic-version']=='2023-06-01'
            assert data['system']=='instructions'
            assert data['tools'][0]['input_schema']['properties']['answer']['type']=='string'
        else:
            assert headers['authorization']=='Bearer test-secret'
            assert data['tools'][0]['function']['parameters']['properties']['answer']['type']=='string'
        assert g.usage['planner']=={'calls':1,'input_tokens':12,'output_tokens':4}


@pytest.mark.parametrize('protocol',['openai','anthropic'])
async def test_tool_roundtrip(protocol,monkeypatch):
    monkeypatch.setenv('TEST_KEY','x');app=FastAPI();seen=[]
    @app.post('/v1/{endpoint:path}')
    async def response(endpoint:str,request:Request):
        body=await request.json();seen.append(body)
        if len(seen)==1:
            if protocol=='openai':return {'choices':[{'message':{'tool_calls':[{'id':'t','function':{'name':'lookup','arguments':'{"query":"company"}'}}]}}]}
            return {'content':[{'type':'tool_use','id':'t','name':'lookup','input':{'query':'company'}}]}
        if protocol=='openai':
            assert body['messages'][-1]['role']=='tool' and body['messages'][-1]['tool_call_id']=='t'
            return {'choices':[{'message':{'content':'done'}}]}
        assert body['messages'][-1]['content'][0]['type']=='tool_result'
        assert body['messages'][-2]['content'][0]['type']=='tool_use'
        return {'content':[{'type':'text','text':'done'}]}
    async def lookup(query):return {'source_id':'s','query':query}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as c:
        g=Gateway({'m':ModelConfig(protocol=protocol,base_url='http://mock/v1',model='m',api_key_env='TEST_KEY')},{'default':'m'},client=c)
        r=await g.with_tools('researcher',[{'role':'user','content':'go'}],[{'name':'lookup','input_schema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}}],{'lookup':lookup})
        assert r.content=='done' and len(seen)==2


async def test_retry_timeout_and_errors(monkeypatch):
    monkeypatch.setenv('TEST_KEY','x');count=0
    def handler(request):
        nonlocal count
        count+=1
        if count==1:return httpx.Response(429,json={'error':'secret-provider-text'})
        return httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}]})
    config=ModelConfig(protocol='openai',base_url='http://mock/v1',model='m',api_key_env='TEST_KEY')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        g=Gateway({'m':config},{'default':'m'},client=c)
        assert (await g.complete('a',[{'role':'user','content':'q'}])).content=='ok'
        assert count==2
    def timeout(request):raise httpx.ReadTimeout('secret',request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as c:
        with pytest.raises(LLMError,match='超时'):
            await Gateway({'m':config},{'default':'m'},client=c,retries=2).complete('a',[])
    monkeypatch.delenv('TEST_KEY')
    with pytest.raises(ConfigurationError):Gateway({'m':config},{'default':'m'}).resolve('a')


def test_key_can_be_loaded_from_an_environment_configured_file(tmp_path, monkeypatch):
    key_file = tmp_path / 'deepseek.key'
    key_file.write_text('test-file-key\n', encoding='utf-8')
    monkeypatch.delenv('FILE_TEST_KEY', raising=False)
    monkeypatch.setenv('FILE_TEST_KEY_PATH', str(key_file))
    config = ModelConfig(protocol='openai', base_url='https://example.test/v1', model='test-model',
                         api_key_env='FILE_TEST_KEY', api_key_file_env='FILE_TEST_KEY_PATH')

    assert config.key() == 'test-file-key'
    assert os.environ['FILE_TEST_KEY'] == 'test-file-key'


async def test_native_and_invalid_structured(monkeypatch):
    monkeypatch.setenv('TEST_KEY','x')
    def handler(request):
        body=json.loads(request.content)
        assert body['response_format']['type']=='json_schema'
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"wrong":1}'}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        g=Gateway({'m':ModelConfig(protocol='openai',base_url='http://mock/v1',model='m',api_key_env='TEST_KEY',structured_mode='native')},{'default':'m'},client=c,retries=2)
        with pytest.raises(LLMError,match='Pydantic'):await g.structured('a',[],Answer)


@pytest.mark.parametrize('usage,expected',[
    ({'prompt_tokens':100,'prompt_cache_hit_tokens':80,'prompt_cache_miss_tokens':20}, {'cache_hit_tokens':80,'cache_miss_tokens':20}),
    ({'prompt_tokens':100,'prompt_tokens_details':{'cached_tokens':0}}, {'cache_hit_tokens':0,'cache_miss_tokens':100}),
    ({'prompt_tokens':100}, {}),
    ({'prompt_tokens':100,'prompt_cache_hit_tokens':101}, {}),
    ({'prompt_tokens':100,'prompt_cache_hit_tokens':80,'prompt_cache_miss_tokens':30}, {}),
    ({'prompt_tokens':100,'prompt_cache_hit_tokens':True}, {}),
])
def test_cache_counters_distinguish_reported_zero_from_unknown(usage,expected):
    from company_research.llm import cache_usage
    assert cache_usage(usage,'openai') == expected


async def test_deepseek_cache_and_reasoning_counters_are_saved_without_response_body(tmp_path,monkeypatch):
    from company_research.schemas import ResearchRun
    from company_research.storage import Store
    monkeypatch.setenv('CACHE_TEST_KEY','test-key')
    store=Store(tmp_path/'cache.sqlite');run=ResearchRun(company_input='test',mode='real');store.save_run(run)
    def respond(request):
        return httpx.Response(200,json={'model':'actual-model',
            'choices':[{'message':{'content':'ok','reasoning_content':'private reasoning'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':100,'completion_tokens':20,'prompt_cache_hit_tokens':80,
                     'prompt_cache_miss_tokens':20,'completion_tokens_details':{'reasoning_tokens':15}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        gateway=Gateway({'m':ModelConfig(protocol='openai',base_url='http://mock',model='requested-model',api_key_env='CACHE_TEST_KEY')},
                        {'default':'m'},client=client)
        gateway.attach_store(store,run.run_id)
        await gateway.complete('writer',[{'role':'user','content':'test'}])
    record=store.records(run.run_id,'call')[0]
    assert (record['cache_hit_tokens'],record['cache_miss_tokens'],record['reasoning_tokens']) == (80,20,15)
    assert record['response_model']=='actual-model'
    assert gateway.reserved_tokens==120  # Cache hits still count as input, not free token budget.
    assert 'private reasoning' not in json.dumps(record)
