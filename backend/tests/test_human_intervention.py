import asyncio
import copy
import json
from decimal import Decimal

import httpx
import pytest

from company_research.api import create_app
from company_research.config import Settings
from company_research.graphs import ResearchWorkflow
from company_research.human_intervention import HumanInterventionAgent, HumanFeedback, FeedbackError, HumanInputRequired
from company_research.runner import Runner
from company_research.schemas import ResearchRun, FinancialFact, SourceRecord, ResearchTask
from company_research.storage import Store
from company_research.work_products import capture_snapshot, export_snapshot

COMPANY={'company_id':'test','name':'测试股份有限公司'}


def material(key,value='100',primary=True,basis='reported'):
    quote=f'测试股份有限公司 2024年度 合并 营业收入 {value}百万元。'
    source=SourceRecord(source_id='s'+key,kind='web',title=COMPANY['name'],content=quote,source_url=('https://cninfo.com.cn/' if primary else 'https://news.example/')+key).model_dump(mode='json')
    ev={'evidence_id':'e'+key,'source_id':source['source_id'],'claim':quote,'quote':quote,'locator':'p1','actual_or_forecast':'actual','validation_status':'verified'}
    fact=FinancialFact(fact_id=key,company_id='test',metric_code='revenue',period='2024A',unit='CNY_million',value=value,actual_or_forecast='actual',source_id=source['source_id'],evidence_id=ev['evidence_id'],locator='p1',validation_status='verified',accounting_basis=basis).model_dump(mode='json')
    return fact,source,ev


def setup(tmp_path,*materials):
    settings=Settings(mode='mock',database=tmp_path/'db',local_sources=tmp_path/'local',artifacts=tmp_path/'out',mock_delay=0,max_replans=0)
    store=Store(settings.database);run=ResearchRun(company_input='test',mode='mock',status='running',rules_version='1.1');store.save_run(run)
    facts,sources,evidence=map(list,zip(*materials)) if materials else ([],[],[])
    c={'company':COMPANY,'brief':{},'facts':facts,'sources':sources,'evidence':evidence,'required_data':[{'data_id':'revenue','company_id':'test','metric_code':'revenue','period':'2024A','unit':'CNY_million','segment_id':None,'priority':'critical','formula_dependency':['core'],'source_status':'missing'}], 'coverage':[],'plan':{'blocks':[]},'limitations':[]}
    workflow=ResearchWorkflow(settings,store,run.run_id)
    workflow.bind(c)
    return settings,store,run,c,workflow


async def test_gate_releases_without_calculation_then_selection_resolves(tmp_path):
    settings,store,run,c,w=setup(tmp_path,material('a'),material('b','120',False))
    c.update(await w.data_gaps(c))
    with pytest.raises(HumanInputRequired):await w.human_gate(c)
    assert not store.records(run.run_id,'calculation')
    issue=w.human.issues()[0]
    w.human.submit(issue['issue_id'],HumanFeedback(signature=issue['signature'],action='select',reason='采用合并年报原文',fact_id='a'))
    result=await w.human_gate(c)
    assert [f['fact_id'] for f in result['facts']]==['a']
    assert w.human.issues()[0]['status']=='resolved'
    assert len(result['fact_candidates'])==2
    assert store.records(run.run_id,'human_feedback')[0]['status']=='accepted'
    snapshot=capture_snapshot(store,run.run_id,settings.work_product_max_bytes)
    exported,_=export_snapshot(snapshot,'json',settings.work_product_max_bytes)
    assert b'human_feedback' in exported and b'human_resolution' in exported


async def test_bad_selection_does_not_turn_human_opinion_into_fact(tmp_path):
    _,store,run,c,w=setup(tmp_path,material('a',primary=False),material('b','120',False))
    c.update(await w.data_gaps(c))
    with pytest.raises(HumanInputRequired):await w.human_gate(c)
    issue=w.human.issues()[0]
    w.human.submit(issue['issue_id'],HumanFeedback(signature=issue['signature'],action='select',reason='我认为此值正确',fact_id='a'))
    with pytest.raises(HumanInputRequired):await w.human_gate(c)
    assert store.records(run.run_id,'human_feedback')[0]['status']=='rejected'
    assert '原始披露' in w.human.issues()[0]['feedback_error']
    assert not store.records(run.run_id,'human_resolution')


