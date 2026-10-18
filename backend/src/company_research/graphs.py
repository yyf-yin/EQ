import asyncio
import copy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from .config import ROOT
from .schemas import (
    Company,
    ResearchBrief,
    ResearchPlan,
    CalculationPlan,
    RequiredData,
    FinancialFact,
    SourceRecord,
    EvidenceRecord,
    ForecastAssumption,
    CalculationResult,
    FinancialForecast,
    ResearchTask,
    ReportDocument,
)
from .agents import ask, ask_bounded, locate_quote, SupervisorDecision, FinancialAnalysis, AssumptionOutput
from .datasources import LocalDatasource, UnifiedDatasource, WebAdapter, HTTPWebSearchProvider, BochaWebSearchProvider
from .evidence import EvidenceStore
from .financials import DependencyResolver, Calculator, ForecastEngine, FinancialError
from .financials.formulas import REGISTRY, FinancialDataProcessor, INPUT_UNITS, input_unit
from .financials.forecast import (
    OPENING_KEYS,
    ASSUMPTION_KEYS,
    COMPANY_SEGMENT,
    forecast_segments,
    has_minority_interest,
)
from .planners import (
    mock_research_plan,
    mock_calculation_plan,
    mock_assumptions,
    execute_calculation_plan,
    ASSUMPTION_UNITS,
    REQUIRED_ASSUMPTION_UNITS,
)
from .researcher import researcher_graph
from .reports import mock_report, export_docx, html_report
from .framework import VERSION, skeleton, validate_plan, coverage_matrix, refresh_coverage, digest, descendants
from .comparisons import requirements, build_comparisons, core_gate
from .contexts import block_context, source_context
from .execution import (
    unit,
    unit_key,
    settle,
    bounded_schedule,
    optimized_run,
    DependencySchedulingError,
    check_pause,
    PauseRequested,
)
from .llm import LLMError, BudgetError
from .datasources import DatasourceError
from .human_intervention import HumanInterventionAgent, HumanInputRequired, FeedbackError
from .isolation import ensure_isolation
from .references import reference_question_support


class WorkflowState(TypedDict):
    context: dict


STAGES = {
    'resolve_company': '公司识别',
    'research_brief': '研究规划',
    'research_plan': '研究规划',
    'calculation_plan': '研究规划',
    'dependencies': '研究规划',
    'supervisor': '数据收集',
    'data_gaps': '数据收集',
    'replan': '数据收集',
    'financial_analysis': '财务分析',
    'assumptions': '盈利预测',
    'calculate': '盈利预测',
    'validate': '盈利预测',
    'write_sections': '报告写作',
    'core_conclusion': '报告写作',
    'assemble': '报告写作',
    'final_review': '最终审核',
    'revise': '最终审核',
    'render': '文档生成',
    'deliver': '文档生成',
}
NODE_LABELS = {
    'resolve_company': '核对上市公司身份',
    'research_brief': '确定研究范围',
    'research_plan': '规划业务与行业研究',
    'calculation_plan': '选择财务指标与预测模型',
    'dependencies': '检查公式所需数据',
    'supervisor': '收集公司、业务与财务资料',
    'data_gaps': '检查数据缺口',
    'replan': '安排补充研究',
    'financial_analysis': '分析历史财务与现金质量',
    'assumptions': '制定有依据的预测假设',
    'calculate': '计算预测与估值',
    'validate': '复算财务结果',
    'write_sections': '编写各研究章节',
    'core_conclusion': '提炼核心观点',
    'assemble': '组装目录、表格与引用',
    'final_review': '独立审核报告',
    'revise': '修订审核定位的问题',
    'render': '生成阅读与下载文件',
    'deliver': '交付研究报告',
}


def analyzer_view(content):
    """Block analyzer input. Only evidence[].evidence_id and calculations[].result_id
    are citable; other IDs (a fact's evidence, upstream citations, comparison IDs)
    are removed so the model cannot cite outside the selected data. Page lists in
    locators are dropped; quotes stay verbatim."""
    hidden = {'locator', 'evidence_id', 'slot_id', 'derivation_id', 'supersedes'}
    data = {k: v for k, v in content.items() if k != 'financial_facts'}
    data['facts'] = [{k: v for k, v in f.items() if k not in hidden} for f in content['financial_facts']]
    data['evidence'] = [{k: v for k, v in e.items() if k != 'locator'} for e in content['evidence']]
    data['upstream'] = [
        {k: v for k, v in a.items() if k not in {'evidence_ids', 'calculation_ids', 'counter_evidence_ids'}}
        for a in content.get('upstream', [])
    ]
    data['comparisons'] = [{k: v for k, v in r.items() if k != 'comparison_id'} for r in content.get('comparisons', [])]
    return data


def near_id(value, known):
    """Return the only known ID one insertion, deletion or substitution away.
    Long hex IDs are occasionally miscopied by one character when the input lists
    hundreds of them; ambiguous or more distant IDs stay unresolved."""
    matches = []
    for k in known:
        if abs(len(k) - len(value)) > 1:
            continue
        if len(k) == len(value):
            close = sum(a != b for a, b in zip(k, value)) == 1
        else:
            short, long = sorted((k, value), key=len)
            close = any(long[:i] + long[i + 1 :] == short for i in range(len(long)))
        if close:
            matches.append(k)
    return matches[0] if len(matches) == 1 else None


def resolve_citations(output, evidence_ids, calculation_ids):
    """Correct unambiguous one-character citation typos; return unresolved IDs."""
    unknown = {'evidence': set(), 'calculation': set()}

    def fix(ids, known, kind):
        fixed = []
        for i in ids:
            j = i if i in known else near_id(i, known)
            if j is None:
                unknown[kind].add(i)
            else:
                fixed.append(j)
        return list(dict.fromkeys(fixed))

    output.evidence_ids = fix(output.evidence_ids, evidence_ids, 'evidence')
    output.counter_evidence_ids = fix(output.counter_evidence_ids, evidence_ids, 'evidence')
    output.calculation_ids = fix(output.calculation_ids, calculation_ids, 'calculation')
    return unknown['evidence'], unknown['calculation']


def brief_business_support(brief, sources):
    """Check each business against cited bodies; allow separate sources and layout whitespace."""
    known = {s['source_id'] for s in sources}
    unknown = sorted(set(brief.source_ids) - known)
    errors = ['Brief 引用未知来源：' + '、'.join(unknown)] if unknown else []
    candidates = [s for s in sources if not brief.source_ids or s['source_id'] in brief.source_ids]
    support = {}
    for segment in brief.segments:
        support[segment] = list(
            dict.fromkeys(
                s['source_id'] for s in candidates if segment.strip() and locate_quote(segment, s['content'])[0] >= 0
            )
        )
    missing = [segment for segment, ids in support.items() if not ids]
    if missing:
        errors.append('业务清单没有来源支持：' + '、'.join(missing))
    return support, errors


def revision_note(problem):
    return f"问题（{problem['location']}）：{problem['description']} 修复：{problem['suggested_fix']}"


