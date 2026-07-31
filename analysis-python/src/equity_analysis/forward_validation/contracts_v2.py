from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from equity_analysis.research_rating.long_horizon_v11 import (
    LONG_HORIZON_V11_VERSION,
    AssessmentStatus,
    DimensionState,
    InputState,
    ResearchClassification,
)
from equity_analysis.tactical.contracts_v22 import (
    TACTICAL_FEATURE_V22_VERSION,
    TACTICAL_INPUT_V22_SCHEMA,
    TACTICAL_SIGNAL_V22_VERSION,
    Actionability,
    EventRiskLevel,
    EvidenceState,
    HorizonOutlook,
    SetupThesis,
    TacticalHorizon,
)

FORWARD_V2_DECISION_SNAPSHOT_VERSION = "FORWARD-DECISION-SNAPSHOT-v2.0.0"
FORWARD_V2_GIT_SAFE_MANIFEST_VERSION = "FORWARD-DECISION-MANIFEST-v2.0.0"
FORWARD_V2_AUDIT_EVENT_VERSION = "FORWARD-DECISION-AUDIT-EVENT-v2.0.0"
FORWARD_V2_DECISION_EVENT_TYPE = "FORWARD_V2_DAILY_DECISION_SNAPSHOT_SEALED"

SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )


class ModelTrack(StrEnum):
    TACTICAL = "TACTICAL"
    LONG_HORIZON = "LONG_HORIZON"


class FreezeStatus(StrEnum):
    INPUT_CONTRACT_ONLY = "INPUT_CONTRACT_ONLY"
    SEALED = "SEALED"


class PopulationTerminalState(StrEnum):
    ASSESSED = "ASSESSED"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"
    EXCLUDED = "EXCLUDED"


class BenchmarkAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"


class OutcomeDependence(StrEnum):
    NON_OVERLAPPING = "NON_OVERLAPPING"
    PURGED_BLOCK = "PURGED_BLOCK"


class ModelFreezeBinding(ContractModel):
    track: ModelTrack
    model_version: str = Field(min_length=1)
    status: FreezeStatus
    model_contract_hash: str = Field(pattern=SHA256_PATTERN)
    formulas_hash: str = Field(pattern=SHA256_PATTERN)
    weights_hash: str = Field(pattern=SHA256_PATTERN)
    input_schema_hash: str = Field(pattern=SHA256_PATTERN)
    applicability_hash: str = Field(pattern=SHA256_PATTERN)
    missing_data_policy_hash: str = Field(pattern=SHA256_PATTERN)
    benchmark_contract_hash: str = Field(pattern=SHA256_PATTERN)
    cost_model_hash: str = Field(pattern=SHA256_PATTERN)
    universe_contract_hash: str = Field(pattern=SHA256_PATTERN)
    validation_protocol_version: str = Field(min_length=1)
    source_artifact_hashes: tuple[str, ...] = Field(min_length=1)
    frozen_at: datetime | None = None
    observed_evidence_cutoff: datetime | None = None
    freeze_record_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    freeze_artifact_content_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    freeze_file_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_track_and_freeze(self) -> ModelFreezeBinding:
        expected = {
            ModelTrack.TACTICAL: TACTICAL_SIGNAL_V22_VERSION,
            ModelTrack.LONG_HORIZON: LONG_HORIZON_V11_VERSION,
        }[self.track]
        if self.model_version != expected:
            raise ValueError(f"{self.track.value} must bind {expected}")
        if any(
            re.fullmatch(SHA256_PATTERN, value) is None for value in self.source_artifact_hashes
        ):
            raise ValueError("Source artifact hashes must be canonical SHA-256 values")
        sealed_values = (
            self.frozen_at,
            self.observed_evidence_cutoff,
            self.freeze_record_hash,
            self.freeze_artifact_content_hash,
            self.freeze_file_sha256,
        )
        if self.status == FreezeStatus.SEALED and any(value is None for value in sealed_values):
            raise ValueError("SEALED model bindings require complete freeze evidence")
        if self.status == FreezeStatus.INPUT_CONTRACT_ONLY and any(
            value is not None for value in sealed_values
        ):
            raise ValueError("INPUT_CONTRACT_ONLY bindings cannot claim sealed freeze evidence")
        if self.status == FreezeStatus.SEALED:
            assert self.frozen_at is not None
            assert self.observed_evidence_cutoff is not None
            if self.frozen_at.tzinfo is None or self.observed_evidence_cutoff.tzinfo is None:
                raise ValueError("Freeze timestamps must be timezone-aware")
            if self.observed_evidence_cutoff >= self.frozen_at:
                raise ValueError("Observed evidence cutoff must precede the freeze")
        return self


