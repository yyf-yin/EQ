"""Task-bound user uploads and reference-first retrieval planning."""

import hashlib
import json
from pathlib import Path

from pydantic import Field
from .schemas import Schema, SourceRecord, uid, now, FinancialFact
from .datasources import EXTENSIONS, MAX_BYTES, parse_material, source_record, join_document_chunks, DatasourceError
from .financials.formulas import FinancialDataProcessor, FinancialError, FIELD_MAP
from .framework import digest

POLICY = 'uploaded-reference-1'


def prepare_uploads(store):
    with store.connect() as db:
        db.execute(
            'CREATE TABLE IF NOT EXISTS reference_attachments(id TEXT PRIMARY KEY, run_id TEXT, payload TEXT NOT NULL)'
        )


def public_attachment(payload):
    return {
        k: payload[k]
        for k in ('attachment_id', 'filename', 'size', 'content_hash', 'created_at', 'status', 'source_count')
    }


def register_upload(store, filename, data):
    filename = filename.replace('\\', '/').rsplit('/', 1)[-1].strip()
    suffix = Path(filename).suffix.lower()
    if not filename or len(filename) > 200 or suffix not in EXTENSIONS:
        raise DatasourceError('不支持的文件格式，请上传 PDF、DOCX、XLSX、CSV、TXT、MD、JSON 或 HTML')
    if not data:
        raise DatasourceError('文件为空，请选择有内容的参考资料')
    if len(data) > MAX_BYTES:
        raise DatasourceError('单份参考资料不能超过 20 MB')
    attachment_id = uid()
    try:
        chunks = parse_material(data, suffix)
        records = join_document_chunks(
            [
                source_record(
                    'upload', filename, content, locator, local_path=attachment_id + suffix, attachment_id=attachment_id
                )
                for locator, content in chunks
                if content.strip()
            ]
        )
    except DatasourceError:
        raise
    except Exception:
        raise DatasourceError('参考资料解析失败，请检查文件格式或提供可复制文本的版本') from None
    if not records:
        raise DatasourceError('参考资料没有可读取的正文，请提供文本或 OCR 后的材料')
    root = store.path.parent / 'reference_uploads'
    root.mkdir(parents=True, exist_ok=True)
    path = root / (attachment_id + suffix)
    path.write_bytes(data)
    payload = {
        'attachment_id': attachment_id,
        'filename': filename,
        'size': len(data),
        'content_hash': hashlib.sha256(data).hexdigest(),
        'created_at': now(),
        'status': 'ready',
        'source_count': len(records),
        'path': str(path.resolve()),
        'sources': [s.model_dump(mode='json') for s in records],
    }
    try:
        with store.lock, store.connect() as db:
            db.execute(
                'INSERT INTO reference_attachments VALUES(?,NULL,?)',
                (attachment_id, json.dumps(payload, ensure_ascii=False)),
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return public_attachment(payload)


def create_with_attachments(store, run, attachment_ids, max_files):
    """Bind all uploads and create the isolated run in one transaction before scheduling."""
    from .isolation import POLICY as isolation_policy

    if len(attachment_ids) > max_files or len(set(attachment_ids)) != len(attachment_ids):
        raise DatasourceError(f'参考资料最多 {max_files} 份，且不能重复绑定')
    with store.lock, store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        payloads = []
        for attachment_id in attachment_ids:
            row = db.execute('SELECT run_id,payload FROM reference_attachments WHERE id=?', (attachment_id,)).fetchone()
            if not row or row[0] is not None:
                raise DatasourceError('参考资料不存在或已绑定其它研究，请重新上传')
            payload = json.loads(row[1])
            path = Path(payload['path'])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != payload['content_hash']:
                raise DatasourceError('参考文件已改变或丢失，请重新上传')
            payloads.append(payload)
        run.reference_attachment_ids = list(attachment_ids)
        db.execute('INSERT INTO runs VALUES(?,?)', (run.run_id, run.model_dump_json()))
        db.execute(
            'INSERT INTO execution_meta VALUES(?,?,?)',
            (run.run_id, 'data-isolation', json.dumps({'version': isolation_policy, 'run_id': run.run_id})),
        )
        for payload in payloads:
            db.execute(
                'UPDATE reference_attachments SET run_id=? WHERE id=? AND run_id IS NULL',
                (run.run_id, payload['attachment_id']),
            )
            db.execute(
                'INSERT INTO records VALUES(?,?,?,?)',
                (
                    run.run_id,
                    'reference_attachment',
                    payload['attachment_id'],
                    json.dumps(public_attachment(payload), ensure_ascii=False),
                ),
            )
            for source in payload['sources']:
                db.execute(
                    'INSERT INTO records VALUES(?,?,?,?)',
                    (run.run_id, 'source', source['source_id'], json.dumps(source, ensure_ascii=False)),
                )


def reference_fingerprint(store, run_id):
    """Check original bytes on resume; sources and attachment ownership remain immutable."""
    run = store.run(run_id)
    if not run or not run.reference_attachment_ids:
        return None
    values = []
    with store.connect() as db:
        for attachment_id in run.reference_attachment_ids:
            row = db.execute('SELECT run_id,payload FROM reference_attachments WHERE id=?', (attachment_id,)).fetchone()
            if not row or row[0] != run_id:
                raise DatasourceError('上传参考资料的任务绑定不匹配')
            payload = json.loads(row[1])
            path = Path(payload['path'])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != payload['content_hash']:
                raise DatasourceError('上传参考文件已改变或丢失，无法沿用原研究断点')
            values.append([attachment_id, payload['content_hash']])
    return {'policy': POLICY, 'attachments': digest(values)}


class ReferenceQuestionSupport(Schema):
    covered: dict[str, list[str]] = Field(default_factory=dict)


def reference_support_context(task, questions, brief, business, evidence, facts):
    """Keep semantic inputs intact; provenance details remain in the audit store.

    Document-wide locators are not evidence text. Repeating their hundreds of
    page labels on each fact and quote used to force almost one HTTP call per
    evidence. Put shared context before the changing lists for prefix caching.
    """
    evidence_fields = ('evidence_id', 'source_id', 'claim', 'quote', 'actual_or_forecast')
    fact_fields = (
        'fact_id',
        'evidence_id',
        'source_id',
        'company_id',
        'metric_code',
        'period',
        'value',
        'unit',
        'currency',
        'scope',
        'segment_id',
        'accounting_basis',
        'actual_or_forecast',
        'version',
        'supersedes',
    )
    return {
        'instructions': [
            '本次只判断上传参考资料能否完整支持每个问题，返回 covered 映射：问题 ID -> 支持它的 evidence_id 列表。',
            '行业规模、需求、价格、政策、竞争、产业链信息也可来自上传资料，不要求资料必须提到目标公司或业务名称；需要确认与目标业务相关。',
            '保留数据年份、地域、统计口径和预测/实际属性；行业或同行数据不能冒充目标公司财务事实。',
            '可直接从已提取财务事实计算或分析的问题无需外部搜索。证据不足的不要填入 covered。不要生成补充查询。',
        ],
        'task': {k: v for k, v in task.items() if k != 'queries'},
        'questions': questions,
        'brief': brief,
        'business': business,
        'facts': [{k: f[k] for k in fact_fields if k in f} for f in facts],
        'evidence': [{k: e[k] for k in evidence_fields if k in e} for e in evidence],
    }


def reference_question_support(context, store=None, run_id=None):
    """Bind question coverage to verified uploaded evidence in this context/run."""
    upload_ids = {s['source_id'] for s in context.get('sources', []) if s.get('kind') == 'upload'}
    allowed = {
        e['evidence_id']
        for e in context.get('evidence', [])
        if (context.get('data_template_version') or e['source_id'] in upload_ids)
        and e.get('validation_status') == 'verified'
    }
    mapping = dict(context.get('reference_question_support', {}))
    if store and run_id:
        for record in store.records(run_id, 'reference_coverage'):
            for q, ids in record.get('covered_questions', {}).items():
                mapping[q] = list(dict.fromkeys(mapping.get(q, []) + ids))
    return {q: [id for id in ids if id in allowed] for q, ids in mapping.items() if any(id in allowed for id in ids)}


async def plan_reference_queries(task, context, gateway, store, run_id):
    """Only absent fields/questions become external queries; support must cite upload evidence."""
    upload_ids = {s['source_id'] for s in context.get('sources', []) if s.get('kind') == 'upload'}
    if not upload_ids:
        return task
    facts = [
        f for f in context.get('facts', []) if f['source_id'] in upload_ids and f['validation_status'] == 'verified'
    ]
    evidence = [
        e for e in context.get('evidence', []) if e['source_id'] in upload_ids and e['validation_status'] == 'verified'
    ]
    requirements = [r for r in context.get('required_data', []) if r['data_id'] in task.get('required_data_ids', [])]
    missing = []
    coverage = []
    processor = FinancialDataProcessor()
    parsed = [FinancialFact.model_validate(f) for f in facts]
    for r in requirements:
        try:
            f = processor.get(
                parsed,
                r['company_id'],
                r['metric_code'],
                r['period'],
                r['unit'],
                r.get('segment_id'),
                'segment' if r.get('segment_id') else 'consolidated',
            )
            coverage.append({'identity': r, 'status': 'covered', 'fact_id': f.fact_id})
        except FinancialError as exc:
            # An upload conflict must never be resolved by querying lower-priority sources.
            conflict = any(
                f.company_id == r['company_id']
                and f.metric_code == r['metric_code']
                and f.period == r['period']
                and f.segment_id == r.get('segment_id')
                and f.unit == r['unit']
                and f.actual_or_forecast == 'actual'
                and f.scope == ('segment' if r.get('segment_id') else 'consolidated')
                for f in parsed
            )
            coverage.append({'identity': r, 'status': 'conflict' if conflict else 'absent', 'reason': str(exc)})
            if not conflict:
                missing.append(r)
    blocks = {b['block_id']: b for b in context.get('plan', {}).get('blocks', [])}
    block = blocks.get(task.get('block_id'), {})
    questions = {q: block.get('questions', {}).get(q, q) for q in task.get('question_ids', [])}
    if not questions and not requirements:
        questions = {'topic': task['topic']}
    covered = {}
    if questions and evidence:
        from .agents import ask_bounded

        decision = await ask_bounded(
            gateway,
            'reference_planner',
            ReferenceQuestionSupport,
            reference_support_context(
                task, questions, context.get('brief', {}), block.get('segment_id'), evidence, facts
            ),
        )
        known = {e['evidence_id'] for e in evidence}
        covered = {q: ids for q, ids in decision.covered.items() if q in questions and ids and set(ids) <= known}
    name = context['company']['name']
    queries = [
        f"{name} {r['period']} {r.get('segment_id') or ''} {next((k for k, v in FIELD_MAP.items() if v == r['metric_code']), r['metric_code'])} 官方报告"
        for r in missing
    ]
    queries += [name + ' ' + text for q, text in questions.items() if q not in covered]
    # One query per missing target; never carry the original full-data query forward.
    record = {
        'task_id': task['task_id'],
        'fields': coverage,
        'covered_questions': covered,
        'missing_questions': [q for q in questions if q not in covered],
        'external_queries': queries,
        'status': 'partial' if queries else 'covered',
    }
    store.record(run_id, 'reference_coverage', task['task_id'], record)
    store.emit(
        run_id,
        '数据收集',
        'reference_coverage',
        'completed',
        f"参考资料覆盖检查：{task['topic']}；仅补查 {len(queries)} 项缺失数据或问题",
    )
    return task | {'queries': queries}
