import json
from types import SimpleNamespace

import pytest

from company_research.datasources import DatasourceError, parse_material
from company_research.schemas import Company, SourceRecord
from test_fixed_collection import prepared


class IdentityGateway:
    def __init__(self, **overrides):
        self.overrides = overrides
        self.calls = []

    def limits(self, role):
        return SimpleNamespace(input_capacity=16000)

    async def structured(self, role, messages, schema):
        data = json.loads(messages[-1]['content'])
        self.calls.append(data)
        return Company(**({'company_id': 'model-guessed-id', 'name': '示例设备股份有限公司',
                           'ticker': '000123', 'source_ids': ['report']} | self.overrides))


def report(content=None, **updates):
    return SourceRecord(**({'source_id': 'report', 'kind': 'upload', 'title': '2025.pdf',
        'content': content or '示例设备股份有限公司2025年年度报告\n公司信息\n公司全称：示例设备股份有限公司\n股票简称：示例设备\n股票代码：000123\n股票上市交易所：深圳证券交易所',
        'locator': 'page:1; page:8'} | updates))


async def resolve(tmp_path, reports, query='示例设备', gateway=None, clear_local=True):
    w, _, store, run = prepared(tmp_path, rows=[])
    if clear_local:
        w.datasource.local.index = []
    w.references = reports
    w.gateway = gateway or IdentityGateway()
    c = {'input': query, 'run_id': run.run_id}
    c.update(await w.resolve_company(c))
    return w, c, store, run


@pytest.mark.parametrize('query', ['示例设备', '示例设备股份有限公司', '000123'])
async def test_uploaded_annual_resolves_without_local_master(tmp_path, query):
    w, c, store, run = await resolve(tmp_path, [report()], query)
    assert c['company']['company_id'] == 'A股:000123'
    assert c['company']['ticker'] == '000123'
    assert c['company']['source_ids'] == ['report']
    assert store.run(run.run_id).company_name == '示例设备股份有限公司'
    assert {s['kind'] for s in w.gateway.calls[0]['sources']} == {'upload'}


async def test_annual_identity_takes_priority_over_local_master(tmp_path):
    _, c, _, _ = await resolve(tmp_path, [report()], query='000123', clear_local=False)
    assert c['company']['name'] == '示例设备股份有限公司'
    assert c['company']['source_ids'] == ['report']
    assert c['company']['company_id'] == 'FIX'  # Existing data joins remain usable.


@pytest.mark.parametrize('overrides', [
    {'ticker': '600999'}, {'name': '不存在的公司'}, {'source_ids': []},
    {'source_ids': ['research-note']}, {'ticker': '123'},
])
async def test_unsubstantiated_model_identity_is_rejected(tmp_path, overrides):
    with pytest.raises(DatasourceError, match='上传年报不足以确认'):
        await resolve(tmp_path, [report()], gateway=IdentityGateway(**overrides))


async def test_unrelated_company_input_is_rejected(tmp_path):
    with pytest.raises(DatasourceError, match='上传年报不足以确认'):
        await resolve(tmp_path, [report()], query='别的公司')


async def test_notes_and_interim_reports_cannot_supply_annual_identity(tmp_path):
    notes = [report(title='示例设备2025年报点评研究报告'),
             report(title='示例设备2026年半年度报告', source_id='interim')]
    with pytest.raises(DatasourceError, match='请上传包含公司全称'):
        await resolve(tmp_path, notes)


async def test_pdf_page_whitespace_is_tolerated(tmp_path):
    source = report().model_copy(update={'content': report().content.replace('示例设备股份有限公司', '示例设备股份有限\n公司')})
    _, c, _, _ = await resolve(tmp_path, [source])
    assert c['company']['ticker'] == '000123'


async def test_structured_annual_identity_needs_no_model_or_local_data(tmp_path):
    body = {'document_type': 'annual_report', 'company_id': 'CUSTOM',
            'company_name': '示例设备股份有限公司', 'security_name': '示例设备', 'ticker': '000123',
            'facts': [{'field_id': 'income.revenue', 'period': '2025A', 'value': '100', 'unit': 'CNY'}]}
    chunks = parse_material(json.dumps(body).encode(), '.json')
    source = report(chunks[0][1], title='annual.json')
    w, c, _, _ = await resolve(tmp_path, [source])
    assert c['company']['company_id'] == 'CUSTOM'
    assert not w.gateway.calls


async def test_annual_identity_populates_security_slots_without_local_master(tmp_path):
    w, _, store, run = prepared(tmp_path)
    w.datasource.local.index = []
    c = {'input': '000123', 'run_id': run.run_id}
    c.update(await w.resolve_company(c))
    c['brief'] = {'company_id': 'FIX', 'scope': 'test', 'historical_periods': ['2023A', '2024A', '2025A'],
                  'forecast_periods': ['2026E', '2027E', '2028E'], 'segments': ['设备'], 'industries': {'设备': '制造业'}}
    c.update(await w.research_plan(c))
    slots = {s['field_id']: s for s in store.records(run.run_id, 'data_slot') if s['field_id'].startswith('security.')}
    for key in ['security.company_name', 'security.ticker']:
        assert slots[key]['state'] == 'locked'
        assert slots[key]['source_id'] in c['company']['source_ids']
    assert slots['security.price']['state'] != 'locked'