class ReadyDataSnapshotBinding(ContractModel):
    data_snapshot_id: UUID
    state: Literal["READY"]
    as_of: datetime
    universe_version: str = Field(min_length=1)
    universe_hash: str = Field(pattern=SHA256_PATTERN)
    profile_set_hash: str = Field(pattern=SHA256_PATTERN)
    source_snapshot_hash: str = Field(pattern=SHA256_PATTERN)


class BenchmarkEvidenceBinding(ContractModel):
    benchmark_kind: str = Field(min_length=1)
    benchmark_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    availability: BenchmarkAvailability
    evidence_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    reason: str | None = None

    @model_validator(mode="after")
    def enforce_availability(self) -> BenchmarkEvidenceBinding:
        if self.availability == BenchmarkAvailability.AVAILABLE:
            if self.evidence_hash is None:
                raise ValueError("Available benchmark evidence requires a hash")
            if self.reason is not None:
                raise ValueError("Available benchmark evidence cannot carry a reason")
        elif not self.reason:
            raise ValueError("Unavailable benchmark evidence requires a reason")
        return self


class CostPolicyBinding(ContractModel):
    policy_version: str = Field(min_length=1)
    contract_hash: str = Field(pattern=SHA256_PATTERN)


class ValidationEvidenceEnvelope(ContractModel):
    availability: Literal["PROSPECTIVE_SEALED"] = "PROSPECTIVE_SEALED"
    universe: Literal["PROSPECTIVE_FROZEN_UNIVERSE"] = "PROSPECTIVE_FROZEN_UNIVERSE"
    price_and_actions: Literal["AS_OF_ACTION_LEDGER"] = "AS_OF_ACTION_LEDGER"
    evaluation_role: Literal["PROSPECTIVE_FORWARD"] = "PROSPECTIVE_FORWARD"
    outcome_dependence: OutcomeDependence


class TacticalComponentRecord(ContractModel):
    state: EvidenceState
    score: Decimal | None = Field(default=None, ge=0, le=100)
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_score_state(self) -> TacticalComponentRecord:
        if self.state == EvidenceState.VALID and self.score is None:
            raise ValueError("VALID tactical components require a score")
        if self.state != EvidenceState.VALID and self.score is not None:
            raise ValueError("Non-VALID tactical components cannot carry a score")
        return self


class TacticalHorizonRecord(ContractModel):
    horizon: TacticalHorizon
    trading_days: int
    selected_thesis: SetupThesis
    continuation_eligible: bool
    mean_reversion_eligible: bool
    continuation_score: Decimal | None = Field(default=None, ge=0, le=100)
    mean_reversion_score: Decimal | None = Field(default=None, ge=0, le=100)
    opportunity_score: Decimal | None = Field(default=None, ge=0, le=100)
    entry_value_score: Decimal | None = Field(default=None, ge=0, le=100)
    risk_score: Decimal | None = Field(default=None, ge=0, le=100)
    outlook: HorizonOutlook
    actionability: Actionability
    confidence: str = Field(min_length=1)
    maximum_risk_unit_multiplier: Decimal = Field(ge=0, le=1)
    missing_inputs: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_horizon(self) -> TacticalHorizonRecord:
        if self.trading_days != self.horizon.trading_days:
            raise ValueError("Tactical horizon and trading-day count disagree")
        return self


