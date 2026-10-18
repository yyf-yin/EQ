"""Independent, immutable evaluation exports. No model calls or report rendering."""

import hashlib
import io
import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zipfile import ZipFile, ZIP_DEFLATED

from .framework import digest
from .schemas import ReportDocument, now, uid

CONTRACT = '1.2'
NOTICE = '阶段成果｜未经最终审核｜可能不完整，仅供研究流程评估'
logger = logging.getLogger(__name__)
SECRET = re.compile(r'password|passwd|secret|token|api[_-]?key|authorization|credential|signature|access[_-]?key', re.I)
PRIVATE = {
    'system',
    'system_prompt',
    'messages',
    'request',
    'request_body',
    'response_body',
    'headers',
    'reasoning',
    'thinking',
    'chain_of_thought',
    'hidden_reasoning',
}


class WorkProductError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def sanitize(value):
    """Defense in depth after allow-list projection; keep ordinary token counters."""
    if isinstance(value, dict):
        return {
            k: sanitize(v)
            for k, v in value.items()
            if k.lower() not in PRIVATE
            and not (SECRET.search(k) and not ('tokens' in k.lower() or k == 'count_method'))
        }
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if not isinstance(value, str):
        return value

    def clean_url(match):
        try:
            parts = urlsplit(match.group())
            host = parts.netloc.rsplit('@', 1)[-1]
            query = [
                (k, '[REDACTED]' if SECRET.search(k) or k.lower() in {'key', 'auth', 'sig'} else v)
                for k, v in parse_qsl(parts.query, keep_blank_values=True)
            ]
            return urlunsplit((parts.scheme, host, parts.path, urlencode(query), ''))
        except ValueError:
            return '[URL不可显示]'

    value = re.sub(r'https?://[^\s<>"\]]+', clean_url, value)
    value = re.sub(r'\bBearer\s+[^\s,;]+', 'Bearer [REDACTED]', value, flags=re.I)
    value = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[REDACTED]', value)
    value = re.sub(
        r'(?i)\b(api[_-]?key|password|secret|access[_-]?token|authorization)\s*[:=]\s*["\x27]?[^\s,;"\x27]+',
        r'\1=[REDACTED]',
        value,
    )
    return value


# Only explicit research fields are eligible. Context packages, provider bodies,
# source full texts and extraction windows are never copied wholesale.
FIELDS = {
    'data_slot': 'slot_id template_version company_id field_id metric_code label requirement period period_start period_end period_kind period_label scope segment_id bond_id detail_id product_name quantity_kind state raw_value raw_unit raw_label normalized_value normalized_unit currency accounting_basis source_id evidence_id locator content_hash report_binding_id header_quote unit_quote period_quote column_index reason locked_at attempt_count absence_quote',
    'collection_slot': 'slot_id topic block_id state source_ids evidence_ids limitations search_count contract_version scope directions direction_statuses search_history stop_reason search_budget',
    'slot_calculation': 'result_id metric_code period value unit input_refs formula policy_version',
    'bond_presence': 'source_id state quote periods',
    'fixed_derived_fact': 'fact_id company_id metric_code period unit value actual_or_forecast source_id evidence_id locator validation_status segment_id scope currency accounting_basis version supersedes value_origin derivation_id',
    'reference_attachment': 'attachment_id filename size content_hash created_at status source_count',
    'reference_coverage': 'task_id fields covered_questions missing_questions external_queries status',
    'human_issue': 'issue_id group_id signature identity candidates reason blocking kind status phase question created_at updated_at feedback_error',
    'human_feedback': 'feedback_id issue_id group_id identity signature action reason fact_id source_id quote locator value unit accounting_basis query status error created_at completed_at',
    'human_resolution': 'resolution_id group_id signature fact_id reason feedback_id created_at',
    'source_metadata': 'source_id differences',
    'fact_decision': 'decision_id group_id policy identity candidate_ids candidates selected_ids status rule reason proof_evidence_ids',
    'fact_verification': 'verification_id group_id attempt queries candidate_ids candidate_signature source_ids evidence_ids status',
    'source': 'source_id kind title source_url locator publication_date retrieved_at content_hash attachment_id',
    'evidence': 'evidence_id source_id claim quote locator actual_or_forecast validation_status',
    'fact': 'fact_id company_id metric_code period unit value actual_or_forecast source_id evidence_id locator validation_status segment_id scope currency accounting_basis version supersedes slot_id raw_value raw_unit locked_at value_origin derivation_id',
    'calculation': 'result_id formula_id formula_version output_metric period scenario segment_id unit value input_refs inputs',
    'comparison': 'comparison_id metric_code current_period previous_period current_fact_id previous_fact_id current_value previous_value delta rate unit status scope currency accounting_basis comparison_type calculation_ids formula_version',
    'assumption': 'assumption_id company_id metric_code period scenario value unit rationale evidence_ids segment_id',
    'forecast': 'company_id period scenario income balance cashflow result_ids assumption_ids segments',
    'block': 'block_id template_id template_version company_id segment_id questions dependencies call_budget status version',
    'block_analysis': 'block_id version conclusions evidence_ids calculation_ids counter_evidence_ids limitations status',
    'coverage': 'block_id question_id required requirements status gaps task_id verified_refs validation',
    'task': 'task_id company_id topic role queries block_id question_ids segment_id required_data_ids linked_segments',
    'review_issue': 'issue_id issue_type severity location description suggested_fix target_node snapshot_id rule_id block_id section_id paragraphs requested_target affected_refs validation_status',
    'batch': 'batch_id block_id company_id segment_id question_ids periods scope_hint metric_codes status estimated_input_tokens parent_id failure',
    'call': 'call_id role block_id batch_id model_config model protocol prompt_version attempt estimated_input_tokens budget_tokens count_method input_tokens output_tokens usage_source finish_reason result duration_seconds',
    'invalidation': 'snapshot_id responsible_blocks affected_blocks reason',
}
SECTION_FIELDS = (
    'section_id title paragraphs children evidence_ids calculation_ids tables number_bindings consistency_checks'
)
REPORT_FIELDS = 'title company_id mode as_of sections sources evidence calculations assumptions forecasts financial_facts issues limitations charts rules_version data_template_version snapshot_id approved_snapshot_id brief blocks coverage comparisons'