class ResearchWorkflow:
    def __init__(self, settings, store, run_id, gateway=None):
        ensure_isolation(store, run_id)
        self.settings, self.store, self.run_id, self.gateway = settings, store, run_id, gateway
        self.store.cache_ttl_hours = settings.cache_ttl_hours
        run = store.run(run_id)
        self.mock = run.mode == 'mock'
        self.references = (
            [SourceRecord.model_validate(s) for s in store.records(run_id, 'source') if s.get('kind') == 'upload']
            if not self.mock
            else []
        )
        self.resume_checkpoint = store.load_checkpoint(run_id)
        if self.resume_checkpoint and self.resume_checkpoint[1].get('rules_version') != VERSION:
            raise FinancialError('旧检查点属于原规则版本；保留原记录，请创建 v1.1 新研究')
        self.optimized = optimized_run(store, run_id)
        self.human = HumanInterventionAgent(store, run_id)
        if gateway:
            gateway.attach_store(store, run_id)
        local = LocalDatasource(ROOT / 'examples/fixtures' if self.mock else settings.local_sources)
        local.build_index(exclude_annual_reports=not self.mock and settings.data_collection_mode == 'fixed')
        if self.mock:
            local.index = [s.model_copy(update={'kind': 'mock'}) for s in local.index]
        bound = EvidenceStore(store, run_id)
        for source in local.index:
            bound.add_source(source)
        local.index = [bound.sources[source.source_id] for source in local.index]
        if self.mock:
            web = None
        elif settings.search_provider == 'bocha':
            web = WebAdapter(
                BochaWebSearchProvider(settings.search_url, settings.resolved_search_key()), store, run_id=run_id
            )
        else:
            web = WebAdapter(
                HTTPWebSearchProvider(settings.search_url, settings.resolved_search_key(), settings.search_auth_header),
                store,
                run_id=run_id,
            )
        self.datasource = UnifiedDatasource(local, web)
        self.datasource.exclude_annual_reports = not self.mock and settings.data_collection_mode == 'fixed'
        self.datasource.reference_sources = self.references
        from .fixed_collection import FixedCollection

        self.fixed_collection = FixedCollection(self)

    def bind(self, ctx):
        bound = EvidenceStore(self.store, self.run_id)
        for s in ctx.get('sources', []):
            bound.add_source(SourceRecord.model_validate(s))
        for e in ctx.get('evidence', []):
            bound.add_evidence(EvidenceRecord.model_validate(e))
        for f in ctx.get('facts', []):
            bound.add_fact(FinancialFact.model_validate(f))
        return bound

    async def resolve_company(self, c):
        if not self.mock and self.settings.data_collection_mode == 'fixed':
            return await self.fixed_collection.identity(c)
        if not self.mock:
            self.gateway.resolve('resolver')
            if not self.settings.search_url and not self.references:
                from .datasources import DatasourceError

                raise DatasourceError('Web Search 未配置 CDR_SEARCH_URL')

        async def retrieve_identity():
            if self.references:
                return {'sources': [s.model_dump(mode='json') for s in self.references], 'warnings': []}
            found, issues = await self.datasource.retrieve(c['input'] + ' 上市公司 股票代码 年报')
            return {'sources': [s.model_dump(mode='json') for s in found], 'warnings': issues}

        retrieved = await unit(self.store, self.run_id, 'search', 'company_identity', c['input'], retrieve_identity)
        sources = [SourceRecord.model_validate(s) for s in retrieved['sources']]
        warnings = retrieved['warnings']
        if self.mock:
            sources = list(self.datasource.local.index)
            company = Company(
                company_id='DEMO',
                name=c['input'] + '（模拟示例）',
                ticker='DEMO',
                source_ids=[s.source_id for s in sources if s.title == 'company.md'],
            )
        else:
            selected = source_context(
                sources,
                c['input'] + ' 上市 公司 证券 股票 主营 身份',
                self.gateway.limits('resolver').input_capacity - 4000,
            )
            company = await ask(self.gateway, 'resolver', Company, {'input': c['input'], 'sources': selected})
            if self.references and (
                not company.ticker
                or not company.source_ids
                or not set(company.source_ids).issubset({s.source_id for s in sources})
            ):
                # Only unresolved identity may be searched; no financial fields are queried here.
                async def missing_identity():
                    found, issues = await self.datasource.retrieve(c['input'] + ' 上市公司 证券代码 主体身份')
                    return {'sources': [s.model_dump(mode='json') for s in found], 'warnings': issues}

                fallback = await unit(
                    self.store, self.run_id, 'search', 'missing_company_identity', c['input'], missing_identity
                )
                sources += [SourceRecord.model_validate(s) for s in fallback['sources']]
                warnings += fallback['warnings']
                selected = source_context(
                    sources, c['input'] + ' 证券代码 主体身份', self.gateway.limits('resolver').input_capacity - 4000
                )
                company = await ask(self.gateway, 'resolver', Company, {'input': c['input'], 'sources': selected})
            if (
                not company.ticker
                or not company.source_ids
                or not set(company.source_ids).issubset({s.source_id for s in sources})
            ):
                raise ValueError('无法从来源确认上市公司身份或存在歧义')
            if company.financial_company or company.market != 'A股':
                raise ValueError('MVP 仅支持 A 股非金融上市公司')
        bound = EvidenceStore(self.store, self.run_id)
        for source in list(self.datasource.local.index) + self.references:
            if source.content.startswith('{'):
                try:
                    import json

                    row = json.loads(source.content)
                    if row.get('company_id') == company.company_id:
                        bound.ingest_structured(source)
                except ValueError:
                    pass
        for source in sources:
            bound.add_source(source)
        run = self.store.run(self.run_id)
        run.company_name = company.name
        self.store.save_run(run)
        return {
            'rules_version': VERSION,
            'company': company.model_dump(mode='json'),
            'sources': [s.model_dump(mode='json') for s in bound.sources.values()],
            'evidence': [e.model_dump(mode='json') for e in bound.evidence.values()],
            'facts': [f.model_dump(mode='json') for f in bound.facts.values()],
            'limitations': warnings,
        }

    async def research_brief(self, c):
        brief_sources = [SourceRecord.model_validate(s) for s in c['sources']]
        if c.get('data_template_version'):
            from .fixed_collection import annual_source

            brief_sources = [s for s in brief_sources if annual_source(s, c['company'])]
            from .reporting_periods import available_source

            brief_sources = [
                s for s in brief_sources if available_source(s, self.store.run(self.run_id).created_at[:10])
            ]
            if not brief_sources:
                raise FinancialError('请上传本次使用的公司年报；年报仅由用户提供，不自动查找本地目录或 web')
        if self.mock:
            brief = ResearchBrief(
                company_id='DEMO',
                scope='合成制造企业示例研究，非真实上市公司研究',
                historical_periods=['2023A', '2024A', '2025A'],
                forecast_periods=['2026E', '2027E', '2028E'],
                segments=['设备', '服务'],
                interim_period='2026H1',
            )
        else:
            annual_manifest = []
            if c.get('data_template_version'):
                from .reporting_periods import report_period

                annual_manifest = [
                    {'source_id': s.source_id, 'title': s.title, 'report_period': report_period(s)}
                    for s in brief_sources
                ]
                brief_sources.sort(key=lambda s: report_period(s) or '', reverse=True)
            if annual_manifest:
                selected = []
                share = (self.gateway.limits('brief').input_capacity - 6000) // len(brief_sources)
                for source in brief_sources:
                    selected.extend(source_context(
                        [source], c['company']['name'] + ' 主营 业务 年报 period segment', share,
                    ))
            else:
                selected = source_context(
                    brief_sources,
                    c['company']['name'] + ' 公司 主营 业务 年报 中期 季报 报告期 period segment',
                    self.gateway.limits('brief').input_capacity - 4000,
                )
            request = {
                'company': c['company'],
                'as_of': self.store.run(self.run_id).created_at[:10],
                'sources': selected,
            }
            if c.get('data_template_version'):
                request['fixed_data_contract'] = c['data_template_version']
                request['annual_report_manifest'] = annual_manifest
                disclosed = [r['report_period'] for r in annual_manifest if (r['report_period'] or '').endswith('A')]
                if disclosed:
                    latest_year = int(max(disclosed)[:4])
                    request['required_historical_periods'] = [f'{y}A' for y in range(latest_year - 2, latest_year + 1)]
                    request['required_forecast_periods'] = [f'{y}E' for y in range(latest_year + 1, latest_year + 4)]
            for attempt in range(self.settings.plan_repairs + 1):
                brief = await ask(self.gateway, 'brief', ResearchBrief, request)
                support, errors = brief_business_support(brief, [s.model_dump(mode='json') for s in brief_sources])
                if request.get('required_historical_periods'):
                    # The upload manifest decides the years; a model slip here
                    # must not cost a repair round or stop the run.
                    brief.historical_periods = list(request['required_historical_periods'])
                    brief.forecast_periods = list(request['required_forecast_periods'])
                self.store.record(
                    self.run_id,
                    'brief_validation',
                    str(attempt),
                    {'brief': brief.model_dump(mode='json'), 'segment_sources': support, 'errors': errors},
                )
                if not errors:
                    break
                if attempt == self.settings.plan_repairs:
                    raise FinancialError('；'.join(errors))
                request = request | {
                    'previous_brief': brief.model_dump(mode='json'),
                    'validation_errors': errors,
                    'repair_instruction': '逐项核对业务来源，使用来源正文中的业务名称，引用覆盖每项业务的已提供 source_id；不同业务可引用不同来源。不得为了通过校验删除有来源支持的业务，也不得虚构来源或业务。',
                }
                self.store.emit(
                    self.run_id, '研究规划', 'research_brief', 'running', '业务来源校验未通过，正在修正业务名称与引用'
                )
        if brief.company_id != c['company']['company_id'] or not brief.segments or not brief.historical_periods:
            raise ValueError('Research Brief 缺少身份、历史期间或业务')
        import re

        if any(not re.fullmatch(r'\d{4}A', p) for p in brief.historical_periods) or any(
            not re.fullmatch(r'\d{4}E', p) for p in brief.forecast_periods
        ):
            raise ValueError('研究期间格式错误')
        if brief.forecast_periods and min(brief.forecast_periods)[:4] <= max(brief.historical_periods)[:4]:
            raise ValueError('实际与预测期间重叠')
        from .framework import validate_brief

        support, errors = brief_business_support(brief, [s.model_dump(mode='json') for s in brief_sources])
        if errors:
            raise FinancialError('；'.join(errors))
        supporting = list(dict.fromkeys(source_id for ids in support.values() for source_id in ids))
        brief.source_ids = brief.source_ids or supporting
        brief.as_of = brief.as_of or self.store.run(self.run_id).created_at
        interim = sorted({f['period'] for f in c['facts'] if re.fullmatch(r'\d{4}(?:H1|Q[1-3])', f['period'])})
        if interim and (not brief.interim_period or brief.interim_period < interim[-1]):
            brief.interim_period = interim[-1]
        validate_brief(brief)
        disclosed_years = {
            f['period']
            for f in c['facts']
            if f['actual_or_forecast'] == 'actual' and re.fullmatch(r'\d{4}A', f['period'])
        }
        if disclosed_years and max(disclosed_years) > max(brief.historical_periods):
            raise FinancialError('Brief 遗漏已取得的最新披露财年')
        return {'brief': brief.model_dump(mode='json')}

    async def research_plan(self, c):
        if c.get('data_template_version'):
            return await self.fixed_collection.plan(c)
        if self.mock and self.settings.data_collection_mode == 'fixed':
            self.fixed_collection.mock_preview(c)
        reference_update = {}
        if self.references:
            # Read every uploaded document before any independent researcher starts web retrieval.
            structured_ids = {f['source_id'] for f in c['facts']}
            text_sources = [s.model_dump(mode='json') for s in self.references if s.source_id not in structured_ids]
            for task_id, role, topic, context_only in (
                [
                    ('uploaded_reference_extract', 'financial', '提取上传参考资料中的公司财务事实', False),
                    (
                        'uploaded_reference_context_extract',
                        'business',
                        '提取上传参考资料中的行业、产业链、政策、需求、竞争、技术、经营和风险信息',
                        True,
                    ),
                ]
                if text_sources
                else []
            ):
                task = ResearchTask(
                    task_id=task_id, company_id=c['company']['company_id'], topic=topic, role=role, queries=[topic]
                ).model_dump(mode='json')
                subgraph = researcher_graph(
                    self.gateway, self.datasource, self.store, self.run_id, 1, False, self.settings
                )
                state = {
                    'task': task,
                    'brief': c['brief'],
                    'round': 0,
                    'sources': text_sources,
                    'evidence': [],
                    'facts': [],
                    'queries': [],
                    'gaps': [],
                    'warnings': [],
                    'summary': {},
                    'reference_only': True,
                    'reference_context': context_only,
                }
                output = await unit(
                    self.store,
                    self.run_id,
                    'research_task',
                    task['task_id'],
                    state,
                    lambda: subgraph.ainvoke(state, {'recursion_limit': 10}),
                )
                bound = self.bind(c)
                for s in output['sources']:
                    bound.add_source(SourceRecord.model_validate(s))
                for e in output['evidence']:
                    bound.add_evidence(EvidenceRecord.model_validate(e))
                for f in output['facts']:
                    bound.add_fact(FinancialFact.model_validate(f))
                reference_update = {
                    'sources': [s.model_dump(mode='json') for s in bound.sources.values()],
                    'evidence': [e.model_dump(mode='json') for e in bound.evidence.values()],
                    'facts': [f.model_dump(mode='json') for f in bound.facts.values()],
                    'limitations': list(dict.fromkeys(c.get('limitations', []) + output['warnings'])),
                }
                c = c | reference_update
                self.store.emit(
                    self.run_id,
                    '研究规划',
                    'reference_extract',
                    'completed',
                    f'上传资料已完成提取：{len(output["facts"])} 项财务事实、{len(output["evidence"])} 项证据；仅补查缺失内容',
                )
        brief = ResearchBrief.model_validate(c['brief'])
        standard = skeleton(brief, self.settings.block_call_budget)
        plan = standard
        if not self.mock:
            errors = []
            for attempt in range(self.settings.plan_repairs + 1):
                plan = await ask(
                    self.gateway,
                    'research_planner',
                    ResearchPlan,
                    {
                        'company': c['company'],
                        'brief': c['brief'],
                        'mandatory_skeleton': standard.model_dump(mode='json'),
                        'repair_missing': errors,
                    },
                )
                errors = validate_plan(plan, brief, standard)
                self.store.record(
                    self.run_id,
                    'plan_validation',
                    str(attempt),
                    {'errors': errors, 'fallback': bool(errors and attempt == self.settings.plan_repairs)},
                )
                if not errors:
                    break
            if errors:
                plan = standard
        for task in plan.tasks:
            self.store.record(self.run_id, 'task', task.task_id, task.model_dump(mode='json'))
        coverage = [e.model_dump(mode='json') for e in coverage_matrix(plan, brief)]
        for b in plan.blocks:
            self.store.record(self.run_id, 'block', b.block_id, b.model_dump(mode='json'))
        return reference_update | {
            'plan': plan.model_dump(mode='json'),
            'coverage': coverage,
            'pending': [t.task_id for t in plan.tasks],
            'summaries': [],
            'block_analyses': {},
        }

    async def calculation_plan(self, c):
        if c.get('data_template_version'):
            return self.fixed_collection.calculation_plan(c)
        registry = [
            {'formula_id': f.id, 'inputs': f.inputs, 'unit': f.unit} for f in REGISTRY.values() if f.unit != 'dynamic'
        ]

        def validate(plan):
            if plan.company_id != c['company']['company_id']:
                raise ValueError('计算计划公司身份错误')
            for request in plan.calculations:
                if request.formula_id not in REGISTRY or request.unit != REGISTRY[request.formula_id].unit:
                    raise FinancialError('计算计划选择未知公式或错误单位')
                if request.period not in c['brief']['historical_periods']:
                    raise FinancialError('历史计算计划期间错误')

        if self.mock:
            plan = mock_calculation_plan()
        else:
            context = {'brief': c['brief'], 'plan': c['plan'], 'registry': registry}
            plan = await ask(self.gateway, 'calculation_planner', CalculationPlan, context)
            for attempt in range(2):
                try:
                    validate(plan)
                    break
                except (FinancialError, ValueError) as exc:
                    context['validation_error'] = str(exc)
                    context['allowed_periods'] = list(c['brief']['historical_periods'])
                    plan = await ask(self.gateway, 'calculation_planner', CalculationPlan, context)
            validate(plan)
        return {'calculation_plan': plan.model_dump(mode='json')}

    async def dependencies(self, c):
        if c.get('data_template_version'):
            return self.fixed_collection.dependencies(c)
        data = DependencyResolver().resolve(CalculationPlan.model_validate(c['calculation_plan']))
        data += requirements(ResearchBrief.model_validate(c['brief']))
        for segment in c['brief']['segments']:
            for period in c['brief']['historical_periods'] + [
                str(int(min(c['brief']['historical_periods'])[:4]) - 1) + 'A'
            ]:
                for metric in ['revenue', 'cost']:
                    data.append(
                        RequiredData(
                            company_id=c['company']['company_id'],
                            segment_id=segment,
                            period=period,
                            metric_code=metric,
                            unit='CNY_million',
                            priority='high',
                            formula_dependency=['F04'],
                        )
                    )
        data = list({(d.metric_code, d.period, d.segment_id, d.unit): d for d in data}.values())
        # Opening balance and segment revenue dependencies always required for three statements.
        period = max(c['brief']['historical_periods'])
        keys = {(d.metric_code, d.period, d.segment_id, d.unit) for d in data}
        for metric, segment, unit in [(m, None, 'CNY_million') for m in OPENING_KEYS] + [
            ('revenue', s, 'CNY_million') for s in c['brief']['segments']
        ]:
            key = (metric, period, segment, unit)
            if key not in keys:
                data.append(
                    RequiredData(
                        metric_code=metric,
                        company_id=c['company']['company_id'],
                        segment_id=segment,
                        period=period,
                        unit=unit,
                        priority='critical',
                        formula_dependency=['three_statements'],
                    )
                )
                keys.add(key)
            else:
                for d in data:
                    if (d.metric_code, d.period, d.segment_id, d.unit) == key:
                        d.priority = 'critical'
                        d.formula_dependency = list(dict.fromkeys(d.formula_dependency + ['three_statements']))
        plan = ResearchPlan.model_validate(c['plan'])
        pending = list(c['pending'])
        facts = [FinancialFact.model_validate(f) for f in c['facts']]
        processor = FinancialDataProcessor()
        missing_by_block = {}
        for d in data:
            try:
                processor.get(
                    facts,
                    d.company_id,
                    d.metric_code,
                    d.period,
                    d.unit,
                    d.segment_id,
                    'segment' if d.segment_id else 'consolidated',
                )
            except FinancialError:
                block = 'F03' if d.metric_code == 'operating_cashflow' else 'F04' if d.segment_id else 'F01'
                missing_by_block.setdefault(block, []).append(d)
        for block, items in missing_by_block.items():
            t = ResearchTask(
                company_id=c['company']['company_id'],
                block_id=block,
                topic='公式与核心同比依赖取数：' + ','.join(sorted({d.metric_code for d in items})),
                role='financial',
                queries=[c['company']['name'] + ' 年报 ' + ' '.join(sorted({d.metric_code for d in items}))],
                required_data_ids=[d.data_id for d in items],
            )
            plan.tasks.append(t)
            pending.append(t.task_id)
        return {
            'required_data': [d.model_dump(mode='json') for d in data],
            'plan': plan.model_dump(mode='json'),
            'pending': pending,
        }

    async def supervisor(self, c):
        if c.get('data_template_version'):
            return await self.fixed_collection.collect(c)
        self.store.execution_put(self.run_id, 'execution_meta', 'human-admitted', {'admitted': False})
        pending = list(c['pending'])
        tasks = {t['task_id']: t for t in c['plan']['tasks']}
        summaries = list(c['summaries'])
        bound = self.bind(c)
        subgraph = researcher_graph(
            self.gateway,
            self.datasource,
            self.store,
            self.run_id,
            self.settings.max_research_rounds,
            self.mock,
            self.settings,
        )
        blocks = {b['block_id']: b for b in c['plan']['blocks']}

        async def research(k):
            task = tasks[k]
            if self.references:
                from .references import plan_reference_queries

                task = await unit(
                    self.store,
                    self.run_id,
                    'reference_plan',
                    k,
                    [task, c['facts'], c['evidence']],
                    lambda: plan_reference_queries(task, c, self.gateway, self.store, self.run_id),
                )
            upload_ids = {s.source_id for s in self.references}
            state = {
                'task': task,
                'brief': c['brief'],
                'round': 0,
                'sources': [s for s in c['sources'] if s['source_id'] in upload_ids],
                'evidence': [e for e in c['evidence'] if e['source_id'] in upload_ids],
                'facts': [f for f in c['facts'] if f['source_id'] in upload_ids],
                'queries': task['queries'],
                'gaps': [],
                'warnings': [],
                'summary': {},
                'reference_prepared': bool(self.references),
            }
            output = await unit(
                self.store,
                self.run_id,
                'research_task',
                k,
                state,
                lambda: subgraph.ainvoke(state, {'recursion_limit': self.settings.max_research_rounds * 4 + 6}),
            )
            # Persist and publish before waiting for unrelated peers. No human wait here.
            bound = EvidenceStore(self.store, self.run_id)
            for source in output['sources']:
                bound.add_source(SourceRecord.model_validate(source))
            for ev in output['evidence']:
                bound.add_evidence(EvidenceRecord.model_validate(ev))
            for fact in output['facts']:
                bound.add_fact(FinancialFact.model_validate(fact))
            if c.get('company'):
                await asyncio.to_thread(self.human.publish_collected, c)
            return output

        if self.optimized:
            initial = set(pending)

            def ready(k, completed):
                done = {
                    block
                    for block in blocks
                    if all(
                        t['task_id'] not in initial or t['task_id'] in completed
                        for t in tasks.values()
                        if t.get('block_id') == block
                    )
                }
                return not tasks[k].get('block_id') or set(
                    blocks.get(tasks[k]['block_id'], {}).get('dependencies', [])
                ).issubset(done)

            try:
                outputs = await bounded_schedule(pending, research, self.settings.concurrency, ready)
            except DependencySchedulingError as exc:
                raise FinancialError('分析块调度依赖无法满足') from exc
            for output in outputs:
                for s in output['sources']:
                    bound.add_source(SourceRecord.model_validate(s))
                for e in output['evidence']:
                    bound.add_evidence(EvidenceRecord.model_validate(e))
                for f in output['facts']:
                    bound.add_fact(FinancialFact.model_validate(f))
                summaries.append(output['summary'])
                c['limitations'] = list(dict.fromkeys(c['limitations'] + output['warnings']))
            return {
                'pending': [],
                'sources': [s.model_dump(mode='json') for s in bound.sources.values()],
                'evidence': [e.model_dump(mode='json') for e in bound.evidence.values()],
                'facts': [f.model_dump(mode='json') for f in bound.facts.values()],
                'summaries': summaries,
                'limitations': c['limitations'],
            }

        def completed_blocks():
            return {
                block
                for block in blocks
                if all(t['task_id'] not in pending for t in tasks.values() if t.get('block_id') == block)
            }

        done = completed_blocks()
        while pending:
            ready = [
                k
                for k in pending
                if not tasks[k].get('block_id')
                or set(blocks.get(tasks[k]['block_id'], {}).get('dependencies', [])).issubset(done)
            ]
            if not ready:
                raise FinancialError('分析块调度依赖无法满足')
            batch = ready[: self.settings.concurrency]
            outputs = await settle(research(k) for k in batch)
            for output in outputs:
                for s in output['sources']:
                    bound.add_source(SourceRecord.model_validate(s))
                for e in output['evidence']:
                    bound.add_evidence(EvidenceRecord.model_validate(e))
                for f in output['facts']:
                    bound.add_fact(FinancialFact.model_validate(f))
                summaries.append(output['summary'])
                c['limitations'] = list(dict.fromkeys(c['limitations'] + output['warnings']))
            pending = [k for k in pending if k not in batch]
            done = completed_blocks()
        return {
            'pending': [],
            'sources': [s.model_dump(mode='json') for s in bound.sources.values()],
            'evidence': [e.model_dump(mode='json') for e in bound.evidence.values()],
            'facts': [f.model_dump(mode='json') for f in bound.facts.values()],
            'summaries': summaries,
            'limitations': c['limitations'],
        }

    async def data_gaps(self, c, *, human_recheck=False):
        if c.get('data_template_version'):
            return self.fixed_collection.gaps(c)
        from .reconciliation import reconcile, POLICY

        candidates = {f['fact_id']: f for f in c.get('fact_candidates', [])}
        candidates.update({f['fact_id']: f for f in c['facts']})
        sources = {s['source_id']: s for s in c['sources']}
        evidence = {e['evidence_id']: e for e in c['evidence']}
        checks = list(c.get('fact_verifications', []))

        def checked_groups():
            initial = reconcile(
                list(candidates.values()), list(sources.values()), list(evidence.values()), c['company']
            )[1]
            signatures = {d['group_id']: digest(d['candidate_ids']) for d in initial}
            return {v['group_id'] for v in checks if v.get('candidate_signature') == signatures.get(v['group_id'])}

        checked = checked_groups()
        active, decisions = reconcile(
            list(candidates.values()), list(sources.values()), list(evidence.values()), c['company'], checked
        )
        # Bounded per identity across replans; successful search/extraction steps replay
        # from the current run's unit ledger after a pause or connection interruption.
        if not self.mock and not human_recheck:
            subgraph = researcher_graph(self.gateway, self.datasource, self.store, self.run_id, 1, False, self.settings)
            for decision in decisions:
                if (
                    decision['status'] != 'unresolved'
                    or not decision['identity']
                    or decision['rule'] == 'reference-conflict'
                ):
                    continue
                gid = decision['group_id']
                prior = [v for v in checks if v['group_id'] == gid]
                for attempt in range(len(prior), self.settings.max_conflict_checks):
                    check_pause(self.store, self.run_id)
                    identity = decision['identity']
                    metric = identity['metric_code']
                    from .financials.formulas import FIELD_MAP

                    label = next((k for k, v in FIELD_MAP.items() if v == metric), metric)
                    topic = f"财务冲突核实：{identity['period']} {label} {identity['scope']} {identity.get('segment_id') or ''}"
                    name = c['company']['name']
                    queries = [
                        f"{name} {identity['period'][:4]} {label} 年报 原始公告",
                        f"{name} {identity['period'][:4]} {label} 更正 追溯调整",
                    ]
                    if attempt:
                        queries = [
                            f"site:{domain} {name} {identity['period'][:4]} {label} {identity.get('segment_id') or ''} 更正前 更正后 年度"
                            for domain in ('cninfo.com.cn', 'sse.com.cn')
                        ]
                    task = ResearchTask(
                        task_id='verify-' + digest([POLICY, gid, attempt])[:24],
                        company_id=identity['company_id'],
                        role='financial',
                        segment_id=identity['segment_id'],
                        topic=topic
                        + '。核对单位、期间、合并或母公司口径；引用完整表头和数值行；更正须引用更正前后值。候选信息：'
                        + str(decision['candidates']),
                        queries=queries,
                    ).model_dump(mode='json')
                    state = {
                        'task': task,
                        'brief': c['brief'],
                        'round': 0,
                        'sources': [],
                        'evidence': [],
                        'facts': [],
                        'queries': queries,
                        'gaps': [],
                        'warnings': [],
                        'summary': {},
                    }
                    self.store.emit(
                        self.run_id, '数据收集', task['task_id'], 'running', topic + '：补查原始披露与更正公告'
                    )
                    output = await unit(
                        self.store,
                        self.run_id,
                        'research_task',
                        task['task_id'],
                        state,
                        lambda: subgraph.ainvoke(state, {'recursion_limit': 10}),
                    )
                    sources.update({s['source_id']: s for s in output['sources']})
                    evidence.update({e['evidence_id']: e for e in output['evidence']})
                    candidates.update({f['fact_id']: f for f in output['facts']})
                    receipt = {
                        'verification_id': task['task_id'],
                        'group_id': gid,
                        'attempt': attempt + 1,
                        'queries': queries,
                        'candidate_ids': decision['candidate_ids'],
                        'source_ids': [s['source_id'] for s in output['sources']],
                        'evidence_ids': [e['evidence_id'] for e in output['evidence']],
                        'status': 'completed',
                    }
                    fresh = reconcile(
                        list(candidates.values()), list(sources.values()), list(evidence.values()), c['company']
                    )[1]
                    receipt['candidate_signature'] = digest(
                        next(d['candidate_ids'] for d in fresh if d['group_id'] == gid)
                    )
                    checks.append(receipt)
                    checked = checked_groups()
                    self.store.record(self.run_id, 'fact_verification', receipt['verification_id'], receipt)
                    active, updated = reconcile(
                        list(candidates.values()),
                        list(sources.values()),
                        list(evidence.values()),
                        c['company'],
                        checked,
                    )
                    current = next((v for v in updated if v['group_id'] == gid), None)
                    if current and current['status'] != 'unresolved':
                        break
                    if current:
                        decision = current
        active, decisions = reconcile(
            list(candidates.values()), list(sources.values()), list(evidence.values()), c['company'], checked
        )
        active, decisions = self.human.apply(
            active, decisions, list(candidates.values()), list(sources.values()), list(evidence.values()), c['company']
        )
        for decision in decisions:
            self.store.record(self.run_id, 'fact_decision', decision['decision_id'], decision | {'policy': POLICY})
        rejected = {f['fact_id'] for f in candidates.values()} - {f['fact_id'] for f in active}
        active_evidence = {f['evidence_id'] for f in active}
        excluded_evidence = {
            f['evidence_id'] for f in candidates.values() if f['fact_id'] in rejected
        } - active_evidence
        unresolved = [d for d in decisions if d['status'] == 'unresolved']
        reconciliation = {
            'facts': active,
            'fact_candidates': list(candidates.values()),
            'fact_decisions': decisions,
            'fact_verifications': checks,
            'sources': list(sources.values()),
            'evidence': list(evidence.values()),
            'excluded_fact_evidence': sorted(excluded_evidence),
            'limitations': list(
                dict.fromkeys(
                    [v for v in c.get('limitations', []) if not v.startswith('财务核验未解决：')]
                    + ['财务核验未解决：' + str(d['identity']) + '；' + d['reason'] for d in unresolved]
                )
            ),
        }
        previous = {d['group_id']: d for d in c.get('fact_decisions', [])}
        changed = [
            d
            for d in decisions
            if d['group_id'] in previous and d['selected_ids'] != previous[d['group_id']]['selected_ids']
        ]
        if changed:
            from .contexts import METRICS

            responsible = set()
            for b in c['plan']['blocks']:
                for d in changed:
                    identity = d['identity']
                    metric = identity.get('metric_code')
                    segment = identity.get('segment_id')
                    if (
                        b['template_id'] in METRICS
                        and metric in METRICS[b['template_id']]
                        and not segment
                        or b['template_id'] == 'F04'
                        and segment
                        or b.get('segment_id') == segment
                        and segment
                    ):
                        responsible.add(b['block_id'])
            affected = descendants(c['plan']['blocks'], responsible)
            self.store.record(
                self.run_id,
                'invalidation',
                'reconcile-' + digest([d['decision_id'] for d in changed])[:24],
                {
                    'snapshot_id': digest([d['decision_id'] for d in changed]),
                    'responsible_blocks': sorted(responsible),
                    'affected_blocks': sorted(affected),
                    'reason': '财务候选裁决变化，仅重算受影响输入及依赖块',
                },
            )
            stale = {id for d in changed for id in previous[d['group_id']]['selected_ids']} - {
                f['fact_id'] for f in active
            }
            results = c.get('calculations', [])
            for _ in range(len(results) + 1):
                new = {r['result_id'] for r in results if set(r['input_refs'].values()) & stale}
                if new <= stale:
                    break
                stale |= new
            reconciliation.update(
                calculations=[r for r in results if r['result_id'] not in stale],
                comparisons=[
                    r for r in c.get('comparisons', []) if not {r['current_fact_id'], r['previous_fact_id']} & stale
                ],
                block_analyses={k: v for k, v in c.get('block_analyses', {}).items() if k not in affected},
                validated=False,
            )
            if 'V01' in affected:
                reconciliation.update(
                    assumption_reuse=c.get('assumptions', []) + c.get('assumption_reuse', []),
                    assumptions=[],
                    forecasts=[],
                    segment_models={},
                )
            if c.get('report'):
                reconciliation['report'] = c['report'] | {'approved_snapshot_id': ''}
        c = c | reconciliation
        processor = FinancialDataProcessor()
        facts = [FinancialFact.model_validate(f) for f in c['facts']]
        missing = []
        data = []
        for raw in c['required_data']:
            d = RequiredData.model_validate(raw)
            try:
                processor.get(
                    facts,
                    d.company_id,
                    d.metric_code,
                    d.period,
                    d.unit,
                    d.segment_id,
                    'segment' if d.segment_id else 'consolidated',
                )
                d.source_status = 'found'
            except FinancialError as exc:
                conflict = any(
                    v['identity'].get('metric_code') == d.metric_code
                    and v['identity'].get('period') == d.period
                    and v['identity'].get('segment_id') == d.segment_id
                    for v in unresolved
                )
                d.source_status = 'conflict' if conflict or '冲突' in str(exc) else 'missing'
                missing.append(d.model_dump(mode='json'))
            data.append(d.model_dump(mode='json'))
        support = reference_question_support(c, self.store, self.run_id)
        reconciliation['reference_question_support'] = support
        coverage = refresh_coverage(
            c['coverage'], c['plan']['blocks'], c['facts'], c['evidence'], c.get('block_analyses', {}), support
        )
        for entry in coverage:
            self.store.record(self.run_id, 'coverage', entry['question_id'], entry)
        missing_questions = (
            [
                entry
                for entry in coverage
                if entry['gaps'] and not entry['requirements'] and entry['block_id'].startswith(('C', 'F', 'I', 'B'))
            ]
            if not self.mock
            else []
        )
        return reconciliation | {
            'required_data': data,
            'missing': missing,
            'missing_questions': missing_questions,
            'coverage': coverage,
        }

    async def replan(self, c):
        if c.get('data_template_version'):
            return {'pending': [], 'missing_questions': []}
        plan = ResearchPlan.model_validate(c['plan'])
        new = []
        grouped = {}
        for d in c['missing']:
            if d['source_status'] == 'conflict':
                continue  # Dedicated checks already exhausted; never loop generic searches.
            block = 'F03' if d['metric_code'] == 'operating_cashflow' else 'F04' if d['segment_id'] else 'F01'
            grouped.setdefault(block, []).append(d)
        for block, items in grouped.items():
            t = ResearchTask(
                company_id=c['company']['company_id'],
                block_id=block,
                topic='核心数据定向补查',
                role='financial',
                queries=[
                    c['company']['name'] + ' 年报 ' + ' '.join(d['metric_code'] + ' ' + d['period'] for d in items)
                ],
                required_data_ids=[d['data_id'] for d in items],
            )
            plan.tasks.append(t)
            new.append(t.task_id)
        question_groups = {}
        for entry in c.get('missing_questions', []):
            question_groups.setdefault(entry['block_id'], []).append(entry)
        blocks = {b.block_id: b for b in plan.blocks}
        for block, entries in question_groups.items():
            b = blocks[block]
            questions = [e['question_id'] for e in entries]
            t = ResearchTask(
                company_id=b.company_id,
                block_id=block,
                question_ids=questions,
                segment_id=b.segment_id,
                topic='未覆盖问题定向补查',
                role='business' if b.segment_id else 'financial' if block.startswith('F') else 'company',
                queries=[c['company']['name'] + ' ' + (b.segment_id or '') + ' ' + b.questions[q] for q in questions],
            )
            plan.tasks.append(t)
            new.append(t.task_id)
        return {'plan': plan.model_dump(mode='json'), 'pending': new, 'replans': c.get('replans', 0) + 1}

    async def human_gate(self, c):
        if c.get('data_template_version'):
            return self.fixed_collection.human_gate(c)
        # The node is intentionally uncached: submitted feedback is external state.
        input_signature = digest(c)
        saved = self.store.execution_get(self.run_id, 'execution_meta', 'human-context')
        if saved and saved.get('input_signature') == digest(c):
            c = saved['context']
        else:
            c = copy.deepcopy(c)
        self.human.refresh(c, final=True)
        for feedback in self.store.records(self.run_id, 'human_feedback'):
            if feedback['status'] not in {'pending', 'researching'}:
                continue
            issue = next((i for i in self.human.issues() if i['issue_id'] == feedback['issue_id']), None)
            if not issue or issue['status'] == 'resolved' or issue['signature'] != feedback['signature']:
                self.human.finish_feedback(feedback, '候选已发生变化，请根据最新问题重新提交')
                continue
            check_pause(self.store, self.run_id)
            try:
                if feedback['action'] == 'research':
                    if not feedback.get('query') or not feedback['query'].strip():
                        raise FeedbackError('请填写新的补查方向或公开材料 URL')
                    feedback = feedback | {'status': 'researching'}
                    self.store.record(self.run_id, 'human_feedback', feedback['feedback_id'], feedback)
                    self.store.record(self.run_id, 'human_issue', issue['issue_id'], issue | {'status': 'researching'})
                    identity = issue['identity']
                    task = ResearchTask(
                        task_id=feedback['feedback_id'],
                        company_id=identity['company_id'],
                        role='financial',
                        segment_id=identity.get('segment_id'),
                        topic='人工指定定向补查：'
                        + feedback['reason']
                        + '；核对期间、单位、范围及原始数值：'
                        + str(identity),
                        queries=[feedback['query']],
                    ).model_dump(mode='json')
                    state = {
                        'task': task,
                        'brief': c['brief'],
                        'round': 0,
                        'sources': [],
                        'evidence': [],
                        'facts': [],
                        'queries': task['queries'],
                        'gaps': [],
                        'warnings': [],
                        'summary': {},
                    }
                    if feedback['query'].strip().startswith(('https://', 'http://')):
                        if not self.datasource.web:
                            raise FeedbackError('当前模式不支持读取公开链接，请指定已收集来源')
                        records = await self.datasource.web.read(
                            {'url': feedback['query'].strip(), 'title': '人工提供披露链接'}
                        )
                        state.update(sources=[s.model_dump(mode='json') for s in records], queries=[])
                    subgraph = researcher_graph(
                        self.gateway, self.datasource, self.store, self.run_id, 1, self.mock, self.settings
                    )
                    output = await unit(
                        self.store,
                        self.run_id,
                        'research_task',
                        task['task_id'],
                        state,
                        lambda: subgraph.ainvoke(state, {'recursion_limit': 10}),
                    )
                    for key in ('sources', 'evidence'):
                        c[key] = list(
                            {
                                v['source_id' if key == 'sources' else 'evidence_id']: v for v in c[key] + output[key]
                            }.values()
                        )
                    c['fact_candidates'] = list(
                        {f['fact_id']: f for f in c.get('fact_candidates', c['facts']) + output['facts']}.values()
                    )
                    c['facts'] = c['fact_candidates']
                    self.bind(c)
                    # Successful retrieval counts as a check for this exact new candidate set.
                    from .reconciliation import reconcile

                    fresh = reconcile(c['facts'], c['sources'], c['evidence'], c['company'])[1]
                    for decision in fresh:
                        if (
                            decision['identity']
                            and decision['identity']['metric_code'] == identity['metric_code']
                            and decision['identity']['period'] == identity['period']
                        ):
                            receipt = {
                                'verification_id': feedback['feedback_id'] + decision['group_id'],
                                'group_id': decision['group_id'],
                                'attempt': 'human',
                                'queries': task['queries'],
                                'candidate_ids': decision['candidate_ids'],
                                'candidate_signature': digest(decision['candidate_ids']),
                                'source_ids': [s['source_id'] for s in output['sources']],
                                'evidence_ids': [e['evidence_id'] for e in output['evidence']],
                                'status': 'completed',
                            }
                            c.setdefault('fact_verifications', []).append(receipt)
                            self.store.record(self.run_id, 'fact_verification', receipt['verification_id'], receipt)
                else:
                    c = self.human.accept(feedback, c)
                self.human.finish_feedback(feedback)
            except BudgetError:
                raise  # Preserve the established budget adjustment/recovery path.
            except (FeedbackError, DatasourceError, LLMError) as exc:
                self.human.finish_feedback(feedback, str(exc))
        c.update(await self.data_gaps(c, human_recheck=True))
        issues = self.human.refresh(c, final=True)
        # Save newly verified input even if another issue still requires a response.
        self.store.execution_put(
            self.run_id, 'execution_meta', 'human-context', {'context': c, 'input_signature': input_signature}
        )
        admitted = not any(i['blocking'] and i['status'] != 'resolved' for i in issues)
        self.store.execution_put(self.run_id, 'execution_meta', 'human-admitted', {'admitted': admitted})
        if not admitted:
            self.store.checkpoint(self.run_id, 'human_gate', c)
            raise HumanInputRequired()
        return c

    async def financial_analysis(self, c):
        # Review repair paths must obey the same prerequisite gate.
        c.update(await self.human_gate(c))
        results, missing = execute_calculation_plan(
            CalculationPlan.model_validate(c['calculation_plan']),
            [FinancialFact.model_validate(f) for f in c['facts']],
            self.store.records(self.run_id, 'calculation'),
        )
        comparisons, computed, gaps = build_comparisons(
            ResearchBrief.model_validate(c['brief']), [FinancialFact.model_validate(f) for f in c['facts']]
        )
        for result in computed:
            self.store.record(self.run_id, 'calculation', result.result_id, result.model_dump(mode='json'))
        for comparison in comparisons:
            self.store.record(self.run_id, 'comparison', comparison.comparison_id, comparison.model_dump(mode='json'))
        # Deterministic stage only; semantic analysis happens once for each DAG block.
        analysis = FinancialAnalysis(
            observations=[],
            evidence_ids=[],
            calculation_ids=[r.result_id for r in results + computed],
            limitations=missing,
        )
        return c | {
            'comparisons': [r.model_dump(mode='json') for r in comparisons],
            'comparison_gaps': gaps,
            'calculations': [r.model_dump(mode='json') for r in results + computed],
            'analysis': analysis.model_dump(mode='json'),
            'limitations': list(dict.fromkeys(c['limitations'] + missing)),
        }

    async def analyze_blocks(self, c):
        from .schemas import BlockAnalysis

        analyses = {a['block_id']: a for a in self.store.records(self.run_id, 'block_analysis')} | dict(
            c.get('block_analyses', {})
        )
        done = set()
        pending = list(c['plan']['blocks'])

        async def analyze(b):
            # X01 uses final sections and is completed by core_conclusion, always last.
            if b['template_id'] == 'X01':
                return
            package = block_context(
                c | {'block_analyses': analyses}, b['block_id'], 'analysis', self.store, self.run_id, 1000000
            )
            version = package.snapshot_id
            if analyses.get(b['block_id'], {}).get('version') == version:
                return
            self.store.emit(self.run_id, '分块分析', b['block_id'], 'running', '分析块：' + b['block_id'])
            data = analyzer_view(package.content)
            if self.mock:
                output = FinancialAnalysis(
                    observations=['合成资料已按本块问题整理，未披露的驱动保持限制。'],
                    evidence_ids=[e['evidence_id'] for e in data['evidence']],
                    calculation_ids=[r['result_id'] for r in data['calculations']],
                    limitations=[],
                    question_answers={
                        q: '合成数据仅验证流程；非核心未披露项按覆盖矩阵列示限制。' for q in b['questions']
                    },
                )
            else:
                output = await ask_bounded(
                    self.gateway,
                    'financial_analyzer',
                    FinancialAnalysis,
                    data,
                    max_splits=self.settings.max_batch_splits,
                )
                missing_questions = [q for q in b['questions'] if not output.question_answers.get(q, '').strip()]
                for attempt in range(self.settings.plan_repairs):
                    if not missing_questions:
                        break
                    repair = await ask_bounded(
                        self.gateway,
                        'financial_analyzer',
                        FinancialAnalysis,
                        data | {'repair_missing_questions': missing_questions},
                        max_splits=self.settings.max_batch_splits,
                    )
                    output.question_answers.update(repair.question_answers)
                    output.observations += repair.observations
                    output.evidence_ids = list(dict.fromkeys(output.evidence_ids + repair.evidence_ids))
                    output.calculation_ids = list(dict.fromkeys(output.calculation_ids + repair.calculation_ids))
                    missing_questions = [q for q in b['questions'] if not output.question_answers.get(q, '').strip()]
                if missing_questions:
                    raise FinancialError('分析块必需问题遗漏，定向修复耗尽：' + b['block_id'])
            known_evidence = {e['evidence_id'] for e in data['evidence']}
            known_calculations = {r['result_id'] for r in data['calculations']}
            unknown_evidence, unknown_calculations = resolve_citations(output, known_evidence, known_calculations)
            for attempt in range(0 if self.mock else self.settings.plan_repairs):
                if not unknown_evidence and not unknown_calculations:
                    break
                # Ask again with the invalid IDs named; keep only citations that resolve.
                repair = await ask_bounded(
                    self.gateway,
                    'financial_analyzer',
                    FinancialAnalysis,
                    data
                    | {
                        'repair_invalid_citations': {
                            'evidence_ids': sorted(unknown_evidence),
                            'calculation_ids': sorted(unknown_calculations),
                            'instruction': '这些 ID 不在输入中。请逐字复制 evidence[].evidence_id 与 '
                            'calculations[].result_id 重新给出引用列表；找不到对应项则不引用。',
                        }
                    },
                    max_splits=self.settings.max_batch_splits,
                )
                unknown_evidence, unknown_calculations = resolve_citations(
                    repair, known_evidence, known_calculations
                )
                output.evidence_ids = list(dict.fromkeys(output.evidence_ids + repair.evidence_ids))
                output.counter_evidence_ids = list(
                    dict.fromkeys(output.counter_evidence_ids + repair.counter_evidence_ids)
                )
                output.calculation_ids = list(dict.fromkeys(output.calculation_ids + repair.calculation_ids))
            if unknown_evidence or unknown_calculations:
                raise FinancialError(
                    f'块分析引用超出已选择数据：{b["block_id"]}，'
                    f'evidence {sorted(unknown_evidence)[:10]}，calculation {sorted(unknown_calculations)[:10]}'
                )
            if not output.observations:
                raise FinancialError('块分析语义输出为空：' + b['block_id'])
            analysis = BlockAnalysis(
                block_id=b['block_id'],
                version=version,
                conclusions=output.observations + list(output.question_answers.values()),
                evidence_ids=output.evidence_ids,
                calculation_ids=output.calculation_ids,
                counter_evidence_ids=output.counter_evidence_ids,
                limitations=output.limitations,
            )
            analyses[b['block_id']] = analysis.model_dump(mode='json')
            b.update(version=version, status='validated')
            self.store.record(self.run_id, 'block_analysis', b['block_id'], analyses[b['block_id']])
            self.store.record(self.run_id, 'block', b['block_id'], b)
            self.store.emit(self.run_id, '分块分析', b['block_id'], 'completed', '分析校验完成：' + b['block_id'])

        if self.optimized:
            blocks = {b['block_id']: b for b in pending}
            try:
                await bounded_schedule(
                    blocks,
                    lambda k: analyze(blocks[k]),
                    self.settings.concurrency,
                    lambda k, done: set(blocks[k]['dependencies']).issubset(done),
                )
            except DependencySchedulingError as exc:
                raise FinancialError('分析块依赖环') from exc
        else:
            while pending:
                ready = [b for b in pending if set(b['dependencies']).issubset(done)]
                if not ready:
                    raise FinancialError('分析块依赖环')
                await settle(analyze(b) for b in ready[: self.settings.concurrency])
                ids = {b['block_id'] for b in ready[: self.settings.concurrency]}
                done |= ids
                pending = [b for b in pending if b['block_id'] not in ids]
        coverage = refresh_coverage(
            c['coverage'],
            c['plan']['blocks'],
            c['facts'],
            c['evidence'],
            analyses,
            reference_question_support(c, self.store, self.run_id),
        )
        for entry in coverage:
            self.store.record(self.run_id, 'coverage', entry['question_id'], entry)
        return {'block_analyses': analyses, 'coverage': coverage, 'plan': c['plan']}

    async def assumptions(self, c):
        if c.get('data_template_version'):
            reason = self.fixed_collection.forecast_limit(c)
            if reason:
                return {
                    'assumptions': [],
                    'segment_models': {},
                    'limitations': list(dict.fromkeys(c['limitations'] + [reason])),
                }
        processor = FinancialDataProcessor()
        facts = [FinancialFact.model_validate(f) for f in c['facts']]
        company = c['company']['company_id']
        period = max(c['brief']['historical_periods'])
        try:
            for metric in OPENING_KEYS:
                processor.get(facts, company, metric, period)
            # Incomplete segment disclosure limits only the segment split, not the forecast.
            segments, _, segment_note = forecast_segments(
                facts, company, period, c['brief']['segments'], bool(c.get('data_template_version'))
            )
        except FinancialError:
            return {
                'assumptions': [],
                'segment_models': {},
                'limitations': list(
                    dict.fromkeys(c['limitations'] + ['预测关键输入尚未核实，暂停生成假设；其他研究继续。'])
                ),
            }
        fallback = segments == [COMPANY_SEGMENT]
        minority = bool(c.get('data_template_version')) and has_minority_interest(facts, company, period)
        if self.mock:
            candidate = next(e for e in c['evidence'] if '模拟预测依据' in e['quote'])
            assumptions = mock_assumptions(candidate['evidence_id'], c['brief']['forecast_periods'], segments)
            models = {s: 'growth' for s in segments}
            limitations = []
        else:
            package = block_context(c, 'V01', 'assumptions', self.store, self.run_id, 1000000)
            instructions = [
                '仅输出本情景本年度公司与各业务假设；不得输出其它期间。以历史证据支持，未取得量价输入时不得编造。'
            ]
            if fallback:
                instructions.append(
                    f'分部收入披露不完整，本次不做分部预测：segment_models 只能是 {{"{COMPANY_SEGMENT}": "growth"}}，'
                    f'收入假设只输出 segment_id="{COMPANY_SEGMENT}" 的 growth_rate（公司口径营业收入增速），'
                    '不得输出各业务分部的收入假设。'
                )
            if minority:
                instructions.append(
                    '历史合并净利润与归母净利润不同（存在少数股东损益）：必须另输出公司级 minority_ratio'
                    '（少数股东损益 / 合并净利润，ratio），以历史少数股东损益占比为依据。'
                )
            base = {k: v for k, v in package.content.items() if k != 'financial_facts'} | {
                'facts': package.content['financial_facts'],
                'required_assumption_keys': REQUIRED_ASSUMPTION_UNITS
                | ({'minority_ratio': ASSUMPTION_UNITS['minority_ratio']} if minority else {}),
                'forecast_segments': segments,
                'registry': {
                    k: {'inputs': REGISTRY[k].inputs}
                    for k in (
                        ['growth']
                        if fallback
                        else ['volume_price', 'capacity_utilization', 'users_arpu', 'market_share', 'growth']
                    )
                },
            }
            assumptions = []
            models = {COMPANY_SEGMENT: 'growth'} if fallback else {}
            limitations = []
            selections = [
                (scenario, period) for scenario in ['Bear', 'Base', 'Bull'] for period in c['brief']['forecast_periods']
            ]

            async def generate(selection):
                scenario, period = selection
                output = await ask_bounded(
                    self.gateway,
                    'assumption_planner',
                    AssumptionOutput,
                    base
                    | {
                        'selected_scenario': scenario,
                        'selected_period': period,
                        'instructions': instructions,
                    },
                    max_splits=self.settings.max_batch_splits,
                )
                if any(a.period != period or a.scenario != scenario for a in output.assumptions):
                    raise FinancialError('有界预测假设返回了其它情景/期间')
                return output

            outputs = (
                await bounded_schedule(selections, generate, self.settings.concurrency)
                if self.optimized
                else [await generate(s) for s in selections]
            )
            for output in outputs:
                if fallback:
                    # Disclosed segments are not forecast; their assumptions would be unused.
                    assumptions += [a for a in output.assumptions if a.segment_id in {None, COMPANY_SEGMENT}]
                    limitations += output.limitations
                    continue
                if any(s in models and models[s] != m for s, m in output.segment_models.items()):
                    raise FinancialError('跨情景业务收入模型冲突')
                assumptions += output.assumptions
                models.update(output.segment_models)
                limitations += output.limitations
        if segment_note:
            limitations.append(segment_note)
        # Preserve identity for regenerated assumptions whose full content and
        # evidence are unchanged; unrelated forecast inputs then keep their cache.
        old_assumptions = {
            digest(ForecastAssumption.model_validate(raw).model_dump(mode='json', exclude={'assumption_id'})): raw[
                'assumption_id'
            ]
            for raw in c.get('assumptions', []) + c.get('assumption_reuse', [])
        }
        for a in assumptions:
            old_id = old_assumptions.get(digest(a.model_dump(mode='json', exclude={'assumption_id'})))
            if old_id:
                a.assumption_id = old_id
        known = {e['evidence_id'] for e in c['evidence'] if e['evidence_id'] not in c.get('excluded_fact_evidence', [])}
        keys = set()
        for a in assumptions:
            key = (a.scenario, a.period, a.segment_id, a.metric_code)
            if key in keys:
                raise FinancialError('预测假设重复')
            keys.add(key)
            if (
                a.period not in c['brief']['forecast_periods']
                or not set(a.evidence_ids).issubset(known)
                or not a.evidence_ids
            ):
                raise FinancialError('假设期间或依据错误')
            expected = ASSUMPTION_UNITS.get(a.metric_code) or INPUT_UNITS.get(a.metric_code, 'CNY_million')
            if (
                a.segment_id
                and models.get(a.segment_id) in {'volume_price', 'capacity_utilization'}
                and a.metric_code == 'price'
            ):
                expected = 'CNY/unit'
            if a.unit != expected:
                raise FinancialError('假设单位错误 ' + a.metric_code)
        from .work_products import preserve_materials

        preserve_materials(
            self.store, self.run_id, [('assumption', a.assumption_id, a.model_dump(mode='json')) for a in assumptions]
        )
        return {
            'assumptions': [a.model_dump(mode='json') for a in assumptions],
            'segment_models': models,
            'limitations': list(dict.fromkeys(c['limitations'] + limitations)),
        }

    async def calculate(self, c):
        processor = FinancialDataProcessor()
        facts = [FinancialFact.model_validate(f) for f in c['facts']]
        assumptions = [ForecastAssumption.model_validate(a) for a in c['assumptions']]
        results = list(c['calculations'])
        forecasts = []
        limitations = list(c['limitations'])
        period = max(c['brief']['historical_periods'])
        company = c['company']['company_id']
        try:
            opening_facts = {k: processor.get(facts, company, k, period) for k in OPENING_KEYS}
            opening = {k: f.value for k, f in opening_facts.items()}
            opening_refs = {k: f.fact_id for k, f in opening_facts.items()}
            segments, historical, segment_note = forecast_segments(
                facts, company, period, c['brief']['segments'], bool(c.get('data_template_version'))
            )
        except FinancialError as exc:
            return {'forecasts': [], 'limitations': limitations + [str(exc), '关键三表输入缺失，未生成预测。']}
        if segment_note:
            limitations.append(segment_note)
        # Fixed-template runs used to stop on minority interest; they now need an
        # explicit split. Legacy runs keep the consolidated simplification.
        minority = bool(c.get('data_template_version')) and has_minority_interest(facts, company, period)
        for scenario in ['Bear', 'Base', 'Bull']:
            balance = dict(opening)
            balance_refs = dict(opening_refs)
            prev = {s: f.value for s, f in historical.items()}
            prev_refs = {s: f.fact_id for s, f in historical.items()}
            for year in sorted(c['brief']['forecast_periods']):
                try:
                    if minority and not any(
                        a.scenario == scenario and a.period == year and a.segment_id is None
                        for a in assumptions
                        if a.metric_code == 'minority_ratio'
                    ):
                        raise FinancialError('历史存在少数股东损益，缺少 minority_ratio 假设')
                    drivers = {}
                    for segment in segments:
                        model = c['segment_models'].get(segment)
                        if model not in {
                            'volume_price',
                            'capacity_utilization',
                            'users_arpu',
                            'market_share',
                            'growth',
                        }:
                            raise FinancialError('分部缺少适用预测模型')
                        params = {}
                        refs = {}
                        for metric in REGISTRY[model].inputs:
                            if model == 'growth' and metric == 'previous':
                                params[metric] = prev[segment]
                                refs[metric] = prev_refs[segment]
                                continue
                            matches = [
                                a
                                for a in assumptions
                                if a.scenario == scenario
                                and a.period == year
                                and a.segment_id == segment
                                and a.metric_code == metric
                            ]
                            if len(matches) != 1:
                                raise FinancialError(f'缺少分部驱动 {segment}/{metric}/{year}/{scenario}')
                            params[metric] = matches[0].value
                            refs[metric] = matches[0].assumption_id
                        drivers[segment] = {'model': model, 'inputs': params, 'input_refs': refs}
                    forecast, computed = ForecastEngine().forecast(
                        company, year, scenario, balance, drivers, assumptions, balance_refs
                    )
                    forecasts.append(forecast.model_dump(mode='json'))
                    results += [r.model_dump(mode='json') for r in computed]
                    from .work_products import preserve_materials

                    preserve_materials(
                        self.store,
                        self.run_id,
                        [('forecast', scenario + '-' + year, forecast.model_dump(mode='json'))]
                        + [('calculation', r.result_id, r.model_dump(mode='json')) for r in computed],
                    )
                    balance = {k: forecast.balance[k] for k in OPENING_KEYS}
                    balance_refs = {**balance_refs, **{r.output_metric: r.result_id for r in computed}}
                    prev = {s: v['revenue'] for s, v in forecast.segments.items()}
                    prev_refs = {
                        s: next(r.result_id for r in computed if r.output_metric == f'{s}.revenue') for s in prev
                    }
                except FinancialError as exc:
                    limitations.append(f'{scenario}/{year}：{exc}')
                    break
        for r in results:
            self.store.record(self.run_id, 'calculation', r['result_id'], r)
        for a in c['assumptions']:
            self.store.record(self.run_id, 'assumption', a['assumption_id'], a)
        return {'calculations': results, 'forecasts': forecasts, 'limitations': list(dict.fromkeys(limitations))}

    async def validate(self, c):
        if any(not Calculator().recompute(CalculationResult.model_validate(r)) for r in c['calculations']):
            raise FinancialError('财务计算复算失败')
        return {'validated': True}

    async def write_sections(self, c):
        from .writers import make_report

        report = await make_report(c, self.gateway, self.mock, self.store, self.run_id)
        return {'report': report.model_dump(mode='json')}

    async def core_conclusion(self, c):
        from .writers import write_core

        section = await write_core(c, self.gateway, self.mock, self.store, self.run_id)
        report = ReportDocument.model_validate(c['report'])
        report.sections[0] = section
        from .schemas import BlockAnalysis

        version = digest([c['block_analyses'], section.model_dump(mode='json')])
        analysis = BlockAnalysis(
            block_id='X01',
            version=version,
            conclusions=section.paragraphs,
            evidence_ids=section.evidence_ids,
            calculation_ids=section.calculation_ids,
        )
        analyses = c['block_analyses'] | {'X01': analysis.model_dump(mode='json')}
        self.store.record(self.run_id, 'block_analysis', 'X01', analysis.model_dump(mode='json'))
        for b in report.blocks:
            if b.block_id == 'X01':
                b.version = version
                b.status = 'validated'
        for b in c['plan']['blocks']:
            if b['block_id'] == 'X01':
                b.update(version=version, status='validated')
                self.store.record(self.run_id, 'block', 'X01', b)
        coverage = refresh_coverage(
            c['coverage'],
            c['plan']['blocks'],
            c['facts'],
            c['evidence'],
            analyses,
            reference_question_support(c, self.store, self.run_id),
        )
        from .schemas import CoverageEntry

        report.coverage = [CoverageEntry.model_validate(e) for e in coverage]
        for entry in coverage:
            self.store.record(self.run_id, 'coverage', entry['question_id'], entry)
        from .writers import report_snapshot

        report.snapshot_id = report_snapshot(report)
        report.approved_snapshot_id = ''
        return {
            'report': report.model_dump(mode='json'),
            'block_analyses': analyses,
            'plan': c['plan'],
            'coverage': coverage,
        }

    async def assemble(self, c):
        report = ReportDocument.model_validate(c['report'])
        if [s.title for s in report.sections] != __import__('company_research.reports', fromlist=['TITLES']).TITLES:
            raise ValueError('报告结构不符合固定要求')
        return {'report': report.model_dump(mode='json')}

    async def final_review(self, c):
        from .reviewers import review_graph, deterministic_review
        from .writers import report_snapshot

        report = ReportDocument.model_validate(c['report'])
        report.snapshot_id = report_snapshot(report)
        report.approved_snapshot_id = ''
        memo = dict(c.get('review_memo') or {})
        from .reports import sections_flat

        titles = {s.section_id: s.title for s in sections_flat(report.sections)}
        from .work_products import preserve_review

        evaluation_review_id = preserve_review(self.store, self.run_id, report, c.get('revisions', 0) + 1)
        deterministic = deterministic_review(report)
        from .schemas import ReviewIssue

        critical_requirements = [d for d in c.get('required_data', []) if d.get('priority') == 'critical']
        for decision in c.get('fact_decisions', []):
            identity = decision['identity']
            critical = any(
                d['metric_code'] == identity.get('metric_code')
                and d['period'] == identity.get('period')
                and d.get('segment_id') == identity.get('segment_id')
                for d in critical_requirements
            )
            if decision['status'] == 'unresolved' and critical:
                deterministic.append(
                    ReviewIssue(
                        issue_type='financial',
                        severity='critical',
                        location='F01',
                        block_id='F01',
                        rule_id='financial.conflict',
                        description='关键财务冲突核实仍未解决：' + str(identity),
                        suggested_fix='补充包含期间、单位、范围及更正前后值的原始披露',
                        target_node='supervisor',
                        affected_refs=decision['candidate_ids'],
                    )
                )
        if any(i.severity in {'critical', 'error'} for i in deterministic):
            all_issues = [i.model_dump(mode='json') for i in deterministic]
        else:
            output = await review_graph(self.gateway, self.store, self.run_id, self.mock, memo).ainvoke(
                {'report': report.model_dump(mode='json'), 'issues': []}
            )
            all_issues = output['issues']
        for i in all_issues:
            i['snapshot_id'] = report.snapshot_id
        hard = [i for i in all_issues if i['severity'] in {'critical', 'error'}]
        unresolved = []
        if (
            hard
            and c.get('revisions', 0) >= self.settings.max_revisions
            and all(i.get('rule_id', '').startswith('semantic.') for i in hard)
        ):
            # Model reviewers drive rework but cannot block on their own: after the last
            # round their open findings are kept on record and disclosed as limitations.
            for i in hard:
                i['severity'], i['validation_status'] = 'warning', 'unresolved'
            unresolved, hard = hard, []
        # Deterministic gate failures lead the blocking message.
        hard.sort(key=lambda i: i.get('rule_id', '').startswith('semantic.'))
        report = ReportDocument.model_validate(c['report'])
        report.issues = [
            __import__('company_research.schemas', fromlist=['ReviewIssue']).ReviewIssue.model_validate(i)
            for i in all_issues
        ]
        by_section = {}
        for i in unresolved:
            by_section.setdefault(i.get('section_id') or i['location'], []).append(i)
        disclosures = [
            f'终审未解决意见（{titles.get(sid, sid)}，{len(items)} 项）：'
            + '；'.join(x['description'][:80] for x in items)
            for sid, items in by_section.items()
        ]
        report.limitations = list(
            dict.fromkeys(
                report.limitations
                + [i['description'] for i in all_issues if i['severity'] == 'warning' and i not in unresolved]
                + disclosures
            )
        )
        preserve_review(
            self.store,
            self.run_id,
            report,
            c.get('revisions', 0) + 1,
            evaluation_review_id,
            'rejected' if hard else 'reviewed',
        )
        immutable_input_issue = c.get('data_template_version') and any(
            i['target_node'] in {'supervisor', 'research_plan', 'financial_analysis'} for i in hard
        )
        if hard and (
            immutable_input_issue
            or c.get('revisions', 0) >= self.settings.max_revisions
            or any(i.get('rule_id') == 'financial.conflict' for i in hard)
        ):
            for i in all_issues:
                self.store.record(self.run_id, 'review_issue', i['issue_id'], i)
            self.store.save_report(self.run_id, report)
            raise FinancialError('终审阻断：' + '; '.join(i['description'] for i in hard[:5]))
        if report.limitations and not self.settings.allow_limited:
            raise FinancialError('当前配置不允许受限报告')
        for i in all_issues:
            self.store.record(self.run_id, 'review_issue', i['issue_id'], i)
        if not hard:
            # Warning disclosures are part of the approved final snapshot.
            report.snapshot_id = report_snapshot(report)
            report.approved_snapshot_id = report.snapshot_id
            for problem in report.issues:
                problem.snapshot_id = report.snapshot_id
                self.store.record(self.run_id, 'review_issue', problem.issue_id, problem.model_dump(mode='json'))
            self.store.record(
                self.run_id,
                'approval',
                report.snapshot_id,
                {'rules_version': VERSION, 'snapshot_id': report.snapshot_id, 'status': 'approved'},
            )
            preserve_review(
                self.store, self.run_id, report, c.get('revisions', 0) + 1, evaluation_review_id, 'approved'
            )
        return {'issues': hard, 'report': report.model_dump(mode='json'), 'review_memo': memo}

    async def revise(self, c):
        targets = {i['target_node'] for i in c['issues']}
        c['report']['approved_snapshot_id'] = ''
        responsible = {i.get('block_id') for i in c['issues'] if i.get('block_id')}
        self.store.record(
            self.run_id,
            'invalidation',
            str(c.get('revisions', 0)),
            {
                'snapshot_id': c['report']['snapshot_id'],
                'responsible_blocks': sorted(responsible),
                'affected_blocks': sorted(descendants(c['plan']['blocks'], responsible)),
                'reason': 'review repair',
            },
        )

        from .reviewers import issue_sections

        report = ReportDocument.model_validate(c['report'])
        # Every core redraft in this round, whichever branch runs it, sees the core findings.
        c['core_instructions'] = list(
            dict.fromkeys(
                revision_note(i)
                for i in c['issues']
                if i['target_node'] == 'core_conclusion' or 'core' in issue_sections(i, report.sections)
            )
        )

        async def execute(node):
            self.store.emit(self.run_id, STAGES[node], f'revision_{node}', 'running', f'定向返工：{NODE_LABELS[node]}')
            c.update(await getattr(self, node)(c))
            self.store.emit(
                self.run_id, STAGES[node], f'revision_{node}', 'completed', f'返工完成：{NODE_LABELS[node]}'
            )

        if targets & {'research_plan', 'supervisor'}:
            bad_evidence = {i['location'] for i in c['issues'] if i['issue_type'] == 'evidence'}
            c['evidence'] = [e for e in c['evidence'] if e['evidence_id'] not in bad_evidence]
            known = {e['evidence_id'] for e in c['evidence']}
            c['facts'] = [f for f in c['facts'] if f['evidence_id'] in known and f['fact_id'] not in bad_evidence]
            plan = ResearchPlan.model_validate(c['plan'])
            new = []
            grouped = {}
            for problem in c['issues']:
                grouped.setdefault(problem.get('block_id') or 'C01', []).append(problem)
            for block, problems in grouped.items():
                t = ResearchTask(
                    task_id='repair-' + digest([c['report']['snapshot_id'], c.get('revisions', 0), block])[:24],
                    company_id=c['company']['company_id'],
                    block_id=block,
                    topic='终审定向补查：' + block,
                    role='financial' if block.startswith('F') else 'company',
                    queries=[c['company']['name'] + ' 年报 ' + '; '.join(p['description'] for p in problems)],
                )
                plan.tasks.append(t)
                new.append(t.task_id)
            c['plan'] = plan.model_dump(mode='json')
            c['pending'] = new
            await execute('supervisor')
            await execute('data_gaps')
            c.update(await self.human_gate(c))
            targets |= {'financial_analysis', 'assumptions', 'calculate', 'write_sections', 'core_conclusion'}
        if 'assumptions' in targets:
            await execute('assumptions')
            targets |= {'calculate', 'write_sections', 'core_conclusion'}
        if targets & {'financial_analysis', 'calculate'}:
            await execute('financial_analysis')
            await execute('calculate')
            await execute('validate')
            await execute('analyze_blocks')
            targets |= {'assemble', 'write_sections', 'core_conclusion'}
        if targets & {'assemble'}:
            await execute('write_sections')
            await execute('core_conclusion')
            await execute('assemble')
        elif 'write_sections' in targets:
            from .writers import write_one, patch_one, mock_sections
            from .reviewers import issue_paragraphs, FIXED_SECTIONS

            report = ReportDocument.model_validate(c['report'])
            per_section = {}
            for problem in c['issues']:
                for sid in issue_sections(problem, report.sections):
                    per_section.setdefault(sid, []).append(problem)
            # Any located issue keeps the repair local; fixed sections (core, statements) are
            # never redrafted here, and core_conclusion below refreshes the core view.
            matched = bool(per_section)

            def patch(sections):
                for index, s in enumerate(sections):
                    if s.section_id in per_section:
                        if self.mock:
                            from .reports import sections_flat

                            fresh = next(
                                (x for x in sections_flat(mock_sections(c)) if x.section_id == s.section_id), None
                            )
                            if fresh:
                                sections[index] = fresh
                    patch(s.children)

            if self.mock:
                patch(report.sections)
            else:
                from .reports import sections_flat

                for s in sections_flat(report.sections):
                    if s.section_id in per_section and s.section_id not in FIXED_SECTIONS:
                        problems = per_section[s.section_id]
                        # Paragraph numbers are relative to the section the reviewer read.
                        spots = [
                            issue_paragraphs(p, len(s.paragraphs)) if p.get('section_id') == s.section_id else []
                            for p in problems
                        ]
                        updated = None
                        if all(spots):
                            notes = {}
                            for p, at in zip(problems, spots):
                                for index in at:
                                    notes.setdefault(index, []).append(revision_note(p))
                            updated = await patch_one(self.gateway, c, s, notes, self.store, self.run_id)
                        if updated is None:
                            updated = await write_one(
                                self.gateway,
                                c,
                                s.section_id,
                                s.title,
                                '修复终审定位问题',
                                instructions=list(dict.fromkeys(revision_note(p) for p in problems)),
                                store=self.store,
                                run_id=self.run_id,
                            )
                        s.paragraphs, s.evidence_ids, s.calculation_ids, s.number_bindings = (
                            updated.paragraphs,
                            updated.evidence_ids,
                            updated.calculation_ids,
                            updated.number_bindings,
                        )
            c['report'] = report.model_dump(mode='json')
            if not matched:
                await execute('write_sections')
            else:
                from .comparisons import bind_financial_sections

                report = ReportDocument.model_validate(c['report'])
                bind_financial_sections(report)
                c['report'] = report.model_dump(mode='json')
            await execute('core_conclusion')
        elif 'core_conclusion' in targets:
            await execute('core_conclusion')
        return {**c, 'core_instructions': [], 'revisions': c.get('revisions', 0) + 1}

    async def render(self, c):
        report = ReportDocument.model_validate(c['report'])
        self.store.save_report(self.run_id, report)
        from .writers import report_snapshot

        if report.rules_version == VERSION and (
            core_gate(report) or report.approved_snapshot_id != report_snapshot(report)
        ):
            raise FinancialError('正式导出阻断：核心同比未通过或审核快照已经失效')
        if report.rules_version == VERSION and digest(
            [f.model_dump(mode='json') for f in report.financial_facts]
        ) != digest(c['facts']):
            raise FinancialError('事实已更新，旧报告和审核失效，需局部重算')
        folder = self.settings.artifacts / self.run_id
        folder.mkdir(parents=True, exist_ok=True)
        from .schemas import uid
        import hashlib

        async def output_format(ext, exporter):
            key = 'render-' + ext
            previous = self.store.execution_get(self.run_id, 'execution_meta', key)
            target = folder / f'report.{ext}'
            version = digest([report.approved_snapshot_id, 'render-1', ext])
            if (
                previous
                and previous['version'] == version
                and target.is_file()
                and hashlib.sha256(target.read_bytes()).hexdigest() == previous['hash']
            ):
                return
            check_pause(self.store, self.run_id)
            owner = self.store.run(self.run_id).attempt_id
            temporary = folder / f'.render-{uid()}.{ext}'
            try:
                await asyncio.to_thread(exporter, report, temporary)
                current = self.store.run(self.run_id)
                if owner is not None and (current.attempt_id != owner or current.status not in {'running', 'pausing'}):
                    raise PauseRequested()
                checksum = hashlib.sha256(temporary.read_bytes()).hexdigest()
                temporary.replace(target)
                self.store.execution_put(self.run_id, 'execution_meta', key, {'version': version, 'hash': checksum})
            finally:
                # A cancelled to_thread may still be writing its isolated temporary file.
                if temporary.exists():
                    try:
                        temporary.unlink()
                    except OSError:
                        pass

        await output_format('docx', export_docx)
        await output_format('html', lambda document, path: path.write_text(html_report(document), encoding='utf-8'))
        try:
            from .renderers import export_pdf

            await output_format('pdf', export_pdf)
        except PauseRequested:
            raise
        except Exception:
            self.store.emit(self.run_id, '文档生成', 'pdf', 'warning', 'PDF 导出失败，完整 DOCX 与在线报告仍可使用')
        return {}

    async def deliver(self, c):
        from .writers import report_snapshot

        report = ReportDocument.model_validate(c['report'])
        if report.rules_version == VERSION and (
            core_gate(report) or report.approved_snapshot_id != report_snapshot(report)
        ):
            raise FinancialError('交付快照失效')
        if report.rules_version == VERSION and digest(
            [f.model_dump(mode='json') for f in report.financial_facts]
        ) != digest(c['facts']):
            raise FinancialError('交付事实版本不一致')
        run = self.store.run(self.run_id)
        run.limitations = c['report']['limitations']
        run.status = 'limited' if run.limitations else 'completed'
        self.store.save_run(run)
        return {'outcome': run.status}

    def build(self, checkpointer=None):
        STAGES['analyze_blocks'] = '分块分析'
        NODE_LABELS['analyze_blocks'] = '按依赖分析财务、业务、估值与风险块'
        graph = StateGraph(WorkflowState)
        for name, stage in STAGES.items():

            def wrap(node, stage):
                async def execute(state):
                    check_pause(self.store, self.run_id)
                    key = unit_key('node', node, state['context'])
                    saved = self.store.execution_get(self.run_id, 'execution_units', key)
                    if not saved or saved['state'] != 'succeeded' or node in {'render', 'deliver'}:
                        self.store.emit(
                            self.run_id,
                            stage,
                            node,
                            'running',
                            ('模拟运行 · ' if self.mock else '') + NODE_LABELS[node],
                        )
                        if self.mock:
                            await asyncio.sleep(self.settings.mock_delay)
                    context = copy.deepcopy(state['context'])

                    async def invoke():
                        return await getattr(self, node)(context)

                    if node in {'render', 'deliver', 'financial_analysis'}:
                        update = await invoke()
                    else:
                        update = await unit(self.store, self.run_id, 'node', node, state['context'], invoke)
                    context.update(update)
                    self.store.checkpoint(self.run_id, node, context)
                    self.store.emit(self.run_id, stage, node, 'completed', f'{NODE_LABELS[node]}已完成', once_key=key)
                    final_nodes = {
                        'resolve_company': '公司识别',
                        'dependencies': '研究规划',
                        'supervisor': '数据收集',
                        'financial_analysis': '财务分析',
                        'validate': '盈利预测',
                        'analyze_blocks': '分块分析',
                        'assemble': '报告写作',
                        'final_review': '最终审核',
                        'render': '文档生成',
                    }
                    if node in final_nodes:
                        self.store.emit(
                            self.run_id,
                            stage,
                            final_nodes[node],
                            'completed',
                            f'{stage}阶段任务已完成',
                            once_key=key + '-stage',
                        )
                    return {'context': context}

                return execute

            graph.add_node(name, wrap(name, stage))
        linear = [
            'resolve_company',
            'research_brief',
            'research_plan',
            'calculation_plan',
            'dependencies',
            'supervisor',
            'data_gaps',
        ]
        graph.add_edge(START, linear[0])
        for a, b in zip(linear, linear[1:]):
            graph.add_edge(a, b)
        graph.add_conditional_edges(
            'data_gaps',
            lambda s: (
                'replan'
                if not s['context'].get('data_template_version')
                and (
                    any(d['source_status'] != 'conflict' for d in s['context']['missing'])
                    or s['context'].get('missing_questions')
                )
                and s['context'].get('replans', 0) < self.settings.max_replans
                else 'financial_analysis'
            ),
        )
        graph.add_edge('replan', 'supervisor')
        linear = [
            'financial_analysis',
            'assumptions',
            'calculate',
            'validate',
            'analyze_blocks',
            'write_sections',
            'core_conclusion',
            'assemble',
            'final_review',
        ]
        for a, b in zip(linear, linear[1:]):
            graph.add_edge(a, b)
        graph.add_conditional_edges(
            'final_review',
            lambda s: (
                'revise'
                if s['context'].get('issues') and s['context'].get('revisions', 0) < self.settings.max_revisions
                else 'render'
            ),
        )
        graph.add_edge('revise', 'final_review')
        graph.add_edge('render', 'deliver')
        graph.add_edge('deliver', END)
        return graph.compile(checkpointer=checkpointer)
