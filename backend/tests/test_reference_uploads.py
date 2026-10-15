import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from company_research.api import create_app
from company_research.config import Settings
from company_research.datasources import DatasourceError
from company_research.evidence import EvidenceStore
from company_research.execution import ensure_manifest, RecoveryError
from company_research.graphs import ResearchWorkflow
from company_research.human_intervention import HumanInterventionAgent
from company_research.references import (prepare_uploads, register_upload, create_with_attachments,
                                         reference_fingerprint, plan_reference_queries, ReferenceQuestionSupport)
from company_research.reconciliation import reconcile
from company_research.schemas import ResearchRun, SourceRecord, FinancialFact, EvidenceRecord
from company_research.storage import Store


def settings(tmp_path, mode='real'):
    return Settings(_env_file=None, mode=mode, database=tmp_path/'db.sqlite',
                    local_sources=tmp_path/'local', artifacts=tmp_path/'out', mock_delay=0)


def financial_rows(value='110'):
    return [{'company_id':'test','metric_code':'revenue','period':'2024A','unit':'CNY_million',
             'value':value,'actual_or_forecast':'actual','scope':'consolidated'}]


def uploaded_run(tmp_path, rows=None):
    store=Store(tmp_path/'db.sqlite');prepare_uploads(store)
    upload=register_upload(store,'reference.json',json.dumps(rows or financial_rows()).encode())
    run=ResearchRun(company_input='测试公司',mode='real',rules_version='1.1')
    create_with_attachments(store,run,[upload['attachment_id']],10)
    bound=EvidenceStore(store,run.run_id)
    for s in store.records(run.run_id,'source'):bound.ingest_structured(SourceRecord.model_validate(s))
    return store,run,bound


