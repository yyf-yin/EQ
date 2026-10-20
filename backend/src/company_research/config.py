from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CDR_", env_file=ROOT / ".env", extra="ignore")
    mode: Literal["mock", "real"] = "mock"
    data_collection_mode: Literal['fixed', 'legacy'] = 'fixed'
    database: Path = ROOT / "data/runs/research.sqlite"
    local_sources: Path = ROOT / "data/local_sources"
    artifacts: Path = ROOT / "data/runs/artifacts"
    models_config: Path = ROOT / "configs/models.yaml"
    # Blocked/preferred web domains for industry material searches.
    source_domains: Path = ROOT / "configs/source_domains.yaml"
    search_url: str = ""
    search_key: str = ""
    search_key_file: Path | None = None
    search_auth_header: str = "Authorization"
    search_provider: Literal["generic", "bocha"] = "generic"
    max_research_rounds: int = Field(default=3, ge=1, le=8)
    material_search_budget: int = Field(default=3, ge=0, le=6)
    material_document_budget: int = Field(default=8, ge=1, le=30)
    # Industry slots search each direction separately and read more reports.
    material_industry_search_budget: int = Field(default=10, ge=0, le=12)
    material_industry_document_budget: int = Field(default=16, ge=1, le=40)
    # Broker reports from Eastmoney (company and industry) are read first by industry slots,
    # within the industry document budget; a failure falls back to web search (real mode only).
    research_reports: bool = True
    research_report_limit: int = Field(default=4, ge=0, le=12)
    research_report_months: int = Field(default=15, ge=3, le=24)
    material_extra_direction_limit: int = Field(default=3, ge=0, le=5)
    material_policy_years: int = Field(default=3, ge=1, le=10)
    max_replans: int = Field(default=2, ge=0, le=4)
    max_conflict_checks: int = Field(default=2, ge=0, le=4)
    max_revisions: int = Field(default=2, ge=0, le=4)
    concurrency: int = Field(default=3, ge=1, le=8)
    max_active_runs: int = Field(default=2, ge=1, le=4)
    mock_delay: float = 0.15
    request_timeout: float = 45
    allow_limited: bool = True
    # Price, Shenwan peers and consensus EPS through AKShare for valuation (real mode only).
    market_data: bool = True
    # Industry slots read the industry sections of the company's and its largest Shenwan
    # peers' latest annual reports (and recent prospectuses) from CNINFO, within the
    # industry document budget, and compute sample CR3/CR5 from them (real mode only).
    peer_disclosures: bool = True
    peer_disclosure_peers: int = Field(default=6, ge=0, le=8)
    peer_disclosure_chars: int = Field(default=12000, ge=2000, le=40000)
    peer_prospectus_years: int = Field(default=5, ge=0, le=15)
    cors_origin: str = "http://localhost:5173"
    extraction_input_tokens: int = Field(default=16000, ge=2000)
    block_call_budget: int = Field(default=40, ge=1)
    global_call_budget: int = Field(default=240, ge=1)
    enforce_call_budgets: bool = False
    global_token_budget: int = Field(default=2000000, ge=1)
    max_batch_splits: int = Field(default=2, ge=0, le=4)
    plan_repairs: int = Field(default=2, ge=0, le=2)
    cache_ttl_hours: float = Field(default=6, ge=0)
    work_product_max_bytes: int = Field(default=50000000, ge=1024)
    reference_max_files: int = Field(default=50, ge=1, le=200)
    resume_package_max_bytes: int = Field(default=1024 * 1024 * 1024, ge=1024)

    def prepare(self) -> None:
        for path in (self.database.parent, self.local_sources, self.artifacts):
            path.mkdir(parents=True, exist_ok=True)

    def resolved_search_key(self) -> str:
        """Load an optional search credential without persisting it in run data."""
        if self.search_key:
            return self.search_key
        if not self.search_key_file:
            return ""
        path = self.search_key_file
        if not path.is_absolute():
            path = ROOT / path
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
