from decimal import Decimal as D
import pytest
from company_research.financials import Calculator,DependencyResolver,FinancialError,ForecastEngine,validate_forecast
from company_research.financials.formulas import REGISTRY,FinancialDataProcessor
from company_research.schemas import CalculationPlan,CalculationRequest,ForecastAssumption,FinancialFact


@pytest.mark.parametrize('formula,inputs,expected,unit',[
 ('yoy',{'current':120,'previous':100},'.2','ratio'),('cagr',{'start':100,'end':121,'years':2},'.1','ratio'),
 ('gross_margin',{'revenue':100,'cost':60},'.4','ratio'),('roe',{'net_income':10,'average_equity':50},'.2','ratio'),
 ('roic',{'ebit':20,'tax_rate':'.25','average_invested_capital':100},'.15','ratio'),
 ('pe',{'price':20,'eps':2},'10','times'),('pb',{'price':20,'shares':10,'equity':100},'2','times'),
 ('volume_price',{'volume':10,'price':20},'200','CNY_million'),('capacity_utilization',{'capacity':10,'utilization':'.5','price':20},'100','CNY_million'),
 ('users_arpu',{'users':2,'arpu':50},'100','CNY_million'),('market_share',{'market_size':1000,'share':'.1'},'100','CNY_million'),('growth',{'previous':100,'growth_rate':'.1'},'110','CNY_million'),
 ('net_margin',{'net_income':10,'revenue':100},'.1','ratio'),('operating_margin',{'ebit':20,'revenue':100},'.2','ratio'),
 ('debt_to_assets',{'liabilities':40,'assets':100},'.4','ratio'),('current_ratio',{'current_assets':100,'current_liabilities':50},'2','times'),
 ('quick_ratio',{'current_assets':100,'inventory':20,'current_liabilities':40},'2','times'),('inventory_turnover',{'cost':100,'average_inventory':20},'5','times'),
 ('receivables_turnover',{'revenue':100,'average_receivables':25},'4','times'),('asset_turnover',{'revenue':100,'average_assets':50},'2','times'),
 ('fcf',{'operating_cashflow':50,'capex':20},'30','CNY_million'),('eps',{'net_income':20,'shares':10},'2','CNY/share'),
 ('ev_ebitda',{'price':10,'shares':10,'debt':20,'cash':10,'ebitda':22},'5','times')])
def test_formulas(formula,inputs,expected,unit):
    r=Calculator().calculate(formula,inputs,period='2025A',unit=unit)
    assert abs(r.value-D(expected))<D('.00000001')
    assert Calculator().recompute(r)


def assumptions(scenario='Base',period='2026E'):
    values={'cost_ratio':'.6','opex_ratio':'.15','tax_rate':'.25','depreciation':20,'capex':30,'receivables_ratio':'.1','inventory_ratio':'.1','payables_ratio':'.1','borrowing':10,'repayment':5,'interest_rate':'.05','payout_ratio':'.2','shares':100,'target_pe':15}
    return [ForecastAssumption(metric_code=k,period=period,value=v,unit='ratio' if 'ratio' in k or 'rate' in k else 'CNY_million',scenario=scenario,rationale='测试假设',evidence_ids=['e']) for k,v in values.items()]


OPENING={k:D(str(v)) for k,v in {'cash':100,'receivables':100,'inventory':60,'ppe':200,'other_assets':40,'payables':60,'debt':100,'other_liabilities':40,'equity':300}.items()}


@pytest.mark.parametrize('scenario,growth',[('Bear','0'),('Base','.1'),('Bull','.2')])
def test_forecast(scenario,growth):
    forecast,results=ForecastEngine().forecast('c','2026E',scenario,OPENING,{'设备':{'model':'growth','inputs':{'previous':600,'growth_rate':growth}},'服务':{'model':'growth','inputs':{'previous':400,'growth_rate':growth}}},assumptions(scenario))
    assert forecast.income['revenue']==1000*(1+D(growth))
    assert not validate_forecast(forecast,OPENING)
    assert all(Calculator().recompute(r) for r in results)
    assert forecast.balance['cash']==OPENING['cash']+sum(forecast.cashflow[k] for k in ['cfo','cfi','cff'])


def test_missing_units_periods_conflicts():
    with pytest.raises(FinancialError):Calculator().calculate('eps',{'net_income':10},period='2025A',unit='CNY/share')
    with pytest.raises(FinancialError):Calculator().calculate('pe',{'price':10,'eps':0},period='2025A',unit='times')
    with pytest.raises(FinancialError):Calculator().calculate('yoy',{'current':10,'previous':5},period='2025A',unit='CNY')
    f=FinancialFact(company_id='c',metric_code='营业收入',period='2025A',unit='CNY_100million',value=10,actual_or_forecast='actual',source_id='s',evidence_id='e',locator='row:2',validation_status='verified')
    p=FinancialDataProcessor();assert p.normalize(f).value==1000
    for period in ['2024A','2025E']:
        with pytest.raises(FinancialError):p.get([f],'c','revenue',period)
    with pytest.raises(FinancialError):p.get([f,f.model_copy(update={'value':D(11)})],'c','revenue','2025A')
    bad={**OPENING,'equity':D(0)}
    with pytest.raises(FinancialError,match='不平衡'):ForecastEngine().forecast('c','2026E','Base',bad,{},assumptions())


def test_dependencies_and_cycles():
    plan=CalculationPlan(company_id='c',forecast_model='growth',calculations=[CalculationRequest(formula_id='pe',output_metric='pe',period='2025A',unit='times',inputs={'eps':'formula:eps'}),CalculationRequest(formula_id='eps',output_metric='eps',period='2025A',unit='CNY/share')])
    data=DependencyResolver().resolve(plan)
    assert {d.metric_code for d in data}=={'price','net_income','shares'}
    assert len(data)==3
    bad=plan.model_copy(update={'calculations':[CalculationRequest(formula_id='pe',output_metric='pe',period='2025A',unit='times',inputs={'eps':'formula:pe'})]})
    with pytest.raises(FinancialError,match='环'):DependencyResolver().resolve(bad)
    with pytest.raises(FinancialError):DependencyResolver().resolve(plan.model_copy(update={'calculations':[CalculationRequest(formula_id='imaginary',output_metric='x',period='2025A',unit='ratio')]}))