async def test_upload_and_create_binds_before_scheduling_and_rejects_reuse(tmp_path,monkeypatch):
    called=[]
    async def fake_run(self,run_id):
        called.append((run_id,self.store.records(run_id,'source')))
    monkeypatch.setattr('company_research.runner.Runner.run',fake_run)
    app=create_app(settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/reference-attachments',params={'filename':'年报.txt'},content='测试公司 2024 年度营业收入 110 百万元'.encode())
        assert response.status_code==201
        uploaded=response.json();assert uploaded['status']=='ready' and uploaded['source_count']==1
        assert 'path' not in uploaded and 'sources' not in uploaded
        response=await client.post('/api/research',json={'company':'测试公司','attachment_ids':[uploaded['attachment_id']]})
        assert response.status_code==202
        run=response.json();assert run['reference_attachment_ids']==[uploaded['attachment_id']]
        attached=(await client.get(f'/api/research/{run["run_id"]}/attachments')).json()
        assert attached['attachments'][0]['filename']=='年报.txt'
        reused=await client.post('/api/research',json={'company':'其它公司','attachment_ids':[uploaded['attachment_id']]})
        assert reused.status_code==422
        assert (await client.get('/api/research/missing/attachments')).status_code==404
        import asyncio
        await asyncio.sleep(0)
        assert called and called[0][1][0]['kind']=='upload'


async def test_bad_upload_and_missing_attachment_do_not_create_run(tmp_path,monkeypatch):
    app=create_app(settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        for filename,body in [('bad.exe',b'abc'),('empty.txt',b''),('broken.pdf',b'not a PDF')]:
            assert (await client.post('/api/reference-attachments',params={'filename':filename},content=body)).status_code==422
        monkeypatch.setattr('company_research.api.MAX_BYTES',8)
        assert (await client.post('/api/reference-attachments',params={'filename':'large.txt'},content=b'123456789')).status_code==413
        assert (await client.post('/api/research',json={'company':'测试','attachment_ids':['missing']})).status_code==422
        assert not app.state.store.active_runs()


def test_binding_atomic_no_cross_run_sources_and_resume_integrity(tmp_path):
    store,run,bound=uploaded_run(tmp_path)
    other=ResearchRun(company_input='其它公司',mode='real')
    upload=register_upload(store,'other.txt',b'other company')
    with pytest.raises(DatasourceError):
        create_with_attachments(store,other,[upload['attachment_id'],'invalid'],10)
    assert not store.run(other.run_id) and not store.records(other.run_id,'source')
    create_with_attachments(store,other,[upload['attachment_id']],10)
    assert not {s.source_id for s in bound.sources.values()} & {s['source_id'] for s in store.records(other.run_id,'source')}
    fingerprint=reference_fingerprint(store,run.run_id)
    assert fingerprint['policy']=='uploaded-reference-1'
    ensure_manifest(settings(tmp_path),store,run.run_id)
    ensure_manifest(settings(tmp_path),store,run.run_id)
    with store.connect() as db:
        payload=json.loads(db.execute('SELECT payload FROM reference_attachments WHERE run_id=?',(run.run_id,)).fetchone()[0])
    from pathlib import Path
    Path(payload['path']).write_bytes(b'changed')
    with pytest.raises(DatasourceError,match='改变或丢失'):reference_fingerprint(store,run.run_id)


def test_reference_overrides_official_without_destroying_original(tmp_path):
    store,run,bound=uploaded_run(tmp_path)
    reference=next(iter(bound.facts.values())).model_dump(mode='json')
    source={'source_id':'official','kind':'web','title':'测试公司年报','source_url':'https://cninfo.com.cn/a',
            'content':'测试公司 2024年度 合并 营业收入 120百万元','locator':'p1'}
    ev={'evidence_id':'ev-official','source_id':'official','quote':source['content'],'claim':source['content'],'locator':'p1','validation_status':'verified'}
    official=reference|{'fact_id':'a-official','source_id':'official','evidence_id':'ev-official','value':'120'}
    facts=[official,reference];original=copy.deepcopy(facts)
    active,decisions=reconcile(facts,[s.model_dump(mode='json') for s in bound.sources.values()]+[source],
                               [e.model_dump(mode='json') for e in bound.evidence.values()]+[ev],{'company_id':'test','name':'测试公司'})
    assert facts==original and active[0]['fact_id']==reference['fact_id']
    assert active[0]['value']=='110' and decisions[0]['rule']=='reference-first'


async def test_reference_conflict_never_requests_lower_sources_and_human_can_select(tmp_path,monkeypatch):
    store,run,bound=uploaded_run(tmp_path,financial_rows()+financial_rows('115'))
    workflow=ResearchWorkflow(settings(tmp_path),store,run.run_id)
    facts=[f.model_dump(mode='json') for f in bound.facts.values()]
    sources=[s.model_dump(mode='json') for s in bound.sources.values()]
    evidence=[e.model_dump(mode='json') for e in bound.evidence.values()]
    context={'company':{'company_id':'test','name':'测试公司'},'brief':{},'facts':facts,'sources':sources,
             'evidence':evidence,'required_data':[],'coverage':[],'plan':{'blocks':[]},'limitations':[]}
    class Forbidden:
        async def ainvoke(self,*args):raise AssertionError('must not search lower priority sources')
    monkeypatch.setattr('company_research.graphs.researcher_graph',lambda *a:Forbidden())
    result=await workflow.data_gaps(context)
    assert not result['facts'] and result['fact_decisions'][0]['rule']=='reference-conflict'
    selected=workflow.human.validate_selection(facts[0],facts,sources,evidence,context['company'],'采用已审核参考资料')
    assert selected['fact_id']==facts[0]['fact_id']


async def test_only_absent_fields_are_queried_and_complete_coverage_makes_zero_queries(tmp_path):
    store,run,bound=uploaded_run(tmp_path)
    req=lambda id,metric:{'data_id':id,'company_id':'test','metric_code':metric,'period':'2024A','unit':'CNY_million','segment_id':None}
    context={'company':{'company_id':'test','name':'测试公司'},'sources':[s.model_dump(mode='json') for s in bound.sources.values()],
             'facts':[f.model_dump(mode='json') for f in bound.facts.values()],
             'evidence':[e.model_dump(mode='json') for e in bound.evidence.values()],
             'required_data':[req('revenue','revenue'),req('cashflow','operating_cashflow')],'plan':{'blocks':[]}}
    task={'task_id':'t','company_id':'test','role':'financial','topic':'收入和现金流','queries':['测试公司 全部财务 年报'],
          'required_data_ids':['revenue','cashflow']}
    planned=await plan_reference_queries(task,context,None,store,run.run_id)
    assert len(planned['queries'])==1 and '经营活动' in planned['queries'][0]
    assert '收入' not in planned['queries'][0]
    covered=await plan_reference_queries(task|{'required_data_ids':['revenue']},context,None,store,run.run_id)
    assert covered['queries']==[]
    # Future or parent-company figures cannot satisfy an actual consolidated requirement.
    wrong=copy.deepcopy(context);wrong['facts'][0]['actual_or_forecast']='forecast'
    assert (await plan_reference_queries(task|{'required_data_ids':['revenue']},wrong,None,store,run.run_id))['queries']


async def test_question_support_requires_known_uploaded_evidence(tmp_path,monkeypatch):
    store,run,bound=uploaded_run(tmp_path)
    context={'company':{'company_id':'test','name':'测试公司'},'sources':[s.model_dump(mode='json') for s in bound.sources.values()],
             'facts':[],'evidence':[e.model_dump(mode='json') for e in bound.evidence.values()],
             'required_data':[],'plan':{'blocks':[{'block_id':'C01','questions':{'q1':'主营业务','q2':'行业规模'}}]}}
    eid=context['evidence'][0]['evidence_id']
    async def support(*args):return ReferenceQuestionSupport(covered={'q1':[eid],'q2':['invented']})
    monkeypatch.setattr('company_research.agents.ask_bounded',support)
    task={'task_id':'t','role':'company','company_id':'test','topic':'公司研究','queries':['全量搜索'],
          'block_id':'C01','question_ids':['q1','q2'],'required_data_ids':[]}
    planned=await plan_reference_queries(task,context,None,store,run.run_id)
    assert planned['queries']==['测试公司 行业规模']


async def test_reference_coverage_uses_default_capacity_and_preserves_all_quotes_without_page_lists(tmp_path,monkeypatch):
    from company_research.llm import Gateway,ModelConfig
    store,run,bound=uploaded_run(tmp_path)
    source=next(iter(bound.sources.values()))
    evidence=[{'evidence_id':f'e{i}','source_id':source.source_id,'claim':'主营业务生产和销售',
               'quote':'保留原文与口径'*20,'actual_or_forecast':'actual','validation_status':'verified',
               'locator':'; '.join(f'page:{p}' for p in range(300))} for i in range(80)]
    facts=[f.model_dump(mode='json') for f in bound.facts.values()]
    facts[0]['locator']=evidence[0]['locator']
    original=copy.deepcopy(evidence)
    context={'company':{'company_id':'test','name':'测试公司'},'sources':[source.model_dump(mode='json')],
             'facts':facts,'evidence':evidence,'required_data':[],'brief':{'historical_periods':['2024A']},
             'plan':{'blocks':[{'block_id':'C01','questions':{'q1':'主营业务'}}]}}
    task={'task_id':'t','company_id':'test','role':'company','topic':'公司','queries':['old query'],
          'block_id':'C01','question_ids':['q1'],'required_data_ids':[]}
    seen=[];monkeypatch.setenv('COVERAGE_TEST_KEY','test-key')
    def respond(request):
        body=json.loads(request.content);part=json.loads(body['messages'][1]['content']);seen.append(part)
        assert '只返回 covered' in body['messages'][0]['content']
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'covered':{'q1':['e0']}})},'finish_reason':'stop'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        gateway=Gateway({'m':ModelConfig(protocol='openai',base_url='http://mock',model='m',api_key_env='COVERAGE_TEST_KEY',structured_mode='json')},
                        {'default':'m'},role_limits={'default':{'input_capacity':120000,'context_capacity':160000},'researcher':{'input_capacity':20000}},client=client)
        planned=await plan_reference_queries(task,context,gateway,store,run.run_id)
    assert planned['queries']==[] and len(seen)==1
    assert len(seen[0]['evidence'])==80 and 'queries' not in seen[0]['task']
    assert all('locator' not in e and e['quote']==original[i]['quote'] for i,e in enumerate(seen[0]['evidence']))
    assert 'locator' not in seen[0]['facts'][0] and seen[0]['facts'][0]['value']==facts[0]['value']
    assert evidence==original


