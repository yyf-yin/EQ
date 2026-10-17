import asyncio
from decimal import Decimal as D
import pytest
from company_research.config import Settings
from company_research.storage import Store
from company_research.schemas import ResearchRun,ReportDocument
from company_research.runner import Runner
from company_research.reviewers import deterministic_review,review_graph
from company_research.graphs import ResearchWorkflow
from company_research.financials import FinancialError


@pytest.fixture(scope='module')
def completed(tmp_path_factory):
    tmp=tmp_path_factory.mktemp('review')
    settings=Settings(database=tmp/'db',artifacts=tmp/'out',local_sources=tmp/'local',mock_delay=0,max_revisions=1)
    store=Store(settings.database);run=ResearchRun(company_input='故障测试公司',mode='mock');store.save_run(run)
    asyncio.run(Runner(settings,store).run(run.run_id))
    assert store.run(run.run_id).status=='limited',store.run(run.run_id)
    return settings,store,run.run_id,store.report(run.run_id)


def test_clean_review(completed):
    report=completed[3]
    assert not [i for i in deterministic_review(report) if i.severity in {'critical','error'}]


@pytest.mark.parametrize('fault,expected',[
 ('eps','复算'),('pe','复算'),('segments','分部'),('balance','不平衡'),('cash','现金'),('period','期间'),('source','来源'),('core','不一致'),('toc','目录')])
def test_fault_injection(completed,fault,expected):
    report=completed[3].model_copy(deep=True)
    if fault in {'eps','pe'}:
        r=next(r for r in report.calculations if r.formula_id==fault and r.scenario=='historical');r.value+=D(1)
    elif fault=='segments':report.forecasts[0].segments['设备']['revenue']+=D(100)
    elif fault=='balance':report.forecasts[0].balance['equity']+=D(100)
    elif fault=='cash':report.forecasts[0].cashflow['cfo']+=D(1)
    elif fault=='period':report.financial_facts[0].actual_or_forecast='forecast'
    elif fault=='source':report.sources=[]
    elif fault=='core':report.sections[0].paragraphs=['没有任何风险，保证收益。模拟报告。']
    elif fault=='toc':report.sections=[s for s in report.sections if s.section_id!='toc']
    issues=deterministic_review(report)
    assert any(expected in i.description and i.location and i.target_node for i in issues)
    assert any(i.severity=='critical' for i in issues)


async def test_targeted_revision_and_gate(completed):
    settings,store,id,report=completed
    c=store.load_checkpoint(id)[1]
    c['report']=report.model_copy(deep=True).model_dump(mode='json')
    c['report']['sections'][0]['paragraphs']=['没有任何风险，保证收益。模拟报告。']
    workflow=ResearchWorkflow(settings,store,id)
    c.update(await workflow.final_review(c));assert c['issues']
    assert all(i['target_node']=='core_conclusion' for i in c['issues'])
    c.update(await workflow.revise(c));c.update(await workflow.final_review(c))
    assert not c['issues'] and c['revisions']==1
    c['report']['sources']=[];c['revisions']=settings.max_revisions
    with pytest.raises(FinancialError,match='终审阻断'):await workflow.final_review(c)


def test_core_conflict_gate_ignores_unverifiable_forecast_checks():
    from company_research.reviewers import critical_review
    from company_research.schemas import ReportSection
    checks={'cash_growth':'limited: 现金流口径未剔除金融子公司','forecast_total':'conflict: forecasts 为空',
            'valuation_evidence':'conflict: 无股价与可比数据','resource_concentration':'集中度高但无法量化'}
    report=ReportDocument(title='t',company_id='c',mode='real',rules_version='1.1',sources=[],sections=[
        ReportSection(section_id='core',title='核心观点',paragraphs=['结论'],consistency_checks=checks),
        ReportSection(section_id='risk',title='风险',paragraphs=['甲','乙','丙'])])
    issues=critical_review(report)
    assert not [i for i in issues if i.severity in {'critical','error'}]
    assert any('受限研究' in i.description for i in issues)
    report.sections[0].consistency_checks['cash_growth']='conflict: 正文增长结论与现金计算方向相反'
    blocked=[i for i in critical_review(report) if i.severity=='critical']
    assert len(blocked)==1 and blocked[0].description.endswith('cash_growth')


def test_review_issue_target_is_restricted_and_mapped():
    from company_research.schemas import ReviewIssue
    base=dict(issue_type='evidence',severity='error',location='x',description='d',suggested_fix='f')
    stray=ReviewIssue(**base,target_node='C01');core=ReviewIssue(**base,target_node='X01');kept=ReviewIssue(**base,target_node='calculate')
    assert (stray.target_node,stray.requested_target)==('write_sections','C01')
    assert (core.target_node,core.requested_target)==('core_conclusion','X01')
    assert (kept.target_node,kept.requested_target)==('calculate','')


def test_semantic_issue_bound_to_reviewed_section():
    from company_research.schemas import ReviewIssue
    from company_research.reviewers import bind_semantic
    base=dict(issue_type='critical',severity='critical',location='第5段',description='d',suggested_fix='f')
    p=bind_semantic(ReviewIssue(**base,target_node='research_plan'),'risk')
    assert (p.section_id,p.block_id,p.target_node,p.requested_target)==('risk','R01','write_sections','research_plan')
    p=bind_semantic(ReviewIssue(**base,target_node='write_sections'),'core')
    assert p.target_node=='core_conclusion'
    assert bind_semantic(ReviewIssue(**base,target_node='assumptions'),'forecast').target_node=='assumptions'


