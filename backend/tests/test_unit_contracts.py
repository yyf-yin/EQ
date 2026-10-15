from decimal import Decimal
import pytest
from company_research.financials.formulas import DependencyResolver,FinancialError
from company_research.planners import execute_calculation_plan
from company_research.schemas import CalculationPlan,CalculationRequest,FinancialFact


def test_product_price_not_stock_price():
    plan=CalculationPlan(company_id='c',forecast_model='volume_price',calculations=[CalculationRequest(formula_id='volume_price',output_metric='revenue',period='2025A',unit='CNY_million')])
    requirements=DependencyResolver().resolve(plan)
    assert next(d.unit for d in requirements if d.metric_code=='price')=='CNY/unit'
    def fact(metric,value,unit):return FinancialFact(company_id='c',metric_code=metric,value=value,unit=unit,period='2025A',actual_or_forecast='actual',source_id='s',evidence_id='e',locator='row',validation_status='verified')
    facts=[fact('volume',10,'million_units'),fact('price',20,'CNY/share')]
    results,errors=execute_calculation_plan(plan,facts)
    assert not results and errors
    results,errors=execute_calculation_plan(plan,[facts[0],fact('price',20,'CNY/unit')])
    assert not errors and results[0].value==200
