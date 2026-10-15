from decimal import Decimal
import copy
import pytest
from company_research.reconciliation import reconcile
from company_research.schemas import FinancialFact, ResearchRun, CalculationPlan
from company_research.financials.formulas import FinancialDataProcessor, FinancialError
from company_research.graphs import ResearchWorkflow
from company_research.storage import Store
from company_research.config import Settings
from company_research.planners import execute_calculation_plan
from company_research.framework import refresh_coverage

COMPANY={'company_id':'test','name':'测试股份有限公司'}


def material(id,value='100',quote=None,url='https://news.example/a',**changes):
    quote=quote or f'测试股份有限公司 2024年度 合并 营业收入 {value}百万元。'
    source={'source_id':'s'+id,'kind':'web','title':'测试股份有限公司2024年报','source_url':url,'content':quote,'locator':'p1'}
    evidence={'evidence_id':'e'+id,'source_id':'s'+id,'claim':quote,'quote':quote,'locator':'p1','validation_status':'verified','actual_or_forecast':'actual'}
    fact=FinancialFact(fact_id=id,company_id='test',metric_code='revenue',period='2024A',unit='CNY_million',value=value,
        source_id='s'+id,evidence_id='e'+id,locator='p1',validation_status='verified',actual_or_forecast='actual').model_dump(mode='json')|changes
    return fact,source,evidence


def adjudicate(*materials,checked=False):
    facts,sources,evidence=map(list,zip(*materials))
    before=copy.deepcopy(facts)
    active,decisions=reconcile(facts,sources,evidence,COMPANY)
    if checked:active,decisions=reconcile(facts,sources,evidence,COMPANY,{d['group_id'] for d in decisions})
    assert facts==before
    return active,decisions


def test_units_same_value_and_percent():
    active,decisions=adjudicate(material('a'),material('b','10000',unit='万元'))
    assert len(active)==1 and decisions[0]['status']=='consistent'
    f=FinancialFact.model_validate(material('c','25',unit='%')[0])
    assert FinancialDataProcessor().normalize(f).value==Decimal('.25')


@pytest.mark.parametrize('change',[{'period':'2024H1'},{'scope':'parent'},{'segment_id':'设备','scope':'segment'},{'actual_or_forecast':'forecast'}])
def test_different_period_scope_forecast_never_mix(change):
    active,decisions=adjudicate(material('a'),material('b','200',**change))
    assert len(active)==2 and all(d['status']=='consistent' for d in decisions)


def test_accounting_basis_is_conflict_even_equal_number():
    active,decisions=adjudicate(material('a'),material('b',accounting_basis='adjusted'),checked=True)
    assert not active and decisions[0]['status']=='unresolved'
    with pytest.raises(FinancialError,match='冲突'):
        FinancialDataProcessor().get([FinancialFact.model_validate(m[0]) for m in [material('a'),material('b',accounting_basis='adjusted')]],'test','revenue','2024A')


def test_only_verified_primary_after_targeted_check():
    primary=material('a',url='https://static.cninfo.com.cn/report.pdf')
    secondary=material('b','120')
    assert not adjudicate(primary,secondary)[0]
    active,decisions=adjudicate(primary,secondary,checked=True)
    assert [f['fact_id'] for f in active]==['a'] and decisions[0]['rule']=='checked-primary'


@pytest.mark.parametrize('url',['https://cninfo.com.cn.evil.example/a','https://fakecninfo.com.cn/a','http://cninfo.com.cn/a'])
def test_fake_domain_cannot_win(url):
    assert not adjudicate(material('a',url=url),material('b','120'),checked=True)[0]


def test_primary_disagreement_needs_directional_correction():
    primary=material('a',url='https://cninfo.com.cn/a')
    other=material('b','120',url='https://sse.com.cn/b',version=2,supersedes='a')
    assert not adjudicate(primary,other,checked=True)[0]
    fixed=material('c','120',quote='测试股份有限公司2024年度合并营业收入由100百万元更正为120百万元。',url='https://cninfo.com.cn/c')
    active,decisions=adjudicate(primary,other,fixed)
    assert [f['fact_id'] for f in active]==['c'] and decisions[0]['proof_evidence_ids']==['ec']


def test_newer_search_date_and_majority_do_not_choose_value():
    items=[material(str(i),'120') for i in range(5)]+[material('a')]
    items[0][1]['publication_date']='2099-01-01'
    assert not adjudicate(*items,checked=True)[0]