def project(value, fields):
    result = {k: value[k] for k in fields.split() if k in value}
    if fields == FIELDS['collection_slot'] and 'search_history' in result:
        result['search_history'] = [
            project(h, 'query direction_ids source_ids warnings state') for h in result['search_history']
        ]
    return result


def section_view(section):
    result = project(section, SECTION_FIELDS)
    result['children'] = [section_view(s) for s in section.get('children', [])]
    result['tables'] = [project(t, 'title columns rows') for t in section.get('tables', [])]
    return result


def report_view(report):
    value = project(report, REPORT_FIELDS)
    value['sections'] = [section_view(s) for s in report.get('sections', [])]
    for name, kind in [
        ('sources', 'source'),
        ('evidence', 'evidence'),
        ('financial_facts', 'fact'),
        ('calculations', 'calculation'),
        ('assumptions', 'assumption'),
        ('forecasts', 'forecast'),
        ('issues', 'review_issue'),
        ('blocks', 'block'),
        ('coverage', 'coverage'),
        ('comparisons', 'comparison'),
    ]:
        value[name] = [project(v, FIELDS[kind]) for v in report.get(name, [])]
    return value


def preserve_review(store, run_id, report, round_number, review_id=None, outcome='pending'):
    """Best effort sidecar. Its failure must never change review control flow."""
    review_id = review_id or uid()
    try:
        from .writers import report_snapshot

        payload = {
            'review_id': review_id,
            'round': round_number,
            'timestamp': now(),
            'snapshot_id': report_snapshot(report),
            'outcome': outcome,
            'report': report_view(report.model_dump(mode='json')),
        }
        if outcome == 'pending':
            payload['report']['issues'] = []
        store.save_work_product_review(run_id, review_id, sanitize(payload))
    except Exception as exc:
        logger.warning('run=%s evaluation_review_unavailable=%s', run_id, type(exc).__name__)
    return review_id


def preserve_materials(store, run_id, materials):
    try:
        store.save_work_product_materials(
            run_id, [(kind, key, sanitize(project(value, FIELDS[kind]))) for kind, key, value in materials]
        )
    except Exception as exc:
        logger.warning('run=%s evaluation_material_unavailable=%s', run_id, type(exc).__name__)


def _flatten(sections):
    for section in sections:
        yield section
        yield from _flatten(section.get('children', []))


def _merge(values, extra, key):
    merged = {v.get(key, digest(v)): v for v in values}
    for value in extra:
        merged[value.get(key, digest(value))] = value
    return list(merged.values())


