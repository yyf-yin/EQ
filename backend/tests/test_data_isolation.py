import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from company_research.api import create_app
from company_research.config import Settings
from company_research.evidence import EvidenceStore
from company_research.execution import RecoveryError, ensure_manifest, recovery_info, unit
from company_research.financials.formulas import FinancialError
from company_research.graphs import ResearchWorkflow
from company_research.isolation import POLICY, ensure_isolation, isolation_info
from company_research.reports import mock_report
from company_research.runner import Runner
from company_research.schemas import Company, ResearchRun, SourceRecord
from company_research.storage import Store
from company_research.datasources import WebAdapter
from company_research.work_products import capture_snapshot, export_snapshot, WorkProductError


def config(tmp_path, **kwargs):
    # These legacy fixtures exercise the original generic retrieval contract.
    return Settings(mode='real', data_collection_mode='legacy', database=tmp_path/'research.sqlite', artifacts=tmp_path/'artifacts',
                    local_sources=tmp_path/'local', search_url='https://fixture.test', mock_delay=0, **kwargs)


@pytest.mark.parametrize('status', ['running', 'interrupted', 'failed', 'blocked', 'completed', 'limited'])
async def test_same_company_other_runs_never_enter_new_or_replayed_task(tmp_path, monkeypatch, status):
    settings = config(tmp_path)
    store = Store(settings.database)
    old = ResearchRun(company_input='revenue', mode='real', status=status)
    store.save_run(old)
    old_source = SourceRecord(kind='local', title='old', content=json.dumps({
        'company_id':'D', 'metric_code':'revenue', 'period':'2025A', 'unit':'CNY_million',
        'value':999, 'actual_or_forecast':'actual'}))
    EvidenceStore(store, old.run_id).ingest_structured(old_source)
    settings.local_sources.mkdir()
    (settings.local_sources/'current.json').write_text(json.dumps({
        'company_id':'D', 'metric_code':'revenue', 'period':'2025A', 'unit':'CNY_million',
        'value':100, 'actual_or_forecast':'actual'}), encoding='utf-8')
    run = ResearchRun(company_input='revenue', mode='real')
    store.save_run(run)
    gateway = SimpleNamespace(attach_store=lambda *args: None, resolve=lambda role: None,
                              limits=lambda role: SimpleNamespace(input_capacity=16000))
    workflow = ResearchWorkflow(settings, store, run.run_id, gateway)
    sources = workflow.datasource.local.index
    queries = []
    async def retrieve(query):
        queries.append(query)
        return sources, []
    async def ask(*args, **kwargs):
        return Company(company_id='D', name='current', ticker='D', source_ids=[sources[0].source_id])
    monkeypatch.setattr(workflow.datasource, 'retrieve', retrieve)
    monkeypatch.setattr('company_research.graphs.ask', ask)
    inputs = {'input':run.company_input, 'run_id':run.run_id}
    result = await unit(store, run.run_id, 'node', 'resolve_company', inputs,
                        lambda: workflow.resolve_company(inputs))
    for _ in range(3):
        async def forbidden():
            raise AssertionError('Successful original-task results must be replayed')
        assert await unit(Store(settings.database), run.run_id, 'node', 'resolve_company', inputs, forbidden) == result
    assert len(queries) == 1
    assert {f['value'] for f in result['facts']} == {'100'}
    assert old_source.source_id not in {s['source_id'] for s in result['sources']}
    assert not store.records(run.run_id, 'reuse')
    assert {f['value'] for f in store.records(old.run_id, 'fact')} == {'999'}


