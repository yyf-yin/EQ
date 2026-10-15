from decimal import Decimal
from .schemas import ResearchPlan,ResearchTask,CalculationPlan,CalculationRequest,ForecastAssumption,FinancialFact
from .financials.formulas import REGISTRY,INPUT_UNITS,input_unit,FinancialDataProcessor,FinancialError,Calculator
from .financials.forecast import ASSUMPTION_KEYS,OPENING_KEYS

ASSUMPTION_UNITS={k:'ratio' if k.endswith('_ratio') or k.endswith('_rate') else 'million_shares' if k=='shares' else 'times' if k=='target_pe' else 'CNY_million' for k in ASSUMPTION_KEYS}


def mock_research_plan() -> ResearchPlan:
    tasks=[ResearchTask(task_id=f'demo-{i}',company_id='DEMO',topic=topic,role=role,queries=[query],segment_id=segment) for i,(topic,role,query,segment) in enumerate([
        ('公司概况与竞争力','company','示例制造公司',None),('历史财务及现金质量','financial','DEMO revenue',None),('设备业务及行业','business','设备行业','设备'),('服务业务及行业','business','服务行业','服务'),('预测与估值依据','financial','模拟预测依据',None),('经营与财务风险','company','风险资料',None)])]
    return ResearchPlan(company_id='DEMO',segments=['设备','服务'],tasks=tasks)


def mock_calculation_plan() -> CalculationPlan:
    requests=[]
    for id in ['yoy','gross_margin','net_margin','operating_margin','roe','roic','debt_to_assets','current_ratio','quick_ratio','inventory_turnover','receivables_turnover','asset_turnover','fcf','eps','pe','pb','ev_ebitda']:
        bindings={}
        if id=='yoy':bindings={'current':'revenue@2025A','previous':'revenue@2024A'}
        if id=='cagr':bindings={'start':'revenue@2023A','end':'revenue@2025A','years':'years@2025A'}
        if id=='pe':bindings={'eps':'formula:eps'}
        requests.append(CalculationRequest(formula_id=id,output_metric=id,period='2025A',unit=REGISTRY[id].unit,inputs=bindings))
    return CalculationPlan(company_id='DEMO',calculations=requests,forecast_model='growth')


def mock_assumptions(evidence_id: str,periods: list[str]) -> list[ForecastAssumption]:
    result=[]
    for scenario,growth,cost_ratio,pe in [('Bear','.02','.65',12),('Base','.1','.6',15),('Bull','.18','.57',18)]:
        for period in periods:
            values={'cost_ratio':cost_ratio,'opex_ratio':'.15','tax_rate':'.25','depreciation':20,'capex':30,'receivables_ratio':'.1','inventory_ratio':'.1','payables_ratio':'.1','borrowing':10,'repayment':5,'interest_rate':'.05','payout_ratio':'.2','shares':100,'target_pe':pe}
            for k,v in values.items():
                result.append(ForecastAssumption(metric_code=k,period=period,value=v,unit=ASSUMPTION_UNITS[k],scenario=scenario,rationale='合成测试场景，全部参数由 Fixture 指定，不代表真实企业预测。',evidence_ids=[evidence_id]))
            for segment in ['设备','服务']:
                result.append(ForecastAssumption(metric_code='growth_rate',period=period,value=growth,unit='ratio',scenario=scenario,rationale='模拟需求情景假设，非真实公司数据。',evidence_ids=[evidence_id],segment_id=segment))
    return result


def execute_calculation_plan(plan: CalculationPlan,facts: list[FinancialFact],cached=()):
    processor=FinancialDataProcessor();calculator=Calculator();results=[];missing=[]
    from .framework import digest
    from .schemas import CalculationResult
    def signature(r):return digest([r.formula_id,r.formula_version,r.output_metric,r.period,r.unit,r.inputs,r.input_refs,r.scenario,r.segment_id])
    cache={signature(r):r for raw in cached for r in [CalculationResult.model_validate(raw)] if calculator.recompute(r)}
    def resolve(id,period,bindings,trail,output_metric=None):
        if id in trail:raise FinancialError('计算依赖图有环')
        if id not in REGISTRY:raise FinancialError(f'未注册公式 {id}')
        f=REGISTRY[id];values={};refs={}
        for argument in f.inputs:
            metric=bindings.get(argument,argument)
            if metric.startswith('formula:'):
                ref=metric[8:];nested_period=period
                if '@' in ref:ref,nested_period=ref.rsplit('@',1)
                nested=resolve(ref,nested_period,{},trail+[id]);values[argument]=nested.value;refs[argument]=nested.result_id;continue
            p=period
            if '@' in metric:metric,p=metric.rsplit('@',1)
            fact=processor.get(facts,plan.company_id,metric,p,input_unit(id,argument))
            values[argument],refs[argument]=fact.value,fact.fact_id
        key=digest([id,f.version,output_metric or id,period,f.unit,values,refs,'historical',None])
        result=cache.get(key)
        if result is None:result=calculator.calculate(id,values,period=period,unit=f.unit,input_refs=refs,output_metric=output_metric)
        results.append(result);return result
    for request in plan.calculations:
        try:
            result=resolve(request.formula_id,request.period,request.inputs,[],request.output_metric)
        except (FinancialError,KeyError,ArithmeticError) as exc:missing.append(str(exc))
    return results,missing