def build_snapshot(state):
    run, ctx, records = state['run'], state.get('context') or {}, state['records']
    records = dict(records)
    primary_keys = {
        'source': 'source_id',
        'evidence': 'evidence_id',
        'fact': 'fact_id',
        'calculation': 'result_id',
        'fact_decision': 'decision_id',
        'fact_verification': 'verification_id',
        'human_issue': 'issue_id',
        'human_feedback': 'feedback_id',
        'human_resolution': 'resolution_id',
        'comparison': 'comparison_id',
        'assumption': 'assumption_id',
        'block': 'block_id',
        'block_analysis': 'block_id',
        'coverage': 'question_id',
        'task': 'task_id',
        'review_issue': 'issue_id',
        'batch': 'batch_id',
    }
    for kind, values in state.get('partial', {}).items():
        if kind != 'forecast':
            records[kind] = _merge(values, records.get(kind, []), primary_keys[kind])
    report = ctx.get('report') or state.get('report')
    # A blocked review saves the last candidate before raising, so it can be newer
    # than the completed-node checkpoint. Select that candidate by its review id.
    saved = state.get('report')
    if saved and state['reviews'] and state['reviews'][-1]['outcome'] == 'rejected':
        if saved.get('snapshot_id') == state['reviews'][-1]['snapshot_id']:
            report = saved
    data = {kind: [project(v, fields) for v in records.get(kind, [])] for kind, fields in FIELDS.items()}
    mapping = [
        ('sources', 'source', 'source_id'),
        ('evidence', 'evidence', 'evidence_id'),
        ('facts', 'fact', 'fact_id'),
        ('calculations', 'calculation', 'result_id'),
        ('comparisons', 'comparison', 'comparison_id'),
        ('assumptions', 'assumption', 'assumption_id'),
    ]
    for name, kind, key in mapping:
        values = ctx.get(name, [])
        if not values and report:
            values = report.get('financial_facts' if name == 'facts' else name, [])
        data[kind] = _merge([project(v, FIELDS[kind]) for v in values], data[kind], key)
    data['forecast'] = [
        project(v, FIELDS['forecast']) for v in ctx.get('forecasts', (report or {}).get('forecasts', []))
    ]
    data['forecast'] = (
        _merge(state.get('partial', {}).get('forecast', []), data['forecast'], 'evaluation_forecast_id')
        if not data['forecast']
        else data['forecast']
    )
    data['block'] = _merge(
        (ctx.get('plan') or {}).get('blocks', (report or {}).get('blocks', [])), data['block'], 'block_id'
    )
    data['block_analysis'] = _merge(list(ctx.get('block_analyses', {}).values()), data['block_analysis'], 'block_id')
    data['coverage'] = _merge(ctx.get('coverage', (report or {}).get('coverage', [])), data['coverage'], 'question_id')
    data['task'] = _merge((ctx.get('plan') or {}).get('tasks', []), data['task'], 'task_id')
    data['brief'] = project(
        ctx.get('brief') or (report or {}).get('brief') or {},
        'company_id scope historical_periods forecast_periods segments interim_period quarterly_collection source_ids as_of',
    )
    data['required_data'] = [
        project(v, 'data_id company_id metric_code period unit segment_id priority formula_dependency source_status')
        for v in ctx.get('required_data', [])
    ]
    data['comparison_gaps'] = ctx.get('comparison_gaps', [])
    data['limitations'] = ctx.get('limitations', run.get('limitations', []))
    raw_sections = [
        project(v, 'section_id version block_id input_snapshot_id selected_versions generated_at')
        | {'content': section_view(v['content'])}
        for v in records.get('section', [])
        if isinstance(v.get('content'), dict)
    ]
    sections = {
        s['section_id']: {
            'section_id': s['section_id'],
            'version': (report or {}).get('snapshot_id', ''),
            'content': section_view(s),
            'from_report': True,
        }
        for s in _flatten((report or {}).get('sections', []))
    }
    for s in raw_sections:
        # Prefer full assembled sections; isolated partial sections remain useful
        # when a later writer call fails before a ReportDocument exists.
        if s.get('generated_at', '') > (report or {}).get('as_of', ''):
            sections[s['section_id']] = s
        else:
            sections.setdefault(s['section_id'], s)
    from .writers import report_snapshot, section_block

    selected_facts = _merge(
        ctx.get('facts', (report or {}).get('financial_facts', [])), records.get('fact', []), 'fact_id'
    )
    if 'fact_decisions' in ctx:
        selected_ids = {f['fact_id'] for f in ctx.get('facts', [])}
        selected_facts = [f for f in selected_facts if f['fact_id'] in selected_ids]
        data['fact_decision'] = [project(v, FIELDS['fact_decision']) for v in ctx['fact_decisions']]
    report_stale = bool(report and digest(selected_facts) != digest(report.get('financial_facts', [])))
    # Compare without list ordering (DB record order differs from report order).
    if report:
        report_stale = digest(sorted(selected_facts, key=lambda f: f['fact_id'])) != digest(
            sorted(report.get('financial_facts', []), key=lambda f: f['fact_id'])
        )
    validity_context = ctx | {'facts': selected_facts}
    baseline_facts = {v['fact_id']: v for v in ctx.get('facts', (report or {}).get('financial_facts', []))}
    changed_fact_ids = {
        v['fact_id']
        for v in selected_facts
        if v['fact_id'] in baseline_facts and digest(v) != digest(baseline_facts[v['fact_id']])
    }
    invalid_blocks = {b for v in records.get('invalidation', []) for b in v.get('affected_blocks', [])}
    stale_refs = {v['supersedes'] for v in data['fact'] if v.get('supersedes')}
    if 'fact_decisions' in ctx:
        stale_refs = {v['fact_id'] for v in data['fact']} - {v['fact_id'] for v in selected_facts}
    superseded_facts = set(stale_refs)
    stale_refs |= changed_fact_ids
    for _ in range(len(data['calculation']) + 1):
        new = {v['result_id'] for v in data['calculation'] if set(v.get('input_refs', {}).values()) & stale_refs}
        if new.issubset(stale_refs):
            break
        stale_refs |= new
    artifacts = []
    current_issues = (report or {}).get('issues', [])
    if state['reviews']:
        current_issues = state['reviews'][-1]['report'].get('issues', current_issues)
    data['current_review_issues'] = [project(i, FIELDS['review_issue']) for i in current_issues]
    for section in sections.values():
        block = section.get('block_id') or section_block(section['section_id'])
        stale = report_stale if section.get('from_report') else block in invalid_blocks
        if section.get('input_snapshot_id') and ctx.get('plan') and ctx.get('brief'):
            try:
                from .contexts import block_context

                stale = section['input_snapshot_id'] != block_context(validity_context, block, 'writing').snapshot_id
            except (KeyError, ValueError, TypeError, RuntimeError):
                stale = True
        bad = any(
            i.get('severity') in {'critical', 'error'}
            and (i.get('location') == section['section_id'] or i.get('block_id') == block)
            for i in current_issues
        )
        content = section['content']
        section.update(
            block_id=block,
            generation_status='complete'
            if content.get('paragraphs') or content.get('tables') or content.get('children')
            else 'not_produced',
            validation_status='rejected' if bad else 'unreviewed',
            version_status='stale' if stale else 'current',
        )
        artifacts.append(
            {k: v for k, v in section.items() if k not in {'content', 'from_report', 'selected_versions'}}
            | {'kind': 'section'}
        )
    final_passed = False
    if report and report.get('rules_version') == '1.1' and not report_stale:
        try:
            from .comparisons import core_gate

            parsed = ReportDocument.model_validate(report)
            approved = parsed.approved_snapshot_id
            final_passed = bool(
                approved
                and approved == report_snapshot(parsed)
                and not core_gate(parsed)
                and any(
                    v.get('snapshot_id') == approved and v.get('status') == 'approved'
                    for v in records.get('approval', [])
                )
            )
        except (ValueError, KeyError, TypeError):
            pass
    for section in sections.values():
        if final_passed and section.get('from_report') and section['version_status'] == 'current':
            section['validation_status'] = 'passed'
    for artifact in artifacts:
        artifact['validation_status'] = sections[artifact['section_id']]['validation_status']
    for kind in FIELDS:
        if kind in {'call', 'invalidation'}:
            continue
        for value in data[kind]:
            item_id = value.get(primary_keys.get(kind, ''), digest(value))
            stale = item_id in (superseded_facts if kind == 'fact' else stale_refs) or bool(
                kind == 'block_analysis' and value.get('block_id') in invalid_blocks
            )
            if kind == 'comparison':
                stale = value.get('current_fact_id') in stale_refs or value.get('previous_fact_id') in stale_refs
            if kind == 'forecast':
                stale = bool(set(value.get('result_ids', [])) & stale_refs)
            if kind == 'block_analysis' and value.get('block_id') == 'X01':
                stale = report_stale
            # Validate the current block package when enough context is available.
            if kind == 'block_analysis' and value.get('block_id') != 'X01' and ctx.get('plan') and ctx.get('brief'):
                try:
                    from .contexts import block_context

                    stale = (
                        value.get('version')
                        != block_context(validity_context, value['block_id'], 'analysis').snapshot_id
                    )
                except (KeyError, ValueError, TypeError, RuntimeError):
                    stale = True
            if kind in {'calculation', 'comparison', 'forecast'} and ctx.get(
                {'calculation': 'calculations', 'comparison': 'comparisons', 'forecast': 'forecasts'}[kind]
            ):
                selected = ctx[
                    {'calculation': 'calculations', 'comparison': 'comparisons', 'forecast': 'forecasts'}[kind]
                ]
                if kind != 'forecast':
                    key = 'result_id' if kind == 'calculation' else 'comparison_id'
                    stale = stale or item_id not in {v[key] for v in selected}
            validation = value.get('validation_status', 'unreviewed')
            if kind == 'fact_decision':
                validation = 'conflict' if value['status'] == 'unresolved' else 'verified'
            if kind == 'fact' and 'fact_decisions' in ctx and item_id not in {f['fact_id'] for f in selected_facts}:
                validation = (
                    'conflict'
                    if any(item_id in d['candidate_ids'] and d['status'] == 'unresolved' for d in ctx['fact_decisions'])
                    else 'excluded'
                )
            if kind in {'block', 'block_analysis'} and value.get('status') == 'validated' and not stale:
                validation = 'verified'
            if (
                kind == 'calculation'
                and ctx.get('validated')
                and not stale
                and item_id in {v['result_id'] for v in ctx.get('calculations', [])}
            ):
                validation = 'verified'
            artifacts.append(
                {
                    'kind': kind,
                    'id': item_id,
                    'block_id': value.get('block_id'),
                    'version': value.get('version'),
                    'generation_status': 'complete',
                    'validation_status': validation,
                    'version_status': 'stale' if stale else 'current',
                    'dependencies': project(
                        value,
                        'evidence_ids calculation_ids input_refs source_id evidence_id current_fact_id previous_fact_id result_ids assumption_ids',
                    ),
                }
            )
    missing = [
        {'kind': 'section', 'id': key, 'reason': '尚未生成'}
        for key in ['core', 'company', 'F01', 'F02', 'F03', 'F04', 'F05', 'business', 'forecast', 'risk', 'statements']
        if key not in sections or sections[key]['generation_status'] == 'not_produced'
    ]
    missing += [
        {'kind': 'coverage', 'id': v['question_id'], 'reason': '；'.join(v.get('gaps', [])) or v['status']}
        for v in data['coverage']
        if v.get('status') in {'pending', 'collecting', 'missing', 'conflict'}
    ]
    missing += [
        {
            'kind': 'data',
            'id': v.get('data_id'),
            'reason': f"{v.get('metric_code')} {v.get('period')} {v.get('source_status')}",
        }
        for v in data['required_data']
        if v.get('source_status') in {'missing', 'conflict'}
    ]
    known_refs = {v.get(primary_keys.get(kind, ''), '') for kind in primary_keys for v in data[kind]}
    for artifact in artifacts:
        deps = artifact.get('dependencies', {})
        refs = []
        for value in deps.values():
            refs.extend(value.values() if isinstance(value, dict) else value if isinstance(value, list) else [value])
        for ref in refs:
            if isinstance(ref, str) and ref and ref not in known_refs and not ref.startswith('constant:'):
                missing.append(
                    {
                        'kind': 'reference',
                        'id': ref,
                        'reason': f"{artifact['kind']}/{artifact.get('id')} 的已保存引用不可解析",
                    }
                )
    # Only registered, sanitized extraction proposals enter diagnostics.
    quarantine = [
        {
            'batch': v.get('batch'),
            'proposals': {
                kind: [
                    project(p, FIELDS['fact' if kind == 'facts' else 'evidence'])
                    for p in (v.get('proposals') or {}).get(kind, [])
                ]
                for kind in ['facts', 'evidence']
            },
            'problems': v.get('problems', []),
            'validation_status': 'rejected',
        }
        for v in records.get('quarantine', [])
    ]
    calls = data.pop('call')
    usage = {
        'calls': len(calls),
        'provider_input_tokens': sum(v.get('input_tokens') or 0 for v in calls),
        'provider_output_tokens': sum(v.get('output_tokens') or 0 for v in calls),
        'usage_missing_calls': sum(v.get('usage_source') != 'provider' for v in calls),
        'budget_tokens_reserved': sum(v.get('budget_tokens') or 0 for v in calls),
        'usage_source': 'provider'
        if calls and all(v.get('usage_source') == 'provider' for v in calls)
        else 'unavailable_or_partial',
        'note': '预算和输入估算不等于供应商实际用量；没有记录不代表零消耗。',
    }
    events = [project(v, 'event_id timestamp stage task_name status display_message') for v in state['events']]
    snapshot = {
        'artifact_type': 'work_product',
        'contract_version': CONTRACT,
        'notice': NOTICE,
        'run_id': run['run_id'],
        'run_status': run['status'],
        'final_review_passed': final_passed,
        'approved_report_snapshot_id': (report or {}).get('approved_snapshot_id') if final_passed else None,
        'approval_scope': 'assembled_report_only' if final_passed else None,
        'run': project(
            run,
            'run_id company_input company_name mode status stage created_at updated_at error rules_version limitations',
        ),
        'boundary': {
            'checkpoint_node': state.get('checkpoint_node'),
            'last_event_id': max((v['event_id'] for v in events), default=0),
            'read_method': 'single SQLite read transaction; committed records only',
        },
        'artifacts': artifacts,
        'missing': missing,
        'unavailable': state['unavailable'],
        'data': data,
        'sections': list(sections.values()),
        'review_history': state['reviews'],
        'diagnostics': {'events': events, 'calls': calls, 'usage': usage, 'quarantine': quarantine},
        'running_tasks': [
            v
            for v in events
            if v.get('status') == 'running'
            and not any(
                other['event_id'] > v['event_id']
                and other.get('task_name') == v.get('task_name')
                and other.get('status') in {'completed', 'failed', 'blocked', 'interrupted'}
                for other in events
            )
        ]
        if run['status'] in {'running', 'queued'}
        else [],
        'notes': [
            '旧运行未记录的模型/提示版本和送审历史标为未知；无法恢复未提交的内存内容。',
            '来源保留定位和证据摘录，不打包全部原始文件。',
        ],
    }
    snapshot = sanitize(snapshot)
    snapshot['snapshot_id'] = digest(snapshot)
    snapshot['snapshot_time'] = now()
    return snapshot