class TacticalDecisionRecord(ContractModel):
    model_version: Literal["TACTICAL-SIGNAL-v2.2.0"]
    input_schema_version: Literal["TACTICAL-INPUT-v2.2.0"]
    feature_version: Literal["TACTICAL-FEATURES-v2.2.0"]
    input_hash: str = Field(pattern=SHA256_PATTERN)
    decision_cutoff: datetime
    as_of_date: date
    effective_from: str = Field(min_length=1)
    signal_ttl_completed_sessions: int
    market_benchmark_id: str = Field(min_length=1)
    sector_benchmark_id: str | None = None
    components: dict[str, TacticalComponentRecord]
    event_risk_state: EvidenceState
    event_risk_level: EventRiskLevel | None = None
    horizons: tuple[TacticalHorizonRecord, ...]
    warnings: tuple[str, ...] = ()
    result_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_tactical_contract(self) -> TacticalDecisionRecord:
        if self.model_version != TACTICAL_SIGNAL_V22_VERSION:
            raise ValueError("Unexpected Tactical model version")
        if self.input_schema_version != TACTICAL_INPUT_V22_SCHEMA:
            raise ValueError("Unexpected Tactical input schema")
        if self.feature_version != TACTICAL_FEATURE_V22_VERSION:
            raise ValueError("Unexpected Tactical feature version")
        if self.signal_ttl_completed_sessions != 1:
            raise ValueError("Tactical v2.2 decisions must expire after one session")
        expected = set(TacticalHorizon)
        observed = {item.horizon for item in self.horizons}
        if observed != expected or len(self.horizons) != len(expected):
            raise ValueError("Tactical v2.2 requires exactly three unique horizons")
        expected_components = {
            "continuationQuality",
            "meanReversionPotential",
            "reboundReadiness",
            "fallingKnifeRisk",
            "chaseRisk",
            "volatilityRisk",
            "liquidity",
            "marketRegime",
            "sectorRegime",
            "marketRelativeStrength",
            "sectorRelativeStrength",
        }
        if set(self.components) != expected_components:
            raise ValueError("Tactical v2.2 requires its complete component set")
        return self


class LongFactorRecord(ContractModel):
    name: str = Field(min_length=1)
    state: InputState
    normalized_score: Decimal | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def enforce_score_state(self) -> LongFactorRecord:
        if self.state == InputState.VALID and self.normalized_score is None:
            raise ValueError("VALID Long Horizon factors require a score")
        if self.state != InputState.VALID and self.normalized_score is not None:
            raise ValueError("Non-VALID Long Horizon factors cannot carry a score")
        return self


class LongDimensionRecord(ContractModel):
    code: str = Field(min_length=1)
    state: DimensionState
    score: Decimal | None = Field(default=None, ge=0, le=100)
    factors: tuple[LongFactorRecord, ...] = ()
    missing_fields: tuple[str, ...] = ()
    invalid_fields: tuple[str, ...] = ()
    not_applicable_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_score_state(self) -> LongDimensionRecord:
        if self.state == DimensionState.VALID and self.score is None:
            raise ValueError("VALID Long Horizon dimensions require a score")
        if self.state != DimensionState.VALID and self.score is not None:
            raise ValueError("Non-VALID Long Horizon dimensions cannot carry a score")
        return self


class ExpectedReturnRangeRecord(ContractModel):
    state: DimensionState
    low: Decimal | None = None
    base: Decimal | None = None
    high: Decimal | None = None
    component_names: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    invalid_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_range(self) -> ExpectedReturnRangeRecord:
        values = (self.low, self.base, self.high)
        if self.state == DimensionState.VALID and any(value is None for value in values):
            raise ValueError("VALID expected-return evidence requires a complete range")
        if self.state != DimensionState.VALID and any(value is not None for value in values):
            raise ValueError("Non-VALID expected-return evidence cannot carry a range")
        if all(value is not None for value in values) and not (
            self.low <= self.base <= self.high  # type: ignore[operator]
        ):
            raise ValueError("Expected-return range must satisfy low <= base <= high")
        return self