async def test_two_primary_disclosures_need_correction_even_with_human(tmp_path):
    _,_,_,c,w=setup(tmp_path,material('a'),material('b','120'))
    c.update(await w.data_gaps(c));w.human.refresh(c,final=True);issue=w.human.issues()[0]
    w.human.submit(issue['issue_id'],HumanFeedback(signature=issue['signature'],action='select',reason='第二个时间较新',fact_id='b'))
    with pytest.raises(HumanInputRequired):await w.human_gate(c)
    assert '更正前后' in w.human.issues()[0]['feedback_error']


async def test_missing_dependency_can_be_supplemented_from_original_source(tmp_path):
    _,store,run,c,w=setup(tmp_path)
    _,source,_=material('original')
    c['sources']=[source];w.bind(c)
    c.update(await w.data_gaps(c))
    with pytest.raises(HumanInputRequired):await w.human_gate(c)
    issue=w.human.issues()[0]
    body=HumanFeedback(signature=issue['signature'],action='supplement',reason='原文列示完整年度合并值',source_id=source['source_id'],quote=source['content'],locator='p1',value='100',unit='CNY_million')
    w.human.submit(issue['issue_id'],body)
    result=await w.human_gate(c)
    assert result['facts'][0]['value']=='100' and not result['missing']
    assert all(i['status']=='resolved' for i in w.human.issues())
    assert store.records(run.run_id,'fact')


async def test_fabricated_quote_is_rejected_and_optional_gaps_do_not_block(tmp_path):
    _,_,_,c,w=setup(tmp_path)
    _,source,_=material('original');c['sources']=[source];w.bind(c)
    c.update(await w.data_gaps(c));w.human.refresh(c,final=True);issue=w.human.issues()[0]
    w.human.submit(issue['issue_id'],HumanFeedback(signature=issue['signature'],action='supplement',reason='补充未公开值',source_id=source['source_id'],quote='伪造原文',locator='p1',value='100',unit='CNY_million'))
    with pytest.raises(HumanInputRequired):await w.human_gate(c)
    assert '原文' in w.human.issues()[0]['feedback_error']
    optional=copy.deepcopy(c);optional['required_data'][0].update(priority='normal',formula_dependency=[])
    # A separate input snapshot must not inherit old blocking requirements.
    assert await w.human_gate(optional)


def test_feedback_is_idempotent_and_new_candidates_invalidate_old_answer(tmp_path):
    _,store,run,c,w=setup(tmp_path,material('a'),material('b','120',False))
    w.human.refresh(c);issue=w.human.issues()[0]
    body=HumanFeedback(signature=issue['signature'],action='select',reason='采用原始年报',fact_id='a')
    assert w.human.submit(issue['issue_id'],body)==w.human.submit(issue['issue_id'],body)
    assert len(store.records(run.run_id,'human_feedback'))==1
    f,s,e=material('new','130',False)
    c['facts'].append(f);c['sources'].append(s);c['evidence'].append(e);w.human.refresh(c)
    with pytest.raises(FeedbackError,match='更新'):w.human.submit(issue['issue_id'],body)
    other=ResearchRun(company_input='test',mode='mock');store.save_run(other)
    with pytest.raises(FeedbackError,match='本任务'):HumanInterventionAgent(store,other.run_id).submit(issue['issue_id'],body)