def capture_snapshot(store, run_id, max_bytes, snapshot_id=None):
    try:
        from .isolation import isolation_info

        isolation = isolation_info(store, run_id)
        if snapshot_id:
            snapshot = store.work_product_snapshot(run_id, snapshot_id)
            if snapshot is None:
                raise WorkProductError('指定阶段快照不存在或无法获取，请重新查看阶段成果。', 404)
            if isolation['reason'] and snapshot.get('data_isolation') != isolation:
                raise WorkProductError('旧快照未通过数据隔离检查，请获取最新阶段成果；原记录保留。', 409)
        else:
            state = store.work_product_state(run_id)
            if not state.get('run'):
                raise WorkProductError('任务数据不可读取，无法获取阶段成果。')
            snapshot = build_snapshot(state)
            snapshot['data_isolation'] = isolation
            if isolation['reason']:
                snapshot.update(final_review_passed=False, approved_report_snapshot_id=None, approval_scope=None)
                snapshot['notes'].append(isolation['reason'])
                for section in snapshot['sections']:
                    if section.get('validation_status') == 'passed':
                        section['validation_status'] = 'unreviewed'
                for artifact in snapshot['artifacts']:
                    if artifact.get('validation_status') == 'passed':
                        artifact['validation_status'] = 'unreviewed'
            snapshot['snapshot_id'] = digest(
                {k: v for k, v in snapshot.items() if k not in {'snapshot_id', 'snapshot_time'}}
            )
            if len(json_bytes(snapshot)) > max_bytes:
                raise WorkProductError(
                    '阶段成果超过导出大小限制，请提高 CDR_WORK_PRODUCT_MAX_BYTES 后重试；未省略内容。', 413
                )
            snapshot = store.save_work_product_snapshot(run_id, snapshot['snapshot_id'], snapshot)
        return snapshot
    except WorkProductError:
        raise
    except Exception as exc:
        logger.warning('run=%s work_product_read_error=%s', run_id, type(exc).__name__)
        raise WorkProductError('已保存阶段成果暂时无法读取或冻结，请检查数据库后重试；研究状态未改变。') from None


