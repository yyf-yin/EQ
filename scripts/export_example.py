"""Run an actual mock graph and save example outputs for distribution."""
import asyncio
import json
import shutil
from pathlib import Path
from company_research.config import Settings,ROOT
from company_research.storage import Store
from company_research.runner import Runner
from company_research.schemas import ResearchRun

async def main():
    output=ROOT/'examples/reference_reports/v1_1';output.mkdir(parents=True,exist_ok=True)
    settings=Settings(mock_delay=0,database=ROOT/'work/v11-example/research.sqlite',artifacts=ROOT/'work/v11-example/artifacts')
    settings.prepare();store=Store(settings.database)
    run=ResearchRun(company_input='示例制造公司',mode='mock');store.save_run(run)
    await Runner(settings,store).run(run.run_id)
    final=store.run(run.run_id)
    if final.status not in {'limited','completed'}:raise RuntimeError(final.error)
    report=store.report(run.run_id)
    (output/'mock_company_report.json').write_text(report.model_dump_json(indent=2),encoding='utf-8')
    for name in ['report.docx','report.html','report.pdf']:
        source=settings.artifacts/run.run_id/name
        if source.exists():shutil.copy2(source,output/('mock_company_'+name))
    (output/'run-events.json').write_text(json.dumps([e.model_dump(mode='json') for e in store.events(run.run_id)],ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'run_id':run.run_id,'status':final.status,'report':str(output),'calculations':len(report.calculations),'forecasts':len(report.forecasts)},ensure_ascii=False))

asyncio.run(main())