async def test_conflict_published_before_slow_peer_finishes(tmp_path,monkeypatch):
    _,_,_,c,w=setup(tmp_path,material('a'))
    slow=asyncio.Event();tasks=[ResearchTask(task_id=k,company_id='test',role='financial',topic=k,queries=[k]).model_dump(mode='json') for k in ('fast','slow')]
    class Subgraph:
        async def ainvoke(self,state,config):
            if state['task']['task_id']=='slow':
                await slow.wait()
                return state
            f,s,e=material('b','120',False)
            return state|{'facts':[f],'sources':[s],'evidence':[e]}
    monkeypatch.setattr('company_research.graphs.researcher_graph',lambda *a,**kw:Subgraph())
    c.update(pending=['fast','slow'],summaries=[],plan={'tasks':tasks,'blocks':[]})
    work=asyncio.create_task(w.supervisor(c))
    try:
        for _ in range(100):
            if w.human.issues():break
            await asyncio.sleep(.01)
        assert w.human.issues() and not work.done()
    finally:
        slow.set()
        await asyncio.wait_for(work,5)


async def test_runner_waits_and_resumes_same_graph_without_recollecting(tmp_path,monkeypatch):
    original=ResearchWorkflow.supervisor;calls=0
    async def inject(self,c):
        nonlocal calls
        calls+=1;result=await original(self,c)
        target=next(f for f in result['facts'] if f['metric_code']=='revenue' and f['scope']=='consolidated' and f['period']==max(c['brief']['historical_periods']))
        for key,delta,primary in [('human-primary',0,True),('human-secondary',1,False)]:
            value=str(Decimal(target['value'])+delta)
            quote=f"{c['company']['name']} {target['period'][:4]}年度 合并 营业收入 {value}百万元。"
            source=SourceRecord(source_id='s'+key,kind='web',title=c['company']['name'],content=quote,source_url=('https://cninfo.com.cn/' if primary else 'https://news.example/')+key).model_dump(mode='json')
            ev={'evidence_id':'e'+key,'source_id':source['source_id'],'claim':quote,'quote':quote,'locator':'p1','actual_or_forecast':'actual','validation_status':'verified'}
            fact=target|{'fact_id':key,'source_id':source['source_id'],'evidence_id':ev['evidence_id'],'value':value}
            result['facts'].append(fact);result['sources'].append(source);result['evidence'].append(ev)
        self.bind(result);return result
    monkeypatch.setattr(ResearchWorkflow,'supervisor',inject)
    settings=Settings(mode='mock',database=tmp_path/'db',local_sources=tmp_path/'local',artifacts=tmp_path/'out',mock_delay=0,max_replans=0)
    store=Store(settings.database);run=ResearchRun(company_input='test',mode='mock');store.save_run(run)
    runner=Runner(settings,store);await runner.run(run.run_id)
    assert store.run(run.run_id).status=='waiting_human',store.run(run.run_id).error
    assert not store.records(run.run_id,'calculation')
    agent=HumanInterventionAgent(store,run.run_id);issue=next(i for i in agent.issues() if any(v['fact_id']=='human-primary' for v in i['candidates']))
    agent.submit(issue['issue_id'],HumanFeedback(signature=issue['signature'],action='select',reason='采用合并年报原始值',fact_id='human-primary'))
    await runner.run(run.run_id)
    assert store.run(run.run_id).status=='limited',store.run(run.run_id).error
    assert calls==1 and store.records(run.run_id,'calculation')


async def test_api_feedback_preserves_pause_and_checks_task_scope(tmp_path):
    settings,store,run,c,w=setup(tmp_path,material('a'),material('b','120',False))
    app=create_app(settings);store=app.state.store
    store.execution_put(run.run_id,'execution_meta','service-session',{'session_id':store.service_session_id})
    w.human.refresh(c);issue=w.human.issues()[0]
    store.transition_run(run.run_id,{'running'},status='interrupted')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=(await client.get(f'/api/research/{run.run_id}/human-intervention')).json()
        assert result['can_submit'] and result['issues'][0]['candidates'][0]['quote']
        body={'signature':issue['signature'],'action':'select','fact_id':'a','reason':'原始合并年报'}
        reply=await client.post(f'/api/research/{run.run_id}/human-intervention/{issue["issue_id"]}',json=body)
        assert reply.status_code==202 and not reply.json()['resumed']
        assert store.run(run.run_id).status=='interrupted'
        bad=await client.post(f'/api/research/{run.run_id}/human-intervention/unknown',json=body)
        assert bad.status_code==409
        report=await client.get(f'/api/research/{run.run_id}/report')
        assert report.status_code==409


