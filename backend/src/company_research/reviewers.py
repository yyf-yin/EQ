"""Independent reviewer subgraph: hard deterministic gates + semantic LLM reviews."""
import operator
import re
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from typing import TypedDict,Annotated
from langgraph.graph import StateGraph,START,END
from .schemas import ReportDocument,ReviewIssue,FinancialFact
from .reports import TITLES,sections_flat,toc
from .financials import Calculator
from .financials.formulas import FinancialDataProcessor,FinancialError
from .agents import ask,ask_bounded,ReviewOutput
from .writers import number


def issue(kind,location,description,target,severity='critical',fix='根据原始资料及注册公式修复后重新审核'):
    return ReviewIssue(issue_type=kind,severity=severity,location=location,description=description,suggested_fix=fix,target_node=target)


def structural_review(report: ReportDocument):
    issues=[]
    if report.rules_version=='1.1':
        from .framework import skeleton,validate_plan
        from .schemas import ResearchPlan,ResearchTask
        if report.brief:
            expected=skeleton(report.brief)
            # Budgets can be lower than defaults or explicitly raised by backend config.
            for b in expected.blocks:
                actual=next((x for x in report.blocks if x.block_id==b.block_id),None)
                if actual:b.call_budget=actual.call_budget
            plan=ResearchPlan(company_id=report.company_id,segments=report.brief.segments,blocks=report.blocks,tasks=expected.tasks)
            for error in validate_plan(plan,report.brief,expected):issues.append(issue('structural','report.blocks',error,'research_plan'))
    if [s.title for s in report.sections]!=TITLES:issues.append(issue('structural','report.sections','固定章节顺序或目录缺失','assemble'))
    ids=[s.section_id for s in sections_flat(report.sections)]
    if len(ids)!=len(set(ids)):issues.append(issue('structural','report.sections','章节 ID 重复，目录定位不唯一','assemble'))
    business=next((s for s in report.sections if s.section_id=='business'),None)
    if not business or not business.children:issues.append(issue('structural','business','主营业务缺失','write_sections'))
    elif any([c.title for c in s.children]!=['（一）行业情况','（二）公司情况'] for s in business.children):issues.append(issue('structural','business','业务缺少行业或公司双层结构','write_sections'))
    if not any(s.section_id=='toc' for s in report.sections) or not toc(report.sections):issues.append(issue('structural','toc','目录缺失','assemble'))
    statements=next((s for s in report.sections if s.section_id=='statements'),None)
    if report.forecasts and (not statements or len(statements.tables)<3):issues.append(issue('structural','statements','完整三表缺失','assemble'))
    for s in sections_flat(report.sections):
        for table in s.tables:
            if any(len(row)!=len(table.columns) for row in table.rows):issues.append(issue('structural',s.section_id,'表格列数不一致','assemble'))
    return issues


