"""Resume packages carry finished stages into a new run; only rejected work is redone."""
import io
import json
from zipfile import ZipFile

import httpx
import pytest

from company_research import reviewers, writers
from company_research.api import create_app
from company_research.config import Settings
from company_research.graphs import ResearchWorkflow
from company_research.reports import sections_flat
from company_research.runner import Runner
from company_research.schemas import ResearchRun, ReviewIssue

MARK = '【源任务写作】'


@pytest.fixture
def service(tmp_path):
    settings = Settings(
        mode='mock', database=tmp_path / 'db', artifacts=tmp_path / 'out', local_sources=tmp_path / 'src', mock_delay=0
    )
    app = create_app(settings)
    return app, settings, app.state.store


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')


def queued(store):
    run = ResearchRun(company_input='成果包公司', mode='mock', rules_version='1.1')
    store.save_run(run)
    store.execution_put(run.run_id, 'execution_meta', 'service-session', {'session_id': store.service_session_id})
    return run.run_id


async def blocked_on_risk(settings, store, monkeypatch):
    """Source run: every section carries a marker and the review rejects the risk section."""
    original_sections, original_review = writers.mock_sections, reviewers.deterministic_review

    def marked(c):
        sections = original_sections(c)
        for s in sections_flat(sections):
            if s.paragraphs:
                s.paragraphs = s.paragraphs + [MARK + s.section_id]
        return sections

    def review(report):
        return original_review(report) + [
            ReviewIssue(
                issue_type='structural',
                severity='error',
                location='risk',
                section_id='risk',
                description='风险章节缺少监测指标',
                suggested_fix='补充监测指标',
                target_node='write_sections',
                rule_id='test.risk',
            )
        ]

    monkeypatch.setattr(writers, 'mock_sections', marked)
    monkeypatch.setattr(reviewers, 'deterministic_review', review)
    settings.max_revisions = 0
    run_id = queued(store)
    await Runner(settings, store).run(run_id)
    assert store.run(run_id).status == 'blocked', store.run(run_id).error
    monkeypatch.setattr(writers, 'mock_sections', original_sections)
    monkeypatch.setattr(reviewers, 'deterministic_review', original_review)
    return run_id


def count_calls(monkeypatch, *nodes):
    calls = {n: 0 for n in nodes}
    for node in nodes:
        original = getattr(ResearchWorkflow, node)

        async def wrapper(self, c, _original=original, _node=node, **kwargs):
            calls[_node] += 1
            return await _original(self, c, **kwargs)

        monkeypatch.setattr(ResearchWorkflow, node, wrapper)
    return calls


async def wait_done(store, run_id):
    import asyncio

    for _ in range(3000):
        if store.run(run_id).status in {'completed', 'limited', 'failed', 'blocked'}:
            return store.run(run_id)
        await asyncio.sleep(0.01)
    raise AssertionError(store.run(run_id))


async def test_rejected_section_is_rewritten_and_everything_else_is_reused(service, monkeypatch):
    app, settings, store = service
    source = await blocked_on_risk(settings, store, monkeypatch)
    async with client(app) as http:
        response = await http.get(f'/api/research/{source}/resume-package')
        assert response.status_code == 200, response.text
        archive = ZipFile(io.BytesIO(response.content))
        assert {'readable/summary.md', 'readable/draft.md', 'state/context.json'} <= set(archive.namelist())
        info = (await http.post('/api/resume-packages', content=response.content)).json()
        assert info['recommended_level'] == 'writing' and not info['risks'] and not info['incompatible']
        sections = {s['section_id']: s for s in info['review']['sections']}
        assert sections['risk']['status'] == 'failed' and not sections['risk']['default_keep']
        assert sections['company']['status'] == 'passed'
        keep = [s for s, v in sections.items() if v['default_keep']]
        calls = count_calls(monkeypatch, 'supervisor', 'assumptions', 'analyze_blocks', 'write_sections')
        imported = await http.post(
            f"/api/resume-packages/{info['package_id']}/import", json={'level': 'writing', 'keep_sections': keep}
        )
        assert imported.status_code == 202, imported.text
        run_id = imported.json()['run_id']
        assert run_id != source
        run = await wait_done(store, run_id)
        assert run.status in {'completed', 'limited'}, run.error
        assert calls == {'supervisor': 0, 'assumptions': 0, 'analyze_blocks': 0, 'write_sections': 1}
        report = {s.section_id: s for s in sections_flat(store.report(run_id).sections)}
        assert MARK + 'company' in report['company'].paragraphs
        assert not any(MARK in p for p in report['risk'].paragraphs)
        # The core view summarises every section and is rewritten with them.
        assert not any(MARK in p for p in report['core'].paragraphs)
        meta = store.execution_get(run_id, 'execution_meta', 'resume-package')
        assert meta['source_run_id'] == source and 'risk' in meta['dropped_sections']
        assert (await http.post(f"/api/resume-packages/{info['package_id']}/import", json={'level': 'writing'})).status_code == 404
    assert store.run(source).status == 'blocked'


