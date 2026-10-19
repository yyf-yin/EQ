from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Any
from uuid import uuid4
from pydantic import BaseModel, Field, ConfigDict, model_validator


def uid() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchRun(Schema):
    run_id: str = Field(default_factory=uid)
    company_input: str
    company_name: str = ""
    mode: Literal["mock", "real"]
    status: Literal[
        "queued", "running", "pausing", "completed", "limited", "blocked", "failed", "interrupted", "waiting_human"
    ] = "queued"
    stage: str = "等待开始"
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    limitations: list[str] = Field(default_factory=list)
    error: str | None = None
    rules_version: str = "1.0"
    stop_reason: str | None = None
    failure_code: str | None = None
    attempt_id: str | None = None
    resume_count: int = 0
    reference_attachment_ids: list[str] = Field(default_factory=list)


class ResearchEvent(Schema):
    event_id: int = 0
    run_id: str
    timestamp: str = Field(default_factory=now)
    stage: str
    task_name: str
    status: str
    display_message: str


class Company(Schema):
    company_id: str
    name: str
    ticker: str
    market: str = "A股"
    financial_company: bool = False
    source_ids: list[str] = Field(default_factory=list)


class ResearchBrief(Schema):
    company_id: str
    scope: str
    historical_periods: list[str]
    forecast_periods: list[str]
    segments: list[str]
    industries: dict[str, str] = Field(default_factory=dict)
    interim_period: str | None = None
    quarterly_collection: bool = False
    source_ids: list[str] = Field(default_factory=list)
    as_of: str | None = None


class ResearchTask(Schema):
    task_id: str = Field(default_factory=uid)
    company_id: str
    topic: str
    role: Literal["company", "financial", "business"]
    queries: list[str]
    segment_id: str | None = None
    required_data_ids: list[str] = Field(default_factory=list)
    linked_segments: list[str] = Field(default_factory=list)
    block_id: str | None = None
    question_ids: list[str] = Field(default_factory=list)
    material_scope: dict[str, Any] = Field(default_factory=dict)
    material_directions: list[dict[str, Any]] = Field(default_factory=list)


class ResearchPlan(Schema):
    company_id: str
    segments: list[str]
    tasks: list[ResearchTask]
    template_version: str = "1.0"
    blocks: list["ResearchBlock"] = Field(default_factory=list)
    collection_mode: Literal['legacy', 'fixed'] = 'legacy'
    data_template_version: str | None = None


class CalculationRequest(Schema):
    formula_id: str
    output_metric: str
    period: str
    unit: str
    segment_id: str | None = None
    inputs: dict[str, str] = Field(default_factory=dict)


class CalculationPlan(Schema):
    company_id: str
    calculations: list[CalculationRequest]
    forecast_model: Literal["volume_price", "capacity_utilization", "users_arpu", "market_share", "growth"]


class RequiredData(Schema):
    data_id: str = Field(default_factory=uid)
    metric_code: str
    company_id: str
    segment_id: str | None = None
    period: str
    unit: str
    priority: Literal["critical", "high", "normal"] = "high"
    formula_dependency: list[str]
    source_status: Literal["missing", "found", "conflict"] = "missing"


class SourceRecord(Schema):
    source_id: str = Field(default_factory=uid)
    kind: Literal["web", "local", "mock", "upload"]
    title: str
    source_url: str | None = None
    local_path: str | None = None
    publication_date: str | None = None
    retrieved_at: str = Field(default_factory=now)
    content: str
    locator: str = "全文"
    content_hash: str = ""
    attachment_id: str | None = None


class EvidenceRecord(Schema):
    evidence_id: str = Field(default_factory=uid)
    source_id: str
    claim: str
    quote: str
    locator: str
    actual_or_forecast: Literal["actual", "forecast", "context"] = "context"
    validation_status: Literal["verified", "unverified", "conflict"] = "unverified"