async def test_split_coverage_keeps_support_from_both_halves(monkeypatch):
    from company_research.agents import ask_bounded
    class Gateway:
        def request_size(self,role,messages,schema):
            data=json.loads(messages[1]['content'])
            return len(data['evidence']),1
    async def answer(gateway,role,schema,context):
        return ReferenceQuestionSupport(covered={'q1':[e['evidence_id'] for e in context['evidence']]})
    monkeypatch.setattr('company_research.agents.ask',answer)
    result=await ask_bounded(Gateway(),'reference_planner',ReferenceQuestionSupport,{'evidence':[{'evidence_id':'e1'},{'evidence_id':'e2'}]})
    assert result.covered=={'q1':['e1','e2']}


async def test_researcher_with_prepared_references_does_not_retrieve_or_reextract(tmp_path,monkeypatch):
    from company_research.researcher import researcher_graph
    from company_research.agents import CompressedResearch
    store,run,bound=uploaded_run(tmp_path)
    class Datasource:
        async def retrieve(self,q):raise AssertionError('covered field must not be fetched')
    async def compress(*args):return CompressedResearch(summary='来自参考资料',evidence_ids=[],unresolved=[])
    monkeypatch.setattr('company_research.researcher.ask_bounded',compress)
    state={'task':{'task_id':'covered','company_id':'test','role':'financial','topic':'收入','queries':[]},
           'brief':{},'round':0,'sources':[s.model_dump(mode='json') for s in bound.sources.values()],
           'facts':[f.model_dump(mode='json') for f in bound.facts.values()],
           'evidence':[e.model_dump(mode='json') for e in bound.evidence.values()],
           'queries':[],'gaps':[],'warnings':[],'summary':{},'reference_prepared':True}
    graph=researcher_graph(None,Datasource(),store,run.run_id,3,False,settings(tmp_path))
    result=await graph.ainvoke(state)
    assert result['facts']==state['facts'] and result['summary']['summary']=='来自参考资料'


