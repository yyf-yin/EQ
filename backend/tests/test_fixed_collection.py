import copy
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from company_research.config import Settings
from company_research.fixed_collection import FIELDS, VERSION, SlotProposal, SlotAbsence, SlotExtraction, MaterialAssessment, annual_source
from company_research.material_collection import MaterialDirectionPlan
from company_research.graphs import ResearchWorkflow
from company_research.framework import validate_plan, skeleton
from company_research.financials.formulas import FinancialError
from company_research.reconciliation import reconcile
from company_research.schemas import ResearchRun, ResearchPlan, ResearchBrief, SourceRecord
from company_research.storage import Store
from company_research.references import prepare_uploads,register_upload,create_with_attachments


class Gateway:
    def __init__(self):
        self.calls=[]
        self.values=[]
        self.sufficient=True
        self.concurrency=3

    def attach_store(self,store,run_id):
        self.store,self.run_id=store,run_id

    def limits(self,role):
        return SimpleNamespace(input_capacity=100000,max_output_tokens=16000)

    async def structured(self,role,messages,schema):
        context=json.loads(messages[-1]['content']);self.calls.append((schema.__name__,context))
        if schema is MaterialDirectionPlan:
            return MaterialDirectionPlan()
        if schema is SlotExtraction:
            source=context['sources'][0]
            values=self.values if context['quantitative_allowed'] else []
            return SlotExtraction.model_validate({'values':values,'evidence':[{'source_id':source['source_id'],
                'quote':source['content'],'claim':'公司设备与服务业务及制造业需求竞争，实际经营资料','actual_or_forecast':'context'}]})
        if schema is MaterialAssessment:
            evidence=[e['evidence_id'] for e in context['evidence']]
            return MaterialAssessment(sufficient=self.sufficient,covered_dimensions={d:evidence for d in context['dimensions']} if self.sufficient else {},
                limitations=[] if self.sufficient else ['缺少足量经营和行业资料'])
        raise AssertionError('unexpected model role/schema: '+schema.__name__)