async def test_directed_research_can_repair_data_and_is_not_repeated(tmp_path,monkeypatch):
    _,store,run,c,w=setup(tmp_path,material('a',primary=False),material('b','120',False))
    c.update(await w.data_gaps(c))
    with pytest.raises(HumanInputRequired):await w.human_gate(c)
    issue=w.human.issues()[0];calls=[]
    class Subgraph:
        async def ainvoke(self,state,config):
            calls.append(state['queries'])
            f,s,e=material('primary')
            return state|{'facts':[f],'sources':[s],'evidence':[e]}
    monkeypatch.setattr('company_research.graphs.researcher_graph',lambda *a,**kw:Subgraph())
    w.human.submit(issue['issue_id'],HumanFeedback(signature=issue['signature'],action='research',reason='补查年度合并原文',query='测试股份 2024 年报 收入'))
    result=await w.human_gate(c)
    assert [f['fact_id'] for f in result['facts']]==['primary']
    assert len(calls)==1 and store.records(run.run_id,'fact_verification')
    assert (await w.human_gate(c))['facts']==result['facts']
    assert len(calls)==1


async def test_partial_repairs_survive_second_wait_and_new_candidate_reopens(tmp_path):
    _,store,run,c,w=setup(tmp_path,material('a'),material('b','120',False))
    requirement=c['required_data'][0]|{'data_id':'second','period':'2023A'}
    c['required_data'].append(requirement)
    c.update(await w.data_gaps(c))
    with pytest.raises(HumanInputRequired):await w.human_gate(c)
    issue=next(i for i in w.human.issues() if i['kind']=='conflict')
    w.human.submit(issue['issue_id'],HumanFeedback(signature=issue['signature'],action='select',reason='合并年报确认',fact_id='a'))
    with pytest.raises(HumanInputRequired):await w.human_gate(c)
    repaired=store.execution_get(run.run_id,'execution_meta','human-context')['context']
    assert [f['fact_id'] for f in repaired['facts']]==['a']
    with pytest.raises(HumanInputRequired):await w.human_gate(c)
    assert store.execution_get(run.run_id,'execution_meta','human-context')['context']['facts']==repaired['facts']
    f,s,e=material('new','140')
    repaired['fact_candidates'].append(f);repaired['sources'].append(s);repaired['evidence'].append(e)
    repaired.update(await w.data_gaps(repaired))
    with pytest.raises(HumanInputRequired):await w.human_gate(repaired)
    reopened=next(i for i in w.human.issues() if i['kind']=='conflict')
    assert reopened['signature']!=issue['signature'] and reopened['status']=='open'
    assert not repaired['facts']


async def test_waiting_feedback_automatically_schedules_same_run_and_admission_is_read_only(tmp_path,monkeypatch):
    settings,_,run,c,w=setup(tmp_path,material('a'),material('b','120',False))
    app=create_app(settings);store=app.state.store
    store.execution_put(run.run_id,'execution_meta','service-session',{'session_id':store.service_session_id})
    w.human.refresh(c);issue=w.human.issues()[0]
    store.transition_run(run.run_id,{'running'},status='waiting_human')
    scheduled=[]
    async def fake_run(run_id):scheduled.append(run_id)
    monkeypatch.setattr(app.state.runner,'run',fake_run)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        reply=await client.post(f'/api/research/{run.run_id}/human-intervention/{issue["issue_id"]}',json={'signature':issue['signature'],'action':'select','fact_id':'a','reason':'采用合并原始年报'})
        assert reply.status_code==202 and reply.json()['resumed']
        await asyncio.sleep(0)
        assert scheduled==[run.run_id]
        store.transition_run(run.run_id,{'queued'},status='running')
        store.execution_put(run.run_id,'execution_meta','human-admitted',{'admitted':True})
        assert not (await client.get(f'/api/research/{run.run_id}/human-intervention')).json()['can_submit']
        rejected=await client.post(f'/api/research/{run.run_id}/human-intervention/{issue["issue_id"]}',json={'signature':issue['signature'],'action':'research','query':'new query','reason':'重新收集原始年报'})
        assert rejected.status_code==409