class SectorRelativeRecord(ContractModel):
    state: DimensionState
    score: Decimal | None = Field(default=None, ge=0, le=100)
    quality_percentile_score: Decimal | None = Field(default=None, ge=0, le=100)
    valuation_attractiveness_percentile_score: Decimal | None = Field(default=None, ge=0, le=100)
    cohort_member_count: int | None = Field(default=None, ge=0)
    cohort_minimum_count: int = Field(ge=1)
    missing_fields: tuple[str, ...] = ()
    invalid_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_score_state(self) -> SectorRelativeRecord:
        scores = (
            self.score,
            self.quality_percentile_score,
            self.valuation_attractiveness_percentile_score,
        )
        if self.state == DimensionState.VALID and any(value is None for value in scores):
            raise ValueError("VALID sector-relative evidence requires all scores")
        if self.state != DimensionState.VALID and any(value is not None for value in scores):
            raise ValueError("Non-VALID sector-relative evidence cannot carry scores")
        return self


class LongHorizonDecisionRecord(ContractModel):
    model_version: Literal["LONG-HORIZON-RESEARCH-v1.1.0"]
    status: AssessmentStatus
    classification: ResearchClassification
    business_quality: LongDimensionRecord
    financial_strength: LongDimensionRecord
    capital_allocation: LongDimensionRecord
    valuation_entry: LongDimensionRecord
    expected_return: ExpectedReturnRangeRecord
    downside_risk: LongDimensionRecord
    sector_relative: SectorRelativeRecord
    evidence_confidence: LongDimensionRecord
    default_ranking_score: None = None
    deterministic_ranking_authorized: Literal[False] = False
    missing_fields: tuple[str, ...] = ()
    invalid_fields: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    input_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hash: str = Field(pattern=SHA256_PATTERN)
    result_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_long_horizon_contract(self) -> LongHorizonDecisionRecord:
        if self.model_version != LONG_HORIZON_V11_VERSION:
            raise ValueError("Unexpected Long Horizon model version")
        if self.default_ranking_score is not None:
            raise ValueError("Long Horizon v1.1 has no default ranking score")
        if self.deterministic_ranking_authorized:
            raise ValueError("Long Horizon v1.1 does not authorize default ranking")
        return self


class SecurityDecisionRecord(ContractModel):
    public_security_id: UUID
    profile_id: UUID
    symbol: str = Field(min_length=1)
    tactical_state: PopulationTerminalState
    long_horizon_state: PopulationTerminalState
    tactical: TacticalDecisionRecord
    long_horizon: LongHorizonDecisionRecord
    exclusion_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_terminal_states(self) -> SecurityDecisionRecord:
        if self.tactical_state == PopulationTerminalState.ASSESSED and all(
            item.outlook == HorizonOutlook.INSUFFICIENT_DATA for item in self.tactical.horizons
        ):
            raise ValueError("ASSESSED Tactical terminal state requires an assessment")
        if (
            self.long_horizon_state == PopulationTerminalState.ASSESSED
            and self.long_horizon.status != AssessmentStatus.ASSESSED
        ):
            raise ValueError("ASSESSED Long Horizon terminal state requires an assessment")
        return self


