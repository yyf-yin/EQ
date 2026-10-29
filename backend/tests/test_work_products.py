"""Evaluation exports must be useful during faults without bypassing approval."""
import asyncio
import hashlib
import io
import json
from zipfile import ZipFile

import httpx
import pytest

from company_research.api import create_app
from company_research.config import Settings
from company_research.graphs import ResearchWorkflow
from company_research.llm import LLMError
from company_research.runner import Runner
from company_research.schemas import ResearchRun
from company_research.storage import Store
from company_research.work_products import capture_snapshot, export_snapshot, sanitize


@pytest.fixture
def service(tmp_path):
    settings = Settings(database=tmp_path/'db', artifacts=tmp_path/'out', local_sources=tmp_path/'sources', mock_delay=0)
    app = create_app(settings)
    return app, settings, app.state.store


def create_run(store, status='failed'):
    run = ResearchRun(company_input='评估公司', mode='mock', status=status, rules_version='1.1', error='故障注入' if status == 'failed' else None)
    store.save_run(run)
    if hasattr(store, 'service_session_id'):
        store.execution_put(run.run_id, 'execution_meta', 'service-session', {'session_id':store.service_session_id})
    return run.run_id


def unpack(response):
    assert response.status_code == 200, response.text[:500] if response.status_code != 200 else ''
    archive = ZipFile(io.BytesIO(response.content))
    manifest = json.loads(archive.read('manifest.json'))
    for entry in manifest['files']:
        content = archive.read(entry['path'])
        assert len(content) == entry['bytes']
        assert hashlib.sha256(content).hexdigest() == entry['sha256']
    for kind, count in manifest['record_counts'].items():
        assert len(json.loads(archive.read(f'data/{kind}.json'))) == count
    return archive, manifest


@pytest.mark.parametrize('status', ['failed', 'blocked', 'running', 'queued', 'interrupted'])
async def test_empty_runs_and_formal_gate(service, status):
    app, _, store = service
    run_id = create_run(store, status)
    before = store.run(run_id).model_dump()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        value = (await client.get(f'/api/research/{run_id}/work-product')).json()
        assert value['artifact_type'] == 'work_product' and value['run_status'] == status
        assert not value['final_review_passed'] and not value['sections']
        assert value['missing'] and value['formats'] == ['zip', 'json', 'md']
        for format in ['zip', 'json', 'md']:
            response = await client.get(f'/api/research/{run_id}/work-product/download', params={'format': format, 'snapshot_id': value['snapshot_id']})
            assert response.status_code == 200
            if format == 'zip':
                archive, manifest = unpack(response)
                assert manifest['run_status'] == status
                assert '当前尚无写作成果' in archive.read('draft.md').decode()
            elif format == 'json':
                assert response.json()['snapshot_id'] == value['snapshot_id']
            else:
                assert '未经最终审核' in response.text and '故障注入' in response.text if status == 'failed' else '未经最终审核' in response.text
        assert (await client.get(f'/api/research/{run_id}/report')).status_code == 409
        assert (await client.get(f'/api/research/{run_id}/download')).status_code == 409
    assert store.run(run_id).model_dump() == before
    assert not store.records(run_id, 'approval')


async def test_fixed_snapshot_running_pagination_restart_and_cross_run(service):
    app, settings, store = service
    run_id = create_run(store, 'running')
    store.record(run_id, 'source', 's1', {'source_id': 's1', 'title': '第一份资料', 'content': '不可打包完整原文'})
    snapshot = capture_snapshot(store, run_id, settings.work_product_max_bytes)
    store.record(run_id, 'source', 's2', {'source_id': 's2', 'title': '后来提交资料'})
    store.emit(run_id, '数据收集', 'task', 'running', '新增已提交成果')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        prefix = f'/api/research/{run_id}/work-product'
        fixed = (await client.get(prefix, params={'snapshot_id': snapshot['snapshot_id'], 'page_size': 1})).json()
        assert fixed['counts']['source'] == 1 and len(fixed['artifacts']) == 1
        latest = (await client.get(prefix, params={'page_size': 1, 'page': 2})).json()
        assert latest['snapshot_id'] != snapshot['snapshot_id'] and latest['counts']['source'] == 2
        assert len(latest['artifacts']) == 1
        archive, _ = unpack(await client.get(prefix+'/download', params={'snapshot_id': snapshot['snapshot_id']}))
        assert len(json.loads(archive.read('data/source.json'))) == 1
        assert '不可打包完整原文' not in archive.read('data/source.json').decode()
        other_id = create_run(store)
        assert (await client.get(f'/api/research/{other_id}/work-product/download', params={'snapshot_id': snapshot['snapshot_id']})).status_code == 404
        assert (await client.get(prefix, params={'snapshot_id': 'f'*64})).status_code == 404
        assert (await client.get(prefix+'/download', params={'format': 'docx'})).status_code == 422
        assert (await client.get('/api/research/unknown/work-product')).status_code == 404
    restarted = Store(settings.database)
    assert capture_snapshot(restarted, run_id, settings.work_product_max_bytes, snapshot['snapshot_id']) == snapshot
    assert capture_snapshot(restarted, run_id, settings.work_product_max_bytes)['snapshot_id'] == latest['snapshot_id']