class FinancialFact(Schema):
    fact_id: str = Field(default_factory=uid)
    company_id: str
    segment_id: str | None = None
    metric_code: str
    period: str
    unit: str
    value: Decimal
    actual_or_forecast: Literal["actual", "forecast"]
    scope: Literal["consolidated", "parent", "segment"] = "consolidated"
    source_id: str
    evidence_id: str
    locator: str
    validation_status: Literal["verified", "unverified", "conflict"] = "unverified"
    currency: str = "CNY"
    accounting_basis: str = "reported"
    version: int = 1
    supersedes: str | None = None
    slot_id: str | None = None
    raw_value: str | None = None
    raw_unit: str | None = None
    locked_at: str | None = None
    value_origin: Literal['reported', 'derived'] = 'reported'
    derivation_id: str | None = None


class IndustryDatum(Schema):
    """A third-party or industry number (market size, capacity, price, share, forecast).
    value_text is the number with its unit exactly as the quote writes it; it is cited
    as [[ind:ID]] and rendered verbatim, never converted or used in calculations."""

    data_id: str
    source_id: str
    evidence_id: str
    subject: str
    metric: str
    period: str
    value_text: str
    actual_or_forecast: Literal["actual", "forecast"] = "actual"
    publisher: str = ""
    quote: str
    locator: str


class CalculationResult(Schema):
    result_id: str = Field(default_factory=uid)
    formula_id: str
    formula_version: str
    output_metric: str
    period: str
    unit: str
    inputs: dict[str, Decimal]
    input_refs: dict[str, str]
    value: Decimal
    scenario: str = "historical"
    segment_id: str | None = None


class ForecastAssumption(Schema):
    assumption_id: str = Field(default_factory=uid)
    metric_code: str
    period: str
    value: Decimal
    unit: str
    scenario: Literal["Bear", "Base", "Bull"]
    rationale: str
    evidence_ids: list[str]
    segment_id: str | None = None


class FinancialForecast(Schema):
    company_id: str
    period: str
    scenario: str
    income: dict[str, Decimal]
    balance: dict[str, Decimal]
    cashflow: dict[str, Decimal]
    result_ids: list[str]
    assumption_ids: list[str]
    segments: dict[str, dict[str, Decimal]]


class Table(Schema):
    title: str
    columns: list[str]
    rows: list[list[str]]


class SectionPart(Schema):
    """A subsection of a section's flat paragraph list: from paragraph `start` (0-based)
    up to the next part. Paragraph indexes used by review and repair stay unchanged."""

    topic: str
    heading: str = ""
    start: int = Field(ge=0)


class ReportSection(Schema):
    section_id: str
    title: str
    # Reader-facing viewpoint title written with the section; `title` stays the fixed
    # structural name that review and resume locate sections by.
    heading: str = ''
    paragraphs: list[str] = Field(default_factory=list)
    parts: list[SectionPart] = Field(default_factory=list)
    children: list["ReportSection"] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    number_bindings: dict[str, str] = Field(default_factory=dict)
    consistency_checks: dict[str, str] = Field(default_factory=dict)


TargetNode = Literal[
    "research_plan",
    "supervisor",
    "financial_analysis",
    "assumptions",
    "calculate",
    "write_sections",
    "core_conclusion",
    "assemble",
]
TARGET_NODES = set(TargetNode.__args__)
TARGET_ALIASES = {
    "core": "core_conclusion",
    "x01": "core_conclusion",
    "core_consistency": "core_conclusion",
    "assumption": "assumptions",
    "forecast": "assumptions",
}


