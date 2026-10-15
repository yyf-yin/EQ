"""Qualitative collection contracts with offline search/model fixtures."""
import json
from types import SimpleNamespace

import pytest

from company_research.config import Settings
from company_research.contexts import block_context
from company_research.datasources import DatasourceError
from company_research.framework import digest
from company_research.material_collection import (MaterialCollector, MaterialDirectionPlan,
    MaterialAssessment, DirectionFinding, PRESETS)
from company_research.schemas import ResearchRun, ResearchTask, EvidenceRecord, SourceRecord
from company_research.storage import Store


class ScriptGateway:
    def __init__(self, handler, input_capacity=100000):
        self.handler, self.calls = handler, []
        self.input_capacity=input_capacity

    def limits(self, role):
        return SimpleNamespace(input_capacity=self.input_capacity)

    async def structured(self, role, messages, schema):
        context = json.loads(messages[-1]['content'])
        self.calls.append((schema.__name__, context))
        return self.handler(schema, context)


def default_handler(schema, context):
    if schema is MaterialDirectionPlan:
        return MaterialDirectionPlan()
    ids = [e['evidence_id'] for e in context['evidence']]
    return MaterialAssessment(sufficient=True, direction_findings={
        d['direction_id']:DirectionFinding(status='found' if d['required'] else 'not_found',
            evidence_ids=ids if d['required'] else [], reason='适用经营机制' if d['required'] else '暂无证据')
        for d in context['directions']})


async def setup(tmp_path, handler=default_handler, input_capacity=100000, task_count=1, **options):
    settings = Settings(_env_file=None, database=tmp_path/'material.sqlite', search_url='https://fixture.invalid', **options)
    store = Store(settings.database)
    run = ResearchRun(company_input='测试公司', mode='real', created_at='2026-10-14T00:00:00+00:00')
    store.save_run(run)
    gateway = ScriptGateway(handler,input_capacity)
    requests, reads = [], []
    async def retrieve(query):
        requests.append(query)
        return [], []
    w = SimpleNamespace(settings=settings, store=store, run_id=run.run_id, gateway=gateway,
                        datasource=SimpleNamespace(web=True, retrieve=retrieve))
    async def extract(c, source, quantitative):
        assert not quantitative
        reads.append(source.source_id)
        store.record(run.run_id, 'source', source.source_id, source.model_dump(mode='json'))
        e = EvidenceRecord(evidence_id='ev-'+digest(source.content)[:16], source_id=source.source_id,
            quote=source.content, claim=source.title, locator=source.locator, validation_status='verified')
        store.record(run.run_id, 'evidence', e.evidence_id, e.model_dump(mode='json'))
    fixed = SimpleNamespace(w=w, store=store, run_id=run.run_id, extract_document=extract,
        facts=lambda c:[], load_bound=lambda c:dict(facts=[], sources=store.records(run.run_id,'source'), evidence=store.records(run.run_id,'evidence')))
    collector = MaterialCollector(fixed)
    task = ResearchTask(task_id='industry', company_id='TEST', topic='行业资料：制造业', role='business',
        segment_id='设备', linked_segments=['设备','服务'], block_id='I01:设备', question_ids=['q'], queries=['旧查询'])
    store.record(run.run_id, 'collection_slot', task.task_id, dict(slot_id=task.task_id, topic=task.topic,
        block_id=task.block_id, state='pending', source_ids=[], evidence_ids=[], limitations=[], search_count=0))
    c = dict(company={'company_id':'TEST','name':'测试公司','source_ids':[]},
        brief={'company_id':'TEST','scope':'制造业务','historical_periods':['2023A','2024A','2025A'],
            'forecast_periods':['2026E'],'segments':['设备','服务'],'industries':{'设备':'制造业','服务':'制造业'}},
        sources=[], material_source_ids=[], facts=[], evidence=[], limitations=[],
        plan={'tasks':[], 'blocks':[dict(block_id=task.block_id, template_id='I01', segment_id='设备', dependencies=[], questions={'q':'产业链'})]})
    tasks=[task]
    for i in range(1,task_count):
        extra=task.model_copy(update={'task_id':f'industry-{i}','topic':f'行业资料：制造细分市场{i}'})
        tasks.append(extra)
        slot=collector.slot(task.model_dump()).copy()
        slot.update(slot_id=extra.task_id,topic=extra.topic)
        store.record(run.run_id,'collection_slot',extra.task_id,slot)
    await collector.configure(c, tasks)
    c['plan']['tasks'] = [t.model_dump(mode='json') for t in tasks]
    return collector, c, task.model_dump(mode='json'), requests, reads, gateway