def prepared(tmp_path,rows=None):
    default_rows=rows is None
    local=tmp_path/'local';local.mkdir()
    security={'company_id':'FIX','company_name':'固定测试公司','ticker':'000123','exchange':'SZSE','security_type':'stock',
              'price':'10','quote_date':'2026-10-13','shares':'20','shares_unit':'million_shares','shares_effective_date':'2026-01-01',
              'quote_currency':'CNY','multi_class_listing':False}
    (local/'security.json').write_text(json.dumps(security,ensure_ascii=False),encoding='utf-8')
    (local/'company.md').write_text('固定测试公司经营设备与服务。设备用于制造客户，服务面向存量设备。制造业行业需求与竞争变化需要结合实际订单分析。公司治理与股权情况、风险机制和重大证据缺口均需保留限制；资料不证明未来增长。',encoding='utf-8')
    if rows is None:
        rows=[{'company_id':'FIX','document_type':'annual_report','field_id':field,'period':p,'unit':'CNY_million',
               'value':str(value),'scope':'consolidated'} for p in ['2022A','2023A','2024A','2025A']
              for field,value in [('income.revenue',100),('income.cost',60),('income.parent_net_income',20),
                                  ('income.adjusted_parent_net_income',18),('cashflow.operating_cashflow',25)]]
    if rows:(local/'annual.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
    settings=Settings(_env_file=None,mode='real',database=tmp_path/'db.sqlite',local_sources=local,
                      artifacts=tmp_path/'out',mock_delay=0,search_url='')
    store=Store(settings.database);run=ResearchRun(company_input='000123',mode='real',created_at='2026-10-15T00:00:00+00:00')
    if rows:
        prepare_uploads(store)
        annual=register_upload(store,'annual.json',json.dumps([
            {'company_name':'固定测试公司','ticker':'000123', **row} for row in rows
        ],ensure_ascii=False).encode('utf-8'))
        note=register_upload(store,'固定测试公司2025年年度报告.txt',('固定测试公司2025年年度报告\n'+(local/'company.md').read_text(encoding='utf-8')).encode('utf-8'))
        attachments=[annual['attachment_id'],note['attachment_id']]
        if default_rows:
            interim_rows=[{'company_id':'FIX','document_type':'interim_report','report_period':'2026H1','field_id':field,'period':p,
                'unit':'CNY_million','value':str(value),'scope':'consolidated'} for p in ['2025H1','2026H1']
                for field,value in [('income.revenue',100),('income.cost',60),('income.parent_net_income',20),
                                    ('income.adjusted_parent_net_income',18),('cashflow.operating_cashflow',25)]]
            interim=register_upload(store,'interim.json',json.dumps(interim_rows,ensure_ascii=False).encode('utf-8'))
            attachments.append(interim['attachment_id'])
        create_with_attachments(store,run,attachments,50)
    else:store.save_run(run)
    gateway=Gateway();workflow=ResearchWorkflow(settings,store,run.run_id,gateway)
    return workflow,gateway,store,run


async def context(workflow):
    c={'input':'000123','run_id':workflow.run_id,'replans':0,'revisions':0}
    c.update(await workflow.resolve_company(c))
    c['brief']={'company_id':'FIX','scope':'固定表测试','historical_periods':['2023A','2024A','2025A'],
        'forecast_periods':['2026E','2027E','2028E'],'segments':['设备','服务'],'industries':{'设备':'制造业','服务':'制造业'}}
    return c


async def test_fixed_plan_imports_annual_inputs_without_financial_search_or_planner(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    c.update(await w.research_plan(c));c.update(await w.calculation_plan(c));c.update(await w.dependencies(c))
    assert len(FIELDS)==133
    slots=store.records(run.run_id,'data_slot')
    assert len(slots)==15+(26+39+20+10+10*2)*38
    assert sum(s['state']=='locked' and s['requirement']=='C' for s in slots)==30
    assert all(s['raw_value']=='100' for s in slots if s['field_id']=='income.revenue' and s['state']=='locked')
    assert not [t for t in c['plan']['tasks'] if t['role']=='financial']
    assert len(c['plan']['tasks'])==4  # company, two businesses, one shared industry
    brief=ResearchBrief.model_validate(c['brief'])
    assert not validate_plan(ResearchPlan.model_validate(c['plan']),brief,skeleton(brief,w.settings.block_call_budget))
    assert all(name not in {'ResearchPlan','CalculationPlan','Company'} for name,_ in g.calls)
    c.update(await w.supervisor(c));c.update(await w.data_gaps(c))
    assert not c['missing_questions']
    assert not [d for d in c['missing'] if d['priority']=='critical']
    assert not w.human.refresh(c,final=True)
    await w.human_gate(c)


async def test_replay_and_review_do_not_reextract_or_reopen_material_slots(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    c.update(await w.research_plan(c));c.update(await w.supervisor(c))
    before=len(g.calls);accepted=copy.deepcopy(store.records(run.run_id,'data_slot'))
    c.update(await w.research_plan(c));c.update(await w.supervisor(c))
    assert len(g.calls)==before
    assert accepted==store.records(run.run_id,'data_slot')
    assert all(s['state']=='ready' for s in store.records(run.run_id,'collection_slot'))


async def test_lower_priority_value_cannot_replace_locked_annual_or_create_human_issue(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w);c.update(await w.research_plan(c))
    original=next(f for f in c['facts'] if f['metric_code']=='revenue' and f['period']=='2025A' and not f['segment_id'])
    lower=original|{'fact_id':'secondary','value':'999','slot_id':None,'locked_at':None}
    active,decisions=reconcile([lower,original],c['sources'],c['evidence'],c['company'])
    assert active[0]['value']=='100' and decisions[0]['rule']=='locked-annual-slot'
    c['facts']=[lower,original]
    assert not w.human.refresh(c,final=True)
    slot=next(s for s in store.records(run.run_id,'data_slot') if s['slot_id']==original['slot_id'])
    with pytest.raises(FinancialError,match='只读'):
        store.record(run.run_id,'data_slot',slot['slot_id'],slot|{'normalized_value':'999'})


async def test_multi_year_row_with_remote_unit_header_locks_once(tmp_path):
    w,g,store,run=prepared(tmp_path,rows=[]);c=await context(w)
    source=SourceRecord(source_id='annual-table',kind='upload',title='固定测试公司2025年年度报告',
        content='固定测试公司2025年年度报告\n合并利润表\n单位：元\n项目 | 2025年 | 2024年\n营业收入 | 1,234,567,890.00 | 900,000,000.00',locator='page:12')
    c['sources'].append(source.model_dump(mode='json'))
    g.values=[{'field_id':'income.revenue','period':'2025A','raw_value':'1,234,567,890.00','raw_unit':'元',
              'quote':'营业收入 | 1,234,567,890.00 | 900,000,000.00','header_quote':'项目 | 2025年 | 2024年',
              'unit_quote':'单位：元','column_index':0}]
    c.update(await w.research_plan(c))
    slot=next(s for s in store.records(run.run_id,'data_slot') if s['field_id']=='income.revenue' and s['period']=='2025A')
    assert slot['state']=='locked' and Decimal(slot['normalized_value'])==Decimal('1234.56789')
    before=len(g.calls)
    await w.fixed_collection.extract_document(c,source,quantitative=False)
    assert len(g.calls)==before  # financial extraction already included qualitative evidence


async def test_bad_column_is_repaired_once_and_never_marked_not_disclosed(tmp_path):
    w,g,store,run=prepared(tmp_path,rows=[]);c=await context(w)
    source=SourceRecord(source_id='bad',kind='upload',title='固定测试公司2025年年报',content='固定测试公司年报\n单位：百万元\n2025年 | 2024年\n营业收入 | 100 | 90',locator='p1')
    c['sources'].append(source.model_dump(mode='json'))
    g.values=[{'field_id':'income.revenue','period':'2025A','raw_value':'90','raw_unit':'百万元',
              'quote':'营业收入 | 100 | 90','header_quote':'2025年 | 2024年','column_index':0}]
    c.update(await w.research_plan(c))
    slot=next(s for s in store.records(run.run_id,'data_slot') if s['field_id']=='income.revenue' and s['period']=='2025A')
    assert slot['state']=='extraction_failed'
    before=len(g.calls);await w.fixed_collection.extract_document(c,source,quantitative=True)
    assert len(g.calls)==before
    assert len([call for name,call in g.calls if name=='SlotExtraction' and call['quantitative_allowed']])==2


async def test_missing_reports_stop_without_web_replans_or_human_confirmation(tmp_path):
    w,g,store,run=prepared(tmp_path,rows=[]);c=await context(w)
    class Forbidden:
        async def retrieve(self,*a):raise AssertionError('financial gaps cannot use web')
    c.update(await w.research_plan(c));c.update(await w.dependencies(c));c.update(await w.supervisor(c));c.update(await w.data_gaps(c))
    assert any(s['state']=='source_missing' for s in store.records(run.run_id,'data_slot') if s['field_id']=='income.revenue')
    assert (await w.replan(c))['pending']==[]
    with pytest.raises(FinancialError,match='核心输入缺失'):await w.human_gate(c)
    assert not store.records(run.run_id,'human_issue')


async def test_bounded_search_per_material_and_terminal_limited_state(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w);c.update(await w.research_plan(c));g.sufficient=False
    w.settings.search_url='https://test-search.invalid';seen=[]
    sources=[SourceRecord.model_validate(s) for s in c['sources']]
    async def retrieve(query):seen.append(query);return sources,[]
    w.datasource.retrieve=retrieve
    c.update(await w.supervisor(c));before=len(g.calls)
    slots=store.records(run.run_id,'collection_slot')
    assert 4<=len(seen)<=sum(s['search_budget'] for s in slots)
    # Industry slots search each direction separately under their own, larger budget.
    budget=lambda s:w.settings.material_industry_search_budget if s['topic'].startswith('行业') else w.settings.material_search_budget
    assert all(s['state']=='limited' and 1<=s['search_count']<=budget(s)==s['search_budget'] for s in slots)
    searches=len(seen)
    c.update(await w.supervisor(c))
    assert len(seen)==searches and len(g.calls)==before


async def test_data_slots_api_and_evaluation_preserve_raw_units_and_lock_metadata(tmp_path):
    import httpx
    from company_research.api import create_app
    w,g,store,run=prepared(tmp_path);c=await context(w);c.update(await w.research_plan(c))
    store.checkpoint(run.run_id,'research_plan',c)
    app=create_app(w.settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get(f'/api/research/{run.run_id}/data-slots')
        assert response.status_code==200
        data=response.json();assert data['template_version']==VERSION and len(data['groups'])==7
        assert data['latest_interim_period']=='2026H1'
        interim=next(s for s in data['slots'] if s['field_id']=='income.revenue' and s['period']=='2026H1')
        assert (interim['period_start'],interim['period_end'],interim['period_kind'])==('2026-01-01','2026-06-30','interim_flow')
        assert interim['requirement']=='C' and interim['state']=='locked'
        industry=next(s for s in data['materials'] if s['topic'].startswith('行业'))
        assert {'政策与监管变化','市场规模与结构'}<={d['label'] for d in industry['directions']}
        assert industry['scope']['linked_segments']==['设备','服务']
        revenue=next(s for s in data['slots'] if s['field_id']=='income.revenue' and s['period']=='2025A')
        assert revenue['raw_value']=='100' and revenue['raw_unit']=='CNY_million' and revenue['locked_at']
        assert 'fact' not in revenue
        assert (await client.get('/api/research/absent/data-slots')).status_code==404
    # Public work-product snapshot includes slots without exposing prompt windows.
    from company_research.work_products import build_snapshot
    snap=build_snapshot(store.work_product_state(run.run_id))
    assert snap['data']['data_slot']
    assert snap['data']['brief']['quarterly_collection']
    assert next(s for s in snap['data']['data_slot'] if s['slot_id']==interim['slot_id'])['period_kind']=='interim_flow'


class FullGateway(Gateway):
    async def structured(self,role,messages,schema):
        name=schema.__name__;data=json.loads(messages[-1]['content'])
        if name in {'SlotExtraction','MaterialAssessment','MaterialDirectionPlan'}:
            return await super().structured(role,messages,schema)
        self.calls.append((name,data))
        if name=='ResearchBrief':
            return schema(company_id='FIX',scope='固定表离线流程测试',historical_periods=['2023A','2024A','2025A'],
                forecast_periods=['2026E','2027E','2028E'],segments=['设备','服务'],industries={'设备':'制造业','服务':'制造业'})
        if name=='FinancialAnalysis':
            return schema(observations=['仅使用固定表与现有资料；缺口明确保留。'],evidence_ids=[e['evidence_id'] for e in data['evidence'][:1]],
                calculation_ids=[r['result_id'] for r in data['calculations']],limitations=[],
                question_answers={q:'原始披露只读；不足之处保留明确的分析限制。' for q in data['block']['questions']})
        if name=='WriterDraft':
            content='本材料是固定填槽流程的离线测试。公司业务、行业竞争和财务变化必须以已有证据为依据，数据缺口会限制预测和估值，不能用估计数替代未披露的原始输入。'
            return schema(paragraphs=[prefix+content*5 for prefix in ['研究边界明确。','业务资料有限。','行业机制需证据。','现金质量需结合口径。','预测条件仍有限制。']],
                evidence_ids=[e['evidence_id'] for e in data['evidence'][:1]],calculation_ids=[],fact_ids=[],assumption_ids=[],
                consistency_checks={k:'离线协议测试保留输入与预测限制。' for k in ['cash_growth','forecast_total','valuation_evidence','resource_concentration']})
        if name=='Reflection':return schema(needs_revision=False,instructions=[])
        if name=='ReviewOutput':return schema(issues=[])
        raise AssertionError('fixed workflow must not call '+name)


async def test_fixed_workflow_reaches_approved_limited_report_without_dynamic_financial_planners(tmp_path,monkeypatch):
    w,_,store,run=prepared(tmp_path)
    gateway=FullGateway();w=ResearchWorkflow(w.settings,store,run.run_id,gateway)
    # Rendering has independent tests; this test exercises collection through
    # approved delivery, without external model or search calls.
    async def no_render(c):return {}
    monkeypatch.setattr(w,'render',no_render)
    output=await w.build().ainvoke({'context':{'input':'000123','run_id':run.run_id,'replans':0,'revisions':0}},
                                 {'recursion_limit':100})
    c=output['context']
    assert store.run(run.run_id).status=='limited'
    assert c['report']['data_template_version']==VERSION
    assert c['report']['approved_snapshot_id']
    assert c['replans']==0 and not c['forecasts']
    assert not store.records(run.run_id,'human_issue')
    names={name for name,_ in gateway.calls}
    assert {'ResearchPlan','CalculationPlan','SupervisorDecision','AssumptionOutput'}.isdisjoint(names)
    assert {'ResearchBrief','SlotExtraction','MaterialAssessment','FinancialAnalysis','WriterDraft','ReviewOutput'}<=names


def test_research_report_mentioning_annual_report_is_not_financial_authority():
    company={'company_id':'FIX','name':'固定测试公司','ticker':'000123'}
    secondary=SourceRecord(kind='upload',title='固定测试公司2025年报点评研报',content='证券研究报告：根据固定测试公司年报，营业收入100百万元。')
    assert not annual_source(secondary,company)
    web=SourceRecord(kind='web',title='2025年年度报告',content=json.dumps({'document_type':'annual_report','company_id':'FIX'}))
    assert not annual_source(web,company)


async def test_known_absent_bond_components_are_zero_contributions_without_fake_raw_zeros(tmp_path):
    w,g,store,run=prepared(tmp_path,rows=[]);c=await context(w);w.fixed_collection.initialize(c)
    codes=['short_term_borrowings','current_debt_borrowings','current_debt_bonds','current_debt_leases',
           'other_current_interest_debt','long_term_borrowings','bonds_payable','lease_liabilities','other_noncurrent_interest_debt']
    text='固定测试公司2025年年报：'+'；'.join('无'+FIELDS['balance.'+code]['label'] for code in codes)
    source=SourceRecord(source_id='absent',kind='upload',title='固定测试公司2025年年报',content=text,locator='p1')
    store.record(run.run_id,'source',source.source_id,source.model_dump(mode='json'))
    for code in codes:
        assert w.fixed_collection.accept_absence(c,source,SlotAbsence(field_id='balance.'+code,period='2025A',quote='无'+FIELDS['balance.'+code]['label']))
    w.fixed_collection.derive(c)
    debt=next(f for f in w.fixed_collection.facts(c) if f['metric_code']=='debt')
    assert debt['value']=='0' and debt['value_origin']=='derived'
    assert all(s['raw_value'] is None for s in store.records(run.run_id,'data_slot') if s['state']=='not_applicable')


async def test_new_fixed_task_never_imports_other_runs_locked_values(tmp_path):
    w,g,store,run=prepared(tmp_path);c=await context(w)
    other=ResearchRun(company_input='000123',mode='real',status='completed');store.save_run(other)
    wrong=w.fixed_collection.make_slot(c,'income.revenue','2025A')|{'state':'locked','normalized_value':'999'}
    store.record(other.run_id,'data_slot',wrong['slot_id'],wrong)
    c.update(await w.research_plan(c))
    revenue=next(f for f in c['facts'] if f['metric_code']=='revenue' and f['period']=='2025A')
    assert revenue['value']=='100'


async def test_quantitative_partial_commit_reuses_lock_time_and_saved_model_output(tmp_path,monkeypatch):
    w,g,store,run=prepared(tmp_path);c=await context(w);w.fixed_collection.initialize(c)
    source=next(s for s in w.references if s.title=='annual.json' and json.loads(s.content)['field_id']=='income.revenue')
    row=json.loads(source.content)
    proposal=SlotProposal(field_id=row['field_id'],period=row['period'],raw_value=str(row['value']),raw_unit=row['unit'],quote=source.content)
    original=w.fixed_collection.save_slot
    monkeypatch.setattr(w.fixed_collection,'save_slot',lambda slot: (_ for _ in ()).throw(RuntimeError('simulate commit interruption')))
    with pytest.raises(RuntimeError):w.fixed_collection.accept(c,source,proposal,structured=True)
    partial=store.records(run.run_id,'fact')[0]
    monkeypatch.setattr(w.fixed_collection,'save_slot',original)
    assert w.fixed_collection.accept(c,source,proposal,structured=True)
    saved=next(s for s in store.records(run.run_id,'data_slot') if s['slot_id']==partial['slot_id'])
    assert saved['locked_at']==partial['locked_at'] and saved['state']=='locked'


async def test_fixed_workflow_uses_real_gateway_protocol_with_mock_http(tmp_path,monkeypatch):
    import httpx
    from company_research.llm import Gateway as RealGateway, ModelConfig
    from company_research.agents import FinancialAnalysis,WriterDraft,Reflection,ReviewOutput
    w,_,store,run=prepared(tmp_path);script=FullGateway()
    schemas={s.__name__:s for s in [ResearchBrief,SlotExtraction,MaterialAssessment,MaterialDirectionPlan,FinancialAnalysis,WriterDraft,Reflection,ReviewOutput]}
    monkeypatch.setenv('FIXED_TEST_KEY','fixture-only')
    async def server(request):
        body=json.loads(request.content)
        title=body['tools'][0]['function']['parameters']['title']
        output=await script.structured('fixture',body['messages'],schemas[title])
        return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'id':'output','function':{
            'name':'structured_output','arguments':output.model_dump_json()}}]},'finish_reason':'tool_calls'}],
            'usage':{'prompt_tokens':10,'completion_tokens':10}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        gateway=RealGateway({'fixture':ModelConfig(protocol='openai',base_url='https://fixture.invalid/v1',model='fixture',api_key_env='FIXED_TEST_KEY')},
            {'default':'fixture'},client=client,global_token_budget=10000000)
        w=ResearchWorkflow(w.settings,store,run.run_id,gateway)
        async def no_render(c):return {}
        monkeypatch.setattr(w,'render',no_render)
        output=await w.build().ainvoke({'context':{'input':'000123','run_id':run.run_id,'replans':0,'revisions':0}},{'recursion_limit':100})
    assert output['context']['report']['approved_snapshot_id']
    assert store.run(run.run_id).status=='limited'
    assert gateway.calls and not store.records(run.run_id,'human_issue')