class ForwardDecisionSnapshot(ContractModel):
    contract_version: Literal["FORWARD-DECISION-SNAPSHOT-v2.0.0"]
    idempotency_key: str = Field(min_length=1, max_length=255)
    sealed_at: datetime
    data_snapshot: ReadyDataSnapshotBinding
    model_freezes: tuple[ModelFreezeBinding, ...]
    benchmark_evidence: tuple[BenchmarkEvidenceBinding, ...]
    cost_policy: CostPolicyBinding
    evidence_envelope: ValidationEvidenceEnvelope
    frozen_security_ids: tuple[UUID, ...] = Field(min_length=1)
    frozen_population_hash: str = Field(pattern=SHA256_PATTERN)
    decisions: tuple[SecurityDecisionRecord, ...]
    prospective_ready: bool
    blocked_reasons: tuple[str, ...] = ()
    ai_used_for_deterministic_decisions: Literal[False] = False
    provider_network_requests: Literal[0] = 0

    @model_validator(mode="after")
    def enforce_complete_snapshot(self) -> ForwardDecisionSnapshot:
        if self.contract_version != FORWARD_V2_DECISION_SNAPSHOT_VERSION:
            raise ValueError("Unexpected Forward decision snapshot contract")
        tracks = tuple(item.track for item in self.model_freezes)
        if len(tracks) != 2 or set(tracks) != set(ModelTrack):
            raise ValueError("Snapshot requires exactly one freeze binding per model track")
        if len(set(self.frozen_security_ids)) != len(self.frozen_security_ids):
            raise ValueError("Frozen population contains duplicate security IDs")
        decision_ids = tuple(item.public_security_id for item in self.decisions)
        if len(set(decision_ids)) != len(decision_ids):
            raise ValueError("Decision population contains duplicate security IDs")
        if set(decision_ids) != set(self.frozen_security_ids):
            raise ValueError("Every frozen security requires exactly one terminal row")
        profile_ids = tuple(item.profile_id for item in self.decisions)
        if len(set(profile_ids)) != len(profile_ids):
            raise ValueError("Decision population contains duplicate profile IDs")
        if self.prospective_ready and self.blocked_reasons:
            raise ValueError("Prospective-ready snapshots cannot carry blockers")
        if self.prospective_ready and any(
            item.status != FreezeStatus.SEALED for item in self.model_freezes
        ):
            raise ValueError("Prospective readiness requires sealed model freezes")
        return self


class GitSafeDecisionRow(ContractModel):
    public_security_id: UUID
    profile_id: UUID
    symbol: str
    tactical_state: PopulationTerminalState
    long_horizon_state: PopulationTerminalState
    tactical_input_hash: str = Field(pattern=SHA256_PATTERN)
    tactical_result_hash: str = Field(pattern=SHA256_PATTERN)
    long_horizon_input_hash: str = Field(pattern=SHA256_PATTERN)
    long_horizon_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    long_horizon_result_hash: str = Field(pattern=SHA256_PATTERN)
    exclusion_reasons: tuple[str, ...] = ()


class GitSafeDecisionManifest(ContractModel):
    schema_version: Literal["FORWARD-DECISION-MANIFEST-v2.0.0"]
    idempotency_key: str
    idempotency_hash: str = Field(pattern=SHA256_PATTERN)
    data_snapshot_id: UUID
    decision_as_of: datetime
    universe_version: str
    universe_hash: str = Field(pattern=SHA256_PATTERN)
    profile_set_hash: str = Field(pattern=SHA256_PATTERN)
    frozen_population_hash: str = Field(pattern=SHA256_PATTERN)
    model_freeze_hashes: dict[str, str]
    controlled_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    controlled_artifact_reference: str = Field(min_length=1)
    prospective_ready: bool
    blocked_reasons: tuple[str, ...]
    security_count: int = Field(ge=1)
    terminal_counts: dict[str, int]
    decisions: tuple[GitSafeDecisionRow, ...]
    raw_provider_values_included: Literal[False] = False
    deterministic_numeric_results_included: Literal[False] = False
    ai_used_for_deterministic_decisions: Literal[False] = False
    manifest_content_hash: str = Field(pattern=SHA256_PATTERN)


class AuditEventPayload(ContractModel):
    event_type: Literal["FORWARD_V2_DAILY_DECISION_SNAPSHOT_SEALED"]
    entity_type: Literal["DATA_SNAPSHOT"]
    entity_id: str
    actor_service: Literal["PYTHON_ANALYTICS"] = "PYTHON_ANALYTICS"
    occurred_at: datetime
    correlation_id: str
    event_hash: str = Field(pattern=SHA256_PATTERN)
    detail: dict[str, Any]