def financial_review(report: ReportDocument):
    issues=[];calculator=Calculator();facts={f.fact_id:f for f in report.financial_facts};results={r.result_id:r for r in report.calculations};assumptions={a.assumption_id:a for a in report.assumptions};refs={**facts,**results,**assumptions}
    from .comparisons import core_gate
    issues+=core_gate(report)
    for r in report.calculations:
        if not calculator.recompute(r):issues.append(issue('financial',r.result_id,f'{r.output_metric} 公式复算不一致','calculate'))
        if r.scenario=='historical' and not re.fullmatch(r'\d{4}(?:A|H1|Q[1-4]|[1-4]Q)',r.period) or r.scenario!='historical' and not r.period.endswith('E'):issues.append(issue('financial',r.result_id,'实际与预测期间混淆','calculate'))
        for parameter,value in r.inputs.items():
            reference=r.input_refs.get(parameter,'');obj=refs.get(reference)
            if reference.startswith('constant:'):
                if Decimal(reference[9:])!=value:issues.append(issue('financial',r.result_id,'常量与计算输入不符','calculate'))
                continue
            if not obj:
                issues.append(issue('financial',r.result_id,'输入引用缺失：'+parameter,'calculate'));continue
            if obj.value!=value:issues.append(issue('financial',r.result_id,'输入与引用数据不一致：'+parameter,'calculate'))
            if r.scenario=='historical' and getattr(obj,'actual_or_forecast','actual')!='actual':issues.append(issue('financial',r.result_id,'历史指标使用预测值','financial_analysis'))
            if isinstance(obj,FinancialFact) and obj.company_id!=report.company_id:issues.append(issue('financial',r.result_id,'计算混入其他公司数据','supervisor'))
    for f in report.financial_facts:
        actual_period=bool(re.fullmatch(r'\d{4}(?:A|H1|Q[1-4]|[1-4]Q)|\d{4}-\d{2}-\d{2}',f.period))
        if f.actual_or_forecast=='actual' and not actual_period or f.actual_or_forecast=='forecast' and not re.fullmatch(r'\d{4}E',f.period):issues.append(issue('financial',f.fact_id,'财务事实期间与实际/预测标志不一致','supervisor'))
    for forecast in report.forecasts:
        location=f'{forecast.scenario}/{forecast.period}';b=forecast.balance;c=forecast.cashflow;i=forecast.income
        if not forecast.period.endswith('E'):issues.append(issue('financial',location,'预测期间被标为实际','calculate'))
        if abs(b['assets']-b['liabilities']-b['equity'])>Decimal('.000001'):issues.append(issue('financial',location,'资产负债表不平衡','calculate'))
        if abs(sum(s['revenue'] for s in forecast.segments.values())-i['revenue'])>Decimal('.000001'):issues.append(issue('financial',location,'营业收入分部汇总错误','calculate'))
        if abs(sum(s['cost'] for s in forecast.segments.values())-i['cost'])>Decimal('.000001'):issues.append(issue('financial',location,'营业成本分部汇总错误','calculate'))
        opening_result=next((results[k] for k in forecast.result_ids if k in results and results[k].output_metric=='cash'),None)
        if not opening_result or abs(b['cash']-opening_result.inputs['opening_cash']-c['cfo']-c['cfi']-c['cff'])>Decimal('.000001'):issues.append(issue('financial',location,'现金流与期末现金不勾稽','calculate'))
        forecast_results={results[k].output_metric:results[k] for k in forecast.result_ids if k in results}
        for scope,values in [('income',i),('balance',b),('cashflow',c)]:
            for metric,value in values.items():
                r=forecast_results.get(metric)
                if r and abs(r.value-value)>Decimal('.000001'):issues.append(issue('financial',location+'/'+scope+'/'+metric,'报表数值与计算结果不一致','assemble'))
        if b['cash']<0:issues.append(issue('financial',location,'资金缺口没有可验证融资安排','assumptions'))
    processor=FinancialDataProcessor();periods={f.period for f in report.financial_facts if f.actual_or_forecast=='actual'}
    for period in periods:
        for metric in ['revenue','cost']:
            segment=[f for f in report.financial_facts if f.period==period and f.scope=='segment' and f.metric_code==metric and f.validation_status=='verified']
            if not segment:continue
            # Deduplicate identical evidence rows, reject conflicting values.
            unique={}
            for f in segment:
                if f.segment_id in unique and unique[f.segment_id]!=f.value:issues.append(issue('financial',period+'/'+metric,'历史分部数据冲突','supervisor'))
                unique[f.segment_id]=f.value
            try:
                total=processor.get(report.financial_facts,report.company_id,metric,period)
                if abs(sum(unique.values())-total.value)>Decimal('.000001'):
                    issues.append(issue('financial',period+'/'+metric,'历史分部披露不构成公司口径完整合计；保留原值，限制分部预测','supervisor',
                                        severity='warning' if report.data_template_version else 'critical'))
            except FinancialError:issues.append(issue('financial',period+'/'+metric,'公司口径数据缺失或冲突','supervisor'))
    for section in sections_flat(report.sections):
        for reference,rendered in section.number_bindings.items():
            kind,id=reference.split(':',1);obj=refs.get(id)
            if not obj or number(obj.value,obj.unit)!=rendered or not any(rendered in p for p in section.paragraphs):issues.append(issue('financial',section.section_id,'正文数字与数据引用不一致','core_conclusion' if section.section_id=='core' else 'write_sections'))
        if not set(section.calculation_ids).issubset(results):issues.append(issue('financial',section.section_id,'章节引用不存在的计算结果','write_sections'))
    return issues


