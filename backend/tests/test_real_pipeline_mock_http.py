"""Real code path against scripted HTTP fixtures, not a real company/LLM test."""
import json
from pathlib import Path
import httpx
import pytest
from company_research.config import ROOT,Settings
from company_research.storage import Store
from company_research.schemas import ResearchRun,Company,ResearchBrief
from company_research.graphs import ResearchWorkflow
from company_research.llm import Gateway,ModelConfig
from company_research.datasources import HTTPWebSearchProvider,WebAdapter,LocalDatasource,UnifiedDatasource
from company_research.planners import mock_research_plan,mock_calculation_plan,mock_assumptions


@pytest.mark.parametrize('performance',['legacy','throughput-1'])
@pytest.mark.parametrize('uploaded',[False,True])
async def test_real_graph_against_scripted_http(tmp_path,monkeypatch,performance,uploaded):
    monkeypatch.setenv('TEST_LLM_KEY','test-only')
    # Retain coverage of the old checkpoint protocol; fixed-slot integration is
    # tested separately with the new securities/annual-report contracts.
    settings=Settings(mode='real',data_collection_mode='legacy',database=tmp_path/'db',artifacts=tmp_path/'out',local_sources=ROOT/'examples/fixtures',search_url='https://fixture-search.test',mock_delay=0,max_replans=1)
    store=Store(settings.database);run=ResearchRun(company_input='合成协议测试企业',mode='real')
    if uploaded:
        from company_research.references import prepare_uploads,register_upload,create_with_attachments
        prepare_uploads(store)
        attachments=[register_upload(store,name,(ROOT/'examples/fixtures'/name).read_bytes())['attachment_id']
                     for name in ['company.md','financials.json']]
        create_with_attachments(store,run,attachments,10)
        settings.local_sources=tmp_path/'empty-local'
    else:store.save_run(run)
    store.execution_put(run.run_id,'execution_meta','performance',{'version':performance})
    seen=[]
    def model_server(request):
        body=json.loads(request.content);schema=body['tools'][0]['function']['parameters']['title'];data=json.loads(body['messages'][-1]['content']);seen.append(schema)
        if schema=='Company':value=Company(company_id='DEMO',name='合成协议测试企业',ticker='999999',source_ids=[data['sources'][0]['source_id']]).model_dump(mode='json')
        elif schema=='ResearchBrief':value=ResearchBrief(company_id='DEMO',scope='HTTP Fixture 测试',historical_periods=['2023A','2024A','2025A'],forecast_periods=['2026E','2027E','2028E'],segments=['设备','服务']).model_dump(mode='json')
        elif schema=='ResearchPlan':value=data['mandatory_skeleton']
        elif schema=='CalculationPlan':value=mock_calculation_plan().model_dump(mode='json')
        elif schema=='SupervisorDecision':value={'task_ids':data['pending'],'reason':'Fixture 调度'}
        elif schema=='ResearchExtraction':
            source=next((s for s in data['sources'] if s['title']=='company.md'),None)
            value={'evidence':[{'source_id':source['source_id'],'claim':'合成资料用于协议测试','quote':source.get('original_content',source['content'])[:200],'actual_or_forecast':'context'}] if source else [],'facts':[],'followup_queries':[],'gaps':[]}
        elif schema=='ReferenceQuestionSupport':value={'covered':{q:[data['evidence'][0]['evidence_id']] for q in data['questions']}}
        elif schema=='CompressedResearch':value={'summary':'Fixture 摘要','evidence_ids':[e['evidence_id'] for e in data['evidence']],'unresolved':[]}
        elif schema=='FinancialAnalysis':value={'observations':['现金与利润需结合解释。'],'evidence_ids':[data['evidence'][0]['evidence_id']] if data['evidence'] else [],'calculation_ids':[r['result_id'] for r in data['calculations']],'limitations':[],
            'question_answers':{q:'Fixture 数据只验证协议，研究结论保留合成证据限制。' for q in data['block']['questions']}}
        elif schema=='AssumptionOutput':value={'assumptions':[a.model_dump(mode='json') for a in mock_assumptions(data['evidence'][0]['evidence_id'],[data['selected_period']]) if a.scenario==data['selected_scenario']],'segment_models':{'设备':'growth','服务':'growth'},'limitations':['HTTP Fixture 假设，不是真实模型输出']}
        elif schema=='WriterDraft':
            content='这是本地协议测试用的合成研究材料。经营增长需要结合现金流、竞争、回款、资本开支和风险分析，缺失资料会限制判断，预测并不保证实现。'
            value={'paragraphs':[prefix+content*5 for prefix in ['首先关注研究边界。','接着分析经营质量。','同时核对财务来源。','另外检查预测条件。','最后保留风险限制。']],'evidence_ids':[data['evidence'][0]['evidence_id']] if data['evidence'] else [],'calculation_ids':[],'fact_ids':[],'assumption_ids':[],
                'consistency_checks':{k:'Fixture 一致性输出，不证明真实模型综合质量。' for k in ['cash_growth','forecast_total','valuation_evidence','resource_concentration']}}
        elif schema=='Reflection':value={'needs_revision':False,'instructions':[]}
        elif schema=='ReviewOutput':value={'issues':[]}
        else:raise AssertionError(schema)
        return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'id':'output','function':{'name':'structured_output','arguments':json.dumps(value,ensure_ascii=False)}}]},'finish_reason':'tool_calls'}],'usage':{'prompt_tokens':10,'completion_tokens':10}})
    def search_server(request):
        if uploaded:raise AssertionError('上传参考资料已完整覆盖，不能重复外部检索')
        if request.method=='POST':return httpx.Response(200,json={'results':[{'url':'https://example.com/company.md','title':'company.md','publication_date':'2026-04-01'}]})
        return httpx.Response(200,content=(ROOT/'examples/fixtures/company.md').read_bytes(),headers={'Content-Type':'text/plain'})
    # DNS is not consulted in this HTTP Fixture; address security has independent tests.
    async def fixture_public_url(url):return None
    monkeypatch.setattr('company_research.datasources.validate_public_url',fixture_public_url)
    async with httpx.AsyncClient(transport=httpx.MockTransport(model_server)) as model_client, httpx.AsyncClient(transport=httpx.MockTransport(search_server)) as web_client:
        gateway=Gateway({'test':ModelConfig(protocol='openai',base_url='https://fixture-model.test/v1',model='fixture-model',api_key_env='TEST_LLM_KEY')},{'default':'test'},client=model_client,global_token_budget=10000000)
        workflow=ResearchWorkflow(settings,store,run.run_id,gateway)
        local=LocalDatasource(settings.local_sources);local.build_index()
        workflow.datasource=UnifiedDatasource(local,WebAdapter(HTTPWebSearchProvider(settings.search_url,client=web_client),store,client=web_client))
        output=await workflow.build().ainvoke({'context':{'input':run.company_input,'run_id':run.run_id,'replans':0,'revisions':0}},{'recursion_limit':150})
    assert store.run(run.run_id).status=='limited'
    assert len(output['context']['forecasts'])==9
    assert {'Company','ResearchBrief','ResearchPlan','CalculationPlan','ResearchExtraction','CompressedResearch','FinancialAnalysis','AssumptionOutput','WriterDraft','Reflection','ReviewOutput'}.issubset(set(seen))
    assert gateway.usage['writer']['calls']>=9
    assert all(s['kind']!='mock' for s in output['context']['sources'])
    if uploaded:
        assert all(s['kind']=='upload' for s in output['context']['sources'])
        assert store.records(run.run_id,'reference_coverage')
        assert all(not r['external_queries'] for r in store.records(run.run_id,'reference_coverage'))
        assert all(d['rule']=='reference-first' for d in output['context']['fact_decisions'])