def test_mismatch_original_quote_cannot_be_primary():
    a=material('a',url='https://cninfo.com.cn/a');a[1]['content']='其他正文'
    assert not adjudicate(a,material('b','120'),checked=True)[0]


def test_coverage_cannot_mark_ambiguous_facts_ready():
    facts=[material('a')[0],material('b','120')[0]]
    entries=[{'block_id':'F01','question_id':'q','requirements':['revenue@2024A']}]
    result=refresh_coverage(entries,[{'block_id':'F01','company_id':'test'}],facts,[],{})
    assert result[0]['status']=='missing' and not result[0]['verified_refs']


async def test_checks_bounded_replayed_and_audited(tmp_path,monkeypatch):
    settings=Settings(database=tmp_path/'db',local_sources=tmp_path/'local',artifacts=tmp_path/'out',max_conflict_checks=2)
    store=Store(settings.database);run=ResearchRun(company_input='test',mode='mock');store.save_run(run)
    workflow=ResearchWorkflow(settings,store,run.run_id);workflow.mock=False
    facts,sources,evidence=map(list,zip(material('a'),material('b','120')))
    c={'company':COMPANY,'brief':{},'facts':facts,'sources':sources,'evidence':evidence,'required_data':[],
       'coverage':[],'plan':{'blocks':[]},'limitations':[]}
    count=0
    class Subgraph:
        async def ainvoke(self,state,config):
            nonlocal count
            count+=1
            return state|{'summary':{},'warnings':[]}
    monkeypatch.setattr('company_research.graphs.researcher_graph',lambda *args:Subgraph())
    first=await workflow.data_gaps(c)
    assert count==2 and len(first['fact_verifications'])==2 and not first['facts']
    assert first['fact_verifications'][0]['queries']!=first['fact_verifications'][1]['queries']
    replay=await workflow.data_gaps(c) # interruption before completed node checkpoint
    assert count==2 and replay['fact_decisions']==first['fact_decisions']
    again=await workflow.data_gaps(c|first)
    assert count==2 and not again['facts']
    assert len(store.records(run.run_id,'fact_verification'))==2
    assert store.records(run.run_id,'fact_decision')[0]['status']=='unresolved'


def test_calculation_reuses_only_identical_input_chain():
    facts=[FinancialFact.model_validate(material('r','100')[0]),FinancialFact.model_validate(material('c','60',metric_code='cost')[0])]
    plan=CalculationPlan(company_id='test',forecast_model='growth',calculations=[{'formula_id':'gross_margin','output_metric':'gm','period':'2024A','unit':'ratio'}])
    result,gaps=execute_calculation_plan(plan,facts)
    assert not gaps
    reused,gaps=execute_calculation_plan(plan,facts,[r.model_dump(mode='json') for r in result])
    assert reused==result
    changed=facts[0].model_copy(update={'fact_id':'new','value':Decimal('120')})
    updated,_=execute_calculation_plan(plan,[changed,facts[1]],[r.model_dump(mode='json') for r in result])
    assert updated[0].result_id!=result[0].result_id and updated[0].value==Decimal('.5')


async def test_new_primary_conflict_reopens_previous_decision(tmp_path,monkeypatch):
    settings=Settings(database=tmp_path/'db',local_sources=tmp_path/'local',artifacts=tmp_path/'out',max_conflict_checks=2)
    store=Store(settings.database);run=ResearchRun(company_input='test',mode='mock');store.save_run(run)
    workflow=ResearchWorkflow(settings,store,run.run_id);workflow.mock=False
    facts,sources,evidence=map(list,zip(material('a',url='https://cninfo.com.cn/a'),material('b','120')))
    c={'company':COMPANY,'brief':{},'facts':facts,'sources':sources,'evidence':evidence,'required_data':[],
       'coverage':[],'plan':{'blocks':[]},'limitations':[]}
    count=0
    class Subgraph:
        async def ainvoke(self,state,config):
            nonlocal count
            count+=1
            return state|{'summary':{},'warnings':[]}
    monkeypatch.setattr('company_research.graphs.researcher_graph',lambda *args:Subgraph())
    first=await workflow.data_gaps(c)
    assert count==1 and first['facts'][0]['fact_id']=='a'
    f,s,e=material('c','120',url='https://sse.com.cn/new')
    next_context=c|first
    next_context['facts']=first['facts']+[f];next_context['sources']=first['sources']+[s];next_context['evidence']=first['evidence']+[e]
    second=await workflow.data_gaps(next_context)
    assert count==2 and not second['facts'] and second['fact_decisions'][0]['status']=='unresolved'
    assert store.records(run.run_id,'invalidation')