def evidence_review(report: ReportDocument):
    issues=[];sources={s.source_id:s for s in report.sources};evidence={e.evidence_id:e for e in report.evidence}
    if not sources:issues.append(issue('evidence','sources','缺少关键来源','supervisor'))
    if report.mode=='real' and any(s.kind=='mock' for s in report.sources):issues.append(issue('evidence','sources','真实报告混入模拟来源','supervisor'))
    if report.mode=='real':
        actual=[f for f in report.financial_facts if f.actual_or_forecast=='actual' and f.scope=='consolidated' and f.company_id==report.company_id and f.validation_status=='verified']
        latest=max((f.period for f in actual if f.period.endswith('A')),default='')
        required={'revenue','cost','parent_net_income','adjusted_parent_net_income','operating_cashflow'} if report.data_template_version else {'revenue','cost','net_income','assets','liabilities','equity','cash'}
        missing=required-{f.metric_code for f in actual if f.period==latest}
        if missing:issues.append(issue('evidence','financial_facts','关键历史财务及来源缺失：'+','.join(sorted(missing)),'supervisor'))
    for e in report.evidence:
        s=sources.get(e.source_id)
        if not s or not e.quote.strip() or e.quote not in s.content or e.validation_status!='verified':issues.append(issue('evidence',e.evidence_id,'引用无法支持事实或原文缺失','supervisor'))
    for f in report.financial_facts:
        e=evidence.get(f.evidence_id)
        if not e or e.source_id!=f.source_id or f.validation_status!='verified':issues.append(issue('evidence',f.fact_id,'财务事实缺少已验证来源','supervisor'))
    for a in report.assumptions:
        if not a.rationale or not a.evidence_ids or not set(a.evidence_ids).issubset(evidence):issues.append(issue('evidence',a.assumption_id,'预测假设缺少依据','assumptions'))
    for s in sections_flat(report.sections):
        if not set(s.evidence_ids).issubset(evidence):issues.append(issue('evidence',s.section_id,'章节引用未知证据','write_sections'))
        if report.mode=='real' and s.section_id in {'company','financial','risk','core'} and not s.evidence_ids and not s.calculation_ids:issues.append(issue('evidence',s.section_id,'关键章节没有依据','write_sections'))
    # Unknown publication date is a visible limitation, not a silently assumed current source.
    if report.mode=='real' and any(s.publication_date is None for s in report.sources):issues.append(issue('evidence','sources','部分来源发布日期未知，请核对时效','supervisor','warning','保留日期未知限制或补充可验证发布日期'))
    if report.mode=='real':
        cutoff=datetime.now(timezone.utc)-timedelta(days=550)
        for source in report.sources:
            if source.kind!='web' or not source.publication_date:continue
            try:
                date=datetime.fromisoformat(source.publication_date.replace('Z','+00:00'))
                if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
                if date<cutoff:issues.append(issue('evidence',source.source_id,'来源较旧，需核对结论时效','supervisor','warning','补充最新公告或解释采用历史资料的原因'))
            except ValueError:issues.append(issue('evidence',source.source_id,'来源发布日期格式不可校验','supervisor','warning','保留日期不可校验限制'))
    return issues


def critical_review(report: ReportDocument):
    issues=[]
    core=next((s for s in report.sections if s.section_id=='core'),None)
    risk=next((s for s in report.sections if s.section_id=='risk'),None)
    if not core or not core.paragraphs:issues.append(issue('critical','core','核心观点缺失','core_conclusion'))
    if not risk or len(risk.paragraphs)<3:issues.append(issue('critical','risk','风险分析不足','write_sections','error'))
    if core and report.mode=='mock' and not any('模拟' in p or '合成' in p for p in core.paragraphs):issues.append(issue('critical','core','核心观点没有披露模拟性质','core_conclusion'))
    if core and risk and any(x in ' '.join(core.paragraphs) for x in ['没有任何风险','不存在风险','保证收益','必然上涨']):issues.append(issue('critical','core','核心观点与风险正文不一致或承诺收益','core_conclusion'))
    if report.rules_version=='1.1' and core:
        keys={'cash_growth','forecast_total','valuation_evidence','resource_concentration'}
        if not keys.issubset(core.consistency_checks) or any(not core.consistency_checks.get(k,'').strip() for k in keys):
            issues.append(issue('critical','core','X01 未回答四类整体一致性检查','core_conclusion'))
        if any(core.consistency_checks.get(k,'').startswith('conflict:') for k in keys):
            issues.append(issue('critical','core','X01 存在未解决重大跨块矛盾','financial_analysis'))
    if report.mode=='real' and not report.forecasts:issues.append(issue('critical','forecast','未生成可验证盈利预测，报告为受限研究','assumptions','warning','说明缺失假设，保留受限状态，不输出虚构预测'))
    if report.forecasts:
        keys={(f.scenario,f.period) for f in report.forecasts};periods={f.period for f in report.forecasts}
        if any((s,p) not in keys for s in ['Bear','Base','Bull'] for p in periods):issues.append(issue('critical','forecast','情景不完整','assumptions','warning','说明缺失情景及原因'))
    return issues


