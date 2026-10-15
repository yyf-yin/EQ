import asyncio
from company_research.config import Settings
from company_research.storage import Store
from company_research.schemas import ResearchRun
from company_research.runner import Runner


async def test_langgraph_nodes_and_checkpoint(tmp_path):
    settings=Settings(database=tmp_path/'db',local_sources=tmp_path/'local',artifacts=tmp_path/'out',mock_delay=0)
    store=Store(settings.database);run=ResearchRun(company_input='示例公司',mode='mock');store.save_run(run)
    await Runner(settings,store).run(run.run_id)
    assert store.run(run.run_id).status=='limited',store.run(run.run_id)
    nodes={e.task_name for e in store.events(run.run_id)}
    assert {'research_brief','calculation_plan','dependencies','supervisor','data_gaps','assumptions','calculate','validate'}.issubset(nodes)
    assert any('检索资料' in e.display_message for e in store.events(run.run_id))
    checkpoint=store.load_checkpoint(run.run_id)
    assert checkpoint[0]=='deliver'
    assert len(checkpoint[1]['forecasts'])==9
    assert len(checkpoint[1]['calculations'])>100
    assert checkpoint[1]['replans']==0


async def test_interrupt_and_resume(tmp_path):
    settings=Settings(database=tmp_path/'db',local_sources=tmp_path/'local',artifacts=tmp_path/'out',mock_delay=.03)
    store=Store(settings.database);run=ResearchRun(company_input='恢复测试',mode='mock');store.save_run(run)
    runner=Runner(settings,store);task=asyncio.create_task(runner.run(run.run_id))
    for _ in range(100):
        if store.load_checkpoint(run.run_id):break
        await asyncio.sleep(.01)
    task.cancel();await asyncio.gather(task,return_exceptions=True)
    assert store.run(run.run_id).status=='interrupted'
    before=len([e for e in store.events(run.run_id) if e.task_name=='resolve_company' and e.status=='completed'])
    await runner.run(run.run_id)
    assert store.run(run.run_id).status=='limited'
    after=len([e for e in store.events(run.run_id) if e.task_name=='resolve_company' and e.status=='completed'])
    assert before==after==1


async def test_real_not_configured(tmp_path):
    settings=Settings(mode='real',database=tmp_path/'db',local_sources=tmp_path/'local',artifacts=tmp_path/'out',models_config=tmp_path/'absent.yaml')
    store=Store(settings.database);run=ResearchRun(company_input='真实公司',mode='real');store.save_run(run)
    await Runner(settings,store).run(run.run_id)
    assert store.run(run.run_id).status=='failed'
    assert 'models.yaml' in store.run(run.run_id).error
    assert store.report(run.run_id) is None
