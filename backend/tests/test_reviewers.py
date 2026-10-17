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