def test_waiting_runs_are_startup_candidates_and_unsupported_basis_cannot_be_invented(tmp_path):
    from company_research.startup import latest_unfinished
    _,store,run,c,w=setup(tmp_path,material('a'))
    store.transition_run(run.run_id,{'running'},status='waiting_human')
    assert latest_unfinished(store).run_id==run.run_id
    bad=c['facts'][0]|{'accounting_basis':'adjusted'}
    with pytest.raises(FeedbackError,match='口径'):
        w.human.validate_selection(bad,c['facts'],c['sources'],c['evidence'],COMPANY,'我认为是调整后值')


def test_numeric_correction_does_not_enter_unrelated_block_contexts():
    from company_research.contexts import block_context
    f,s,e=material('segment');f.update(segment_id='设备',scope='segment')
    e['quote']='测试股份有限公司 2024年度 设备 营业收入100百万元。'
    c={'company':COMPANY|{'source_ids':[]},'brief':{'historical_periods':['2024A'],'forecast_periods':['2025E']},
       'plan':{'blocks':[{'block_id':k,'template_id':template,'segment_id':segment,'dependencies':[],'questions':{'q':'设备收入与业务'}} for k,template,segment in [('F01','F01',None),('I01-0','I01','设备'),('B01-1','B01','服务'),('F04','F04',None)]]},
       'facts':[],'fact_candidates':[],'sources':[],'evidence':[],'coverage':[]}
    changed=c|{'facts':[f],'fact_candidates':[f],'sources':[s],'evidence':[e]}
    for block in ['F01','I01-0','B01-1']:
        assert block_context(c,block,'analysis').snapshot_id==block_context(changed,block,'analysis').snapshot_id
    assert block_context(c,'F04','analysis').snapshot_id!=block_context(changed,'F04','analysis').snapshot_id


async def test_invalid_manual_unit_is_rejected_without_stopping_other_repairs(tmp_path):
    _,store,run,c,w=setup(tmp_path)
    _,source,_=material('original');c['sources']=[source];w.bind(c)
    c.update(await w.data_gaps(c));w.human.refresh(c,final=True);issue=w.human.issues()[0]
    w.human.submit(issue['issue_id'],HumanFeedback(signature=issue['signature'],action='supplement',reason='原文单位待核对',source_id=source['source_id'],quote=source['content'],locator='p1',value='100',unit='unsupported-unit'))
    with pytest.raises(HumanInputRequired):await w.human_gate(c)
    assert store.records(run.run_id,'human_feedback')[0]['status']=='rejected'
    assert not store.records(run.run_id,'human_resolution')


def test_compatible_real_progress_is_retained_but_dirty_advanced_checkpoint_is_rejected(tmp_path):
    from company_research.execution import ensure_manifest, manifest, RecoveryError
    settings,store,run,c,_=setup(tmp_path,material('a'))
    run.mode='real';store.save_run(run)
    old=manifest(settings,mode='real');old.pop('human_intervention')
    store.execution_put(run.run_id,'execution_meta','manifest',old)
    store.checkpoint(run.run_id,'data_gaps',c)
    ensure_manifest(settings,store,run.run_id)
    assert store.execution_get(run.run_id,'execution_meta','manifest')['human_intervention']=='human-data-1'
    # An old run already beyond the gate may migrate only with proven clean inputs.
    store.execution_put(run.run_id,'execution_meta','manifest',old)
    store.checkpoint(run.run_id,'write_sections',c|{'fact_decisions':[]})
    with pytest.raises(RecoveryError):ensure_manifest(settings,store,run.run_id)
    c['required_data'][0]['source_status']='found'
    store.checkpoint(run.run_id,'write_sections',c|{'fact_decisions':[]})
    ensure_manifest(settings,store,run.run_id)