async def test_multiple_failures_reuse_only_exact_inputs_of_original_run(tmp_path):
    store = Store(tmp_path/'db')
    count = {}
    async def produce(label):
        count[label] = count.get(label, 0) + 1
        return {'value':label}
    async def attempt(run_id, label, fail):
        first = await unit(store, run_id, 'search', 'identity', {'query':'same'}, lambda: produce(label))
        async def finish():
            if fail:raise RuntimeError('interruption')
            return first
        return await unit(store, run_id, 'node', 'finish', {'source':first}, finish)
    for _ in range(2):
        with pytest.raises(RuntimeError):await attempt('a', 'own', True)
    assert await attempt('b', 'other', False) == {'value':'other'}
    assert await attempt('a', 'own', False) == {'value':'own'}
    assert count == {'own':1, 'other':1}
    assert await unit(store, 'a', 'search', 'identity', {'query':'changed'}, lambda: produce('new')) == {'value':'new'}


@pytest.mark.parametrize('reuse_marker', [True, False])
async def test_legacy_mixed_or_unproven_runs_block_resume_and_formal_download(tmp_path, reuse_marker):
    settings = config(tmp_path)
    app = create_app(settings)
    store = app.state.store
    run = ResearchRun(company_input='legacy', mode='real', status='interrupted', rules_version='1.1')
    store.save_run(run)
    store.record(run.run_id, 'fact', 'old', {'fact_id':'old', 'value':'999'})
    if reuse_marker:store.record(run.run_id, 'reuse', 'old', {'fact_id':'old'})
    store.save_report(run.run_id, mock_report('legacy'))
    before = store.work_product_state(run.run_id)
    assert not recovery_info(settings, store, run.run_id)['can_resume']
    with pytest.raises(RecoveryError):ensure_isolation(store, run.run_id)
    assert store.work_product_state(run.run_id) == before
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post(f'/api/research/{run.run_id}/resume')).status_code == 409
        store.transition_run(run.run_id, {'interrupted'}, status='completed')
        assert (await client.get(f'/api/research/{run.run_id}/report')).status_code == 409
        assert (await client.get(f'/api/research/{run.run_id}/download')).status_code == 409
        state = (await client.get(f'/api/research/{run.run_id}')).json()
        assert state['formats'] == [] and state['recovery']['data_isolation']['status'] == 'blocked'
        evaluation = (await client.get(f'/api/research/{run.run_id}/work-product')).json()
        assert not evaluation['final_review_passed'] and evaluation['data_isolation']['status'] == 'blocked'
    snapshot = capture_snapshot(store, run.run_id, settings.work_product_max_bytes)
    assert snapshot['data']['fact'][0]['value'] == '999'
    exported, _ = export_snapshot(snapshot, 'json', settings.work_product_max_bytes)
    assert json.loads(exported)['data_isolation']['status'] == 'blocked'
    import io
    from zipfile import ZipFile
    package, _ = export_snapshot(snapshot, 'zip', settings.work_product_max_bytes)
    with ZipFile(io.BytesIO(package)) as archive:
        assert json.loads(archive.read('manifest.json'))['data_isolation']['status'] == 'blocked'
    # Saved snapshots from before the guard cannot bypass it.
    store.save_work_product_snapshot(run.run_id, '0'*64, {'final_review_passed':True})
    with pytest.raises(WorkProductError):capture_snapshot(store, run.run_id, settings.work_product_max_bytes, '0'*64)


async def test_startup_blocks_legacy_before_loading_models_or_running_graph(tmp_path, monkeypatch):
    settings = config(tmp_path)
    app = create_app(settings)
    store = app.state.store
    run = ResearchRun(company_input='old', mode='real', status='running')
    store.save_run(run)
    store.record(run.run_id, 'reuse', 'f', {'fact_id':'f'})
    def forbidden(*args):raise AssertionError('Unisolated task must not load a model or graph')
    monkeypatch.setattr('company_research.runner.load_gateway', forbidden)
    async with app.router.lifespan_context(app):
        result = store.run(run.run_id)
        assert result.status == 'interrupted' and result.stop_reason == 'restart'
        assert not recovery_info(settings, store, run.run_id)['can_resume']
    assert store.records(run.run_id, 'reuse') == [{'fact_id':'f'}]


