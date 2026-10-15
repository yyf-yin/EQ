"""Run-scoped human data work queue; evidence rules remain deterministic."""

import json
import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict

from .framework import digest
from .schemas import FinancialFact, EvidenceRecord, now
from .reconciliation import reconcile, primary_proof, correction_proof, group_key
from .financials.formulas import FinancialDataProcessor

POLICY = 'human-data-1'


class HumanInputRequired(Exception):
    pass


class FeedbackError(ValueError):
    pass


class HumanFeedback(BaseModel):
    model_config = ConfigDict(extra='forbid')
    signature: str = Field(min_length=64, max_length=64)
    action: Literal['select', 'supplement', 'research']
    reason: str = Field(min_length=3, max_length=2000)
    fact_id: str | None = Field(default=None, max_length=100)
    source_id: str | None = Field(default=None, max_length=100)
    quote: str | None = Field(default=None, max_length=12000)
    locator: str | None = Field(default=None, max_length=500)
    value: Decimal | None = None
    unit: str | None = Field(default=None, max_length=50)
    accounting_basis: str = Field(default='reported', max_length=100)
    query: str | None = Field(default=None, max_length=1000)


def blocking(requirement):
    return requirement.get('priority') == 'critical' or bool(requirement.get('formula_dependency'))


def matches(identity, requirement):
    return (
        all(identity.get(k) == requirement.get(k) for k in ('company_id', 'metric_code', 'period', 'segment_id'))
        and identity.get('scope', 'consolidated') == ('segment' if requirement.get('segment_id') else 'consolidated')
        and identity.get('actual_or_forecast', 'actual') == 'actual'
    )