async def test_json_business_notes_are_extracted_instead_of_skipped(tmp_path,monkeypatch):
    from company_research.schemas import ResearchBrief,ResearchPlan
    store,run,bound=uploaded_run(tmp_path,[{'company':'测试公司','business':'设备生产与销售'}])
    workflow=ResearchWorkflow(settings(tmp_path),store,run.run_id)
    captured=[];tasks=[]
    class Extract:
        async def ainvoke(self,state,*args):
            captured.extend(state['sources'])
            tasks.append(state['task'])
            return state
    async def plan(gateway,role,schema,context):
        return ResearchPlan.model_validate(context['mandatory_skeleton'])
    monkeypatch.setattr('company_research.graphs.researcher_graph',lambda *a:Extract())
    monkeypatch.setattr('company_research.graphs.ask',plan)
    context={'company':{'company_id':'test','name':'测试公司'},'sources':[s.model_dump(mode='json') for s in bound.sources.values()],
             'evidence':[],'facts':[],'limitations':[],
             'brief':ResearchBrief(company_id='test',scope='参考资料',historical_periods=['2023A','2024A','2025A'],
                                   forecast_periods=['2026E','2027E','2028E'],segments=['设备']).model_dump(mode='json')}
    await workflow.research_plan(context)
    assert captured and '设备生产与销售' in captured[0]['content']
    assert [t['role'] for t in tasks]==['financial','business']


async def test_more_than_ten_attachments_bind_and_configured_limit_is_reported(tmp_path,monkeypatch):
    async def idle(*args):pass
    monkeypatch.setattr('company_research.runner.Runner.run',idle)
    cfg=settings(tmp_path);app=create_app(cfg)
    attachments=[register_upload(app.state.store,f'行业报告{i}.txt',f'行业材料 {i}'.encode())['attachment_id'] for i in range(12)]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        startup=(await client.get('/api/startup')).json()
        assert startup['reference_limits']['max_files']==50
        response=await client.post('/api/research',json={'company':'测试公司','attachment_ids':attachments})
        assert response.status_code==202 and len(response.json()['reference_attachment_ids'])==12
    limited=settings(tmp_path/'limited');limited.reference_max_files=11
    app=create_app(limited)
    attachments=[register_upload(app.state.store,f'file{i}.txt',b'industry report')['attachment_id'] for i in range(12)]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/api/startup')).json()['reference_limits']['max_files']==11
        assert (await client.post('/api/research',json={'company':'测试公司','attachment_ids':attachments})).status_code==422
        assert not app.state.store.active_runs()


