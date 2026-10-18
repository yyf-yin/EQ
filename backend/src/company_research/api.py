import asyncio
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field
from .config import Settings
from .storage import Store, TERMINAL
from .schemas import ResearchRun, uid
from .runner import Runner
from .reports import html_report
from .execution import recovery_info, budget_limits, ensure_manifest, RecoveryError, load_gateway
from .llm import ConfigurationError
from .isolation import ensure_isolation, isolation_info
from .startup import latest_unfinished, continuation_view
from .human_intervention import HumanInterventionAgent, HumanFeedback, FeedbackError
from .references import prepare_uploads, register_upload, create_with_attachments
from .datasources import MAX_BYTES, DatasourceError


class CreateResearch(BaseModel):
    company: str = Field(min_length=1, max_length=100)
    attachment_ids: list[str] = Field(default_factory=list, max_length=200)


class UpdateBudget(BaseModel):
    global_call_budget: int = Field(ge=1)
    global_token_budget: int = Field(ge=1)
    block_call_budget: int = Field(ge=1)


class ImportPackage(BaseModel):
    level: Literal['collection', 'forecast', 'blocks', 'writing']
    keep_sections: list[str] = Field(default_factory=list, max_length=200)
    accept_risks: bool = False


class StartupDecision(BaseModel):
    run_id: str
    session_id: str
    answer: Literal['Y', 'N']


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.prepare()
    import logging

    print(
        f'EFFECTIVE_BUDGETS call_limits_enabled={settings.enforce_call_budgets} block_call={settings.block_call_budget} global_call={settings.global_call_budget} global_token={settings.global_token_budget}',
        flush=True,
    )
    store = Store(settings.database)
    prepare_uploads(store)
    store.service_session_id = uid()
    startup_candidate = latest_unfinished(store)
    startup_state = {'selected_run_id': None, 'answer': None}
    startup_lock = asyncio.Lock()
    runner = Runner(settings, store)
    tasks: dict[str, asyncio.Task] = {}
    pause_tasks: set[asyncio.Task] = set()

    def schedule(run_id: str):
        if run_id in tasks and not tasks[run_id].done():
            return
        task = asyncio.create_task(runner.run(run_id))
        tasks[run_id] = task

        def cleanup(finished):
            if tasks.get(run_id) is finished:
                tasks.pop(run_id, None)

        task.add_done_callback(cleanup)

    async def finish_pause(run_id, task):
        if task:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=60)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            except asyncio.CancelledError:
                if not task.done():
                    raise
        paused = store.transition_run(run_id, {'pausing'}, status='interrupted')
        if paused:
            store.emit(run_id, paused.stage, 'run', 'interrupted', '任务已暂停，已提交成果保留')

    @asynccontextmanager
    async def lifespan(app):
        for run in store.active_runs():
            store.transition_run(
                run.run_id, {'running', 'queued', 'pausing'}, status='interrupted', stop_reason='restart'
            )
            store.emit(
                run.run_id,
                run.stage,
                'run',
                'interrupted',
                '程序已重启，等待启动窗口选择是否继续；可查看或导出已保存成果。',
            )
        yield
        active = list(tasks.items())
        for run_id, task in active:
            run = store.run(run_id)
            store.transition_run(
                run_id, {'running', 'queued'}, status='pausing', stop_reason=run.stop_reason or 'shutdown'
            )
            if run.status == 'queued':
                task.cancel()
        await asyncio.gather(*(finish_pause(run_id, task) for run_id, task in active), return_exceptions=True)
        await asyncio.gather(*list(pause_tasks), return_exceptions=True)
        for run in store.active_runs():
            store.transition_run(run.run_id, {'pausing'}, status='interrupted')

    app = FastAPI(title='Company Deep Research Agent', lifespan=lifespan)
    app.state.store, app.state.runner = store, runner
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],
        allow_methods=['GET', 'POST'],
        allow_headers=['Last-Event-ID', 'Content-Type'],
    )

    def get_run(run_id):
        run = store.run(run_id)
        if not run:
            raise HTTPException(404, '研究任务不存在')
        return run

    def approved_report(run_id):
        isolation = isolation_info(store, run_id)
        if isolation['reason']:
            raise HTTPException(409, isolation['reason'])
        report = store.report(run_id)
        if not report:
            raise HTTPException(404, '报告不存在')
        if report.rules_version == '1.1':
            from .comparisons import core_gate
            from .writers import report_snapshot

            if core_gate(report) or report.approved_snapshot_id != report_snapshot(report):
                raise HTTPException(409, '报告快照审核已失效')
        return report

    @app.get('/api/health')
    async def health():
        return {'status': 'ok', 'mode': settings.mode, 'pdf': True, 'session_id': store.service_session_id}

    @app.get('/api/startup')
    async def startup():
        candidate = None
        if startup_candidate:
            current = store.run(startup_candidate.run_id)
            _, info = continuation_view(settings, store, current)
            candidate = {
                'run_id': current.run_id,
                'company': current.company_name or current.company_input,
                'created_at': current.created_at,
                'stage': current.stage,
                'status': current.status,
                'can_continue': info['can_resume'],
                'can_adjust_budget': info['can_increase_budget'],
                'reason': info['reason'],
            }
        return {
            'session_id': store.service_session_id,
            'candidate': candidate,
            'reference_limits': {
                'max_files': settings.reference_max_files,
                'max_file_bytes': MAX_BYTES,
                'annual_reports_required': settings.mode == 'real' and settings.data_collection_mode == 'fixed',
            },
        } | startup_state

    @app.post('/api/startup/decision')
    async def startup_decision(body: StartupDecision):
        async with startup_lock:
            if (
                body.session_id != store.service_session_id
                or not startup_candidate
                or body.run_id != startup_candidate.run_id
            ):
                raise HTTPException(409, '启动选择已过期或不属于最近的未完成任务，请重新启动检查。')
            if startup_state['answer']:
                if startup_state['answer'] != body.answer:
                    raise HTTPException(409, '本次启动已经完成选择，不能再次更改。')
                return startup_state
            latest = latest_unfinished(store)
            if not latest or latest.run_id != startup_candidate.run_id:
                raise HTTPException(409, '已有更新的任务，本次启动选择已过期。')
            run = store.run(body.run_id)
            if body.answer == 'N':
                selected_id = None
                store.execution_put(
                    run.run_id,
                    'execution_meta',
                    'startup-decision',
                    {'session_id': store.service_session_id, 'answer': 'N'},
                )
            else:
                candidate, info = continuation_view(settings, store, run)
                if not info['can_increase_budget']:
                    raise HTTPException(409, info['reason'])
                try:
                    gateway = load_gateway(settings, store, run.run_id) if run.mode == 'real' else None
                    if gateway:
                        for role in gateway.routes:
                            gateway.resolve(role)
                    ensure_manifest(settings, store, run.run_id, gateway)
                except (ConfigurationError, RecoveryError, ValueError, KeyError, OSError) as exc:
                    raise HTTPException(
                        409, '原资料、模型或配置不支持安全继续，请选择 N 返回首页；原成果保留。'
                    ) from None
                store.execution_put(
                    run.run_id,
                    'execution_meta',
                    'startup-decision',
                    {
                        'session_id': store.service_session_id,
                        'answer': 'Y',
                        'previous_status': run.status,
                        'previous_error': run.error,
                        'previous_failure_code': run.failure_code,
                    },
                )
                store.execution_put(
                    run.run_id, 'execution_meta', 'service-session', {'session_id': store.service_session_id}
                )
                selected = store.transition_run(
                    run.run_id,
                    {'interrupted', 'failed', 'blocked', 'waiting_human'},
                    status='queued' if info['can_resume'] else 'interrupted',
                    failure_code=candidate.failure_code,
                    stop_reason=None,
                )
                if not selected:
                    raise HTTPException(409, '任务状态已变化，不能继续。')
                selected_id = run.run_id
                store.emit(
                    selected_id, selected.stage, 'run', selected.status, '启动时选择继续，仅使用本任务已保存成果'
                )
                if info['can_resume']:
                    schedule(selected_id)
            startup_state.update(selected_run_id=selected_id, answer=body.answer)
            return startup_state

    @app.post('/api/reference-attachments', status_code=201)
    async def upload_reference(request: Request, filename: str = Query(min_length=1, max_length=250)):
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_BYTES:
                raise HTTPException(413, '单份参考资料不能超过 20 MB')
            data.extend(chunk)
        try:
            return await asyncio.to_thread(register_upload, store, filename, bytes(data))
        except DatasourceError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get('/api/research/{run_id}/attachments')
    async def reference_attachments(run_id: str):
        get_run(run_id)
        return {
            'attachments': store.records(run_id, 'reference_attachment'),
            'coverage': store.records(run_id, 'reference_coverage'),
        }

    @app.post('/api/research', status_code=202)
    async def create(body: CreateResearch):
        name = body.company.strip()
        if not name:
            raise HTTPException(422, '请输入公司名称或股票代码')
        if settings.mode == 'real' and settings.data_collection_mode == 'fixed' and not body.attachment_ids:
            raise HTTPException(422, '请先上传本次使用的公司年报；程序不自动寻找年报')
        if len(store.active_runs()) >= settings.max_active_runs * 4:
            raise HTTPException(429, '研究队列已满，请稍后重试')
        run = ResearchRun(company_input=name, mode=settings.mode, rules_version='1.1')
        if body.attachment_ids:
            try:
                create_with_attachments(store, run, body.attachment_ids, settings.reference_max_files)
            except DatasourceError as exc:
                raise HTTPException(422, str(exc)) from None
        else:
            store.save_run(run)
        store.execution_put(run.run_id, 'execution_meta', 'service-session', {'session_id': store.service_session_id})
        ensure_isolation(store, run.run_id)
        store.emit(run.run_id, '等待开始', 'run', 'queued', '模拟运行已排队' if run.mode == 'mock' else '研究已排队')
        if body.attachment_ids:
            store.emit(
                run.run_id,
                '等待开始',
                'reference_upload',
                'completed',
                f'已绑定 {len(body.attachment_ids)} 份参考资料；'
                + (
                    '模拟模式仅保存附件，真实研究时使用'
                    if run.mode == 'mock'
                    else '年报由本次上传文件提供，业务行业资料可补充搜索'
                ),
            )
        schedule(run.run_id)
        return run

    @app.get('/api/research/{run_id}')
    async def status(run_id: str):
        run = get_run(run_id)
        formats = (
            [ext for ext in ['docx', 'pdf'] if (settings.artifacts / run.run_id / f'report.{ext}').is_file()]
            if run.status in {'completed', 'limited'} and not isolation_info(store, run_id)['reason']
            else []
        )
        blocks = store.records(run_id, 'block')
        batches = store.records(run_id, 'batch')
        coverage = store.records(run_id, 'coverage')
        slots = store.records(run_id, 'data_slot')
        materials = store.records(run_id, 'collection_slot')
        return run.model_dump(mode='json') | {
            'formats': formats,
            'runtime': store.runtime_summary(run_id),
            'recovery': recovery_info(settings, store, run_id),
            'blocks': [{'block_id': b['block_id'], 'status': b['status'], 'version': b['version']} for b in blocks],
            'batch_counts': {
                state: sum(b['status'] == state for b in batches)
                for state in {'pending', 'running', 'split', 'validated', 'quarantined'}
            },
            'coverage_counts': {
                state: sum(e['status'] == state for e in coverage)
                for state in {'pending', 'collecting', 'ready', 'verified', 'missing', 'conflict'}
            },
            'data_template_version': (
                store.execution_get(run_id, 'execution_meta', 'fixed-collection')
                or store.execution_get(run_id, 'execution_meta', 'fixed-table-preview')
                or {}
            ).get('version'),
            'data_slot_counts': {
                state: sum(s['state'] == state for s in slots)
                for state in {
                    'pending',
                    'filling',
                    'locked',
                    'not_disclosed',
                    'not_applicable',
                    'source_missing',
                    'extraction_failed',
                }
            },
            'collection_slot_counts': {
                state: sum(s['state'] == state for s in materials) for state in {'pending', 'ready', 'limited'}
            },
        }

    @app.get('/api/research/{run_id}/data-slots')
    async def data_slots(run_id: str):
        get_run(run_id)
        from .fixed_collection import TEMPLATE
        from .work_products import FIELDS, project, sanitize

        return sanitize(
            {
                'template_version': (
                    store.execution_get(run_id, 'execution_meta', 'fixed-collection')
                    or store.execution_get(run_id, 'execution_meta', 'fixed-table-preview')
                    or {}
                ).get('version'),
                'groups': [
                    {'group_id': g['group_id'], 'title': g['title'], 'fields': g['fields']} for g in TEMPLATE['groups']
                ],
                'slots': [project(s, FIELDS['data_slot']) for s in store.records(run_id, 'data_slot')],
                'materials': [project(s, FIELDS['collection_slot']) for s in store.records(run_id, 'collection_slot')],
                'derived': [project(s, FIELDS['slot_calculation']) for s in store.records(run_id, 'slot_calculation')],
                'latest_interim_period': (
                    store.execution_get(run_id, 'execution_meta', 'fixed-source-manifest') or {}
                ).get('latest_interim_period'),
                'bond_presence': store.records(run_id, 'bond_presence'),
            }
        )

    def human_can_submit(run_id):
        run = store.run(run_id)
        return (
            recovery_info(settings, store, run_id)['current_session']
            and not isolation_info(store, run_id)['reason']
            and run.status in {'running', 'waiting_human', 'interrupted'}
            and not (store.execution_get(run_id, 'execution_meta', 'human-admitted') or {}).get('admitted')
        )

    @app.get('/api/research/{run_id}/human-intervention')
    async def human_intervention(run_id: str):
        get_run(run_id)
        from .work_products import sanitize

        agent = HumanInterventionAgent(store, run_id)
        sources = {s['source_id']: s for s in store.records(run_id, 'source')}
        evidence = {e['evidence_id']: e for e in store.records(run_id, 'evidence')}
        issues = agent.issues()
        for issue in issues:
            issue['candidates'] = [
                v
                | {
                    'quote': evidence.get(v.get('evidence_id'), {}).get('quote', ''),
                    'title': sources.get(v.get('source_id'), {}).get('title', ''),
                    'source_url': sources.get(v.get('source_id'), {}).get('source_url'),
                    'locator': evidence.get(v.get('evidence_id'), {}).get('locator', ''),
                }
                for v in issue['candidates']
            ]
        return sanitize(
            {
                'issues': issues,
                'feedback': store.records(run_id, 'human_feedback'),
                'sources': [
                    {'source_id': key, 'title': s['title'], 'source_url': s.get('source_url')}
                    for key, s in sources.items()
                ],
                'can_submit': human_can_submit(run_id),
            }
        )

    @app.post('/api/research/{run_id}/human-intervention/{issue_id}', status_code=202)
    async def human_feedback(run_id: str, issue_id: str, body: HumanFeedback):
        run = get_run(run_id)
        info = recovery_info(settings, store, run_id)
        if not human_can_submit(run_id):
            raise HTTPException(409, '当前任务不能提交人工反馈；请在启动窗口选择兼容任务，原成果仍可查看。')
        try:
            receipt = HumanInterventionAgent(store, run_id).submit(issue_id, body)
        except FeedbackError as exc:
            raise HTTPException(409, str(exc)) from None
        store.emit(run_id, '数据核验', 'human_intervention', 'submitted', '人工反馈已保存，等待证据核验')
        # A waiting run has released its execution slot. Reuse the normal recovery
        # checks and scheduler; paused runs remain paused until the user continues.
        resumed = False
        resume_reason = None
        if run.status == 'waiting_human' and not info['can_resume']:
            resume_reason = info['reason']
        if run.status == 'waiting_human' and info['can_resume']:
            previous = tasks.get(run_id)
            if previous and not previous.done():
                await asyncio.shield(previous)
            try:
                await resume(run_id)
                resumed = True
            except HTTPException as exc:
                resume_reason = exc.detail  # Feedback remains durably accepted.
        return {
            'feedback_id': receipt['feedback_id'],
            'status': receipt['status'],
            'resumed': resumed,
            'resume_reason': resume_reason,
        }

    @app.get('/api/research/{run_id}/events')
    async def events(run_id: str, request: Request, after: int = Query(0, ge=0)):
        get_run(run_id)
        try:
            cursor = max(after, int(request.headers.get('last-event-id', '0')))
        except ValueError:
            raise HTTPException(400, '无效的事件游标')

        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                batch = store.events(run_id, cursor)
                for event in batch:
                    cursor = event.event_id
                    yield f'id: {event.event_id}\nevent: progress\ndata: {event.model_dump_json()}\n\n'
                run = store.run(run_id)
                if run.status in TERMINAL and not store.events(run_id, cursor):
                    yield 'event: done\ndata: {}\n\n'
                    break
                yield ': heartbeat\n\n'
                await asyncio.sleep(0.2)

        return StreamingResponse(
            stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
        )

    @app.get('/api/research/{run_id}/report')
    async def report(run_id: str, format: Literal['json', 'html'] = 'json'):
        run = get_run(run_id)
        if run.status not in {'completed', 'limited'}:
            raise HTTPException(409, '报告尚未完成或审核阻断')
        report = approved_report(run_id)
        if not report:
            raise HTTPException(404, '报告不存在')
        return (
            HTMLResponse(
                html_report(report),
                headers={
                    'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; frame-ancestors 'self'"
                },
            )
            if format == 'html'
            else report
        )

    @app.get('/api/research/{run_id}/work-product')
    async def work_product(
        run_id: str,
        snapshot_id: str | None = Query(None, max_length=64, pattern=r'^[a-f0-9]{64}$'),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ):
        from .work_products import capture_snapshot, preview, WorkProductError

        try:
            get_run(run_id)
            snapshot = await asyncio.to_thread(
                capture_snapshot, store, run_id, settings.work_product_max_bytes, snapshot_id
            )
            return preview(snapshot, page, page_size)
        except WorkProductError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except (sqlite3.Error, ValueError):
            raise HTTPException(503, '任务记录暂时无法读取，请检查数据库后重试；研究状态未改变。') from None

    @app.get('/api/research/{run_id}/work-product/download')
    async def work_product_download(
        run_id: str,
        format: Literal['zip', 'json', 'md'] = 'zip',
        snapshot_id: str | None = Query(None, max_length=64, pattern=r'^[a-f0-9]{64}$'),
    ):
        from .work_products import capture_snapshot, export_snapshot, WorkProductError

        try:
            get_run(run_id)
            snapshot = await asyncio.to_thread(
                capture_snapshot, store, run_id, settings.work_product_max_bytes, snapshot_id
            )
            content, media_type = await asyncio.to_thread(
                export_snapshot, snapshot, format, settings.work_product_max_bytes
            )
        except WorkProductError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except (sqlite3.Error, ValueError):
            raise HTTPException(503, '任务记录暂时无法读取，请检查数据库后重试；研究状态未改变。') from None
        return Response(
            content,
            media_type=media_type,
            headers={
                'Content-Disposition': f'attachment; filename="work-product-{snapshot["snapshot_id"][:12]}.{format}"',
                'X-Work-Product-Snapshot': snapshot['snapshot_id'],
                'X-Artifact-Type': 'work_product',
                'X-Run-Status': snapshot['run_status'],
                'X-Final-Review-Passed': str(snapshot['final_review_passed']).lower(),
                'X-Content-Type-Options': 'nosniff',
                'Cache-Control': 'no-store',
            },
        )

    @app.get('/api/research/{run_id}/resume-package')
    async def resume_package(run_id: str):
        from .resume_packages import export_package, PackageError

        get_run(run_id)
        try:
            content = await asyncio.to_thread(export_package, settings, store, run_id)
        except PackageError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except (sqlite3.Error, OSError, ValueError):
            raise HTTPException(503, '任务记录暂时无法读取，成果包未生成；研究状态未改变。') from None
        return Response(
            content,
            media_type='application/zip',
            headers={
                'Content-Disposition': f'attachment; filename="resume-package-{run_id[:8]}.zip"',
                'X-Content-Type-Options': 'nosniff',
                'Cache-Control': 'no-store',
            },
        )

    @app.post('/api/resume-packages', status_code=201)
    async def upload_resume_package(request: Request):
        from .resume_packages import inspect, read_package, save_upload, PackageError

        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > settings.resume_package_max_bytes:
                raise HTTPException(413, '成果包超过大小限制，可提高 CDR_RESUME_PACKAGE_MAX_BYTES 后重试')
            data.extend(chunk)
        try:
            await asyncio.to_thread(read_package, bytes(data), settings.resume_package_max_bytes)
            package_id = await asyncio.to_thread(save_upload, store, bytes(data))
            return await inspect(settings, store, package_id)
        except PackageError as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @app.post('/api/resume-packages/{package_id}/import', status_code=202)
    async def import_resume_package(package_id: str, body: ImportPackage):
        from .resume_packages import import_package, PackageError

        if len(store.active_runs()) >= settings.max_active_runs * 4:
            raise HTTPException(429, '研究队列已满，请稍后重试')
        try:
            run = await import_package(
                settings, store, package_id, body.level, body.keep_sections, body.accept_risks
            )
        except PackageError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except (ConfigurationError, RecoveryError, DatasourceError) as exc:
            raise HTTPException(409, str(exc)) from None
        schedule(run.run_id)
        return run

    @app.get('/api/research/{run_id}/download')
    async def download(run_id: str, format: Literal['docx', 'pdf'] = 'docx'):
        run = get_run(run_id)
        if run.status not in {'completed', 'limited'}:
            raise HTTPException(409, '报告尚未通过审核')
        approved_report(run_id)
        file = settings.artifacts / run.run_id / f'report.{format}'
        if not file.is_file():
            raise HTTPException(
                501 if format == 'pdf' else 404, '此环境未生成 PDF' if format == 'pdf' else '文件不存在'
            )
        return FileResponse(
            file,
            filename=f'company-research-{run.run_id[:8]}.{format}',
            media_type='application/pdf'
            if format == 'pdf'
            else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )

    @app.get('/api/research/{run_id}/recovery')
    async def recovery(run_id: str):
        get_run(run_id)
        return recovery_info(settings, store, run_id)

    @app.post('/api/research/{run_id}/pause', status_code=202)
    @app.post('/api/research/{run_id}/cancel', status_code=202)
    async def cancel(run_id: str):
        run = get_run(run_id)
        if not recovery_info(settings, store, run_id)['current_session']:
            raise HTTPException(409, '此任务未被启动窗口选择继续，不能暂停或继续；原成果可查看或导出。')
        if run.status in {'pausing', 'interrupted'}:
            return run
        if run.status not in {'running', 'queued'}:
            raise HTTPException(409, '仅运行中或排队任务可以中断')
        paused = store.transition_run(run_id, {'running', 'queued'}, status='pausing', stop_reason='user')
        if not paused:
            return get_run(run_id)
        store.emit(run_id, paused.stage, 'run', 'pausing', '正在保存进度，停止启动新工作；已发请求可能完成并计费')
        task = tasks.get(run_id)
        if run.status == 'queued' and task:
            task.cancel()
        watcher = asyncio.create_task(finish_pause(run_id, task))
        pause_tasks.add(watcher)
        watcher.add_done_callback(pause_tasks.discard)
        return paused

    @app.post('/api/research/pause-active')
    async def pause_active():
        """Local launcher shutdown: drain active work before terminating the service."""
        ids = [run.run_id for run in store.active_runs()]
        for run_id in ids:
            await cancel(run_id)
        await asyncio.gather(*list(pause_tasks), return_exceptions=True)
        return {'paused_runs': ids}

    @app.post('/api/research/{run_id}/budget')
    async def update_budget(run_id: str, body: UpdateBudget):
        run = get_run(run_id)
        if not recovery_info(settings, store, run_id)['can_increase_budget']:
            raise HTTPException(409, '仅暂停或可恢复失败任务可以调整预算')
        old = budget_limits(settings, store, run_id)
        value = body.model_dump()
        if any(value[k] < old[k] for k in old):
            raise HTTPException(422, '只能增加总预算，已有消耗和块预算不会清零')
        try:
            store.adjust_budget(run_id, value, old)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return recovery_info(settings, store, run_id)

    @app.post('/api/research/{run_id}/resume', status_code=202)
    async def resume(run_id: str):
        run = get_run(run_id)
        if run.status in {'running', 'queued'} and run_id in tasks and not tasks[run_id].done():
            return run
        info = recovery_info(settings, store, run_id)
        if not info['can_resume']:
            raise HTTPException(409, info['reason'])
        if len(store.active_runs()) >= settings.max_active_runs * 4:
            raise HTTPException(429, '研究队列已满，请稍后重试')
        try:
            gateway = load_gateway(settings, store, run_id) if run.mode == 'real' else None
            if gateway:
                for role in gateway.routes:
                    gateway.resolve(role)
            ensure_manifest(settings, store, run_id, gateway)
        except (ConfigurationError, RecoveryError, ValueError, KeyError, OSError):
            raise HTTPException(
                409, '资料、模型或配置无法通过恢复检查，请恢复原资料/模型并检查凭证；已有进度保留。'
            ) from None
        run = store.transition_run(run_id, {'interrupted', 'failed', 'blocked', 'waiting_human'}, status='queued')
        if not run:
            return get_run(run_id)
        store.emit(run_id, run.stage, 'run', 'queued', '已从断点排队，复用已保存的有效成果')
        schedule(run_id)
        return run

    return app


app = create_app()
