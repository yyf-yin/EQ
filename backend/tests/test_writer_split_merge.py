"""Split writer requests are consolidated into one section, not concatenated drafts."""
import json

from company_research.agents import WriterDraft, ask_bounded
from company_research.llm import TruncatedOutput
from company_research.schemas import SectionPart


CHECKS = ['cash_growth', 'forecast_total', 'valuation_evidence', 'resource_concentration']


def core_context():
    return {
        'section': {'section_id': 'core', 'block_id': 'X01', 'title': '核心观点', 'goal': '汇总核心判断'},
        'instructions': [],
        'consistency_checks': ['收入增长与现金流匹配'],
        'evidence': [{'evidence_id': f'e{i}', 'claim': '经营资料'} for i in range(4)],
        'calculations': [{'result_id': f'c{i}'} for i in range(4)],
        'final_sections': [{'section_id': f's{i}', 'conclusions': ['结论']} for i in range(4)],
    }


def half_draft(context):
    ids = [e['evidence_id'] for e in context['evidence']]
    calcs = [c['result_id'] for c in context['calculations']]
    first = calcs[0] == 'c0'
    return WriterDraft(
        paragraphs=[f'{"上半" if first else "下半"}核心观点{i}：现金流 [[calc:{calcs[0]}]]。' for i in range(5)],
        evidence_ids=ids,
        calculation_ids=calcs,
        fact_ids=[],
        assumption_ids=[],
        consistency_checks={
            # The first half lacks cash data and wrongly reports a conflict.
            'cash_growth': 'conflict: 缺少现金流数据，F01 负责' if first else '增长与现金基本匹配',
            **{k: '已核对' for k in CHECKS[1:]},
        },
    )


class SplitGateway:
    """Forces one capacity split for the writer, then answers the merge call."""

    def __init__(self, merge=None):
        self.calls = []
        self.merge = merge

    def request_size(self, role, messages, schema):
        sent = json.loads(messages[1]['content'])
        return (10 if sent.get('merge_contract') or len(sent['final_sections']) <= 2 else 100), 50

    async def structured(self, role, messages, schema):
        sent = json.loads(messages[1]['content'])
        self.calls.append((role, messages[0]['content'], sent))
        if not sent.get('merge_contract'):
            return half_draft(sent)
        if self.merge:
            return self.merge(sent)
        return WriterDraft(
            paragraphs=[
                f'统一核心观点{i}：增长与现金匹配 [[calc:c0]]，下半资料补充 [[calc:c3]]。' for i in range(5)
            ],
            evidence_ids=['e0', 'e3', 'e-invented'],
            calculation_ids=['c0', 'c-invented'],
            fact_ids=['f-invented'],
            assumption_ids=[],
            consistency_checks={'cash_growth': '增长与现金匹配，依据 [[calc:c0]]'},
        )


async def test_split_core_draft_is_consolidated_with_declared_ids_only():
    gateway = SplitGateway()
    draft = await ask_bounded(gateway, 'core_writer', WriterDraft, core_context())

    writes = [c for c in gateway.calls if not c[2].get('merge_contract')]
    merges = [c for c in gateway.calls if c[2].get('merge_contract')]
    assert len(writes) == 2 and len(merges) == 1
    role, prompt, sent = merges[0]
    assert role == 'core_writer'
    assert '拆分草稿整合为一份完整章节' in prompt
    # The consolidation input is small: drafts, IDs and the section goal, no source payload.
    assert set(sent) == {'merge_contract', 'section', 'drafts', 'allowed_ids', 'consistency_checks'}
    assert sent['section']['goal'] == '汇总核心判断'
    assert [len(d['paragraphs']) for d in sent['drafts']] == [5, 5]
    assert sent['allowed_ids']['calculation_ids'] == ['c0', 'c1', 'c2', 'c3']

    # One section, not the ten concatenated paragraphs of both halves.
    assert len(draft.paragraphs) == 5
    assert all(p.startswith('统一核心观点') for p in draft.paragraphs)
    assert draft.evidence_ids == ['e0', 'e3']
    # Invented IDs are dropped; c3 is used in text and declared by a half, so it is declared.
    assert draft.calculation_ids == ['c0', 'c3']
    assert draft.fact_ids == []
    # The half-context conflict does not override the consolidated judgment;
    # keys the merger left out keep the halves' values.
    assert not draft.consistency_checks['cash_growth'].startswith('conflict:')
    assert set(draft.consistency_checks) == set(CHECKS)


async def test_writer_role_split_is_consolidated_too():
    gateway = SplitGateway()
    context = core_context() | {'section': {'section_id': 'risk', 'block_id': 'R01', 'title': '风险', 'goal': '风险'}}
    context.pop('consistency_checks')
    draft = await ask_bounded(gateway, 'writer', WriterDraft, context)
    merge = next(c for c in gateway.calls if c[2].get('merge_contract'))
    assert merge[0] == 'writer' and 'consistency_checks' not in merge[2]
    assert len(draft.paragraphs) == 5


async def test_failed_consolidation_keeps_union_instead_of_failing_section():
    def truncated(sent):
        raise TruncatedOutput('fixture merge truncated')

    draft = await ask_bounded(SplitGateway(truncated), 'core_writer', WriterDraft, core_context())
    assert len(draft.paragraphs) == 10
    assert draft.calculation_ids == ['c0', 'c1', 'c2', 'c3']


async def test_empty_consolidation_falls_back_to_union():
    def empty(sent):
        return WriterDraft(paragraphs=[], evidence_ids=[], calculation_ids=[], fact_ids=[], assumption_ids=[])

    draft = await ask_bounded(SplitGateway(empty), 'core_writer', WriterDraft, core_context())
    assert len(draft.paragraphs) == 10


async def test_split_merges_when_only_first_half_has_parts():
    # Regression: an empty second-half `parts` list sent dict items to dict.fromkeys.
    class PartsGateway(SplitGateway):
        async def structured(self, role, messages, schema):
            draft = await super().structured(role, messages, schema)
            sent = self.calls[-1][2]
            if not sent.get('merge_contract') and sent['calculations'][0]['result_id'] == 'c0':
                draft.parts = [SectionPart(topic='现金流', heading='现金流匹配', start=0)]
            return draft

    gateway = PartsGateway()
    draft = await ask_bounded(gateway, 'core_writer', WriterDraft, core_context())
    assert len(draft.paragraphs) == 5


async def test_unsplit_writer_request_makes_no_merge_call():
    gateway = SplitGateway()
    context = core_context() | {'final_sections': core_context()['final_sections'][:2]}
    await ask_bounded(gateway, 'core_writer', WriterDraft, context)
    assert len(gateway.calls) == 1