def add_source(collector, c, text, source_id='existing', title='制造业行业报告'):
    source = SourceRecord(source_id=source_id, kind='upload', title=title, content=text, publication_date='2025-12-31')
    c['sources'].append(source.model_dump(mode='json'))
    c['material_source_ids'].append(source_id)
    return source


async def test_neutral_presets_and_bounded_model_extras_are_frozen(tmp_path):
    def handler(schema, context):
        if schema is MaterialDirectionPlan:
            return schema.model_validate({'slots':[{'slot_id':'industry','directions':[
                {'label':'贸易规则与海外布局','description':'贸易条件及海外经营范围','reason':'设备业务涉及海外市场'},
                {'label':'近期利好政策','description':'证明政策推动增长','reason':'有增长机会'},
                {'label':'新产品能否成为增长点','description':'分析增长','reason':'新产品'},
                {'label':'证券代码与股价','description':'股票基础资料','reason':'识别证券'},
                {'label':'资源条件','description':'资源基础','reason':'行业特性'},
                {'label':'产品生态','description':'上下游兼容与生态','reason':'应用特性'}]}]})
        return default_handler(schema, context)
    collector,c,task,_,_,gateway = await setup(tmp_path,handler,material_extra_direction_limit=2)
    slot = collector.slot(task)
    labels = [d['label'] for d in slot['directions']]
    assert {'政策与监管变化','市场规模与结构','贸易规则与海外布局','资源条件'} <= set(labels)
    assert '近期利好政策' not in labels and '产品生态' not in labels and '证券代码与股价' not in labels
    assert len(slot['directions']) == len(PRESETS['industry'])+2
    assert slot['scope']['policy_start_date'] == '2023-10-14'
    assert slot['scope']['linked_segments'] == ['设备','服务']
    before = len(gateway.calls)
    add_source(collector,c,'制造业出现新的设备应用')
    await collector.configure(c,[ResearchTask.model_validate(task)])
    assert len(gateway.calls) == before


async def test_optional_gaps_can_deliver_ready_packet_without_false_no_change(tmp_path):
    collector,c,task,requests,_,_ = await setup(tmp_path)
    add_source(collector,c,'制造业的设备需求与供给、市场参与者和产业链范围。')
    result = await collector.collect(c)
    slot = collector.slot(task)
    assert slot['state'] == 'ready'
    assert slot['direction_statuses']['policy']['status'] == 'not_found'
    assert '不代表不存在或无变化' in slot['direction_statuses']['policy']['reason']
    assert slot['direction_statuses']['market']['status'] == 'not_found'
    assert 1 <= len(requests) <= collector.settings.material_search_budget
    assert result['material_collections'][0]['limitations']
    assert not result['facts']


async def test_no_search_is_pending_not_not_found(tmp_path):
    collector,c,task,requests,_,_ = await setup(tmp_path, material_search_budget=0)
    add_source(collector,c,'制造业设备需求和产业链。')
    await collector.collect(c)
    slot = collector.slot(task)
    assert slot['direction_statuses']['policy']['status'] == 'pending'
    assert slot['stop_reason'] == 'search_budget' and not requests


