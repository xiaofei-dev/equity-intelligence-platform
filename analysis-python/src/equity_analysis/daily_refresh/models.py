from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from equity_analysis.market_data.models import AdjustmentMode


class Dataset(StrEnum):
    DAILY_PRICE = "DAILY_PRICE"
    CORPORATE_ACTION = "CORPORATE_ACTION"


class FreshnessState(StrEnum):
    CURRENT = "CURRENT"
    LATE = "LATE"
    STALE = "STALE"
    MISSING = "MISSING"
    INACTIVE = "INACTIVE"
    FAILED = "FAILED"


class RefreshOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED_LOCKED = "SKIPPED_LOCKED"
    SKIPPED_BUDGET = "SKIPPED_BUDGET"


class WorkStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    LATE = "LATE"
    MISSING = "MISSING"
    FAILED = "FAILED"
    INACTIVE = "INACTIVE"


@dataclass(frozen=True)
class SecurityTarget:
    security_id: str
    symbol: str
    active: bool = True
    listing_end_date: date | None = None


@dataclass(frozen=True)
class DatasetCursor:
    security_id: str
    dataset: Dataset
    provider_code: str
    adjustment_mode: AdjustmentMode | None
    last_successful_update: datetime | None = None
    last_market_session_date: date | None = None
    last_as_of_date: date | None = None


@dataclass(frozen=True)
class RefreshPolicy:
    initial_lookback_sessions: int = 5
    overlap_sessions: int = 5
    late_grace_sessions: int = 1
    stale_after_sessions: int = 2
    max_attempts: int = 3
    base_backoff_seconds: float = 2.0
    eodhd_daily_budget: int = 100_000
    eodhd_reserve: int = 10_000
    full_refresh_limit: int = 1_000


@dataclass(frozen=True)
class WorkItem:
    security: SecurityTarget
    dataset: Dataset
    provider_code: str
    adjustment_mode: AdjustmentMode | None
    start_date: date
    end_date: date
    expected_session_date: date
    estimated_weighted_calls: int

    @property
    def key(self) -> str:
        mode = self.adjustment_mode.value if self.adjustment_mode else "NA"
        return (
            f"{self.security.security_id}:{self.dataset.value}:"
            f"{self.provider_code}:{mode}:{self.end_date.isoformat()}"
        )


@dataclass(frozen=True)
class RefreshPlan:
    as_of: datetime
    provider_code: str
    universe_version: str
    configuration_hash: str
    expected_session_date: date
    items: tuple[WorkItem, ...]
    estimated_weighted_calls: int
    available_weighted_calls: int | None
    skipped_inactive: int = 0


@dataclass(frozen=True)
class WorkResult:
    key: str
    status: WorkStatus
    attempts: int
    rows_written: int
    rows_rejected: int
    freshness_state: FreshnessState
    market_session_date: date | None
    as_of_date: date
    source_reference: str | None = None
    content_hash: str | None = None
    provider_schema_version: str | None = None
    parser_version: str | None = None
    normalization_version: str = "market-normalization-v1.0.0"
    provider_code: str = ""
    ingestion_batch_id: str | None = None
    effective_at: datetime | None = None
    available_at: datetime | None = None
    ingested_at: datetime | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class RunResult:
    run_id: str
    outcome: RefreshOutcome
    started_at: datetime
    completed_at: datetime
    planned_items: int
    completed_items: int
    failed_items: int
    late_or_missing_items: int
    weighted_calls_used: int
    results: tuple[WorkResult, ...] = field(default_factory=tuple)
