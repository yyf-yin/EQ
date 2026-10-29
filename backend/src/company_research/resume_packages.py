"""Resume packages: export a run's finished stages and start a new run that skips them.

A package carries the business context after the last completed node, the run's business
records and its uploaded files. Importing it creates a new run whose graph thread starts
right after the reused stages; only accepted report sections are carried into writing.
"""

import asyncio
import hashlib
import io
import json
import logging
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from .framework import VERSION, digest
from .schemas import ResearchRun, now, uid
from .storage import TERMINAL

logger = logging.getLogger('company_research')

FORMAT = 'cdr-resume-package'
PACKAGE_VERSION = 1
ORDER = [
    'resolve_company',
    'research_brief',
    'research_plan',
    'calculation_plan',
    'dependencies',
    'supervisor',
    'data_gaps',
    'replan',
    'financial_analysis',
    'assumptions',
    'calculate',
    'validate',
    'analyze_blocks',
    'write_sections',
    'core_conclusion',
    'assemble',
    'final_review',
    'revise',
    'render',
    'deliver',
]
# level -> what is reused, the node the new run starts at, the node it is seeded as,
# and the last node the source run must have completed.
LEVELS = {
    'collection': {
        'label': '资料与数据收集',
        'entry': 'financial_analysis',
        'as_node': 'data_gaps',
        'requires': 'data_gaps',
        'stages': ['公司识别', '研究规划', '数据收集'],
    },
    'forecast': {
        'label': '财务分析与盈利预测',
        'entry': 'analyze_blocks',
        'as_node': 'validate',
        'requires': 'validate',
        'stages': ['公司识别', '研究规划', '数据收集', '财务分析', '盈利预测'],
    },
    'blocks': {
        'label': '分块分析',
        'entry': 'write_sections',
        'as_node': 'analyze_blocks',
        'requires': 'analyze_blocks',
        'stages': ['公司识别', '研究规划', '数据收集', '财务分析', '盈利预测', '分块分析'],
    },
    'writing': {
        'label': '合格章节',
        'entry': 'write_sections',
        'as_node': 'analyze_blocks',
        'requires': 'assemble',
        'stages': ['公司识别', '研究规划', '数据收集', '财务分析', '盈利预测', '分块分析'],
    },
}
RANK = list(LEVELS)
# Record kinds never carried over: accounting, approvals and review results belong to the
# source run, and section records are writer caches that would replay rejected drafts.
SKIPPED_RECORDS = {
    'call',
    'usage',
    'approval',
    'review_issue',
    'invalidation',
    'reuse',
    'section',
    'reference_attachment',
}
ISSUE_LEVELS = {
    'research_plan': None,
    'supervisor': None,
    'financial_analysis': 'collection',
    'assumptions': 'collection',
    'calculate': 'collection',
}
RISKS = {
    'version': ('执行规则版本', 'high', '沿用的成果按旧执行规则保存，新流程读取时可能缺字段或口径不同。'),
    'financial_reconciliation': ('财务核对规则', 'high', '沿用的财务数据未按新核对规则检查。'),
    'data_collection': ('数据采集规则与槽位模板', 'high', '沿用的数据可能缺少新字段或口径不同。'),
    'prompts': ('提示词', 'medium', '沿用的成果按旧提示词生成，口径可能与新提示词不一致；未改动章节也会重新审核。'),
    'models': ('模型配置', 'medium', '沿用的成果来自其它模型或参数。'),
    'sources': ('本地资料目录', 'medium', '沿用的收集结果基于旧资料，新增或删除的资料不会体现。'),
    'research_limits': ('研究限额', 'low', '沿用的收集结果按旧的轮次与搜索限额完成。'),
    'retrieval': ('检索服务', 'low', '沿用的检索结果来自原检索服务。'),
    'human_intervention': ('人工核验规则', 'low', '沿用的人工核验结果按旧规则处理。'),
}
FILE_NAME = re.compile(r'^(package\.json|state/(context|records)\.json|attachments/[0-9a-f]{32}\.[a-z0-9]{1,8}|readable/[a-z_-]+\.md)$')
CONTAINERS = {'financial', 'business'}
FIXED = {'toc', 'statements', 'disclaimer'}


class PackageError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=1, default=str).encode('utf-8')


def available_levels(node):
    done = ORDER.index(node) if node in ORDER else -1
    return [level for level, spec in LEVELS.items() if done >= ORDER.index(spec['requires'])]