async def test_failure_before_writing_exports_evidence(service, monkeypatch):
    app, settings, store = service
    async def stop(self, context):
        raise LLMError('写作前故障注入')
    monkeypatch.setattr(ResearchWorkflow, 'financial_analysis', stop)
    run_id = create_run(store, 'queued')
    await Runner(settings, store).run(run_id)
    assert store.run(run_id).status == 'failed' and not store.report(run_id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        archive, manifest = unpack(await client.get(f'/api/research/{run_id}/work-product/download'))
    assert manifest['record_counts']['fact'] > 0 and manifest['record_counts']['evidence'] > 0
    assert '写作前故障注入' in archive.read('evaluation.md').decode()
    assert '当前尚无写作成果' in archive.read('draft.md').decode()


async def test_core_blocked_and_preserved_review_rounds(service, monkeypatch):
    app, settings, store = service
    # Data gaps now wait before calculation. Inject a report-level fault instead
    # to keep testing rejected review rounds and formal delivery protection.
    original = ResearchWorkflow.final_review
    async def corrupt_table(self, context):
        context['report']['sections'][3]['children'][0]['tables'][0]['rows'][0][2]='999'
        return await original(self, context)
    monkeypatch.setattr(ResearchWorkflow, 'final_review', corrupt_table)
    run_id = create_run(store, 'queued')
    settings.max_replans = 0
    settings.max_revisions = 1
    await Runner(settings, store).run(run_id)
    assert store.run(run_id).status == 'blocked'
    before = store.run(run_id).model_dump()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        prefix = f'/api/research/{run_id}'
        archive, manifest = unpack(await client.get(prefix+'/work-product/download'))
        assert not manifest['final_review_passed']
        rounds = json.loads(archive.read('diagnostics/review-history.json'))
        assert len(rounds) == 2 and all(v['outcome'] == 'rejected' for v in rounds)
        assert rounds[0]['review_id'] != rounds[1]['review_id']
        assert all(v['report']['sections'] and v['report']['issues'] for v in rounds)
        assert json.loads(archive.read('data/current_review_issues.json'))
        assert any(i['rule_id']=='core.table' for i in json.loads(archive.read('data/current_review_issues.json')))
        assert (await client.get(prefix+'/report')).status_code == 409
        assert (await client.get(prefix+'/download')).status_code == 409
    assert store.run(run_id).model_dump() == before


@pytest.fixture(scope='module')
def finished(tmp_path_factory):
    path = tmp_path_factory.mktemp('work-product-finished')
    settings = Settings(database=path/'db', artifacts=path/'out', local_sources=path/'sources', mock_delay=0)
    app = create_app(settings)
    store = app.state.store
    run_id = create_run(store, 'queued')
    asyncio.run(Runner(settings, store).run(run_id))
    assert store.run(run_id).status == 'limited', store.run(run_id).error
    return app, settings, store, run_id


async def test_approved_snapshot_and_dependency_integrity(finished):
    app, settings, store, run_id = finished
    snapshot = capture_snapshot(store, run_id, settings.work_product_max_bytes)
    assert snapshot['final_review_passed']
    ids = {v[k] for kind, k in [('fact', 'fact_id'), ('calculation', 'result_id'), ('assumption', 'assumption_id')]
           for v in snapshot['data'][kind]}
    for calc in snapshot['data']['calculation']:
        assert {v for v in calc['input_refs'].values() if not v.startswith('constant:')}.issubset(ids)
    assert all(v['formula_version'] for v in snapshot['data']['calculation'])
    assert all(v['validation_status'] == 'passed' for v in snapshot['sections'])
    assert not any(v['version_status'] == 'stale' for v in snapshot['artifacts'] if v['kind'] == 'block_analysis')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get(f'/api/research/{run_id}/download')).status_code == 200
        response = await client.get(f'/api/research/{run_id}/work-product/download')
        unpack(response)