async def test_forecast_level_reruns_blocks_but_not_collection(service, monkeypatch):
    app, settings, store = service
    source = await blocked_on_risk(settings, store, monkeypatch)
    async with client(app) as http:
        package = (await http.get(f'/api/research/{source}/resume-package')).content
        info = (await http.post('/api/resume-packages', content=package)).json()
        calls = count_calls(monkeypatch, 'supervisor', 'assumptions', 'analyze_blocks')
        response = await http.post(f"/api/resume-packages/{info['package_id']}/import", json={'level': 'forecast'})
        assert response.status_code == 202, response.text
        run = await wait_done(store, response.json()['run_id'])
        assert run.status in {'completed', 'limited'}, run.error
        assert calls == {'supervisor': 0, 'assumptions': 0, 'analyze_blocks': 1}
        report = {s.section_id: s for s in sections_flat(store.report(run.run_id).sections)}
        assert not any(MARK in p for p in report['company'].paragraphs)


async def test_tampered_package_and_unconfirmed_risks_are_rejected(service, monkeypatch):
    app, settings, store = service
    source = await blocked_on_risk(settings, store, monkeypatch)
    async with client(app) as http:
        package = (await http.get(f'/api/research/{source}/resume-package')).content
        original = ZipFile(io.BytesIO(package))
        buffer = io.BytesIO()
        with ZipFile(buffer, 'w') as altered:
            for name in original.namelist():
                value = original.read(name)
                if name == 'state/context.json':
                    value = value.replace('成果包公司'.encode(), '其它公司'.encode())
                altered.writestr(name, value)
        response = await http.post('/api/resume-packages', content=buffer.getvalue())
        assert response.status_code == 422 and '校验失败' in response.json()['detail']
        assert (await http.post('/api/resume-packages', content=b'not a zip')).status_code == 422

        from company_research import execution

        real = execution.manifest
        monkeypatch.setattr(execution, 'manifest', lambda *a, **kw: real(*a, **kw) | {'prompts': 'changed'})
        info = (await http.post('/api/resume-packages', content=package)).json()
        assert [r['field'] for r in info['risks']] == ['prompts']
        url = f"/api/resume-packages/{info['package_id']}/import"
        assert (await http.post(url, json={'level': 'writing'})).status_code == 409
        assert (await http.post(url, json={'level': 'writing', 'keep_sections': ['nope'], 'accept_risks': True})).status_code == 422
        before = {r.run_id for r in store.active_runs()}
        response = await http.post(url, json={'level': 'blocks', 'accept_risks': True})
        assert response.status_code == 202, response.text
        assert response.json()['run_id'] not in before


async def test_running_or_unstarted_runs_cannot_export(service):
    app, settings, store = service
    run_id = queued(store)
    async with client(app) as http:
        response = await http.get(f'/api/research/{run_id}/resume-package')
        assert response.status_code == 409


def test_non_zip_package_is_rejected():
    from company_research.resume_packages import PackageError, read_package

    with pytest.raises(PackageError):
        read_package(json.dumps({}).encode(), 1024)


async def test_switching_to_the_bullish_style_rewrites_every_section(service, monkeypatch):
    app, settings, store = service
    source = await blocked_on_risk(settings, store, monkeypatch)
    async with client(app) as http:
        package = (await http.get(f'/api/research/{source}/resume-package')).content
        info = (await http.post('/api/resume-packages', content=package)).json()
        assert info['source']['bullish'] is False
        keep = [s['section_id'] for s in info['review']['sections'] if s['default_keep']]
        imported = await http.post(
            f"/api/resume-packages/{info['package_id']}/import",
            json={'level': 'writing', 'keep_sections': keep, 'bullish': True},
        )
        assert imported.status_code == 202, imported.text
        run = await wait_done(store, imported.json()['run_id'])
        assert run.bullish and run.status in {'completed', 'limited'}, run.error
        report = store.report(run.run_id)
        assert report.writing_style == 'bullish'
        assert not any(MARK in p for s in sections_flat(report.sections) for p in s.paragraphs)
        meta = store.execution_get(run.run_id, 'execution_meta', 'resume-package')
        assert meta['writing_style'] == 'bullish' and meta['kept_sections'] == []
