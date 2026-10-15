import asyncio
import io
from pathlib import Path
from zipfile import ZipFile
import httpx
from company_research.api import create_app
from company_research.config import Settings
from company_research.storage import Store


def settings(tmp_path):
    return Settings(_env_file=None, mode='mock', database=tmp_path/'runs.sqlite', artifacts=tmp_path/'artifacts', local_sources=tmp_path/'sources', mock_delay=.001)


async def test_mock_flow(tmp_path):
    app = create_app(settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/api/health')).json()['mode']=='mock'
            assert (await client.post('/api/research',json={'company':'  '})).status_code==422
            created=await client.post('/api/research',json={'company':'示例制造'})
            assert created.status_code==202
            run_id=created.json()['run_id']
            for _ in range(400):
                run=(await client.get(f'/api/research/{run_id}')).json()
                if run['status'] in ['limited','failed']:break
                await asyncio.sleep(.02)
            assert run['status']=='limited',run
            assert run['mode']=='mock'
            report=(await client.get(f'/api/research/{run_id}/report')).json()
            assert len(report['sections'])==9
            events=await client.get(f'/api/research/{run_id}/events')
            assert 'event: progress' in events.text and 'event: done' in events.text
            first=app.state.store.events(run_id)[0].event_id
            resumed=await client.get(f'/api/research/{run_id}/events',headers={'Last-Event-ID':str(first)})
            assert f'id: {first}\n' not in resumed.text
            file=await client.get(f'/api/research/{run_id}/download')
            assert file.status_code==200
            with ZipFile(io.BytesIO(file.content)) as doc:
                assert 'word/document.xml' in doc.namelist()
                assert '免责声明' in doc.read('word/document.xml').decode()
            assert Store(settings(tmp_path).database).run(run_id).status=='limited'


async def test_missing_and_html_safety(tmp_path):
    app=create_app(settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        assert (await c.get('/api/research/missing')).status_code==404
    from company_research.reports import mock_report,html_report
    html=html_report(mock_report('<script>alert(1)</script>'))
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