async def test_critical_conflict_preserves_independent_work_and_blocks_delivery(tmp_path,monkeypatch):
    from company_research.runner import Runner
    from company_research.schemas import SourceRecord
    from company_research.work_products import capture_snapshot,preview,export_snapshot
    original=ResearchWorkflow.supervisor
    async def inject(self,c):
        result=await original(self,c)
        target=next(f for f in result['facts'] if f['metric_code']=='revenue' and f['scope']=='consolidated' and f['period']==max(c['brief']['historical_periods']))
        value=str(Decimal(target['value'])+1)
        f,s,e=material('disagree',value)
        f=target|{'fact_id':'disagree','source_id':s['source_id'],'evidence_id':e['evidence_id'],'value':value}
        s=SourceRecord.model_validate(s).model_dump(mode='json')
        result['sources'].append(s);result['evidence'].append(e);result['facts'].append(f)
        self.bind(result)
        return result
    monkeypatch.setattr(ResearchWorkflow,'supervisor',inject)
    settings=Settings(database=tmp_path/'db',local_sources=tmp_path/'local',artifacts=tmp_path/'out',mock_delay=0,max_replans=0)
    store=Store(settings.database);run=ResearchRun(company_input='test',mode='mock');store.save_run(run)
    await Runner(settings,store).run(run.run_id)
    assert store.run(run.run_id).status=='waiting_human',store.run(run.run_id).error
    assert store.records(run.run_id,'task')  # Independent collection is preserved.
    assert not store.records(run.run_id,'calculation')
    assert not store.records(run.run_id,'block_analysis')
    assert not (settings.artifacts/run.run_id/'report.docx').exists()
    ctx=store.load_checkpoint(run.run_id)[1]
    unresolved=[d for d in ctx['fact_decisions'] if d['status']=='unresolved']
    assert unresolved and not set(unresolved[0]['candidate_ids']) & {f['fact_id'] for f in ctx['facts']}
    snapshot=capture_snapshot(store,run.run_id,settings.work_product_max_bytes)
    assert not snapshot['final_review_passed'] and preview(snapshot)['fact_decisions']
    assert all(d['policy']=='financial-reconciliation-1' for d in snapshot['data']['fact_decision'])
    assert any(a['kind']=='fact' and a['id']=='disagree' and a['validation_status']=='conflict' for a in snapshot['artifacts'])
    data,media=export_snapshot(snapshot,'json',settings.work_product_max_bytes)
    assert b'fact_decision' in data


def test_unrelated_metric_correction_cannot_settle_revenue():
    wrong=material('b','120',quote='测试股份有限公司2024年度合并营业收入100百万元，净利润由100百万元更正为120百万元。',url='https://cninfo.com.cn/a')
    assert not adjudicate(material('a'),wrong,checked=True)[0]


def test_unknown_currency_and_nonfinite_values_never_enter_inputs():
    for changes in [{'currency':'USD'},{'value':'Infinity'},{'unit':'CNY/share','currency':'USD'}]:
        raw,s,e=material('a');raw.update(changes)
        active,decisions=adjudicate((raw,s,e))
        assert not active and decisions[0]['rule']=='invalid'


def test_conflict_affects_only_relevant_context_snapshots():
    from company_research.contexts import block_context
    blocks=[{'block_id':id,'template_id':id,'segment_id':None,'questions':{},'dependencies':[]} for id in ['C01','F01','F02']]
    c={'company':COMPANY|{'source_ids':[]},'brief':{'historical_periods':['2024A'],'forecast_periods':['2025E']},
       'plan':{'blocks':blocks},'facts':[material('a')[0]],'sources':[],'evidence':[],'coverage':[]}
    decision=adjudicate(material('a'),material('b','120'))[1][0]
    changed=c|{'facts':[],'fact_decisions':[decision]}
    assert block_context(c,'C01','analysis').snapshot_id==block_context(changed,'C01','analysis').snapshot_id
    assert block_context(c,'F02','analysis').snapshot_id==block_context(changed,'F02','analysis').snapshot_id
    assert block_context(c,'F01','analysis').snapshot_id!=block_context(changed,'F01','analysis').snapshot_id


def test_declared_revision_cannot_erase_another_accounting_basis():
    a=FinancialFact.model_validate(material('a')[0]);b=FinancialFact.model_validate(material('b','120',accounting_basis='adjusted',supersedes='a',version=2)[0])
    with pytest.raises(FinancialError,match='冲突'):FinancialDataProcessor().get([a,b],'test','revenue','2024A')
