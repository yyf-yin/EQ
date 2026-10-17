"""Incomplete segment disclosure and minority interest limit the model, not the whole forecast."""
from decimal import Decimal as D
from types import SimpleNamespace
from company_research import graphs
from company_research.agents import AssumptionOutput
from company_research.config import Settings
from company_research.financials import Calculator, ForecastEngine, validate_forecast
from company_research.financials.forecast import COMPANY_SEGMENT, SEGMENT_FALLBACK_NOTE, forecast_segments
from company_research.graphs import ResearchWorkflow
from company_research.planners import mock_assumptions
from company_research.schemas import FinancialFact, ForecastAssumption, ResearchRun
from company_research.storage import Store

OPENING = {'cash': 100, 'receivables': 100, 'inventory': 60, 'ppe': 200, 'other_assets': 40,
           'payables': 60, 'debt': 100, 'other_liabilities': 40, 'equity': 300}


def fact(metric, value, period='2025A', segment=None):
    return FinancialFact(company_id='C', metric_code=metric, period=period, unit='CNY_million', value=D(str(value)),
                         actual_or_forecast='actual', source_id='s', evidence_id='ev-1', locator='row',
                         validation_status='verified', scope='segment' if segment else 'consolidated', segment_id=segment)


def company_facts(**extra):
    values = OPENING | {'revenue': 1000, 'net_income': 150, 'parent_net_income': 145, 'assets': 500} | extra
    return [fact(k, v) for k, v in values.items()]


def test_incomplete_or_non_additive_segments_fall_back_to_company_level():
    facts = company_facts() + [fact('revenue', 870, segment='甲')]
    segments, historical, note = forecast_segments(facts, 'C', '2025A', ['甲', '乙'])
    assert segments == [COMPANY_SEGMENT] and note == SEGMENT_FALLBACK_NOTE
    assert historical[COMPANY_SEGMENT].value == 1000
    complete = facts + [fact('revenue', 100, segment='乙')]
    assert forecast_segments(complete, 'C', '2025A', ['甲', '乙'])[0] == ['甲', '乙']
    # 870 + 100 != 1000: only a strict caller falls back, originals stay untouched.
    assert forecast_segments(complete, 'C', '2025A', ['甲', '乙'], require_total=True)[0] == [COMPANY_SEGMENT]
    assert forecast_segments(company_facts(), 'C', '2025A', [])[0] == [COMPANY_SEGMENT]


def test_minority_ratio_splits_parent_income_for_eps_and_dividends():
    assumptions = [a for a in mock_assumptions('e', ['2026E'], [COMPANY_SEGMENT]) if a.scenario == 'Base']
    assumptions.append(ForecastAssumption(metric_code='minority_ratio', period='2026E', value=D('.05'), unit='ratio',
                                          scenario='Base', rationale='历史少数股东损益占比', evidence_ids=['e']))
    opening = {k: D(v) for k, v in OPENING.items()}
    drivers = {COMPANY_SEGMENT: {'model': 'growth', 'inputs': {'previous': 1000, 'growth_rate': '.1'}}}
    forecast, results = ForecastEngine().forecast('C', '2026E', 'Base', opening, drivers, assumptions)
    i = forecast.income
    assert i['revenue'] == 1100 and i['minority_net_income'] == i['net_income'] * D('.05')
    assert i['parent_net_income'] == i['net_income'] - i['minority_net_income']
    assert i['eps'] == i['parent_net_income'] / 100
    assert forecast.cashflow['dividends'] == i['parent_net_income'] * D('.2')
    assert not validate_forecast(forecast, opening)
    assert all(Calculator().recompute(r) for r in results)
    plain, _ = ForecastEngine().forecast('C', '2026E', 'Base', opening, drivers, assumptions[:-1])
    assert 'parent_net_income' not in plain.income and plain.income['eps'] == plain.income['net_income'] / 100


async def test_fixed_run_with_partial_segments_still_forecasts_three_scenarios(tmp_path, monkeypatch):
    settings = Settings(database=tmp_path / 'db', artifacts=tmp_path / 'out', mock_delay=0)
    store = Store(settings.database)
    run = ResearchRun(company_input='分部不完整', mode='mock')
    store.save_run(run)
    workflow = ResearchWorkflow(settings, store, run.run_id)
    workflow.mock = False
    periods = ['2026E', '2027E', '2028E']
    requests = []

    async def answer(gateway, role, schema, context, max_splits=0):
        requests.append(context)
        scenario, period = context['selected_scenario'], context['selected_period']
        # The disclosed segment's driver must be dropped, not forecast.
        values = [a for a in mock_assumptions('ev-1', [period], [COMPANY_SEGMENT, '甲']) if a.scenario == scenario]
        values.append(ForecastAssumption(metric_code='minority_ratio', period=period, value=D('.03'), unit='ratio',
                                         scenario=scenario, rationale='历史少数股东损益占比', evidence_ids=['ev-1']))
        return AssumptionOutput(assumptions=values, segment_models={'甲': 'volume_price'}, limitations=[])

    monkeypatch.setattr(graphs, 'ask_bounded', answer)
    monkeypatch.setattr(graphs, 'block_context', lambda *a, **k: SimpleNamespace(content={'financial_facts': []}))
    facts = company_facts() + [fact('revenue', 77724, period='2026H1', segment='甲')]
    c = {'data_template_version': 'fixed-slots-2', 'company': {'company_id': 'C'}, 'limitations': [],
         'facts': [f.model_dump(mode='json') for f in facts], 'evidence': [{'evidence_id': 'ev-1'}],
         'brief': {'historical_periods': ['2023A', '2024A', '2025A'], 'forecast_periods': periods,
                   'segments': ['甲', '乙']},
         'calculations': []}
    c.update(await workflow.assumptions(c))
    assert len(requests) == 9 and requests[0]['forecast_segments'] == [COMPANY_SEGMENT]
    assert 'minority_ratio' in requests[0]['required_assumption_keys']
    assert c['segment_models'] == {COMPANY_SEGMENT: 'growth'}
    assert not any(a['segment_id'] == '甲' for a in c['assumptions'])
    c.update(await workflow.calculate(c))
    assert {(f['scenario'], f['period']) for f in c['forecasts']} == {(s, p) for s in ['Bear', 'Base', 'Bull'] for p in periods}
    assert all(set(f['segments']) == {COMPANY_SEGMENT} for f in c['forecasts'])
    assert SEGMENT_FALLBACK_NOTE in c['limitations']
    assert {r['scenario'] for r in c['calculations']} == {'Bear', 'Base', 'Bull'}

    # Immaterial leases stay in the simplified model; material ones still stop it.
    def lease(code, value):
        store.record(run.run_id, 'data_slot', code, {'slot_id': code, 'field_id': 'balance.' + code, 'period': '2025A',
                     'state': 'locked', 'normalized_value': value, 'segment_id': None, 'bond_id': None})
    lease('lease_liabilities', '2')
    assert workflow.fixed_collection.forecast_limit(c) is None
    lease('current_debt_leases', '58')
    assert '租赁' in workflow.fixed_collection.forecast_limit(c)

    # Without the explicit minority split a fixed-template forecast is withheld, not misstated.
    c['assumptions'] = [a for a in c['assumptions'] if a['metric_code'] != 'minority_ratio']
    c['calculations'] = []
    result = await workflow.calculate(c)
    assert not result['forecasts'] and any('minority_ratio' in x for x in result['limitations'])