def preview(snapshot, page=1, page_size=20):
    start = (page - 1) * page_size
    result = {
        k: snapshot[k]
        for k in [
            'artifact_type',
            'contract_version',
            'notice',
            'run_id',
            'run_status',
            'final_review_passed',
            'run',
            'snapshot_id',
            'snapshot_time',
            'boundary',
            'missing',
            'unavailable',
            'notes',
        ]
    }
    result.update(
        approved_report_snapshot_id=snapshot.get('approved_report_snapshot_id'),
        approval_scope=snapshot.get('approval_scope'),
    )
    result['data_isolation'] = snapshot.get('data_isolation')
    conflicts = [d for d in snapshot['data'].get('fact_decision', []) if d['status'] != 'consistent']
    result.update(fact_decisions=conflicts[start : start + page_size], fact_decision_count=len(conflicts))
    result.update(
        artifacts=snapshot['artifacts'][start : start + page_size],
        sections=snapshot['sections'][start : start + page_size],
        page=page,
        page_size=page_size,
        artifact_count=len(snapshot['artifacts']),
        section_count=len(snapshot['sections']),
        counts={k: len(v) for k, v in snapshot['data'].items() if isinstance(v, list)},
        blocks=snapshot['data']['block'],
        issues=snapshot['data']['current_review_issues'],
        usage=snapshot['diagnostics']['usage'],
        review_count=len(snapshot['review_history']),
        formats=['zip', 'json', 'md'],
        running_tasks=snapshot['running_tasks'],
    )
    return result


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def safe_md(value):
    # Downloaded Markdown also remains readable when opened by an HTML renderer.
    import html

    return html.escape(str(value)).replace('![', '\\![').replace('[', '\\[').replace(']', '\\]')