async def test_policy_no_change_requires_real_quote_and_known_evidence(tmp_path):
    def handler(schema, context):
        if schema is MaterialDirectionPlan:return schema()
        output = default_handler(schema, context)
        output.direction_findings['policy'] = DirectionFinding(status='no_change',
            evidence_ids=[context['evidence'][0]['evidence_id']], reason='仅限设备许可规则在披露期间')
        output.direction_findings['market'] = DirectionFinding(status='found', evidence_ids=['invented'])
        return output
    collector,c,task,_,_,_ = await setup(tmp_path,handler)
    source = add_source(collector,c,'制造业设备业务适用政策，不能说明政策是否改变。')
    await collector.fixed.extract_document(c,source,False)
    await collector.assess(c,task)
    assert collector.slot(task)['direction_statuses']['policy']['status'] == 'partial'
    assert collector.slot(task)['direction_statuses']['market']['status'] == 'pending'
    source = add_source(collector,c,'制造业设备许可规则在2025年维持不变。','unchanged')
    await collector.fixed.extract_document(c,source,False)
    await collector.assess(c,task)
    assert collector.slot(task)['direction_statuses']['policy']['status'] == 'no_change'


async def test_transport_failure_never_becomes_no_information(tmp_path):
    collector,c,task,_,_,_ = await setup(tmp_path)
    async def failed(query):raise DatasourceError('搜索服务请求失败')
    collector.w.datasource.retrieve = failed
    await collector.collect(c)
    slot = collector.slot(task)
    assert slot['state'] == 'limited'
    assert slot['search_count'] <= 3
    assert all(v['status']=='retrieval_failed' for v in slot['direction_statuses'].values())
    assert slot['search_history'][0]['warnings'] == ['搜索服务请求失败']


async def test_incremental_evidence_and_irrelevant_material_filter(tmp_path):
    collector,c,task,_,_,gateway = await setup(tmp_path)
    good = add_source(collector,c,'制造业设备供需和竞争范围。')
    unrelated = add_source(collector,c,'互联网游戏用户规模和付费渠道。','unrelated',title='游戏行业报告')
    await collector.fixed.extract_document(c,good,False)
    await collector.fixed.extract_document(c,unrelated,False)
    await collector.assess(c,task)
    sent = [context for name,context in gateway.calls if name=='MaterialAssessment']
    assert len(sent)==1 and all(e['source_id']=='existing' for e in sent[0]['evidence'])
    assert sent[0]['evidence'][0]['publication_date']=='2025-12-31'
    before = len(gateway.calls)
    await collector.assess(c,task)
    assert len(gateway.calls)==before
    source = add_source(collector,c,'制造业设备下游应用变化。','new')
    await collector.fixed.extract_document(c,source,False)
    await collector.assess(c,task)
    sent = [context for name,context in gateway.calls if name=='MaterialAssessment']
    assert len(sent)==2 and [e['source_id'] for e in sent[1]['evidence']]==['new']


async def test_grouped_supplement_closes_gaps_and_terminal_replay(tmp_path):
    def handler(schema, context):
        if schema is MaterialDirectionPlan:return schema()
        ids = [e['evidence_id'] for e in context['evidence']]
        return MaterialAssessment(sufficient=True, direction_findings={d['direction_id']:DirectionFinding(
            status='found', evidence_ids=ids, reason='适用行业资料') for d in context['directions']})
    collector,c,task,requests,reads,gateway = await setup(tmp_path,handler)
    async def retrieve(query):
        requests.append(query)
        if len(requests)==1:return [],[]
        return [SourceRecord(source_id='external',kind='web',title='制造业综合资料',content='制造业供需、竞争与政策资料。')],[]
    collector.w.datasource.retrieve=retrieve
    result = await collector.collect(c)
    slot = collector.slot(task)
    assert slot['state']=='ready' and len(requests)==2 and reads==['external']
    assert set(slot['search_history'][0]['direction_ids'])=={d['direction_id'] for d in slot['directions']}
    assert len(slot['search_history'][1]['direction_ids'])==3
    assert slot['stop_reason']=='coverage_complete'
    calls=len(gateway.calls)
    await collector.collect(result | {'plan':c['plan'],'company':c['company'],'brief':c['brief']})
    assert len(gateway.calls)==calls and len(requests)==2 and reads==['external']