async def test_export_failure_does_not_change_state_and_retries(finished, monkeypatch):
    app, settings, store, run_id = finished
    before = store.run(run_id).model_dump()
    snapshot = capture_snapshot(store, run_id, settings.work_product_max_bytes)
    from company_research import work_products
    original = work_products.summary_md
    def fail(snapshot):
        raise OSError('pack failure')
    monkeypatch.setattr(work_products, 'summary_md', fail)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url = f'/api/research/{run_id}/work-product/download'
        response = await client.get(url, params={'snapshot_id': snapshot['snapshot_id']})
        assert response.status_code == 503 and '可重试' in response.json()['detail']
        assert store.run(run_id).model_dump() == before
        assert (await client.get(f'/api/research/{run_id}/download')).status_code == 200
        monkeypatch.setattr(work_products, 'summary_md', original)
        unpack(await client.get(url, params={'snapshot_id': snapshot['snapshot_id']}))


def test_upstream_update_marks_stale_and_keeps_old_snapshot(finished):
    _, settings, store, run_id = finished
    original = store.records(run_id, 'fact')[0]
    old = capture_snapshot(store, run_id, settings.work_product_max_bytes)
    def inject(value):
        # Simulate database damage outside the application's immutable record API.
        with store.connect() as db:
            db.execute("UPDATE records SET payload=? WHERE run_id=? AND kind='fact' AND id=?",
                       (json.dumps(value), run_id, original['fact_id']))
    try:
        inject(original | {'value': '999999'})
        changed = capture_snapshot(store, run_id, settings.work_product_max_bytes)
        assert not changed['final_review_passed'] and changed['snapshot_id'] != old['snapshot_id']
        assert any(v['version_status'] == 'stale' for v in changed['sections'])
        assert capture_snapshot(store, run_id, settings.work_product_max_bytes, old['snapshot_id'])['final_review_passed']
    finally:
        inject(original)


async def test_redaction_corrupt_record_size_limit_and_safe_markdown(service):
    app, settings, store = service
    run_id = create_run(store)
    store.record(run_id, 'source', 's', {'source_id': 's', 'source_url': 'https://user:pass@example.test/a?token=credentialvalue',
                                        'title': '<script>alert(1)</script> api_key=privatevalue', 'content': 'raw-body', 'headers': {'Authorization': 'Bearer privatevalue'}})
    store.record(run_id, 'call', 'c', {'call_id': 'c', 'input_tokens': 9, 'output_tokens': 4, 'usage_source': 'provider',
                                     'model': 'fixture', 'messages': [{'role': 'system', 'content': 'hidden prompt'}], 'reasoning': 'hidden reasoning'})
    with store.connect() as db:
        db.execute('INSERT INTO records VALUES(?,?,?,?)', (run_id, 'fact', 'bad', '{'))
    snapshot = capture_snapshot(store, run_id, settings.work_product_max_bytes)
    assert snapshot['unavailable'][0]['artifact'] == 'fact/bad'
    payload = json.dumps(snapshot, ensure_ascii=False)
    for secret in ['credentialvalue', 'privatevalue', 'user:pass', 'raw-body', 'hidden prompt', 'hidden reasoning']:
        assert secret not in payload
    assert snapshot['diagnostics']['usage']['provider_input_tokens'] == 9
    markdown = export_snapshot(snapshot, 'md', settings.work_product_max_bytes)[0].decode()
    assert '<script>' not in markdown and '&lt;script&gt;' in markdown
    settings.work_product_max_bytes = 1024
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get(f'/api/research/{run_id}/work-product')
        assert response.status_code == 413 and '未省略' in response.json()['detail']
    assert store.run(run_id).status == 'failed'