def summary_md(snapshot):
    run = snapshot['run']
    lines = [
        f'# {NOTICE}',
        '',
        f"公司：{safe_md(run.get('company_name') or run['company_input'])}",
        f"任务：{snapshot['run_id']}",
        f"快照：{snapshot['snapshot_id']}",
        f"快照时间：{snapshot['snapshot_time']}",
        f"运行状态：{snapshot['run_status']}；对应内容最终审核通过：{snapshot['final_review_passed']}",
        f"停止阶段：{safe_md(run['stage'])}",
        f"原因：{safe_md(run.get('error') or '未记录停止错误')}",
        '',
        '## 成果清单',
        '',
    ]
    lines += [f'- {kind}：{len(values)} 项' for kind, values in snapshot['data'].items() if isinstance(values, list)]
    lines += ['', '## 缺失与不可获取内容', '']
    lines += [
        f"- {safe_md(v.get('id') or v.get('artifact'))}：{safe_md(v['reason'])}"
        for v in snapshot['missing'] + snapshot['unavailable']
    ] or ['- 无已记录缺失项']
    lines += ['', '## 当前审核问题', '']
    lines += [
        f"- {safe_md(i.get('severity'))} · {safe_md(i.get('location'))} · {safe_md(i.get('rule_id'))}：{safe_md(i.get('description'))}"
        for i in snapshot['data']['current_review_issues']
    ] or ['- 尚无已记录审核问题；不代表审核通过']
    lines += [
        '',
        '## 用量记录',
        '',
        safe_md(json.dumps(snapshot['diagnostics']['usage'], ensure_ascii=False)),
        '',
        f"已保存送审轮次：{len(snapshot['review_history'])}",
        '',
        '## 限制',
        '',
    ]
    lines += [f'- {safe_md(v)}' for v in snapshot['notes'] + snapshot['data']['limitations']]
    lines += ['', '## 业务行业资料方向与覆盖', '']
    for slot in snapshot['data'].get('collection_slot', []):
        lines.append(
            f"- {safe_md(slot['topic'])} · {safe_md(slot['state'])} · 检索 {slot.get('search_count', 0)} 次 · {safe_md(slot.get('stop_reason', ''))}"
        )
        for direction in slot.get('directions', []):
            finding = slot.get('direction_statuses', {}).get(direction['direction_id'], {})
            lines.append(
                f"  - {safe_md(direction['label'])} · {safe_md(direction['origin'])} · {safe_md(finding.get('status', 'pending'))}：{safe_md(finding.get('reason', ''))}"
            )
    lines += ['', '## 来源与定位', '']
    lines += [
        f"- {safe_md(v.get('source_id'))} · {safe_md(v.get('title'))} · {safe_md(v.get('locator', ''))} · {safe_md(v.get('source_url') or '')}"
        for v in snapshot['data']['source']
    ]
    lines += ['', '## 财务事实（含已保存的历史版本，以成果标签为准）', '']
    lines += [
        f"- 裁决 {safe_md(d['group_id'])} · {safe_md(d['status'])}：{safe_md(d['reason'])}；选用 {safe_md(', '.join(d['selected_ids']) or '无')}；候选 {safe_md(', '.join(d['candidate_ids']))}；证明 {safe_md(', '.join(d['proof_evidence_ids']))}"
        for d in snapshot['data'].get('fact_decision', [])
        if d['status'] != 'consistent'
    ]
    lines += [
        f"- {safe_md(v.get('fact_id'))} · {safe_md(v.get('metric_code'))} · {safe_md(v.get('period'))} · {safe_md(v.get('segment_id') or '公司')} · {safe_md(v.get('value'))} {safe_md(v.get('unit'))} · {safe_md(v.get('validation_status'))} · 来源 {safe_md(v.get('source_id'))}"
        for v in snapshot['data']['fact']
    ]
    lines += ['', '## 人工数据核验', '']
    lines += [
        f"- {safe_md(i['issue_id'])} · {safe_md(i['status'])} · {'关键依赖' if i['blocking'] else '非关键问题'}：{safe_md(i['reason'])}；{safe_md(i.get('feedback_error', ''))}"
        for i in snapshot['data'].get('human_issue', [])
    ]
    lines += [
        f"- 反馈 {safe_md(f['feedback_id'])} · {safe_md(f['status'])}：{safe_md(f['reason'])}；{safe_md(f.get('error', ''))}"
        for f in snapshot['data'].get('human_feedback', [])
    ]
    lines += ['', '## 财务比较', '']
    lines += [
        f"- {safe_md(v.get('comparison_id'))} · {safe_md(v.get('metric_code'))} · {safe_md(v.get('current_period'))}/{safe_md(v.get('previous_period'))} · {safe_md(v.get('current_value'))}/{safe_md(v.get('previous_value'))} · {safe_md(v.get('status'))} · 增减 {safe_md(v.get('delta'))} {safe_md(v.get('unit'))} · 比率 {safe_md(v.get('rate'))}"
        for v in snapshot['data']['comparison']
    ]
    lines += ['', '## 已保存块分析', '']
    labels = {v['id']: v['version_status'] for v in snapshot['artifacts'] if v['kind'] == 'block_analysis'}
    for block in snapshot['data']['block_analysis']:
        lines += [f"### {safe_md(block['block_id'])} · {labels.get(block['block_id'], 'unknown')}", '']
        lines += [safe_md(v) + '\n' for v in block.get('conclusions', [])]
    return '\n'.join(lines) + '\n'


