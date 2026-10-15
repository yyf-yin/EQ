from types import SimpleNamespace

import pytest

from company_research.config import Settings
from company_research.financials import FinancialError
from company_research.graphs import ResearchWorkflow, brief_business_support
from company_research.schemas import ResearchBrief, ResearchRun, SourceRecord
from company_research.storage import Store


def brief(segments=None, source_ids=None):
    return ResearchBrief(
        company_id='600519', scope='公司研究',
        historical_periods=['2023A', '2024A', '2025A'],
        forecast_periods=['2026E', '2027E', '2028E'],
        segments=segments or ['茅台酒', '系列酒'], source_ids=source_ids or [],
    )


def sources():
    return [SourceRecord(source_id=id, kind='local', title=id, content=content).model_dump(mode='json')
            for id, content in [('s1', '主营产品为茅台酒。'), ('s2', '系列\n酒的生产与销售。')]]


def test_businesses_can_have_separate_sources_and_layout_whitespace():
    support, errors = brief_business_support(brief(), sources())
    assert not errors
    assert support == {'茅台酒': ['s1'], '系列酒': ['s2']}


def test_only_cited_bodies_support_businesses():
    support, errors = brief_business_support(brief(source_ids=['s1']), sources())
    assert support['系列酒'] == []
    assert errors == ['业务清单没有来源支持：系列酒']
    rows = sources()
    rows[1]['content'] = '未披露相关业务'
    rows[1]['title'] = '系列酒'
    assert brief_business_support(brief(), rows)[1]


def test_unknown_sources_and_invented_names_are_rejected():
    _, errors = brief_business_support(brief(source_ids=['s1', 's2', 'fake']), sources())
    assert errors == ['Brief 引用未知来源：fake']
    assert brief_business_support(brief(['茅台酒业务']), sources())[1]
    assert brief_business_support(brief(['   ']), sources())[1]


@pytest.fixture
def workflow(tmp_path):
    settings = Settings(database=tmp_path/'db', local_sources=tmp_path/'local',
                        artifacts=tmp_path/'out', plan_repairs=2)
    store = Store(settings.database)
    run = ResearchRun(company_input='贵州茅台', mode='real')
    store.save_run(run)
    # Exercise the real brief node without initiating network retrieval.
    result = ResearchWorkflow.__new__(ResearchWorkflow)
    result.settings, result.store, result.run_id = settings, store, run.run_id
    result.mock = False
    result.gateway = SimpleNamespace(limits=lambda role: SimpleNamespace(input_capacity=20000))
    return result


def context():
    return {'company': {'company_id': '600519', 'name': '贵州茅台'},
            'sources': sources(), 'facts': []}


async def test_repair_names_and_persist_attempts(workflow, monkeypatch):
    requests = []

    async def ask(gateway, role, schema, request):
        requests.append(request)
        return brief(['茅台酒业务', '系列酒']) if len(requests) == 1 else brief()

    monkeypatch.setattr('company_research.graphs.ask', ask)
    output = await workflow.research_brief(context())
    assert output['brief']['segments'] == ['茅台酒', '系列酒']
    assert output['brief']['source_ids'] == ['s1', 's2']
    assert requests[1]['validation_errors'] == ['业务清单没有来源支持：茅台酒业务']
    records = workflow.store.records(workflow.run_id, 'brief_validation')
    assert len(records) == 2
    assert records[0]['brief']['segments'][0] == '茅台酒业务'
    assert records[1]['segment_sources'] == {'茅台酒': ['s1'], '系列酒': ['s2']}
    assert not records[1]['errors']


async def test_exhausted_repairs_still_block_with_specific_missing_business(workflow, monkeypatch):
    requests = []

    async def ask(gateway, role, schema, request):
        requests.append(request)
        return brief(['虚构业务'])

    monkeypatch.setattr('company_research.graphs.ask', ask)
    with pytest.raises(FinancialError, match='业务清单没有来源支持：虚构业务'):
        await workflow.research_brief(context())
    assert len(requests) == 3
    assert len(workflow.store.records(workflow.run_id, 'brief_validation')) == 3