def test_policy_cannot_be_copied_between_tasks_and_reuse_cannot_be_blessed(tmp_path):
    store = Store(tmp_path/'db')
    run = ResearchRun(company_input='new', mode='real')
    store.save_run(run)
    ensure_isolation(store, run.run_id)
    policy = store.execution_get(run.run_id, 'execution_meta', 'data-isolation')
    assert policy == {'version':POLICY, 'run_id':run.run_id}
    other = ResearchRun(company_input='new', mode='real')
    store.save_run(other)
    store.execution_put(other.run_id, 'execution_meta', 'data-isolation', policy)
    with pytest.raises(RecoveryError):ensure_isolation(store, other.run_id)
    store.record(run.run_id, 'reuse', 'f', {'fact_id':'f'})
    assert isolation_info(store, run.run_id)['status'] == 'blocked'


@pytest.mark.parametrize('kind,field,original,replacement', [
    ('source','content','original','changed'), ('evidence','quote','original','changed'),
    ('fact','value','100','999'), ('fact','company_id','A','B'), ('fact','period','2025A','2024A'),
])
def test_same_id_cannot_overwrite_saved_identity_even_after_restart(tmp_path, kind, field, original, replacement):
    store = Store(tmp_path/'db')
    store.record('a', kind, 'id', {field:original})
    restarted = Store(store.path)
    with pytest.raises(FinancialError):restarted.record('a', kind, 'id', {field:replacement})
    assert restarted.records('a', kind) == [{field:original}]
    restarted.record('b', kind, 'id', {field:replacement})
    assert restarted.records('b', kind) == [{field:replacement}]


async def test_search_and_document_caches_are_run_scoped(tmp_path, monkeypatch):
    store = Store(tmp_path/'db')
    calls = []
    class Provider:
        async def search(self, query):
            calls.append('search')
            return [{'url':'https://example.com/source.txt', 'title':str(len(calls))}]
    def response(request):
        calls.append('read')
        return httpx.Response(200, content=f'document {len(calls)}', headers={'Content-Type':'text/plain'})
    async def public(url):pass
    monkeypatch.setattr('company_research.datasources.validate_public_url', public)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        first = WebAdapter(Provider(), store, client, run_id='a')
        item = (await first.search('same'))[0]
        doc = await first.read(item)
        again = WebAdapter(Provider(), store, client, run_id='a')
        assert await again.search('same') == [item] and await again.read(item) == doc
        second = WebAdapter(Provider(), store, client, run_id='b')
        assert await second.search('same') != [item]
        assert await second.read(item) != doc
    assert calls == ['search','read','search','read']


def test_search_provider_change_invalidates_saved_inputs(tmp_path):
    settings = config(tmp_path)
    store = Store(settings.database)
    run = ResearchRun(company_input='same', mode='real')
    store.save_run(run)
    ensure_manifest(settings, store, run.run_id)
    settings.search_url = 'https://different.test'
    with pytest.raises(RecoveryError):ensure_manifest(settings, store, run.run_id)


async def test_checkpoint_copied_from_another_task_is_rejected(tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    settings = Settings(mode='mock', database=tmp_path/'research.sqlite', local_sources=tmp_path/'local',
                        artifacts=tmp_path/'out', mock_delay=0)
    store = Store(settings.database)
    run = ResearchRun(company_input='original', mode='mock', status='interrupted', rules_version='1.1')
    store.save_run(run)
    workflow = ResearchWorkflow(settings, store, run.run_id)
    wrong = {'input':'other', 'run_id':'other', 'rules_version':'1.1'}
    store.checkpoint(run.run_id, 'resolve_company', wrong)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path/'graph.sqlite')) as saver:
        graph = workflow.build(saver)
        await graph.aupdate_state({'configurable':{'thread_id':run.run_id}}, {'context':wrong}, as_node='resolve_company')
    await Runner(settings, store).run(run.run_id)
    result = store.run(run.run_id)
    assert result.status == 'failed' and result.failure_code == 'incompatible'
    assert '不属于当前任务' in result.error
    assert store.load_checkpoint(run.run_id)[1] == wrong