def draft_md(snapshot):
    from .reports import TITLES

    order = ['core', 'toc', 'company', 'financial', 'business', 'forecast', 'risk', 'statements', 'disclaimer']
    lookup = {s['section_id']: s for s in snapshot['sections']}
    lines = [f'# {NOTICE}', '', f"快照：{snapshot['snapshot_id']}", '']
    if not lookup:
        lines += ['当前尚无写作成果。', '']

    def write(section, depth, version='current'):
        item = lookup.get(section['section_id'])
        if item is None or item['version_status'] != version:
            return
        lines.extend(
            [
                f"{'#' * min(depth, 6)} {safe_md(section['title'])}",
                '',
                f"状态：{item['generation_status']} / {item['validation_status']} / {item['version_status']}",
                '',
            ]
        )
        lines.extend([safe_md(p) + '\n' for p in section.get('paragraphs', [])])
        for table in section.get('tables', []):
            lines.extend(
                [
                    safe_md(table['title']),
                    '',
                    '| '
                    + ' | '.join(safe_md(v).replace('|', '\\|').replace('\n', ' ') for v in table['columns'])
                    + ' |',
                    '| ' + ' | '.join('---' for _ in table['columns']) + ' |',
                ]
            )
            lines.extend(
                '| ' + ' | '.join(safe_md(v).replace('|', '\\|').replace('\n', ' ') for v in row) + ' |'
                for row in table['rows']
            )
            lines.append('')
        if section.get('evidence_ids') or section.get('calculation_ids'):
            lines.extend(
                [
                    '引用：' + safe_md(', '.join(section.get('evidence_ids', []) + section.get('calculation_ids', []))),
                    '',
                ]
            )
        for child in section.get('children', []):
            write(child, depth + 1, version)

    emitted = set()
    for section_id, title in zip(order, TITLES):
        if section_id in lookup and lookup[section_id]['version_status'] == 'current':
            write(lookup[section_id]['content'], 2)
            emitted.update(s['section_id'] for s in _flatten([lookup[section_id]['content']]))
        else:
            reason = (
                '已保存章节因上游更新失效，见历史失效章节；未补写当前结论。'
                if section_id in lookup
                else '尚未生成该章节；未补写内容。'
            )
            lines.extend([f'## {safe_md(title)}', '', reason, ''])
    for item in lookup.values():
        if item['section_id'] not in emitted and item['version_status'] == 'current':
            write(item['content'], 3)
    stale = [v for v in lookup.values() if v['version_status'] == 'stale']
    if stale:
        lines.extend(['## 历史失效章节（仅供评估，不作为当前结论）', ''])
        emitted_stale = set()
        for item in stale:
            if item['section_id'] not in emitted_stale:
                write(item['content'], 3, 'stale')
                emitted_stale.update(s['section_id'] for s in _flatten([item['content']]))
    return '\n'.join(lines)