async def test_search_interruption_reuses_saved_search_and_reads_result(tmp_path,monkeypatch):
    collector,c,task,requests,reads,_ = await setup(tmp_path)
    async def retrieve(query):
        requests.append(query)
        return [SourceRecord(source_id='web',kind='web',title='制造业资料',content='制造业设备供需与产业链。')],[]
    collector.w.datasource.retrieve=retrieve
    original=collector.process_search
    async def interrupted(*args):raise RuntimeError('interrupted before document reading')
    monkeypatch.setattr(collector,'process_search',interrupted)
    with pytest.raises(RuntimeError):await collector.collect(c)
    assert len(requests)==1 and not reads
    monkeypatch.setattr(collector,'process_search',original)
    await collector.collect(c)
    assert len(set(requests))==len(requests) and reads==['web']
    assert collector.slot(task)['search_history'][0]['processed']


async def test_mirrored_document_extracted_once_and_not_applicable_requires_reason(tmp_path):
    def handler(schema, context):
        if schema is MaterialDirectionPlan:return schema()
        output=default_handler(schema,context)
        output.direction_findings['policy']=DirectionFinding(status='not_applicable',reason='')
        output.direction_findings['technology']=DirectionFinding(status='not_applicable',reason='该资料范围未涉及技术产品')
        return output
    collector,c,task,_,reads,_=await setup(tmp_path,handler)
    a=SourceRecord(source_id='a',kind='web',title='制造业资料',content='制造业 设备供需与产业链。')
    b=SourceRecord(source_id='b',kind='web',title='制造业转载',content='制造业\n设备供需与产业链。')
    await collector.read_sources(c,task,[a,b])
    assert len(reads)==1
    assert collector.slot(task)['direction_statuses']['policy']['status']=='pending'
    assert collector.slot(task)['direction_statuses']['technology']['status']=='not_applicable'


async def test_analysis_receives_shared_industry_gaps_and_snapshot_tracks_them(tmp_path):
    collector,c,task,_,_,_=await setup(tmp_path,material_search_budget=0)
    add_source(collector,c,'制造业设备的产业链机制。')
    result=await collector.collect(c)
    c.update(result)
    package=block_context(c,task['block_id'],'analysis')
    assert package.content['material_collections'][0]['direction_statuses']['market']['status']=='pending'
    first=package.snapshot_id
    c['material_collections'][0]['direction_statuses']['market']['reason']='统计范围存在缺口'
    assert block_context(c,task['block_id'],'analysis').snapshot_id!=first
    c['plan']['blocks'].append(dict(block_id='I01:服务',template_id='I01',segment_id='服务',dependencies=[],questions={}))
    assert block_context(c,'I01:服务','analysis').content['material_collections']


async def test_many_slots_plan_within_real_researcher_capacity(tmp_path):
    from company_research.agents import request_messages
    from company_research.contexts import estimate_tokens
    collector,c,task,_,_,gateway=await setup(tmp_path,input_capacity=7000,task_count=12)
    calls=[v for name,v in gateway.calls if name=='MaterialDirectionPlan']
    assert len(calls)>1
    assert {s['slot_id'] for v in calls for s in v['slots']}=={t['task_id'] for t in c['plan']['tasks']}
    assert all(estimate_tokens(request_messages('researcher',v))+estimate_tokens(MaterialDirectionPlan.model_json_schema())+1000<=7000 for v in calls)