def selectable_sections(report):
    """Sections a writer produces on its own; containers and fixed tables are rebuilt."""
    result = []
    for top in report.sections:
        if top.section_id in FIXED:
            continue
        if top.section_id == 'financial':
            result.extend(top.children)
            continue
        result.append(top)
        if top.section_id == 'business':
            for segment in top.children:
                result.extend(segment.children)
    return result


def section_review(store, run_id, context):
    """Per-section verdicts from the review of the context's current report snapshot."""
    from .reports import sections_flat
    from .reviewers import issue_sections
    from .schemas import ReportDocument
    from .writers import report_snapshot

    report = ReportDocument.model_validate(context['report'])
    snapshot = report_snapshot(report)
    issues = [i for i in store.records(run_id, 'review_issue') if i.get('snapshot_id') == snapshot]
    reviewed = bool(issues) or any(r.get('snapshot_id') == snapshot for r in store.records(run_id, 'approval'))
    selectable = selectable_sections(report)
    ids = {s.section_id for s in selectable}
    children = {s.section_id: [x.section_id for x in sections_flat(s.children)] for s in sections_flat(report.sections)}
    failed, unmapped, levels = {}, [], []
    for issue in issues:
        if issue['severity'] not in {'critical', 'error'} and issue.get('validation_status') != 'unresolved':
            continue
        target = issue.get('target_node')
        if target in ISSUE_LEVELS:
            levels.append(ISSUE_LEVELS[target])
        hits = []
        for sid in issue_sections(issue, report.sections):
            hits += [sid] if sid in ids else [c for c in children.get(sid, []) if c in ids]
        if hits:
            for sid in hits:
                failed.setdefault(sid, []).append(issue['description'])
        elif target not in ISSUE_LEVELS:
            unmapped.append(issue['description'])
    sections = []
    for s in selectable:
        status = 'failed' if s.section_id in failed else 'passed' if reviewed else 'unreviewed'
        sections.append(
            {
                'section_id': s.section_id,
                'title': s.title,
                'status': status,
                'issues': failed.get(s.section_id, [])[:5],
                'default_keep': status != 'failed',
            }
        )
    return {
        'snapshot_id': snapshot,
        'reviewed': reviewed,
        'sections': sections,
        'unmapped_issues': unmapped[:10],
        'issue_levels': levels,
    }


def recommend(levels, review):
    if not levels:
        return None, '原任务尚未完成数据收集，没有可沿用的阶段。'
    best = levels[-1]
    note = '沿用全部已完成阶段，只做未完成的部分。'
    if review:
        wanted = review['issue_levels']
        if None in wanted:
            return levels[0], '终审问题指向资料收集，成果包无法只重做收集；建议新建研究，或从财务分析起重做。'
        if wanted:
            best = min(wanted, key=RANK.index)
            note = '终审问题指向财务计算或预测，建议从财务分析起重做。'
        elif review['unmapped_issues'] and best == 'writing':
            best = 'blocks'
            note = '部分写作问题无法定位到章节，建议重写全部章节。'
        elif best == 'writing' and any(s['status'] == 'failed' for s in review['sections']):
            note = '沿用合格章节，只重写不合格章节，并重新生成核心观点。'
        if best not in levels:
            best = levels[0]
    return best, note


async def _current_manifest(settings, store):
    from .execution import load_gateway, manifest

    gateway = None
    try:
        if settings.mode == 'real':
            gateway = load_gateway(settings, store, '')
        return manifest(settings, gateway, settings.mode), None
    except Exception as exc:
        return None, str(exc) or type(exc).__name__
    finally:
        if gateway:
            try:
                await gateway.aclose()
            except Exception:
                pass


def risks(previous, current, error=None):
    if error:
        return [{'field': 'models', 'label': '当前配置', 'level': 'high', 'message': '无法读取当前配置：' + error}]
    if not previous:
        return [
            {
                'field': 'manifest',
                'label': '执行指纹',
                'level': 'medium',
                'message': '原任务没有记录执行指纹，无法判断提示词、模型和资料是否变化。',
            }
        ]
    result = []
    for field, (label, level, message) in RISKS.items():
        if previous.get(field) != current.get(field):
            result.append({'field': field, 'label': label, 'level': level, 'message': message})
    return result