async def test_industry_upload_support_survives_analysis_writing_and_coverage(tmp_path,monkeypatch):
    from company_research.contexts import block_context
    from company_research.framework import refresh_coverage
    from company_research.references import reference_question_support
    quote='2025年全球工业自动化市场规模达到3000亿元。统计范围为工业自动化设备及软件。需求受制造业投资影响。'
    source=SourceRecord(kind='upload',attachment_id='industry',title='全球自动化行业报告',content=quote).model_dump(mode='json')
    ev=EvidenceRecord(evidence_id='industry-evidence',source_id=source['source_id'],claim='行业规模和需求',quote=quote,
                      locator='page:1',actual_or_forecast='context',validation_status='verified').model_dump(mode='json')
    block={'block_id':'I01-0','template_id':'I01','company_id':'test','segment_id':'传感器','questions':{'q1':'需求规模周期价格与政策','q2':'竞争格局与产业链'},'dependencies':[]}
    c={'company':{'company_id':'test','name':'测试公司','source_ids':[]},'brief':{'historical_periods':['2023A','2024A','2025A'], 'forecast_periods':['2026E']},
       'sources':[source],'evidence':[ev],'facts':[],'plan':{'blocks':[block]},'coverage':[]}
    store=Store(tmp_path/'industry.db')
    async def support(*args):return ReferenceQuestionSupport(covered={'q1':['industry-evidence']})
    monkeypatch.setattr('company_research.agents.ask_bounded',support)
    task={'task_id':'industry-task','company_id':'test','role':'business','topic':'传感器行业','block_id':'I01-0',
          'question_ids':['q1','q2'],'required_data_ids':[],'queries':['全部行业信息']}
    planned=await plan_reference_queries(task,c,None,store,'r')
    assert planned['queries']==['测试公司 竞争格局与产业链']
    support_map=reference_question_support(c,store,'r')
    entries=[{'block_id':'I01-0','question_id':'q1','requirements':[],'gaps':[]}]
    covered=refresh_coverage(entries,[block],[],[ev],{},support_map)
    assert covered[0]['status']=='ready' and covered[0]['verified_refs']==['industry-evidence'] and not covered[0]['gaps']
    for purpose in ['analysis','writing']:
        package=block_context(c,'I01-0',purpose,store,'r')
        assert package.content['evidence'][0]['quote']==quote
        assert not package.content['financial_facts']
    wrong=copy.deepcopy(c);wrong['sources'][0]['kind']='web'
    assert reference_question_support(wrong,store,'r')=={}
    assert not block_context(wrong,'I01-0','analysis',store,'r').content['evidence']


async def test_industry_context_extraction_keeps_numbers_as_evidence_not_company_facts(tmp_path,monkeypatch):
    from company_research.researcher import researcher_graph
    from company_research.agents import ResearchExtraction,CompressedResearch
    store=Store(tmp_path/'context.db')
    source=SourceRecord(kind='upload',attachment_id='industry',title='市场报告',content='2025年全球市场规模为3000百万元。')
    class Datasource:
        async def retrieve(self,q):raise AssertionError('must read only uploaded industry material')
    class Gateway:
        concurrency=1
        def limits(self,*args):return SimpleNamespace(input_capacity=50000,concurrency=1)
    requests=[]
    async def extract(gateway,role,schema,context):
        requests.append(context)
        return ResearchExtraction.model_validate({'evidence':[{'source_id':source.source_id,'claim':'全球市场规模','quote':source.content,'actual_or_forecast':'context'}],
            'facts':[{'source_id':source.source_id,'quote':source.content,'metric_code':'revenue','period':'2025A','unit':'CNY_million','value':'3000','actual_or_forecast':'actual'}],
            'gaps':[],'followup_queries':[]})
    async def compress(*args):return CompressedResearch(summary='行业报告证据',evidence_ids=[],unresolved=[])
    monkeypatch.setattr('company_research.researcher.ask',extract)
    monkeypatch.setattr('company_research.researcher.ask_bounded',compress)
    state={'task':{'task_id':'uploaded_reference_context_extract','company_id':'test','topic':'行业','role':'business','queries':['行业']},
           'brief':{'company_id':'test','scope':'研究','historical_periods':['2023A','2024A','2025A'],'forecast_periods':['2026E','2027E','2028E'],'segments':['传感器']},
           'round':0,'sources':[source.model_dump(mode='json')],'evidence':[],'facts':[],'queries':[],'gaps':[],
           'warnings':[],'summary':{},'reference_only':True,'reference_context':True}
    graph=researcher_graph(Gateway(),Datasource(),store,'r',1,False,settings(tmp_path))
    result=await graph.ainvoke(state)
    assert result['facts']==[] and result['evidence'][0]['quote']==source.content
    assert any('行业统计' in text for text in requests[0]['instructions'])