async def test_annual_report_quarterly_or_forecast_revenue_cannot_fill_annual_actual_slot(tmp_path):
    w,g,store,run=prepared(tmp_path,rows=[]);c=await context(w);w.fixed_collection.initialize(c)
    source=SourceRecord(source_id='quarter',kind='upload',title='固定测试公司2025年年度报告',
        content='固定测试公司2025年年度报告\n分季度主要财务数据\n单位：百万元\n2025年\n营业收入 | 100 | 110 | 120 | 130\n预计2025年营业收入500百万元',locator='p1')
    quarter=SlotProposal(field_id='income.revenue',period='2025A',raw_value='100',raw_unit='百万元',
        quote='营业收入 | 100 | 110 | 120 | 130',header_quote='2025年',unit_quote='单位：百万元')
    forecast=quarter.model_copy(update={'raw_value':'500','quote':'预计2025年营业收入500百万元'})
    assert not w.fixed_collection.accept(c,source,quarter)
    assert not w.fixed_collection.accept(c,source,forecast)


async def test_annual_rows_after_the_quarterly_table_are_not_treated_as_quarterly(tmp_path):
    w,g,store,run=prepared(tmp_path,rows=[]);c=await context(w);w.fixed_collection.initialize(c)
    content=('固定测试公司2025年年度报告\n分季度主要财务数据\n单位：百万元\n2025年\n营业收入 | 100 | 110 | 120 | 130\n'
             '季度数据与已披露定期报告数据差异说明\n□适用 √不适用\n十、非经常性损益项目和金额\n'
             '五、经营情况讨论与分析\n单位：元 币种：人民币\n主营业务分产品情况\n分产品 营业收入 营业成本 毛利率（%）\n'
             '设备 300,000,000.00 180,000,000.00 40.00 5.00 4.00\n服务 160,000,000.00 64,000,000.00 60.00 8.00 6.00\n主营业务分地区情况\n'
             '2025年度营业成本合计 244 百万元')
    source=SourceRecord(source_id='mdna',kind='upload',title='固定测试公司2025年年度报告',content=content,locator='p1')
    cost=SlotProposal(field_id='income.cost',period='2025A',raw_value='244',raw_unit='百万元',quote='2025年度营业成本合计 244 百万元')
    assert w.fixed_collection.accept(c,source,cost),w.fixed_collection.last_reject
    w.fixed_collection.standard_tables(c,source)
    locked={(s['segment_id'],s['field_id']):s for s in store.records(run.run_id,'data_slot') if s.get('segment_id') and s['state']=='locked'}
    assert Decimal(locked[('设备','segment.revenue')]['normalized_value'])==300
    assert Decimal(locked[('服务','segment.cost')]['normalized_value'])==64