def export_snapshot(snapshot, format, max_bytes):
    try:
        if format == 'json':
            result, media = json_bytes(snapshot), 'application/json'
        elif format == 'md':
            result, media = (
                (summary_md(snapshot) + '\n' + draft_md(snapshot)).encode('utf-8'),
                'text/markdown; charset=utf-8',
            )
        else:
            files = {
                'evaluation.md': summary_md(snapshot).encode('utf-8'),
                'draft.md': draft_md(snapshot).encode('utf-8'),
            }
            files.update({f'data/{kind}.json': json_bytes(value) for kind, value in snapshot['data'].items()})
            files.update(
                {f'diagnostics/{kind}.json': json_bytes(value) for kind, value in snapshot['diagnostics'].items()}
            )
            files['diagnostics/review-history.json'] = json_bytes(snapshot['review_history'])
            manifest = {
                k: snapshot[k]
                for k in [
                    'artifact_type',
                    'contract_version',
                    'notice',
                    'run_id',
                    'run_status',
                    'final_review_passed',
                    'run',
                    'snapshot_id',
                    'snapshot_time',
                    'boundary',
                    'artifacts',
                    'missing',
                    'unavailable',
                    'notes',
                    'running_tasks',
                ]
            }
            manifest['export_time'] = now()
            manifest.update(
                approved_report_snapshot_id=snapshot.get('approved_report_snapshot_id'),
                approval_scope=snapshot.get('approval_scope'),
            )
            manifest['data_isolation'] = snapshot.get('data_isolation')
            manifest['record_counts'] = {k: len(v) for k, v in snapshot['data'].items() if isinstance(v, list)}
            manifest['files'] = [
                {'path': name, 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
                for name, value in files.items()
            ]
            files['manifest.json'] = json_bytes(manifest)
            if sum(len(v) for v in files.values()) > max_bytes:
                raise WorkProductError(
                    '评估包超过导出大小限制，未省略内容，请提高 CDR_WORK_PRODUCT_MAX_BYTES 后重试。', 413
                )
            buffer = io.BytesIO()
            with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
                for name, value in files.items():
                    archive.writestr(name, value)
            result, media = buffer.getvalue(), 'application/zip'
        if len(result) > max_bytes:
            raise WorkProductError('阶段成果超过导出大小限制，未省略内容，请调整配置后重试。', 413)
        return result, media
    except WorkProductError:
        raise
    except Exception as exc:
        logger.warning('run=%s work_product_export_error=%s', snapshot['run_id'], type(exc).__name__)
        raise WorkProductError('阶段成果打包失败，可重试导出；研究状态和已有成果未改变。') from None