class HumanInterventionAgent:
    """Publishes concrete questions and validates feedback without holding workers."""

    def __init__(self, store, run_id):
        self.store, self.run_id = store, run_id

    def issues(self):
        return sorted(self.store.records(self.run_id, 'human_issue'), key=lambda i: (not i['blocking'], i['issue_id']))

    def refresh(self, context, *, final=False):
        if context.get('data_template_version') or self.store.execution_get(
            self.run_id, 'execution_meta', 'fixed-collection'
        ):
            return self.issues()
        facts = context.get('fact_candidates', context.get('facts', []))
        sources = context.get('sources', [])
        evidence = context.get('evidence', [])
        decisions = context.get('fact_decisions') if final else None
        if decisions is None:
            _, decisions = reconcile(facts, sources, evidence, context['company'])
        unresolved = [d for d in decisions if d['status'] == 'unresolved' and d['identity']]
        requirements = context.get('required_data', [])
        proposals = []
        for d in unresolved:
            required = [r for r in requirements if matches(d['identity'], r)]
            proposals.append(
                (
                    d['group_id'],
                    d['identity'],
                    d['candidates'],
                    d['reason'],
                    any(blocking(r) for r in required),
                    'conflict',
                )
            )
        if final:
            for r in context.get('missing', []):
                if r.get('source_status') == 'conflict' or not blocking(r):
                    continue
                identity = {k: r.get(k) for k in ('company_id', 'metric_code', 'period', 'unit', 'segment_id')}
                identity.update(
                    scope='segment' if r.get('segment_id') else 'consolidated',
                    actual_or_forecast='actual',
                    currency='CNY',
                )
                proposals.append(
                    ('missing-' + digest(identity)[:24], identity, [], '核心计算依赖仍缺少已核实数据', True, 'missing')
                )
        current = set()
        with self.store.lock:
            existing = {i['issue_id']: i for i in self.issues()}
            for gid, identity, candidates, reason, required, kind in proposals:
                issue_id = 'human-' + gid
                current.add(issue_id)
                signature = digest([POLICY, identity, candidates])
                old = existing.get(issue_id)
                unchanged = old and old['signature'] == signature
                status = old['status'] if unchanged and old['status'] in {'submitted', 'researching'} else 'open'
                # Rejected feedback stays visible until a new revision is submitted.
                issue = {
                    'issue_id': issue_id,
                    'group_id': gid,
                    'signature': signature,
                    'identity': identity,
                    'candidates': candidates,
                    'reason': reason,
                    'blocking': required,
                    'kind': kind,
                    'status': status,
                    'phase': 'awaiting_human' if final else 'checking',
                    'question': '请提供原始披露依据、选择有证据的候选，或指定新的补查方向。',
                    'created_at': old['created_at'] if old else now(),
                    'updated_at': now(),
                    'feedback_error': old.get('feedback_error', '') if unchanged else '',
                }
                self.store.record(self.run_id, 'human_issue', issue_id, issue)
                if not unchanged:
                    self.store.emit(
                        self.run_id,
                        '数据收集',
                        'human_intervention',
                        'pending',
                        '发现数据问题，已加入人工核验待办；其他采集继续',
                        once_key=issue_id + signature,
                    )
            for issue_id, old in existing.items():
                # Partial results cannot close missing tasks or already collected conflicts.
                if final and issue_id not in current and old['status'] != 'resolved':
                    self.store.record(
                        self.run_id,
                        'human_issue',
                        issue_id,
                        old | {'status': 'resolved', 'updated_at': now(), 'feedback_error': ''},
                    )
        return self.issues()

    def publish_collected(self, context):
        self.refresh(
            context
            | {
                kind: self.store.records(self.run_id, record)
                for kind, record in [('facts', 'fact'), ('sources', 'source'), ('evidence', 'evidence')]
            }
            | {'fact_candidates': self.store.records(self.run_id, 'fact')}
        )

    def submit(self, issue_id, body):
        """Atomic version check and idempotent feedback receipt, isolated by run."""
        if len(body.reason.strip()) < 3:
            raise FeedbackError('请提供明确的原始依据和处理理由')
        with self.store.lock, self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute(
                "SELECT payload FROM records WHERE run_id=? AND kind='human_issue' AND id=?", (self.run_id, issue_id)
            ).fetchone()
            if not row:
                raise FeedbackError('人工待办不存在或不属于本任务')
            issue = json.loads(row[0])
            if body.signature != issue['signature'] or issue['status'] == 'resolved':
                raise FeedbackError('候选数据已更新或问题已解决，请刷新后重新提交')
            payload = body.model_dump(mode='json')
            feedback_id = 'feedback-' + digest([issue_id, payload])[:24]
            saved = db.execute(
                "SELECT payload FROM records WHERE run_id=? AND kind='human_feedback' AND id=?",
                (self.run_id, feedback_id),
            ).fetchone()
            if saved:
                return json.loads(saved[0])
            if issue['status'] in {'submitted', 'researching'}:
                raise FeedbackError('该问题的反馈正在核验，请等待处理结果')
            feedback = {
                'feedback_id': feedback_id,
                'issue_id': issue_id,
                'group_id': issue['group_id'],
                'identity': issue['identity'],
                'status': 'pending',
                'created_at': now(),
                **payload,
            }
            issue.update(status='submitted', feedback_error='', updated_at=now())
            db.execute(
                'INSERT INTO records VALUES(?,?,?,?)',
                (self.run_id, 'human_feedback', feedback_id, json.dumps(feedback, ensure_ascii=False)),
            )
            db.execute(
                'UPDATE records SET payload=? WHERE run_id=? AND kind=? AND id=?',
                (json.dumps(issue, ensure_ascii=False), self.run_id, 'human_issue', issue_id),
            )
        return feedback

    def finish_feedback(self, feedback, error=''):
        self.store.record(
            self.run_id,
            'human_feedback',
            feedback['feedback_id'],
            feedback | {'status': 'rejected' if error else 'accepted', 'error': error, 'completed_at': now()},
        )
        with self.store.lock:
            issue = next((i for i in self.issues() if i['issue_id'] == feedback['issue_id']), None)
            if issue and issue['signature'] == feedback['signature']:
                self.store.record(
                    self.run_id,
                    'human_issue',
                    issue['issue_id'],
                    issue | {'status': 'open', 'feedback_error': error, 'updated_at': now()},
                )

    def validate_selection(self, fact, candidates, sources, evidence, company, reason):
        if self.store.execution_get(self.run_id, 'execution_meta', 'fixed-collection'):
            raise FeedbackError('固定年报数据版本只读，不能通过人工候选覆盖；请明确创建新的数据版本')
        sm = {s['source_id']: s for s in sources}
        em = {e['evidence_id']: e for e in evidence}
        try:
            normalized = FinancialDataProcessor().normalize(FinancialFact.model_validate(fact))
        except ValueError as exc:
            raise FeedbackError('所选数据的数值、单位或币种无效：' + str(exc)) from None
        source = sm.get(normalized.source_id, {})
        ev = em.get(normalized.evidence_id, {})
        uploaded = (
            source.get('kind') == 'upload'
            and source.get('attachment_id')
            and ev.get('source_id') == normalized.source_id
            and ev.get('validation_status') == 'verified'
            and ev.get('quote')
            and ev['quote'] in source.get('content', '')
        )
        has_upload = any(
            sm.get(f['source_id'], {}).get('kind') == 'upload'
            for f in candidates
            if group_key(FinancialFact.model_validate(f)) == group_key(normalized)
        )
        if has_upload and not uploaded:
            raise FeedbackError('该字段已有上传参考资料，请选择参考资料中的候选或修正其提取值')
        if (
            normalized.validation_status != 'verified'
            or normalized.actual_or_forecast != 'actual'
            or not normalized.value.is_finite()
            or not (uploaded or primary_proof(normalized, sm, em, company))
        ):
            raise FeedbackError('所选数据缺少可定位的原始披露证明，需补充期间、单位、范围和数值原文')
        if uploaded:
            return normalized.model_dump(mode='json')
        if normalized.accounting_basis != 'reported':
            quote = em[normalized.evidence_id]['quote']
            label = {'adjusted': r'调整|adjusted', 'restated': r'重述|restated'}.get(
                normalized.accounting_basis, re.escape(normalized.accounting_basis)
            )
            if not re.search(label, quote, re.I):
                raise FeedbackError('所选会计口径缺少原文说明，不能自行改变口径')
        for raw in candidates:
            other = FinancialDataProcessor().normalize(FinancialFact.model_validate(raw))
            if group_key(other) != group_key(normalized) or other.accounting_basis != normalized.accounting_basis:
                continue
            if (
                other.value != normalized.value
                and primary_proof(other, sm, em, company)
                and not correction_proof(normalized, other, sm, em, company)
            ):
                raise FeedbackError('两个同口径原始披露仍不一致，需提供明确的更正前后证明')
        return normalized.model_dump(mode='json')

    def apply(self, active, decisions, candidates, sources, evidence, company):
        """A resolution authorizes only its immutable candidate set and source proof."""
        resolutions = self.store.records(self.run_id, 'human_resolution')
        fm = {f['fact_id']: f for f in candidates}
        for decision in decisions:
            if not decision['identity']:
                continue
            signature = digest([POLICY, decision['identity'], decision['candidates']])
            receipt = next(
                (
                    r
                    for r in reversed(resolutions)
                    if r['group_id'] == decision['group_id'] and r['signature'] == signature
                ),
                None,
            )
            if not receipt:
                continue
            selected = fm.get(receipt['fact_id'])
            if not selected or selected['fact_id'] not in decision['candidate_ids']:
                continue
            selected = self.validate_selection(
                selected, [fm[k] for k in decision['candidate_ids']], sources, evidence, company, receipt['reason']
            )
            ids = set(decision['candidate_ids'])
            active = [f for f in active if f['fact_id'] not in ids] + [selected]
            decision.update(
                status='resolved',
                rule='human-evidence',
                selected_ids=[selected['fact_id']],
                proof_evidence_ids=[selected['evidence_id']],
                reason='人工指定口径或补充原始证据，经核验：' + receipt['reason'],
            )
            decision['decision_id'] = 'decision-' + digest(decision)[:24]
        return active, decisions

    def accept(self, feedback, context):
        candidates = context.get('fact_candidates', context['facts'])
        sources = context['sources']
        evidence = context['evidence']
        if feedback['action'] == 'supplement':
            source = next((s for s in sources if s['source_id'] == feedback.get('source_id')), None)
            quote = feedback.get('quote') or ''
            if not source or not quote.strip() or quote not in source['content']:
                raise FeedbackError('补充摘录必须能在本任务已收集的来源原文中定位；新材料请先指定补查方向')
            if feedback.get('value') is None or not feedback.get('unit') or not feedback.get('locator'):
                raise FeedbackError('补充数据需要数值、单位和原文位置')
            identity = feedback['identity']
            ev = EvidenceRecord(
                evidence_id='ev-' + feedback['feedback_id'],
                source_id=source['source_id'],
                claim=quote,
                quote=quote,
                locator=feedback['locator'],
                actual_or_forecast='actual',
                validation_status='verified',
            ).model_dump(mode='json')
            fact = FinancialFact(
                **{k: v for k, v in identity.items() if k in FinancialFact.model_fields},
                fact_id='fact-' + feedback['feedback_id'],
                value=feedback['value'],
                source_id=source['source_id'],
                evidence_id=ev['evidence_id'],
                locator=feedback['locator'],
                validation_status='verified',
                accounting_basis=feedback['accounting_basis'],
            ).model_dump(mode='json')
            fact['unit'] = feedback['unit']
            fact = self.validate_selection(
                fact, candidates, sources, evidence + [ev], context['company'], feedback['reason']
            )
            if not matches(group_key(FinancialFact.model_validate(fact)), identity) or fact['unit'] != identity['unit']:
                raise FeedbackError('补充数据的期间、范围或单位与待办不匹配')
            self.store.record(self.run_id, 'evidence', ev['evidence_id'], ev)
            self.store.record(self.run_id, 'fact', fact['fact_id'], fact)
            evidence.append(ev)
            candidates.append(fact)
        else:
            fact = next((f for f in candidates if f['fact_id'] == feedback.get('fact_id')), None)
            if not fact:
                raise FeedbackError('所选候选不存在或不属于当前问题')
            fact = self.validate_selection(fact, candidates, sources, evidence, context['company'], feedback['reason'])
            if group_key(FinancialFact.model_validate(fact)) != feedback['identity']:
                raise FeedbackError('所选候选不属于当前问题的期间、单位或口径')
        _, decisions = reconcile(candidates, sources, evidence, context['company'])
        decision = next(d for d in decisions if fact['fact_id'] in d['candidate_ids'])
        receipt = {
            'resolution_id': feedback['feedback_id'],
            'group_id': decision['group_id'],
            'signature': digest([POLICY, decision['identity'], decision['candidates']]),
            'fact_id': fact['fact_id'],
            'reason': feedback['reason'],
            'feedback_id': feedback['feedback_id'],
            'created_at': now(),
        }
        self.store.record(self.run_id, 'human_resolution', receipt['resolution_id'], receipt)
        return context | {'facts': candidates, 'fact_candidates': candidates, 'evidence': evidence}
