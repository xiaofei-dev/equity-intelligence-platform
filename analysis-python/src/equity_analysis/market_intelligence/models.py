from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class FactState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ProfileState(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INELIGIBLE = "INELIGIBLE"


class RankingState(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class Horizon(StrEnum):
    ONE_WEEK = "ONE_WEEK"
    ONE_MONTH = "ONE_MONTH"
    THREE_MONTHS = "THREE_MONTHS"
    TWELVE_MONTHS_PLUS = "TWELVE_MONTHS_PLUS"


class DeterministicViewState(StrEnum):
    ASSESSED = "ASSESSED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RankMetric(StrEnum):
    OBJECTIVE_QUALITY = "OBJECTIVE_QUALITY"
    OBJECTIVE_VALUATION = "OBJECTIVE_VALUATION"
    TACTICAL_ONE_WEEK = "TACTICAL_ONE_WEEK"
    TACTICAL_ONE_MONTH = "TACTICAL_ONE_MONTH"
    TACTICAL_THREE_MONTHS = "TACTICAL_THREE_MONTHS"
    LONG_HORIZON = "LONG_HORIZON"
    BUYING_OPPORTUNITY = "BUYING_OPPORTUNITY"


class SortDirection(StrEnum):
    ASCENDING = "ASCENDING"
    DESCENDING = "DESCENDING"


class EvidenceLineage(ContractModel):
    provider_code: str = Field(min_length=1)
    provider_schema_version: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    available_at: datetime
    retrieved_at: datetime
    effective_at: datetime | None = None


class ProfileFact(ContractModel):
    name: str = Field(min_length=1)
    metric_version: str = Field(min_length=1)
    state: FactState
    value: str | Decimal | int | bool | None = None
    reason: str | None = None
    lineage: tuple[EvidenceLineage, ...] = ()

    @model_validator(mode="after")
    def enforce_state_semantics(self) -> ProfileFact:
        if self.state == FactState.VALID and self.value is None:
            raise ValueError("VALID facts require a value")
        if self.state != FactState.VALID and self.value is not None:
            raise ValueError("Non-VALID facts cannot carry a value")
        if self.state != FactState.VALID and not self.reason:
            raise ValueError("Non-VALID facts require a reason")
        if self.state == FactState.VALID and not self.lineage:
            raise ValueError("VALID facts require lineage")
        return self


class SecurityMaster(ContractModel):
    security_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    issuer_name: str = Field(min_length=1)
    exchange_mic: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)
    instrument_type: str = Field(min_length=1)
    cik: str | None = None
    durable_provider_id: str | None = None


class Classification(ContractModel):
    taxonomy_code: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    sector_code: str = Field(min_length=1)
    sector_name: str = Field(min_length=1)
    industry_code: str = Field(min_length=1)
    industry_name: str = Field(min_length=1)
    company_type: str = Field(min_length=1)
    effective_at: datetime
    lineage: tuple[EvidenceLineage, ...] = Field(min_length=1)


class ComparableCohort(ContractModel):
    cohort_id: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    sector_code: str = Field(min_length=1)
    industry_code: str | None = None
    company_type: str = Field(min_length=1)
    size_band: str | None = None
    eligible_member_count: int = Field(ge=0)
    minimum_member_count: int = Field(ge=1)

    @property
    def is_sufficient(self) -> bool:
        return self.eligible_member_count >= self.minimum_member_count


class DeterministicView(ContractModel):
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    state: DeterministicViewState
    as_of: datetime
    effective_at: datetime
    expires_at: datetime | None = None
    score: Decimal | None = Field(default=None, ge=0, le=100)
    label: str = Field(min_length=1)
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    missing_inputs: tuple[str, ...] = ()
    explanation: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_score_state(self) -> DeterministicView:
        if self.state == DeterministicViewState.ASSESSED and self.score is None:
            raise ValueError("ASSESSED deterministic views require a score")
        if self.state != DeterministicViewState.ASSESSED and self.score is not None:
            raise ValueError("Unassessed deterministic views cannot carry a score")
        return self


class HorizonView(ContractModel):
    horizon: Horizon
    deterministic_view: DeterministicView


class ValuationEvidence(ContractModel):
    state: FactState
    as_of: datetime
    objective_valuation_score: Decimal | None = Field(default=None, ge=0, le=100)
    long_horizon_valuation_score: Decimal | None = Field(default=None, ge=0, le=100)
    own_history_percentile: Decimal | None = Field(default=None, ge=0, le=100)
    evidence: tuple[ProfileFact, ...] = ()
    limitations: tuple[str, ...] = ()


class AiNarrative(ContractModel):
    status: str
    narrative: str | None = None
    source_references: tuple[str, ...] = ()
    generated_at: datetime | None = None
    prompt_version: str | None = None
    model_version: str | None = None
    confidence: str | None = None
    may_affect_deterministic_fields: bool = False

    @model_validator(mode="after")
    def enforce_ai_boundary(self) -> AiNarrative:
        if self.may_affect_deterministic_fields:
            raise ValueError("AI narrative cannot affect deterministic fields")
        if self.narrative and not self.source_references:
            raise ValueError("AI narrative requires source references")
        if self.status == "AVAILABLE" and (
            not self.narrative
            or self.generated_at is None
            or not self.prompt_version
            or not self.model_version
            or not self.confidence
        ):
            raise ValueError(
                "AVAILABLE AI narrative requires cited generation and version metadata"
            )
        return self


class ProfileInput(ContractModel):
    security: SecurityMaster
    classification: Classification | None
    comparable_cohorts: tuple[ComparableCohort, ...] = ()
    facts: tuple[ProfileFact, ...]
    objective_quality_score: Decimal | None = Field(default=None, ge=0, le=100)
    objective_valuation_score: Decimal | None = Field(default=None, ge=0, le=100)
    objective_rating_status: str
    objective_rating_version: str = "Objective-Rating-v1"
    horizons: tuple[HorizonView, ...]
    valuation: ValuationEvidence
    ai_narrative: AiNarrative = AiNarrative(status="NOT_EXECUTED")


class SecurityProfile(ContractModel):
    contract_version: str
    security: SecurityMaster
    classification: Classification | None
    comparable_cohorts: tuple[ComparableCohort, ...]
    facts: tuple[ProfileFact, ...]
    objective_quality_score: Decimal | None
    objective_valuation_score: Decimal | None
    objective_rating_status: str
    objective_rating_version: str
    horizons: tuple[HorizonView, ...]
    valuation: ValuationEvidence
    profile_state: ProfileState
    ranking_state: RankingState
    ranking_exclusions: tuple[str, ...]
    explainability: tuple[str, ...]
    ai_narrative: AiNarrative


class ScreeningFilter(ContractModel):
    sectors: tuple[str, ...] = ()
    industries: tuple[str, ...] = ()
    company_types: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    horizons: tuple[Horizon, ...] = ()
    require_ranking_eligible: bool = True


class ScreeningRequest(ContractModel):
    as_of: datetime
    filters: ScreeningFilter = ScreeningFilter()
    rank_by: RankMetric
    direction: SortDirection = SortDirection.DESCENDING
    limit: int = Field(default=50, ge=1, le=500)


class RankedSecurity(ContractModel):
    rank: int
    security_id: str
    symbol: str
    sector_code: str
    industry_code: str
    metric: RankMetric
    value: Decimal
    profile: SecurityProfile


class ScreeningResult(ContractModel):
    contract_version: str
    as_of: datetime
    rank_by: RankMetric
    direction: SortDirection
    eligible_count: int
    excluded_count: int
    items: tuple[RankedSecurity, ...]
    exclusions: dict[str, tuple[str, ...]]
    acceptance: dict[str, Any]


class MarketIntelligenceErrorCode(StrEnum):
    PROFILE_NOT_FOUND = "MARKET_INTELLIGENCE_PROFILE_NOT_FOUND"
    RUN_NOT_FOUND = "MARKET_INTELLIGENCE_RUN_NOT_FOUND"
    SNAPSHOT_NOT_READY = "MARKET_INTELLIGENCE_SNAPSHOT_NOT_READY"
    UNIVERSE_MISMATCH = "MARKET_INTELLIGENCE_UNIVERSE_MISMATCH"
    IDEMPOTENCY_KEY_CONFLICT = "IDEMPOTENCY_KEY_CONFLICT"
    INVALID_REQUEST = "INVALID_MARKET_INTELLIGENCE_REQUEST"
    INVALID_CURSOR = "INVALID_CURSOR"


class SnapshotScreeningRequest(ScreeningRequest):
    model_config = ConfigDict(extra="forbid")

    data_snapshot_id: UUID
    universe_version: str = Field(min_length=1)


class CurrentMarketData(ContractModel):
    state: FactState
    price: Decimal | None = None
    currency: str
    trading_date: date | None = None
    provider_code: str | None = None
    available_at: datetime | None = None
    ingested_at: datetime | None = None
    adjustment_mode: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def enforce_market_data_state(self) -> CurrentMarketData:
        if self.state == FactState.VALID and (
            self.price is None
            or self.trading_date is None
            or not self.provider_code
            or self.available_at is None
            or self.ingested_at is None
        ):
            raise ValueError("VALID current market data requires complete provenance")
        if self.state != FactState.VALID and self.price is not None:
            raise ValueError("Non-VALID current market data cannot carry a price")
        if self.state != FactState.VALID and not self.reason:
            raise ValueError("Non-VALID current market data requires a reason")
        return self


class DatasetFreshness(ContractModel):
    dataset_code: str
    state: str
    provider_code: str | None = None
    effective_at: datetime | None = None
    available_at: datetime | None = None
    ingested_at: datetime | None = None
    evaluated_at: datetime
    stale_after: datetime | None = None
    reason_code: str | None = None


class MarketIntelligenceProfileEnvelope(ContractModel):
    profile_id: UUID
    security_id: str
    profile: SecurityProfile
    current_market_data: CurrentMarketData
    freshness: tuple[DatasetFreshness, ...]
    model_versions: dict[str, str]


class DurableProfileItem(MarketIntelligenceProfileEnvelope):
    pass


class ScreeningRunMetadata(ContractModel):
    run_id: UUID
    state: str = "SEALED"
    data_snapshot_id: UUID
    universe_version: str
    as_of: datetime
    rank_by: RankMetric
    direction: SortDirection
    eligible_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    gate_status: str
    profile_set_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sealed_at: datetime


class ScreeningResultPage(ContractModel):
    run: ScreeningRunMetadata
    items: tuple[DurableProfileItem, ...]
    next_cursor: str | None = None


class SecuritySearchItem(ContractModel):
    security_id: str
    symbol: str
    issuer_name: str
    exchange_mic: str
    membership_status: str
    company_type: str
    sector: str | None = None
    industry: str | None = None
    latest_profile_id: UUID | None = None
    current_market_data: CurrentMarketData
    freshness: tuple[DatasetFreshness, ...] = ()
    model_versions: dict[str, str] = Field(default_factory=dict)


class SecuritySearchPage(ContractModel):
    data_snapshot_id: UUID
    universe_version: str
    items: tuple[SecuritySearchItem, ...]
    next_cursor: str | None = None


class MarketIntelligenceFacets(ContractModel):
    data_snapshot_id: UUID
    universe_version: str
    sectors: tuple[str, ...]
    industries: tuple[str, ...]
    company_types: tuple[str, ...]
    membership_statuses: tuple[str, ...]