async def test_saved_unit_with_changed_output_is_never_replayed(tmp_path):
    from company_research.execution import unit_key
    store = Store(tmp_path/'db')
    async def produce():return {'value':'own'}
    inputs = {'input':'original'}
    await unit(store, 'a', 'node', 'step', inputs, produce)
    key = unit_key('node', 'step', inputs)
    old = store.execution_get('a', 'execution_units', key)
    store.execution_put('a', 'execution_units', key, old | {'output':{'value':'other'}})
    with pytest.raises(RecoveryError):await unit(store, 'a', 'node', 'step', inputs, produce)


def test_unchanged_legacy_mock_manifest_can_upgrade_without_losing_progress(tmp_path):
    settings = Settings(mode='mock', database=tmp_path/'db', local_sources=tmp_path/'local', artifacts=tmp_path/'out')
    store = Store(settings.database)
    run = ResearchRun(company_input='mock', mode='mock', status='interrupted')
    store.save_run(run)
    ensure_manifest(settings, store, run.run_id)
    saved = store.execution_get(run.run_id, 'execution_meta', 'manifest')
    legacy = {key:value for key,value in saved.items() if key != 'retrieval'}
    store.execution_put(run.run_id, 'execution_meta', 'manifest', legacy)
    store.checkpoint(run.run_id, 'resolve_company', {'rules_version':'1.1', 'run_id':run.run_id})
    ensure_manifest(settings, store, run.run_id)
    assert store.execution_get(run.run_id, 'execution_meta', 'manifest') == saved
    assert store.load_checkpoint(run.run_id)[0] == 'resolve_company'


@pytest.mark.parametrize('saved_date,observed_date', [
    (None, '2023-03-31'), ('2023-03-31T10:39:19+08:00', '2023-03-31'),
    ('2023-03-31', '2024-04-01'),
])
def test_source_metadata_observations_preserve_first_version_after_restart(tmp_path, saved_date, observed_date):
    store = Store(tmp_path/'db')
    source = SourceRecord(kind='web', title='first title', content='same document',
                          source_url='https://example.com/report', publication_date=saved_date)
    EvidenceStore(store, 'a').add_source(source)
    changed = source.model_copy(update={'title':'later title', 'publication_date':observed_date})
    restarted = Store(store.path)
    bound = EvidenceStore(restarted, 'a')
    for _ in range(2):
        bound.add_source(changed)
        assert bound.sources[source.source_id] == source
    assert restarted.records('a', 'source') == [source.model_dump(mode='json')]
    observations = restarted.records('a', 'source_metadata')
    assert len(observations) == 1
    assert observations[0]['differences']['publication_date'] == {'saved':saved_date, 'observed':observed_date}
    EvidenceStore(restarted, 'b').add_source(changed)
    assert restarted.records('b', 'source')[0]['publication_date'] == observed_date


@pytest.mark.parametrize('field,changed', [('content','changed document'), ('source_url','https://other.test/report')])
def test_metadata_difference_never_masks_document_identity_conflicts(tmp_path, field, changed):
    store = Store(tmp_path/'db')
    source = SourceRecord(kind='web', title='first', content='original', source_url='https://example.com/report')
    bound = EvidenceStore(store, 'a')
    bound.add_source(source)
    with pytest.raises(FinancialError):
        bound.add_source(source.model_copy(update={field:changed, 'publication_date':'2023-03-31'}))
    assert bound.sources[source.source_id] == source
    assert store.records('a', 'source') == [source.model_dump(mode='json')]
    assert store.records('a', 'source_metadata') == []