class ReviewIssue(Schema):
    issue_id: str = Field(default_factory=uid)
    issue_type: Literal["structural", "financial", "evidence", "critical", "editorial"]
    severity: Literal["info", "warning", "error", "critical"]
    location: str
    description: str
    suggested_fix: str
    target_node: TargetNode
    snapshot_id: str = ""
    rule_id: str = ""
    block_id: str | None = None
    section_id: str | None = None
    # 1-based positions in the reviewed section's paragraphs; empty means the whole section.
    paragraphs: list[int] = Field(default_factory=list)
    requested_target: str = ""
    affected_refs: list[str] = Field(default_factory=list)
    validation_status: str = "open"

    @model_validator(mode="before")
    @classmethod
    def normalize_target(cls, data):
        # Reviewers sometimes put a location ("C01", "risk") in target_node; unknown
        # values would match no rework branch, so map them and keep the raw value.
        if isinstance(data, dict) and data.get("target_node") not in TARGET_NODES:
            raw = str(data.get("target_node") or "")
            data = data | {
                "target_node": TARGET_ALIASES.get(raw.strip().lower(), "write_sections"),
                "requested_target": data.get("requested_target") or raw,
            }
        return data


class ReportDocument(Schema):
    title: str
    company_id: str
    mode: str
    as_of: str = Field(default_factory=now)
    sections: list[ReportSection]
    sources: list[SourceRecord]
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    calculations: list[CalculationResult] = Field(default_factory=list)
    assumptions: list[ForecastAssumption] = Field(default_factory=list)
    forecasts: list[FinancialForecast] = Field(default_factory=list)
    financial_facts: list[FinancialFact] = Field(default_factory=list)
    industry_data: list[IndustryDatum] = Field(default_factory=list)
    issues: list[ReviewIssue] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    charts: list[dict[str, Any]] = Field(default_factory=list)
    rules_version: str = "1.0"
    data_template_version: str | None = None
    snapshot_id: str = ""
    approved_snapshot_id: str = ""
    brief: ResearchBrief | None = None
    blocks: list["ResearchBlock"] = Field(default_factory=list)
    coverage: list["CoverageEntry"] = Field(default_factory=list)
    comparisons: list["ComparisonResult"] = Field(default_factory=list)


class ResearchBlock(Schema):
    block_id: str
    template_id: str
    template_version: str = "1.1"
    company_id: str
    segment_id: str | None = None
    questions: dict[str, str]
    dependencies: list[str]
    call_budget: int = 20
    status: str = "pending"
    version: str = ""


class CoverageEntry(Schema):
    block_id: str
    question_id: str
    required: bool = True
    requirements: list[str] = Field(default_factory=list)
    status: Literal["pending", "collecting", "ready", "verified", "missing", "conflict"] = "pending"
    gaps: list[str] = Field(default_factory=list)
    task_id: str = ""
    verified_refs: list[str] = Field(default_factory=list)
    validation: str = ""


class ExtractionBatch(Schema):
    batch_id: str
    block_id: str
    question_ids: list[str]
    windows: list[dict[str, Any]]
    periods: list[str]
    company_id: str = ""
    segment_id: str | None = None
    scope_hint: str = "consolidated"
    metric_codes: list[str] = Field(default_factory=list)
    status: str = "pending"
    estimated_input_tokens: int = 0
    parent_id: str | None = None
    failure: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class ContextPackage(Schema):
    package_id: str
    purpose: str
    block_id: str
    snapshot_id: str
    selected_versions: dict[str, str]
    selection_reason: str
    content: dict[str, Any]
    estimated_tokens: int
    count_method: str = "utf8-byte-upper-bound estimate; not provider tokenization"


class BlockAnalysis(Schema):
    block_id: str
    version: str
    conclusions: list[str]
    evidence_ids: list[str]
    calculation_ids: list[str]
    counter_evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    status: str = "validated"


class ComparisonResult(Schema):
    comparison_id: str
    metric_code: str
    current_fact_id: str
    previous_fact_id: str
    current_period: str
    previous_period: str
    current_value: Decimal
    previous_value: Decimal
    unit: str
    scope: str
    currency: str
    accounting_basis: str
    comparison_type: str = "yoy"
    delta: Decimal
    rate: Decimal | None = None
    status: str
    calculation_ids: list[str]
    formula_version: str = "1.1"


ResearchPlan.model_rebuild()
ReportDocument.model_rebuild()