def editorial_review(report: ReportDocument):
    issues=[]
    for s in sections_flat(report.sections):
        if s.section_id not in {'toc','business'} and not s.children and not s.paragraphs and not s.tables:issues.append(issue('editorial',s.section_id,'章节为空','write_sections','error'))
        if len(s.paragraphs)!=len(set(s.paragraphs)):issues.append(issue('editorial',s.section_id,'重复段落','write_sections','error','删除重复内容并保持分析完整'))
        if any('[[' in p or '<script' in p.lower() for p in s.paragraphs):issues.append(issue('editorial',s.section_id,'未解析引用或不可信脚本标记','write_sections','error'))
    return issues


class ReviewState(TypedDict):
    report: dict
    issues: Annotated[list[dict],operator.add]


def review_graph(gateway=None,store=None,run_id=None,mock=False):
    g=StateGraph(ReviewState);nodes=[]
    for name,fn in [('structural',structural_review),('financial',financial_review),('evidence',evidence_review),('critical',critical_review),('editorial',editorial_review)]:
        def reviewer(name,fn):
            async def run(state):
                label={'structural':'报告结构','financial':'财务与三表','evidence':'来源与时效','critical':'研究逻辑','editorial':'语言与完整性'}[name]
                if store:store.emit(run_id,'最终审核','review_'+name,'running',f'独立审核：{label}')
                report=ReportDocument.model_validate(state['report']);issues=fn(report)
                if gateway and not mock and name in {'evidence','critical','editorial'}:
                    # Review a section and its referenced originals, never a full-company dump.
                    for section in sections_flat(report.sections):
                        if not section.paragraphs:continue
                        evidence=[e for e in report.evidence if e.evidence_id in section.evidence_ids]
                        source_ids={e.source_id for e in evidence}
                        from .writers import section_block
                        data={'snapshot_id':report.snapshot_id,'section':section.model_dump(mode='json')|{'block_id':section_block(section.section_id)},
                            'evidence':[e.model_dump(mode='json') for e in evidence],
                            'facts':[f.model_dump(mode='json') for f in report.financial_facts if f.evidence_id in section.evidence_ids],
                            'calculations':[r.model_dump(mode='json') for r in report.calculations if r.result_id in section.calculation_ids],
                            'source_metadata':[s.model_dump(mode='json',exclude={'content'}) for s in report.sources if s.source_id in source_ids],
                            'core_consistency':report.sections[0].consistency_checks}
                        semantic=await ask_bounded(gateway,name+'_reviewer',ReviewOutput,data)
                        for problem in semantic.issues:
                            problem.snapshot_id=report.snapshot_id
                            # Models cannot soften deterministic gates; separate issues only.
                            problem.rule_id='semantic.'+name
                        issues+=semantic.issues
                if store:store.emit(run_id,'最终审核','review_'+name,'completed',f'{label}审核完成，发现 {len(issues)} 项问题')
                return {'issues':[i.model_dump(mode='json') for i in issues]}
            return run
        g.add_node(name,reviewer(name,fn));g.add_edge(START,name);nodes.append(name)
    def finish(state):return {}
    g.add_node('finish',finish);g.add_edge(nodes,'finish');g.add_edge('finish',END)
    return g.compile()


def deterministic_review(report):
    return [i for fn in [structural_review,financial_review,evidence_review,critical_review,editorial_review] for i in fn(report)]