async def test_large_excerpt_does_not_hide_other_evidence_or_reextract(tmp_path):
    collector,c,task,_,_,gateway=await setup(tmp_path,input_capacity=20000)
    large=add_source(collector,c,'制造业设备需求与供给。'+('详细资料。'*10000),'large')
    small=add_source(collector,c,'制造业设备竞争格局。','small')
    await collector.fixed.extract_document(c,large,False)
    await collector.fixed.extract_document(c,small,False)
    await collector.assess(c,task)
    calls=[v for name,v in gateway.calls if name=='MaterialAssessment']
    assert {e['source_id'] for v in calls for e in v['evidence']}=={'large','small'}
    assert any(e.get('excerpt_truncated') for v in calls for e in v['evidence'])
    assert any(len(e['quote'])>50000 for e in collector.store.records(collector.run_id,'evidence'))
    before=len(gateway.calls)
    await collector.assess(c,task)
    assert len(gateway.calls)==before


async def test_future_dated_material_is_excluded_and_document_budget_is_bounded(tmp_path):
    collector,c,task,requests,reads,_=await setup(tmp_path,material_document_budget=1)
    future=add_source(collector,c,'制造业设备未来资料','future')
    future.publication_date='2027-01-01'
    c['sources'][0]=future.model_dump(mode='json')
    add_source(collector,c,'制造业设备现有资料','valid')
    add_source(collector,c,'制造业设备第二份资料','second')
    await collector.collect(c)
    assert len(reads)==1 and 'future' not in reads and not requests
    assert collector.slot(task)['stop_reason']=='document_budget'


async def test_public_collection_export_omits_internal_search_receipts(tmp_path):
    from company_research.work_products import FIELDS,project
    collector,c,task,_,_,_=await setup(tmp_path,material_search_budget=1)
    await collector.collect(c)
    public=project(collector.slot(task),FIELDS['collection_slot'])
    assert public['search_count']==1 and public['direction_statuses']['policy']['status']=='not_found'
    assert 'before_coverage' not in public['search_history'][0] and 'processed' not in public['search_history'][0]
    assert public['search_history'][0]['direction_ids'] and public['scope']['as_of']=='2026-10-14'


async def test_failed_extraction_without_search_is_not_missing_information(tmp_path):
    from company_research.fixed_collection import VERSION,periods
    collector,c,task,requests,_,_=await setup(tmp_path,material_search_budget=0)
    source=add_source(collector,c,'制造业设备扫描资料不可提取','broken')
    async def failed_extract(c,source,quantitative):
        collector.store.record(collector.run_id,'source',source.source_id,source.model_dump(mode='json'))
        key='document-'+digest([VERSION,digest(source.content),c['company']['company_id'],periods(c['brief']),c['brief']['segments']])[:24]
        collector.store.execution_put(collector.run_id,'execution_meta',key,dict(state='failed',source_id=source.source_id))
    collector.fixed.extract_document=failed_extract
    await collector.collect(c)
    assert not requests
    assert all(v['status']=='retrieval_failed' for v in collector.slot(task)['direction_statuses'].values())
    assert any('提取失败' in v for v in collector.slot(task)['limitations'])


async def test_new_counter_evidence_can_reduce_adequacy_without_losing_old_refs(tmp_path):
    def handler(schema,context):
        if schema is MaterialDirectionPlan:return schema()
        if any('口径冲突' in e['quote'] for e in context['evidence']):
            return MaterialAssessment(sufficient=False,direction_findings={'boundary':DirectionFinding(
                status='partial',evidence_ids=[e['evidence_id'] for e in context['evidence']],reason='新增资料显示统计范围存在口径冲突')},
                limitations=['行业边界证据存在冲突，不能认定资料足量'])
        return default_handler(schema,context)
    collector,c,task,_,_,_=await setup(tmp_path,handler)
    original=add_source(collector,c,'制造业设备供需和产业链范围。')
    await collector.fixed.extract_document(c,original,False)
    assert (await collector.assess(c,task)).sufficient
    old=set(collector.slot(task)['direction_statuses']['boundary']['evidence_ids'])
    counter=add_source(collector,c,'制造业新资料说明行业口径冲突，市场范围不能混用。','counter')
    await collector.fixed.extract_document(c,counter,False)
    assert not (await collector.assess(c,task)).sufficient
    finding=collector.slot(task)['direction_statuses']['boundary']
    assert finding['status']=='partial' and old<set(finding['evidence_ids'])