def test_issue_location_resolves_to_sections():
    from company_research.reviewers import issue_sections
    from company_research.schemas import ReportSection
    sections=[ReportSection(section_id='financial',title='二、财务情况分析',children=[
                ReportSection(section_id='F01',title='（一）财务增长与盈利能力')]),
              ReportSection(section_id='business',title='三、公司业务',children=[
                ReportSection(section_id='segment-0',title='茅台酒',children=[
                  ReportSection(section_id='position-0',title='（二）公司情况')]),
                ReportSection(section_id='segment-1',title='其他系列酒',children=[
                  ReportSection(section_id='position-1',title='（二）公司情况')])]),
              ReportSection(section_id='risk',title='五、风险提示')]
    find=lambda **p:issue_sections({'location':'','block_id':None}|p,sections)
    assert find(location='五、风险提示 第3段')==['risk']
    assert find(location='F01第2段（毛利率与净利率）')==['F01']
    assert find(location='segment-0/position-0')==['segment-0','position-0']
    assert find(location='二、财务情况分析 / （一）财务增长与盈利能力')==['F01']
    assert find(location='其他系列酒（二）公司情况',block_id='B01-1')==['position-1']
    assert find(location='无法识别',block_id='R01')==['risk']
    assert find(location='五、风险提示',section_id='F01')==['F01']
    assert find(location='无法识别')==[]


async def test_located_issue_rewrites_only_its_section(completed,monkeypatch):
    settings,store,id,report=completed
    c=store.load_checkpoint(id)[1]
    c['report']=report.model_copy(deep=True).model_dump(mode='json')
    workflow=ResearchWorkflow(settings,store,id)
    async def full_redraft(_):raise AssertionError('整稿重写')
    monkeypatch.setattr(workflow,'write_sections',full_redraft)
    c['issues']=[{'issue_id':'i1','issue_type':'critical','severity':'error','location':'第3段（经营现金流归因）',
                  'description':'d','suggested_fix':'删除无证据归因','target_node':'write_sections',
                  'section_id':'risk','block_id':'R01','rule_id':'semantic.critical'}]
    c.update(await workflow.revise(c))
    assert c['revisions']==1


def test_reviewer_context_follows_section_citations():
    from company_research.reviewers import cited_context
    from company_research.schemas import ReportSection,FinancialFact,CalculationResult,EvidenceRecord,Table
    ev=lambda i:EvidenceRecord(evidence_id='ev-'+i,source_id='src-1',claim=i,quote='原文'+i,locator='p1')
    fact=lambda i,**k:FinancialFact(fact_id='fact-slot-'+i,company_id='c',metric_code=i,period='2024',unit='CNY_million',
                                    value=D(1),actual_or_forecast='actual',source_id='src-1',evidence_id='ev-'+i,locator='p1',**k)
    calc=lambda i,refs:CalculationResult(result_id='calc-'+i,formula_id='f',formula_version='1',output_metric=i,period='2024',
                                         unit='ratio',inputs={k:D(1) for k in refs},input_refs=refs,value=D(1))
    report=ReportDocument(title='t',company_id='c',mode='real',sources=[],
        evidence=[ev(i) for i in ['revenue','net_income','cost','derived','table','unrelated']],
        financial_facts=[fact('revenue'),fact('net_income'),fact('cost'),fact('table'),fact('unrelated'),
                         fact('derived',value_origin='derived',derivation_id='calc-gross0000000')],
        calculations=[calc('margin000000000',{'net_income':'fact-slot-net_income','revenue':'fact-slot-revenue'}),
                      calc('gross0000000',{'cost':'fact-slot-cost'}),
                      calc('tabled000000000',{'x':'fact-slot-table'}),calc('other0000000000',{})],
        sections=[ReportSection(section_id='F01',title='财务',paragraphs=['净利率为12.00%。','[[fact:fact-slot-derived]]'],
                                number_bindings={'calc:calc-margin000000000':'12.00%'},
                                tables=[Table(title='计算',columns=['ID'],rows=[['calc-tabled0']])])])
    cited=cited_context(report,report.sections[0])
    assert {f.fact_id for f in cited['facts']}=={'fact-slot-'+i for i in ['revenue','net_income','cost','derived','table']}
    assert {r.result_id for r in cited['calculations']}=={'calc-margin000000000','calc-gross0000000','calc-tabled000000000'}
    assert {e.quote for e in cited['evidence']}=={'原文'+i for i in ['revenue','net_income','cost','derived','table']}


async def test_semantic_review_skips_generated_sections_and_sends_citations(completed,monkeypatch):
    import company_research.reviewers as reviewers
    from company_research.agents import ReviewOutput
    from company_research.reports import sections_flat
    report=completed[3]
    seen={}
    async def fake(gateway,role,schema,data):
        seen.setdefault(data['section']['section_id'],data);return ReviewOutput(issues=[])
    monkeypatch.setattr(reviewers,'ask_bounded',fake)
    await review_graph(gateway=object(),mock=False).ainvoke({'report':report.model_dump(mode='json'),'issues':[]})
    assert seen and not seen.keys()&{'statements','disclaimer','toc'}
    for section in sections_flat(report.sections):
        if section.section_id not in seen:continue
        facts={f['fact_id'] for f in seen[section.section_id]['facts']}
        calcs={r['result_id'] for r in seen[section.section_id]['calculations']}
        evidence={e['evidence_id'] for e in seen[section.section_id]['evidence']}
        for ref in section.number_bindings:
            kind,id=ref.split(':',1)
            assert id in (facts if kind=='fact' else calcs if kind=='calc' else {a['assumption_id'] for a in seen[section.section_id]['assumptions']})
        assert {f['evidence_id'] for f in seen[section.section_id]['facts']}<=evidence
