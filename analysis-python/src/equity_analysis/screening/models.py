from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class FactorStatus(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CoverageState(StrEnum):
    QUANT_ELIGIBLE = "QUANT_ELIGIBLE"
    QUANT_INELIGIBLE = "QUANT_INELIGIBLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STALE = "STALE"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"


class CompanyType(StrEnum):
    MATURE_OPERATING_COMPANY = "MATURE_OPERATING_COMPANY"
    FINANCIAL = "FINANCIAL"
    REIT = "REIT"
    RESOURCE = "RESOURCE"
    BIOTECHNOLOGY = "BIOTECHNOLOGY"
    EMERGING_GROWTH = "EMERGING_GROWTH"
    SPECIAL_SITUATION = "SPECIAL_SITUATION"
    BENCHMARK = "BENCHMARK"


class SizeCohort(StrEnum):
    SMALL = "SMALL"
    MID = "MID"
    LARGE = "LARGE"
    MEGA = "MEGA"


class CohortLevel(StrEnum):
    SECTOR_SIZE_COMPANY_TYPE = "SECTOR_SIZE_COMPANY_TYPE"
    SECTOR_COMPANY_TYPE = "SECTOR_COMPANY_TYPE"
    GENERAL_COMPANY = "GENERAL_COMPANY"


class Horizon(StrEnum):
    NEAR_TERM = "NEAR_TERM"
    MEDIUM_TERM = "MEDIUM_TERM"
    LONG_TERM = "LONG_TERM"


class AssessmentStatus(StrEnum):
    SCORED = "SCORED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_DEFINED = "NOT_DEFINED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ErrorCode(StrEnum):
    UNSUPPORTED_COMPANY_TYPE = "UNSUPPORTED_COMPANY_TYPE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STALE_DATA = "STALE_DATA"
    PIT_LINEAGE_FAILED = "PIT_LINEAGE_FAILED"
    INVALID_UNITS = "INVALID_UNITS"
    COHORT_TOO_SMALL = "COHORT_TOO_SMALL"
    STRATEGY_VERSION_UNSUPPORTED = "STRATEGY_VERSION_UNSUPPORTED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"


class RiskFlag(StrEnum):
    REVENUE_DECLINE = "REVENUE_DECLINE"
    MARGIN_DETERIORATION = "MARGIN_DETERIORATION"
    HIGH_LEVERAGE = "HIGH_LEVERAGE"
    LOW_INTEREST_COVERAGE = "LOW_INTEREST_COVERAGE"
    MATERIAL_DILUTION = "MATERIAL_DILUTION"
    GOING_CONCERN = "GOING_CONCERN"
    PROVIDER_MISMATCH = "PROVIDER_MISMATCH"


class DataLineage(ContractModel):
    provider: str
    source_reference: str
    period_end: date | None = None
    filed_at: datetime | None = None
    available_at: datetime
    ingested_at: datetime
    currency: str | None = None
    unit: str | None = None
    revision_status: str
    quality_status: str
    content_hash: str


class FactorInput(ContractModel):
    name: str
    value: Decimal | None
    status: FactorStatus
    reason: str | None = None
    lineage: tuple[DataLineage, ...] = ()


class SecurityObservation(ContractModel):
    security_id: str
    symbol: str
    as_of_time: datetime
    sector: str
    size_cohort: SizeCohort
    company_type: CompanyType
    factors: tuple[FactorInput, ...]
    risk_flags: tuple[RiskFlag, ...] = ()


class RatingRequest(ContractModel):
    as_of_time: datetime
    data_snapshot_id: str
    universe_version: str
    strategy_versions: tuple[str, ...]
    observations: tuple[SecurityObservation, ...] = Field(min_length=1)


class FactorResult(ContractModel):
    name: str
    status: FactorStatus
    raw_value: Decimal | None = None
    winsorized_value: Decimal | None = None
    normalized_score: Decimal | None = None
    cohort_level: CohortLevel | None = None
    cohort_size: int | None = None
    reason: str | None = None


class FactorContribution(ContractModel):
    factor_name: str
    normalized_score: Decimal
    weight: Decimal
    contribution: Decimal


class StrategyRating(ContractModel):
    strategy_version: str
    status: AssessmentStatus
    score: Decimal | None = None
    rank: int | None = None
    contributions: tuple[FactorContribution, ...] = ()
    missing_factors: tuple[str, ...] = ()
    error_code: ErrorCode | None = None


class HorizonAssessment(ContractModel):
    horizon: Horizon
    status: AssessmentStatus
    score: Decimal | None = None
    label: str
    strategy_ratings: tuple[StrategyRating, ...] = ()


class SecurityRating(ContractModel):
    security_id: str
    symbol: str
    as_of_time: datetime
    coverage_state: CoverageState
    company_type: CompanyType
    size_cohort: SizeCohort
    quality_score: Decimal | None = None
    valuation_score: Decimal | None = None
    factor_results: tuple[FactorResult, ...] = ()
    horizon_assessments: tuple[HorizonAssessment, ...]
    risk_flags: tuple[RiskFlag, ...] = ()
    missing_reasons: tuple[str, ...] = ()
    lineage: tuple[DataLineage, ...] = ()


class ScreeningRunRequest(ContractModel):
    as_of_time: datetime
    data_snapshot_id: str
    universe_version: str
    strategy_versions: tuple[str, ...] = Field(min_length=1)
    include_near_term_market_condition: bool = True


class ScreeningRunAccepted(ContractModel):
    run_id: str
    status: RunStatus
    submitted_at: datetime


class CoverageSummary(ContractModel):
    universe_count: int
    scored_count: int
    ineligible_count: int
    insufficient_data_count: int
    specialized_model_count: int


class ScreeningRunStatus(ContractModel):
    run_id: str
    status: RunStatus
    as_of_time: datetime
    data_snapshot_id: str
    universe_version: str
    strategy_versions: tuple[str, ...]
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    coverage: CoverageSummary | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None


class RatingPage(ContractModel):
    run_id: str
    items: tuple[SecurityRating, ...]
    next_cursor: str | None = None


class ContractError(ContractModel):
    code: str
    message: str