@pytest.mark.parametrize('field,isolated,expected', [
    ('publication_date', True, False), ('content', True, False),
    ('source_url', True, False), ('publication_date', False, False),
])
def test_quality_blocks_cannot_resume_even_when_metadata_guard_is_repaired(tmp_path, field, isolated, expected):
    settings = config(tmp_path)
    store = Store(settings.database)
    run = ResearchRun(company_input='same', mode='real', status='blocked', failure_code='quality',
                      error=f'已保存source的同一 ID 对应不同内容，拒绝覆盖：source-id/{field}')
    store.save_run(run)
    if isolated:ensure_isolation(store, run.run_id)
    else:store.record(run.run_id, 'source', 'source-id', {'content':'legacy'})
    result = recovery_info(settings, store, run.run_id)
    assert result['can_resume'] is expected


async def test_metadata_failed_retrieval_replays_own_search_and_uses_canonical_source(tmp_path, monkeypatch):
    from company_research.researcher import researcher_graph
    from company_research.schemas import ResearchTask
    store = Store(tmp_path/'db')
    source = SourceRecord(kind='web', title='first', content='document', publication_date='2023-03-31')
    store.record('a', 'source', source.source_id, source.model_dump(mode='json'))
    calls = []
    async def retrieve(query):
        calls.append(query)
        return [source.model_copy(update={'publication_date':'2024-04-01'})], []
    datasource = SimpleNamespace(retrieve=retrieve)
    task = ResearchTask(task_id='C01', company_id='D', topic='identity', role='company', queries=['same'])
    state = {'task':task.model_dump(mode='json'), 'brief':{}, 'round':0, 'sources':[],
             'evidence':[], 'facts':[], 'queries':['same'], 'gaps':[], 'warnings':[], 'summary':{}}
    original = store.record
    def old_guard(run_id, kind, key, payload, **kwargs):
        if kind == 'source':
            raise FinancialError(f'已保存source的同一 ID 对应不同内容，拒绝覆盖：{key}/publication_date')
        return original(run_id, kind, key, payload, **kwargs)
    monkeypatch.setattr(store, 'record', old_guard)
    with pytest.raises(FinancialError):
        await researcher_graph(None, datasource, store, 'a', 1, mock=True).ainvoke(state)
    monkeypatch.setattr(store, 'record', original)
    result = await researcher_graph(None, datasource, store, 'a', 1, mock=True).ainvoke(state)
    assert calls == ['same']
    assert result['sources'] == [source.model_dump(mode='json')]
    assert len(result['evidence']) == 1
    assert all(u['state'] == 'succeeded' for u in store.execution_states('a'))


async def test_api_resumes_connection_failure_in_original_run_without_repeating_success(tmp_path, monkeypatch):
    settings = Settings(mode='mock', database=tmp_path/'db', local_sources=tmp_path/'local',
                        artifacts=tmp_path/'out', mock_delay=0)
    app = create_app(settings)
    store = app.state.store
    run = ResearchRun(company_input='metadata resume', mode='mock')
    store.save_run(run)
    store.execution_put(run.run_id, 'execution_meta', 'service-session', {'session_id':store.service_session_id})
    resolve, brief = ResearchWorkflow.resolve_company, ResearchWorkflow.research_brief
    calls = {'resolve':0, 'brief':0}
    async def counted_resolve(self, context):
        calls['resolve'] += 1
        return await resolve(self, context)
    async def fail_once(self, context):
        calls['brief'] += 1
        if calls['brief'] == 1:
            raise RuntimeError('network interrupted')
        return await brief(self, context)
    monkeypatch.setattr(ResearchWorkflow, 'resolve_company', counted_resolve)
    monkeypatch.setattr(ResearchWorkflow, 'research_brief', fail_once)
    await Runner(settings, store).run(run.run_id)
    assert store.run(run.run_id).status == 'failed'
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post(f'/api/research/{run.run_id}/resume')
            assert response.status_code == 202 and response.json()['run_id'] == run.run_id
            for _ in range(3000):
                final = store.run(run.run_id)
                if final.status not in {'queued','running'}:break
                await asyncio.sleep(.01)
            assert final.status == 'limited'
            assert final.resume_count == 1
    assert calls == {'resolve':1, 'brief':2}