async def test_render_failure_still_exports_reviewed_work(service, monkeypatch):
    app, settings, store = service
    async def fail(self, context):
        raise OSError('render injected failure')
    monkeypatch.setattr(ResearchWorkflow, 'render', fail)
    run_id = create_run(store, 'queued')
    await Runner(settings, store).run(run_id)
    assert store.run(run_id).status == 'failed' and not store.report(run_id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        archive, manifest = unpack(await client.get(f'/api/research/{run_id}/work-product/download'))
        assert manifest['final_review_passed'] and manifest['run_status'] == 'failed'
        assert '当前尚无写作成果' not in archive.read('draft.md').decode()
        assert (await client.get(f'/api/research/{run_id}/download')).status_code == 409


def test_sidecar_failure_cannot_break_review(finished, monkeypatch):
    _, settings, store, run_id = finished
    def fail(*args):
        raise OSError('sidecar unavailable')
    monkeypatch.setattr(store, 'save_work_product_review', fail)
    context = store.load_checkpoint(run_id)[1]
    result = asyncio.run(ResearchWorkflow(settings, store, run_id).final_review(context))
    assert not result['issues'] and result['report']['approved_snapshot_id']


def test_secret_field_filter_preserves_token_metrics():
    assert sanitize({'access_token': 'no', 'input_tokens': 12, 'system_prompt': 'no'}) == {'input_tokens': 12}


async def test_completed_batch_survives_next_model_call_failure(service, monkeypatch):
    from company_research.agents import ResearchExtraction, FactProposal
    from company_research.schemas import SourceRecord, ResearchBrief, ResearchTask, ExtractionBatch
    from company_research.llm import RoleLimits
    from company_research.researcher import researcher_graph
    from company_research import contexts
    _, settings, store = service
    run_id = create_run(store, 'running')
    quote = '合并 单位百万元 营业收入 2025A 550'
    source = SourceRecord(kind='local', title='披露', content=quote)
    class Datasource:
        async def retrieve(self, query, **options):
            return [source], []
    class Gateway:
        calls = 0
        def limits(self, role):
            return RoleLimits()
        async def structured(self, role, messages, schema):
            self.calls += 1
            if self.calls > 1:
                raise LLMError('下一批模型故障')
            return ResearchExtraction(evidence=[], facts=[FactProposal(source_id=source.source_id, quote=quote,
                metric_code='revenue', period='2025A', unit='CNY_million', value=550, actual_or_forecast='actual')],
                followup_queries=[], gaps=[])
    monkeypatch.setattr(contexts, 'extraction_batches', lambda *args, **kwargs: [ExtractionBatch(batch_id=f'b{i}', block_id='F01',
        question_ids=[], windows=[], periods=['2025A']) for i in range(2)])
    brief = ResearchBrief(company_id='D', scope='fixture', historical_periods=['2023A', '2024A', '2025A'], forecast_periods=[], segments=['设备'])
    task = ResearchTask(company_id='D', block_id='F01', topic='收入', role='financial', queries=['收入'])
    graph = researcher_graph(Gateway(), Datasource(), store, run_id, 1, settings=settings)
    with pytest.raises(LLMError):
        await graph.ainvoke({'task': task.model_dump(mode='json'), 'brief': brief.model_dump(mode='json'), 'round': 0,
            'sources': [], 'evidence': [], 'facts': [], 'queries': task.queries, 'gaps': [], 'warnings': [], 'summary': {}})
    assert not store.load_checkpoint(run_id) and not store.records(run_id, 'fact')
    snapshot = capture_snapshot(store, run_id, settings.work_product_max_bytes)
    assert len(snapshot['data']['fact']) == 1 and snapshot['data']['fact'][0]['value'] == '550'
    assert snapshot['data']['evidence'][0]['validation_status'] == 'verified'
    assert not snapshot['sections'] and not snapshot['final_review_passed']


async def test_unreadable_task_returns_specific_error(service, monkeypatch):
    app, _, store = service
    run_id = create_run(store)
    def fail(*args):
        raise ValueError('corrupt task payload')
    monkeypatch.setattr(store, 'run', fail)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for path in ['work-product', 'work-product/download']:
            response = await client.get(f'/api/research/{run_id}/{path}')
            assert response.status_code == 503 and '任务记录暂时无法读取' in response.json()['detail']


def test_superseded_fact_invalidates_dependent_calculations_and_draft(service):
    from company_research.reports import mock_report
    from company_research.schemas import FinancialFact
    _, settings, store = service
    run_id = create_run(store)
    old = FinancialFact(company_id='D', metric_code='revenue', period='2025A', value=550, unit='CNY_million',
                        actual_or_forecast='actual', source_id='s', evidence_id='e', locator='row').model_dump(mode='json')
    new = old | {'fact_id': 'new-fact', 'value': '560', 'version': 2, 'supersedes': old['fact_id']}
    report = mock_report('历史候选稿')
    report.financial_facts = [FinancialFact.model_validate(old)]
    store.checkpoint(run_id, 'write_sections', {'report': report.model_dump(mode='json'), 'facts': [old]})
    store.record(run_id, 'fact', old['fact_id'], old)
    store.record(run_id, 'fact', new['fact_id'], new)
    store.record(run_id, 'calculation', 'calc-old', {'result_id': 'calc-old', 'input_refs': {'revenue': old['fact_id']}})
    store.record(run_id, 'calculation', 'calc-dependent', {'result_id': 'calc-dependent', 'input_refs': {'revenue': 'calc-old'}})
    snapshot = capture_snapshot(store, run_id, settings.work_product_max_bytes)
    lookup = {(v['kind'], v.get('id')): v['version_status'] for v in snapshot['artifacts']}
    assert lookup['fact', old['fact_id']] == 'stale' and lookup['fact', 'new-fact'] == 'current'
    assert lookup['calculation', 'calc-old'] == lookup['calculation', 'calc-dependent'] == 'stale'
    markdown = export_snapshot(snapshot, 'md', settings.work_product_max_bytes)[0].decode()
    assert '历史失效章节（仅供评估，不作为当前结论）' in markdown
    assert '已保存章节因上游更新失效' in markdown
    assert not snapshot['final_review_passed']