def export_package(settings, store, run_id):
    from .isolation import isolation_info

    run = store.run(run_id)
    if run.status not in TERMINAL:
        raise PackageError('任务仍在运行，请先暂停后再导出成果包。')
    reason = isolation_info(store, run_id)['reason']
    if reason:
        raise PackageError(reason)
    checkpoint = store.load_checkpoint(run_id)
    if not checkpoint:
        raise PackageError('任务尚无已完成的阶段成果，无法导出成果包。')
    node, context = checkpoint
    if context.get('rules_version') != VERSION:
        raise PackageError('旧规则任务的成果不能用于当前流程。')
    levels = available_levels(node)
    if not levels:
        raise PackageError('任务尚未完成数据收集，没有可沿用的阶段；请使用断点续跑或新建研究。')
    review = section_review(store, run_id, context) if 'writing' in levels else None
    recommended, note = recommend(levels, review)
    records = [
        {'kind': kind, 'id': record_id, 'payload': payload}
        for kind, record_id, payload in store.all_records(run_id)
        if kind not in SKIPPED_RECORDS
    ]
    files = {'state/context.json': _bytes(context), 'state/records.json': _bytes(records)}
    attachments = []
    with store.connect() as db:
        for attachment_id in run.reference_attachment_ids:
            row = db.execute('SELECT payload FROM reference_attachments WHERE id=?', (attachment_id,)).fetchone()
            if not row:
                raise PackageError('本次上传的资料记录缺失，无法导出成果包。')
            payload = json.loads(row[0])
            path = Path(payload.pop('path'))
            data = path.read_bytes() if path.is_file() else b''
            if hashlib.sha256(data).hexdigest() != payload['content_hash']:
                raise PackageError('本次上传的资料文件已改变或丢失，无法导出成果包。')
            name = 'attachments/' + uid() + (Path(payload['filename']).suffix.lower() or '.bin')
            files[name] = data
            attachments.append(payload | {'file': name})
    try:
        from .work_products import capture_snapshot, draft_md, summary_md

        snapshot = capture_snapshot(store, run_id, settings.work_product_max_bytes)
        files['readable/summary.md'] = summary_md(snapshot).encode('utf-8')
        files['readable/draft.md'] = draft_md(snapshot).encode('utf-8')
    except Exception as exc:
        logger.warning('run=%s resume_package_readable_error=%s', run_id, type(exc).__name__)
    package = {
        'format': FORMAT,
        'package_version': PACKAGE_VERSION,
        'created_at': now(),
        'source': {
            'run_id': run_id,
            'company_input': run.company_input,
            'company_name': run.company_name,
            'mode': run.mode,
            'status': run.status,
            'stage': run.stage,
            'error': run.error,
            'bullish': run.bullish,
        },
        'rules_version': VERSION,
        'checkpoint_node': node,
        'manifest': store.execution_get(run_id, 'execution_meta', 'manifest'),
        'performance': store.execution_get(run_id, 'execution_meta', 'performance'),
        'levels': levels,
        'recommended_level': recommended,
        'recommendation': note,
        'review': review,
        'attachments': attachments,
        'files': [
            {'path': name, 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
            for name, value in files.items()
        ],
    }
    buffer = io.BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('package.json', _bytes(package))
        for name, value in files.items():
            archive.writestr(name, value)
    return buffer.getvalue()


def read_package(data, max_bytes):
    """Verify every listed file; anything unlisted, missing or altered rejects the package."""
    try:
        archive = ZipFile(io.BytesIO(data))
        infos = archive.infolist()
        if sum(i.file_size for i in infos) > max_bytes * 4 or any(not FILE_NAME.match(i.filename) for i in infos):
            raise PackageError('成果包包含无法识别的文件，已拒绝。', 422)
        package = json.loads(archive.read('package.json'))
        if package.get('format') != FORMAT or package.get('package_version') != PACKAGE_VERSION:
            raise PackageError('不是本程序导出的成果包，或成果包版本不受支持。', 422)
        listed = {f['path']: f for f in package['files']}
        names = {i.filename for i in infos} - {'package.json'}
        if names != set(listed):
            raise PackageError('成果包文件清单不一致，可能已损坏或被修改。', 422)
        content = {}
        for name, entry in listed.items():
            value = archive.read(name)
            if len(value) != entry['bytes'] or hashlib.sha256(value).hexdigest() != entry['sha256']:
                raise PackageError('成果包内容校验失败，可能已损坏或被修改：' + name, 422)
            content[name] = value
    except PackageError:
        raise
    except (BadZipFile, KeyError, ValueError, TypeError):
        raise PackageError('成果包无法读取，可能已损坏或不是 ZIP 文件。', 422) from None
    return package, content


def _root(store):
    return store.path.parent / 'resume_packages'


def save_upload(store, data):
    package_id = uid()
    root = _root(store)
    root.mkdir(parents=True, exist_ok=True)
    (root / f'{package_id}.zip').write_bytes(data)
    return package_id


def load_upload(settings, store, package_id):
    if not re.fullmatch(r'[0-9a-f]{32}', package_id or ''):
        raise PackageError('成果包不存在，请重新上传。', 404)
    path = _root(store) / f'{package_id}.zip'
    if not path.is_file():
        raise PackageError('成果包不存在或已导入，请重新上传。', 404)
    return read_package(path.read_bytes(), settings.resume_package_max_bytes)


async def inspect(settings, store, package_id):
    package, _ = load_upload(settings, store, package_id)
    current, error = await _current_manifest(settings, store)
    incompatible = None
    if package['source']['mode'] != settings.mode:
        incompatible = '成果包来自{}，当前为{}，不能混用。'.format(
            *('模拟运行' if m == 'mock' else '真实研究' for m in (package['source']['mode'], settings.mode))
        )
    elif package['rules_version'] != VERSION:
        incompatible = '成果包属于其它业务规则版本，不能用于当前流程。'
    return {
        'package_id': package_id,
        'created_at': package['created_at'],
        'source': package['source'],
        'checkpoint_node': package['checkpoint_node'],
        'levels': [
            {
                'level': level,
                'label': spec['label'],
                'stages': spec['stages'],
                'available': level in package['levels'],
            }
            for level, spec in LEVELS.items()
        ],
        'recommended_level': package['recommended_level'],
        'recommendation': package['recommendation'],
        'review': package['review'],
        'attachments': [{'filename': a['filename'], 'size': a['size']} for a in package['attachments']],
        'risks': [] if incompatible else risks(package['manifest'], current or {}, error),
        'incompatible': incompatible,
    }


def _discard(store, run_id):
    tables = [
        'runs',
        'events',
        'reports',
        'checkpoints',
        'records',
        'work_product_snapshots',
        'work_product_reviews',
        'work_product_materials',
        'execution_units',
        'execution_meta',
        'execution_attempts',
    ]
    with store.lock, store.connect() as db:
        for row in db.execute('SELECT payload FROM reference_attachments WHERE run_id=?', (run_id,)).fetchall():
            Path(json.loads(row[0])['path']).unlink(missing_ok=True)
        db.execute('DELETE FROM reference_attachments WHERE run_id=?', (run_id,))
        for table in tables:
            db.execute(f'DELETE FROM {table} WHERE {"id" if table == "runs" else "run_id"}=?', (run_id,))


async def _seed_graph(settings, store, run_id, context, as_node):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .graphs import ResearchWorkflow

    async with AsyncSqliteSaver.from_conn_string(str(settings.database.parent / 'graph.sqlite')) as saver:
        config = {'configurable': {'thread_id': run_id}}
        try:
            graph = ResearchWorkflow(settings, store, run_id).build(saver)
            await graph.aupdate_state(config, {'context': context}, as_node=as_node)
            return (await graph.aget_state(config)).next
        except BaseException:
            await saver.adelete_thread(run_id)
            raise


async def import_package(settings, store, package_id, level, keep_sections, accept_risks, bullish=None):
    from .graphs import NODE_LABELS, STAGES
    from .isolation import POLICY as isolation_policy
    from .references import public_attachment

    info = await inspect(settings, store, package_id)
    if info['incompatible']:
        raise PackageError(info['incompatible'])
    package, content = load_upload(settings, store, package_id)
    if level not in package['levels']:
        raise PackageError('原任务尚未完成该阶段，不能从这里沿用。', 422)
    if info['risks'] and not accept_risks:
        raise PackageError('当前配置与成果包生成时不同，请确认风险后再导入。')
    spec = LEVELS[level]
    source = package['source']
    old = source['run_id']
    run = ResearchRun(company_input=source['company_input'], mode=settings.mode, rules_version='1.1')
    new = run.run_id
    context = json.loads(content['state/context.json'].decode('utf-8').replace(old, new))
    records = json.loads(content['state/records.json'].decode('utf-8').replace(old, new))
    context.update(revisions=0, issues=[], core_instructions=[])
    context.pop('imported_sections', None)
    source_style = context.get('writing_style', 'neutral')
    style = source_style if bullish is None else 'bullish' if bullish else 'neutral'
    context['writing_style'] = style
    run.bullish = style == 'bullish'
    if style != source_style:
        # Sections written in the other style would be kept verbatim; rewrite them all.
        keep_sections = []
    if any(r['field'] in {'prompts', 'models', 'manifest'} for r in info['risks']):
        context.pop('review_memo', None)
    if level in {'collection', 'forecast'}:
        context['block_analyses'] = {}
        records = [r for r in records if r['kind'] != 'block_analysis']
    kept, dropped = [], []
    if level == 'writing':
        from .reports import sections_flat
        from .schemas import ReportDocument

        report = ReportDocument.model_validate(context['report'])
        allowed = {s['section_id'] for s in package['review']['sections']}
        unknown = set(keep_sections) - allowed
        if unknown:
            raise PackageError('沿用章节不在成果包中：' + '，'.join(sorted(unknown)), 422)
        kept = [sid for sid in allowed if sid in keep_sections]
        dropped = sorted(allowed - set(kept))
        if dropped and 'core' in kept:
            # The core view summarises every section, so any rewrite invalidates it.
            kept.remove('core')
            dropped.append('core')
        flat = {s.section_id: s for s in sections_flat(report.sections)}
        context['imported_sections'] = {
            sid: flat[sid].model_copy(update={'children': [], 'tables': []}).model_dump(mode='json') for sid in kept
        }
    root = store.path.parent / 'reference_uploads'
    root.mkdir(parents=True, exist_ok=True)
    uploads = []
    for item in package['attachments']:
        attachment_id = uid()
        path = root / (attachment_id + Path(item['file']).suffix)
        path.write_bytes(content[item['file']])
        payload = {k: v for k, v in item.items() if k != 'file'} | {
            'attachment_id': attachment_id,
            'path': str(path.resolve()),
        }
        uploads.append(payload)
    run.reference_attachment_ids = [u['attachment_id'] for u in uploads]
    provenance = {
        'package_sha256': digest(package['files']),
        'source_run_id': old,
        'level': level,
        'kept_sections': sorted(kept),
        'dropped_sections': dropped,
        'writing_style': style,
        'accepted_risks': [r['field'] for r in info['risks']],
        'imported_at': now(),
    }
    meta = {
        'data-isolation': {'version': isolation_policy, 'run_id': new},
        'service-session': {'session_id': getattr(store, 'service_session_id', None)},
        'resume-package': provenance,
        'performance': package.get('performance') or {'version': 'throughput-1'},
    }
    try:
        with store.lock, store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO runs VALUES(?,?)', (new, run.model_dump_json()))
            for key, value in meta.items():
                db.execute('INSERT INTO execution_meta VALUES(?,?,?)', (new, key, json.dumps(value, ensure_ascii=False)))
            for payload in uploads:
                db.execute(
                    'INSERT INTO reference_attachments VALUES(?,?,?)',
                    (payload['attachment_id'], new, json.dumps(payload, ensure_ascii=False)),
                )
                db.execute(
                    'INSERT INTO records VALUES(?,?,?,?)',
                    (
                        new,
                        'reference_attachment',
                        payload['attachment_id'],
                        json.dumps(public_attachment(payload), ensure_ascii=False),
                    ),
                )
            for r in records:
                db.execute(
                    'INSERT OR REPLACE INTO records VALUES(?,?,?,?)',
                    (new, r['kind'], r['id'], json.dumps(r['payload'], ensure_ascii=False)),
                )
        store.checkpoint(new, spec['as_node'], context)
        following = await _seed_graph(settings, store, new, context, spec['as_node'])
        if following != (spec['entry'],):
            raise PackageError('成果包的研究进度无法衔接到所选阶段，请选择更早的阶段。', 422)
    except BaseException:
        await asyncio.to_thread(_discard, store, new)
        for payload in uploads:
            Path(payload['path']).unlink(missing_ok=True)
        raise
    for stage in dict.fromkeys(spec['stages']):
        store.emit(new, stage, stage, 'completed', f'{stage}：沿用成果包')
    detail = f'沿用至「{spec["label"]}」，从「{NODE_LABELS[spec["entry"]]}」继续'
    if level == 'writing':
        detail += f'；沿用 {len(kept)} 个章节，重写 {len(dropped)} 个'
    store.emit(new, STAGES[spec['entry']], 'resume_package', 'queued', f'已导入成果包（来源任务 {old[:8]}）：{detail}')
    (_root(store) / f'{package_id}.zip').unlink(missing_ok=True)
    return store.run(new)