async def test_rounded_narrative_or_another_metric_cannot_lock_revenue(tmp_path):
    w,g,store,run=prepared(tmp_path,rows=[]);c=await context(w);w.fixed_collection.initialize(c)
    text='固定测试公司2025年年报\n2025年度营业收入约100百万元\n2025年度营业收入100百万元，营业成本60百万元'
    source=SourceRecord(source_id='approx',kind='upload',title='固定测试公司2025年年报',content=text,locator='p1')
    proposal=SlotProposal(field_id='income.revenue',period='2025A',raw_value='100',raw_unit='百万元',quote='2025年度营业收入约100百万元')
    assert not w.fixed_collection.accept(c,source,proposal)
    wrong=proposal.model_copy(update={'raw_value':'60','quote':'2025年度营业收入100百万元，营业成本60百万元'})
    assert not w.fixed_collection.accept(c,source,wrong)


async def test_negative_cashflow_with_chinese_adjacent_minus_is_preserved_and_range_endpoint_rejected(tmp_path):
    w,g,store,run=prepared(tmp_path,rows=[]);c=await context(w);w.fixed_collection.initialize(c)
    text='固定测试公司2025年年报\n2025年度经营活动产生的现金流量净额−100百万元\n2025年度营业收入848-908百万元'
    source=SourceRecord(source_id='negative',kind='upload',title='固定测试公司2025年年报',content=text,locator='p1')
    negative=SlotProposal(field_id='cashflow.operating_cashflow',period='2025A',raw_value='−100',raw_unit='百万元',quote='2025年度经营活动产生的现金流量净额−100百万元')
    assert w.fixed_collection.accept(c,source,negative)
    slot=next(s for s in store.records(run.run_id,'data_slot') if s['field_id']==negative.field_id and s['period']=='2025A')
    assert slot['raw_value']=='−100' and slot['normalized_value']=='-100'
    endpoint=negative.model_copy(update={'field_id':'income.revenue','raw_value':'848','quote':'2025年度营业收入848-908百万元'})
    assert not w.fixed_collection.accept(c,source,endpoint)
