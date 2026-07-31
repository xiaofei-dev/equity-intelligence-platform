from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import GitSafeDecisionManifest, ModelTrack
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    ForwardV2AuditEventPayload,
    ForwardV2Enrollment,
    ForwardV2Preregistration,
    HorizonEvaluationRole,
    ResamplingPolicy,
    verify_enrollment,
    verify_preregistration,
)
from equity_analysis.historical_validation.protocol_v2 import (
    BenchmarkKind,
    LiquiditySensitiveCostPolicy,
)

FORWARD_V2_OUTCOME_VERSION = "FORWARD-DQV-OUTCOME-v2.0.0"
FORWARD_V2_OUTCOME_MANIFEST_VERSION = "FORWARD-DQV-OUTCOME-MANIFEST-v2.0.0"
FORWARD_V2_QUALITY_REPORT_VERSION = "FORWARD-DQV-QUALITY-REPORT-v2.0.0"
FORWARD_V2_OUTCOME_EVENT_TYPE = "FORWARD_V2_OUTCOME_BATCH_SEALED"
FORWARD_V2_QUALITY_EVENT_TYPE = "FORWARD_V2_MODEL_QUALITY_ASSESSED"
FORWARD_V2_AUDIT_EVENT_VERSION = "FORWARD-DQV-AUDIT-EVENT-v2.0.0"

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_OUTCOME_NAMESPACE = UUID("abfc4206-47f5-48e2-b66d-31ca1ea3641e")
_CONTROLLED_ROOT = PurePosixPath("storage/forward-validation/outcomes-v2")
_REQUIRED_BENCHMARKS = tuple(BenchmarkKind)
_FROZEN_COST_POLICY = LiquiditySensitiveCostPolicy(
    fixed_round_trip_bps=Decimal("2"),
    base_slippage_one_way_bps=Decimal("1"),
    impact_bps_at_full_participation=Decimal("25"),
    maximum_impact_one_way_bps=Decimal("50"),
)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )


class OutcomeObservationState(StrEnum):
    ASSESSED = "ASSESSED"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    EXCLUDED = "EXCLUDED"


class BenchmarkOutcomeState(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"


class OperationalCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"


class QualityTerminalStatus(StrEnum):
    NOT_MATURED = "NOT_MATURED"
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
    VALIDATED = "VALIDATED"
    MIXED = "MIXED"
    NOT_VALIDATED = "NOT_VALIDATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    BLOCKED_BY_DATA = "BLOCKED_BY_DATA"


class QualityTarget(StrEnum):
    TACTICAL_DECISION_QUALITY = "TACTICAL_DECISION_QUALITY"
    BUSINESS_QUALITY = "BUSINESS_QUALITY"
    SECURITY_ATTRACTIVENESS = "SECURITY_ATTRACTIVENESS"
    DOWNSIDE_RISK = "DOWNSIDE_RISK"


class BenchmarkOutcomeInput(ContractModel):
    kind: BenchmarkKind
    identifier: str = Field(min_length=1)
    state: BenchmarkOutcomeState
    gross_return: Decimal | None = None
    order_notional: Decimal | None = Field(default=None, gt=0)
    average_daily_dollar_volume: Decimal | None = Field(default=None, gt=0)
    price_action_evidence_hash: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    reason: str | None = None

    @model_validator(mode="after")
    def enforce_evidence(self) -> BenchmarkOutcomeInput:
        values = (
            self.gross_return,
            self.order_notional,
            self.average_daily_dollar_volume,
            self.price_action_evidence_hash,
        )
        if self.state == BenchmarkOutcomeState.AVAILABLE:
            if any(value is None for value in values):
                raise ValueError("Available benchmark outcomes require complete cost evidence")
            if self.reason is not None:
                raise ValueError("Available benchmark outcomes cannot carry a reason")
        else:
            if any(value is not None for value in values):
                raise ValueError("Unavailable benchmark outcomes cannot carry numeric evidence")
            if not self.reason:
                raise ValueError("Unavailable benchmark outcomes require a reason")
        return self


class SecurityOutcomeInput(ContractModel):
    public_security_id: UUID
    state: OutcomeObservationState
    gross_return: Decimal | None = None
    order_notional: Decimal | None = Field(default=None, gt=0)
    average_daily_dollar_volume: Decimal | None = Field(default=None, gt=0)
    price_action_evidence_hash: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_evidence(self) -> SecurityOutcomeInput:
        values = (
            self.gross_return,
            self.order_notional,
            self.average_daily_dollar_volume,
            self.price_action_evidence_hash,
        )
        if self.state == OutcomeObservationState.ASSESSED:
            if any(value is None for value in values):
                raise ValueError("ASSESSED outcomes require return, cost, and source evidence")
            if self.reason_codes:
                raise ValueError("ASSESSED outcomes cannot carry missing-data reasons")
        else:
            if any(value is not None for value in values):
                raise ValueError("Non-assessed outcomes cannot carry numeric evidence")
            if not self.reason_codes:
                raise ValueError("Non-assessed outcomes require explicit reason codes")
        return self


class BenchmarkOutcomeRecord(ContractModel):
    kind: BenchmarkKind
    identifier: str
    state: BenchmarkOutcomeState
    gross_return: Decimal | None = None
    round_trip_cost_rate: Decimal | None = None
    net_return: Decimal | None = None
    price_action_evidence_hash: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    reason: str | None = None


class SecurityOutcomeRecord(ContractModel):
    public_security_id: UUID
    state: OutcomeObservationState
    gross_return: Decimal | None = None
    round_trip_cost_rate: Decimal | None = None
    net_return: Decimal | None = None
    net_excess_returns: dict[str, Decimal] = Field(default_factory=dict)
    price_action_evidence_hash: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    reason_codes: tuple[str, ...] = ()
    record_hash: str = Field(pattern=_SHA256_PATTERN)


class ForwardOutcomeBatch(ContractModel):
    schema_version: Literal["FORWARD-DQV-OUTCOME-v2.0.0"]
    outcome_batch_id: UUID
    observed_at: datetime
    enrollment_content_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_controlled_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    completed_sessions: int
    evaluation_role: HorizonEvaluationRole
    entry_at_completed_session_open: datetime
    matured_at_completed_session: datetime
    benchmark_outcomes: tuple[BenchmarkOutcomeRecord, ...]
    security_outcomes: tuple[SecurityOutcomeRecord, ...]
    frozen_population_hash: str = Field(pattern=_SHA256_PATTERN)
    security_count: int = Field(ge=1)
    operational_completeness: OperationalCompleteness
    evidence_blockers: tuple[str, ...] = ()
    model_quality_status: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    decision_snapshot_mutated: Literal[False] = False
    ai_used_for_outcomes: Literal[False] = False
    outcome_batch_content_hash: str = Field(pattern=_SHA256_PATTERN)


class GitSafeOutcomeRow(ContractModel):
    public_security_id: UUID
    state: OutcomeObservationState
    price_action_evidence_hash: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    reason_codes: tuple[str, ...]
    controlled_record_hash: str = Field(pattern=_SHA256_PATTERN)


class GitSafeOutcomeManifest(ContractModel):
    schema_version: Literal["FORWARD-DQV-OUTCOME-MANIFEST-v2.0.0"]
    outcome_batch_id: UUID
    enrollment_content_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    completed_sessions: int
    evaluation_role: HorizonEvaluationRole
    observed_at: datetime
    controlled_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    controlled_artifact_reference: str
    frozen_population_hash: str = Field(pattern=_SHA256_PATTERN)
    security_count: int = Field(ge=1)
    terminal_counts: dict[str, int]
    benchmark_states: dict[str, BenchmarkOutcomeState]
    operational_completeness: OperationalCompleteness
    evidence_blockers: tuple[str, ...]
    rows: tuple[GitSafeOutcomeRow, ...]
    raw_provider_values_included: Literal[False] = False
    deterministic_numeric_results_included: Literal[False] = False
    ai_used_for_outcomes: Literal[False] = False
    manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)


@dataclass(frozen=True)
class OutcomeBatchBundle:
    batch: ForwardOutcomeBatch
    controlled_artifact_hash: str
    controlled_artifact_reference: str
    manifest: GitSafeOutcomeManifest


class ForwardTargetMetricEvidence(ContractModel):
    model_track: ModelTrack
    completed_sessions: int
    target: QualityTarget
    eligible_security_decisions: int = Field(ge=0)
    frozen_population_decisions: int = Field(ge=1)
    coverage_ratio: Decimal = Field(ge=0, le=1)
    completed_decision_sessions: int = Field(ge=0)
    outcome_dependence: Literal["PURGED_BLOCK"] = "PURGED_BLOCK"
    resampling: Literal["BLOCK_BOOTSTRAP"] = "BLOCK_BOOTSTRAP"
    bootstrap_block_sessions: int = Field(ge=1)
    benchmark_states: dict[BenchmarkKind, BenchmarkOutcomeState]
    discrimination_lower_confidence_bound: Decimal | None = None
    versus_benchmark_lower_confidence_bounds: dict[BenchmarkKind, Decimal] = Field(
        default_factory=dict
    )
    maximum_drawdown: Decimal | None = None
    benchmark_maximum_drawdown: Decimal | None = None
    downside_capture: Decimal | None = None
    future_fundamental_observations: int | None = Field(default=None, ge=0)
    outcome_batch_hashes: tuple[str, ...] = Field(min_length=1)
    decision_manifest_hashes: tuple[str, ...] = Field(min_length=1)
    matured_through: datetime
    all_outcomes_naturally_matured: Literal[True] = True
    metric_evidence_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_population_and_resampling(self) -> ForwardTargetMetricEvidence:
        expected_track = (
            ModelTrack.TACTICAL
            if self.target == QualityTarget.TACTICAL_DECISION_QUALITY
            else ModelTrack.LONG_HORIZON
        )
        if self.model_track != expected_track:
            raise ValueError("Quality target does not match its model track")
        if self.completed_sessions not in {5, 20, 60, 126, 252}:
            raise ValueError("Metric evidence horizon is not preregistered")
        if self.eligible_security_decisions > self.frozen_population_decisions:
            raise ValueError("Eligible decisions cannot exceed the frozen population")
        observed_coverage = (
            Decimal(self.eligible_security_decisions)
            / Decimal(self.frozen_population_decisions)
        )
        if abs(observed_coverage - self.coverage_ratio) > Decimal("0.000000000001"):
            raise ValueError("Coverage ratio does not match the frozen population counts")
        if self.resampling != ResamplingPolicy.BLOCK_BOOTSTRAP.value:
            raise ValueError("Formal Forward v2 evidence requires block bootstrap")
        for label, values in (
            ("Outcome batch", self.outcome_batch_hashes),
            ("Decision manifest", self.decision_manifest_hashes),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} hashes must be unique")
            if any(
                re.fullmatch(_SHA256_PATTERN, value) is None
                for value in values
            ):
                raise ValueError(f"{label} hashes must be canonical SHA-256 values")
        _aware(self.matured_through, "Metric evidence maturity cutoff")
        return self


class ForwardTargetQualityResult(ContractModel):
    target: QualityTarget
    status: QualityTerminalStatus
    reasons: tuple[str, ...]
    metric_evidence_hash: str = Field(pattern=_SHA256_PATTERN)


class ForwardQualityReport(ContractModel):
    schema_version: Literal["FORWARD-DQV-QUALITY-REPORT-v2.0.0"]
    model_track: ModelTrack
    model_version: str
    completed_sessions: int
    evaluation_role: HorizonEvaluationRole
    assessed_at: datetime
    preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)
    operational_completeness: OperationalCompleteness
    model_quality_status: QualityTerminalStatus
    target_results: tuple[ForwardTargetQualityResult, ...]
    source_outcome_batch_hashes: tuple[str, ...] = Field(min_length=1)
    source_decision_manifest_hashes: tuple[str, ...] = Field(min_length=1)
    matured_through: datetime
    ordinary_iid_bootstrap_used: Literal[False] = False
    ai_influence: Literal[False] = False
    report_content_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_chronology(self) -> ForwardQualityReport:
        if self.matured_through > self.assessed_at:
            raise ValueError("Quality assessment cannot precede its maturity cutoff")
        return self


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _hash_without(model: BaseModel, field: str) -> str:
    payload = model.model_dump(mode="json", by_alias=True)
    payload.pop(field)
    return canonical_hash(payload)


def _verify_decision_manifest(manifest: GitSafeDecisionManifest) -> None:
    if _hash_without(manifest, "manifestContentHash") != manifest.manifest_content_hash:
        raise ValueError("Decision manifest canonical hash is invalid")


def _cost_rate(order_notional: Decimal, average_daily_dollar_volume: Decimal) -> Decimal:
    return _FROZEN_COST_POLICY.round_trip_cost_rate(
        order_notional=order_notional,
        average_daily_dollar_volume=average_daily_dollar_volume,
    )


def _benchmark_record(value: BenchmarkOutcomeInput) -> BenchmarkOutcomeRecord:
    if value.state != BenchmarkOutcomeState.AVAILABLE:
        return BenchmarkOutcomeRecord(
            kind=value.kind,
            identifier=value.identifier,
            state=value.state,
            reason=value.reason,
        )
    assert value.gross_return is not None
    assert value.order_notional is not None
    assert value.average_daily_dollar_volume is not None
    cost = _cost_rate(value.order_notional, value.average_daily_dollar_volume)
    return BenchmarkOutcomeRecord(
        kind=value.kind,
        identifier=value.identifier,
        state=value.state,
        gross_return=value.gross_return,
        round_trip_cost_rate=cost,
        net_return=value.gross_return - cost,
        price_action_evidence_hash=value.price_action_evidence_hash,
    )


def _security_record(
    value: SecurityOutcomeInput,
    benchmarks: tuple[BenchmarkOutcomeRecord, ...],
) -> SecurityOutcomeRecord:
    body: dict[str, Any] = {
        "publicSecurityId": str(value.public_security_id),
        "state": value.state.value,
        "grossReturn": None,
        "roundTripCostRate": None,
        "netReturn": None,
        "netExcessReturns": {},
        "priceActionEvidenceHash": value.price_action_evidence_hash,
        "reasonCodes": value.reason_codes,
    }
    if value.state == OutcomeObservationState.ASSESSED:
        assert value.gross_return is not None
        assert value.order_notional is not None
        assert value.average_daily_dollar_volume is not None
        cost = _cost_rate(value.order_notional, value.average_daily_dollar_volume)
        net_return = value.gross_return - cost
        body["grossReturn"] = value.gross_return
        body["roundTripCostRate"] = cost
        body["netReturn"] = net_return
        body["netExcessReturns"] = {
            item.kind.value: net_return - item.net_return
            for item in benchmarks
            if item.state == BenchmarkOutcomeState.AVAILABLE
            and item.net_return is not None
        }
    return SecurityOutcomeRecord.model_validate(
        {**body, "recordHash": canonical_hash(body)}
    )


def build_outcome_batch(
    *,
    preregistration: ForwardV2Preregistration,
    enrollment: ForwardV2Enrollment,
    decision_manifest: GitSafeDecisionManifest,
    completed_sessions: int,
    observed_at: datetime,
    benchmark_inputs: tuple[BenchmarkOutcomeInput, ...],
    security_inputs: tuple[SecurityOutcomeInput, ...],
) -> OutcomeBatchBundle:
    verify_preregistration(preregistration)
    verify_enrollment(enrollment)
    _verify_decision_manifest(decision_manifest)
    observed_at = _aware(observed_at, "Outcome observation timestamp")
    if enrollment.preregistration_content_hash != preregistration.preregistration_content_hash:
        raise ValueError("Enrollment does not belong to this preregistration")
    if (
        enrollment.decision_manifest_content_hash
        != decision_manifest.manifest_content_hash
        or enrollment.decision_controlled_artifact_hash
        != decision_manifest.controlled_artifact_hash
    ):
        raise ValueError("Outcome cannot substitute or mutate the enrolled decision snapshot")
    policy = next(
        (
            item
            for item in preregistration.horizons
            if item.completed_sessions == completed_sessions
        ),
        None,
    )
    schedule = next(
        (
            item
            for item in enrollment.maturity_schedule
            if item.completed_sessions == completed_sessions
        ),
        None,
    )
    if policy is None or schedule is None:
        raise ValueError("Outcome horizon is not preregistered")
    if observed_at < schedule.matures_at_completed_session:
        raise ValueError("Only naturally matured completed-session outcomes may be observed")

    benchmark_kinds = tuple(item.kind for item in benchmark_inputs)
    if len(set(benchmark_kinds)) != len(benchmark_kinds):
        raise ValueError("Benchmark outcome kinds must be unique")
    if set(benchmark_kinds) != set(_REQUIRED_BENCHMARKS):
        raise ValueError("Outcome batch requires the complete frozen benchmark set")
    benchmarks = tuple(
        sorted(
            (_benchmark_record(item) for item in benchmark_inputs),
            key=lambda item: item.kind.value,
        )
    )

    expected_ids = {item.public_security_id for item in decision_manifest.decisions}
    input_ids = tuple(item.public_security_id for item in security_inputs)
    if len(set(input_ids)) != len(input_ids):
        raise ValueError("Outcome population contains duplicate security IDs")
    if set(input_ids) != expected_ids:
        raise ValueError("Every enrolled security requires one terminal outcome row")
    records = tuple(
        sorted(
            (_security_record(item, benchmarks) for item in security_inputs),
            key=lambda item: str(item.public_security_id),
        )
    )
    blockers = []
    if any(item.state != BenchmarkOutcomeState.AVAILABLE for item in benchmarks):
        blockers.append("REQUIRED_BENCHMARK_OUTCOME_UNAVAILABLE")
    if any(
        item.state
        in {
            OutcomeObservationState.MISSING,
            OutcomeObservationState.STALE,
            OutcomeObservationState.INVALID,
        }
        for item in records
    ):
        blockers.append("SECURITY_OUTCOME_EVIDENCE_INCOMPLETE")
    operational = OperationalCompleteness.COMPLETE
    batch_id = uuid5(
        _OUTCOME_NAMESPACE,
        f"{enrollment.enrollment_content_hash}:{completed_sessions}",
    )
    body: dict[str, Any] = {
        "schemaVersion": FORWARD_V2_OUTCOME_VERSION,
        "outcomeBatchId": str(batch_id),
        "observedAt": observed_at,
        "enrollmentContentHash": enrollment.enrollment_content_hash,
        "decisionManifestContentHash": decision_manifest.manifest_content_hash,
        "decisionControlledArtifactHash": decision_manifest.controlled_artifact_hash,
        "completedSessions": completed_sessions,
        "evaluationRole": policy.evaluation_role.value,
        "entryAtCompletedSessionOpen": enrollment.effective_at_completed_session_open,
        "maturedAtCompletedSession": schedule.matures_at_completed_session,
        "benchmarkOutcomes": tuple(
            item.model_dump(mode="json", by_alias=True) for item in benchmarks
        ),
        "securityOutcomes": tuple(
            item.model_dump(mode="json", by_alias=True) for item in records
        ),
        "frozenPopulationHash": enrollment.frozen_population_hash,
        "securityCount": enrollment.security_count,
        "operationalCompleteness": operational.value,
        "evidenceBlockers": tuple(blockers),
        "modelQualityStatus": "NOT_EVALUATED",
        "decisionSnapshotMutated": False,
        "aiUsedForOutcomes": False,
    }
    batch = ForwardOutcomeBatch.model_validate(
        {**body, "outcomeBatchContentHash": canonical_hash(body)}
    )
    controlled_reference = str(
        _CONTROLLED_ROOT
        / f"{batch.outcome_batch_content_hash.removeprefix('sha256:')}.json"
    )
    terminal_counts: dict[str, int] = {}
    for item in records:
        terminal_counts[item.state.value] = terminal_counts.get(item.state.value, 0) + 1
    rows = tuple(
        GitSafeOutcomeRow(
            public_security_id=item.public_security_id,
            state=item.state,
            price_action_evidence_hash=item.price_action_evidence_hash,
            reason_codes=item.reason_codes,
            controlled_record_hash=item.record_hash,
        )
        for item in records
    )
    manifest_body: dict[str, Any] = {
        "schemaVersion": FORWARD_V2_OUTCOME_MANIFEST_VERSION,
        "outcomeBatchId": str(batch_id),
        "enrollmentContentHash": enrollment.enrollment_content_hash,
        "decisionManifestContentHash": decision_manifest.manifest_content_hash,
        "completedSessions": completed_sessions,
        "evaluationRole": policy.evaluation_role.value,
        "observedAt": observed_at,
        "controlledArtifactHash": batch.outcome_batch_content_hash,
        "controlledArtifactReference": controlled_reference,
        "frozenPopulationHash": enrollment.frozen_population_hash,
        "securityCount": enrollment.security_count,
        "terminalCounts": dict(sorted(terminal_counts.items())),
        "benchmarkStates": {
            item.kind.value: item.state.value for item in benchmarks
        },
        "operationalCompleteness": operational.value,
        "evidenceBlockers": tuple(blockers),
        "rows": tuple(item.model_dump(mode="json", by_alias=True) for item in rows),
        "rawProviderValuesIncluded": False,
        "deterministicNumericResultsIncluded": False,
        "aiUsedForOutcomes": False,
    }
    manifest = GitSafeOutcomeManifest.model_validate(
        {**manifest_body, "manifestContentHash": canonical_hash(manifest_body)}
    )
    return OutcomeBatchBundle(
        batch=batch,
        controlled_artifact_hash=batch.outcome_batch_content_hash,
        controlled_artifact_reference=controlled_reference,
        manifest=manifest,
    )


def verify_outcome_bundle(bundle: OutcomeBatchBundle) -> None:
    if _hash_without(bundle.batch, "outcomeBatchContentHash") != (
        bundle.batch.outcome_batch_content_hash
    ):
        raise ValueError("Controlled outcome batch canonical hash is invalid")
    if _hash_without(bundle.manifest, "manifestContentHash") != (
        bundle.manifest.manifest_content_hash
    ):
        raise ValueError("Git-safe outcome manifest canonical hash is invalid")
    if bundle.controlled_artifact_hash != bundle.batch.outcome_batch_content_hash:
        raise ValueError("Outcome bundle controlled hash is inconsistent")


def verify_idempotent_outcome_replay(
    existing: OutcomeBatchBundle,
    candidate: OutcomeBatchBundle,
) -> None:
    verify_outcome_bundle(existing)
    verify_outcome_bundle(candidate)
    if existing.batch.outcome_batch_id != candidate.batch.outcome_batch_id:
        raise ValueError("Cannot compare different outcome batches")
    if existing.batch.outcome_batch_content_hash != candidate.batch.outcome_batch_content_hash:
        raise ValueError("Outcome batch identity is associated with different evidence")


def _target_status(
    evidence: ForwardTargetMetricEvidence,
    *,
    policy_minimum: int,
    policy_coverage: Decimal,
    horizon: int,
) -> ForwardTargetQualityResult:
    benchmark_states = evidence.benchmark_states
    if set(benchmark_states) != set(_REQUIRED_BENCHMARKS):
        return ForwardTargetQualityResult(
            target=evidence.target,
            status=QualityTerminalStatus.BLOCKED_BY_DATA,
            reasons=("COMPLETE_BENCHMARK_SET_REQUIRED",),
            metric_evidence_hash=evidence.metric_evidence_hash,
        )
    if any(value != BenchmarkOutcomeState.AVAILABLE for value in benchmark_states.values()):
        return ForwardTargetQualityResult(
            target=evidence.target,
            status=QualityTerminalStatus.BLOCKED_BY_DATA,
            reasons=("REQUIRED_BENCHMARK_EVIDENCE_UNAVAILABLE",),
            metric_evidence_hash=evidence.metric_evidence_hash,
        )
    if evidence.bootstrap_block_sessions < horizon:
        return ForwardTargetQualityResult(
            target=evidence.target,
            status=QualityTerminalStatus.BLOCKED_BY_DATA,
            reasons=("BOOTSTRAP_BLOCK_SHORTER_THAN_OUTCOME_HORIZON",),
            metric_evidence_hash=evidence.metric_evidence_hash,
        )
    if (
        evidence.eligible_security_decisions < policy_minimum
        or evidence.coverage_ratio < policy_coverage
        or evidence.completed_decision_sessions < horizon * 2
    ):
        return ForwardTargetQualityResult(
            target=evidence.target,
            status=QualityTerminalStatus.INSUFFICIENT_EVIDENCE,
            reasons=("NATURALLY_MATURED_SAMPLE_REQUIREMENT_NOT_MET",),
            metric_evidence_hash=evidence.metric_evidence_hash,
        )

    missing = []
    adverse = []
    if evidence.discrimination_lower_confidence_bound is None:
        missing.append("DISCRIMINATION_INTERVAL_REQUIRED")
    elif evidence.discrimination_lower_confidence_bound <= 0:
        adverse.append("DISCRIMINATION_LOWER_BOUND_NOT_POSITIVE")

    if evidence.target in {
        QualityTarget.TACTICAL_DECISION_QUALITY,
        QualityTarget.SECURITY_ATTRACTIVENESS,
    }:
        required = {
            BenchmarkKind.SPY,
            BenchmarkKind.SECTOR,
            BenchmarkKind.EQUAL_WEIGHT,
            BenchmarkKind.PURE_MOMENTUM,
        }
        if not required.issubset(evidence.versus_benchmark_lower_confidence_bounds):
            missing.append("REQUIRED_NET_BENCHMARK_INTERVALS_MISSING")
        elif any(
            evidence.versus_benchmark_lower_confidence_bounds[item] <= 0
            for item in required
        ):
            adverse.append("NET_BENCHMARK_LOWER_BOUND_NOT_POSITIVE")

    if evidence.target in {
        QualityTarget.TACTICAL_DECISION_QUALITY,
        QualityTarget.DOWNSIDE_RISK,
    }:
        if (
            evidence.maximum_drawdown is None
            or evidence.benchmark_maximum_drawdown is None
            or evidence.downside_capture is None
        ):
            missing.append("DOWNSIDE_AND_DRAWDOWN_METRICS_REQUIRED")
        else:
            if evidence.maximum_drawdown < evidence.benchmark_maximum_drawdown:
                adverse.append("MAXIMUM_DRAWDOWN_WORSE_THAN_BENCHMARK")
            if evidence.downside_capture > 1:
                adverse.append("DOWNSIDE_CAPTURE_EXCEEDS_ONE")

    if evidence.target == QualityTarget.BUSINESS_QUALITY:
        if not evidence.future_fundamental_observations:
            missing.append("FUTURE_FUNDAMENTAL_OBSERVATIONS_REQUIRED")

    status = (
        QualityTerminalStatus.INSUFFICIENT_EVIDENCE
        if missing
        else QualityTerminalStatus.NOT_VALIDATED
        if adverse
        else QualityTerminalStatus.VALIDATED
    )
    return ForwardTargetQualityResult(
        target=evidence.target,
        status=status,
        reasons=tuple(missing + adverse),
        metric_evidence_hash=evidence.metric_evidence_hash,
    )


def assess_forward_quality(
    *,
    preregistration: ForwardV2Preregistration,
    model_track: ModelTrack,
    model_version: str,
    completed_sessions: int,
    assessed_at: datetime,
    operational_completeness: OperationalCompleteness,
    target_evidence: tuple[ForwardTargetMetricEvidence, ...],
) -> ForwardQualityReport:
    verify_preregistration(preregistration)
    assessed_at = _aware(assessed_at, "Quality assessment timestamp")
    policy = next(
        (
            item
            for item in preregistration.horizons
            if item.completed_sessions == completed_sessions
        ),
        None,
    )
    if policy is None:
        raise ValueError("Quality assessment horizon is not preregistered")
    expected_track = (
        ModelTrack.TACTICAL if completed_sessions in {5, 20, 60} else ModelTrack.LONG_HORIZON
    )
    if model_track != expected_track:
        raise ValueError("Model track does not match the outcome horizon")
    freeze = next(item for item in preregistration.model_freezes if item.track == model_track)
    if model_version != freeze.model_version:
        raise ValueError("Quality assessment model version differs from its freeze")
    expected_targets = (
        {QualityTarget.TACTICAL_DECISION_QUALITY}
        if model_track == ModelTrack.TACTICAL
        else {
            QualityTarget.BUSINESS_QUALITY,
            QualityTarget.SECURITY_ATTRACTIVENESS,
            QualityTarget.DOWNSIDE_RISK,
        }
    )
    if {item.target for item in target_evidence} != expected_targets or len(
        target_evidence
    ) != len(expected_targets):
        raise ValueError("Quality assessment requires the complete target set")
    if any(
        item.model_track != model_track
        or item.completed_sessions != completed_sessions
        for item in target_evidence
    ):
        raise ValueError("Metric evidence track or horizon differs from the assessment")
    if any(item.matured_through > assessed_at for item in target_evidence):
        raise ValueError("Quality assessment cannot precede its source outcomes")

    if operational_completeness != OperationalCompleteness.COMPLETE:
        results = tuple(
            ForwardTargetQualityResult(
                target=item.target,
                status=QualityTerminalStatus.BLOCKED_BY_DATA,
                reasons=("OPERATIONAL_EVIDENCE_INCOMPLETE",),
                metric_evidence_hash=item.metric_evidence_hash,
            )
            for item in target_evidence
        )
        overall = QualityTerminalStatus.BLOCKED_BY_DATA
    elif not policy.formal_gate_eligible:
        results = tuple(
            ForwardTargetQualityResult(
                target=item.target,
                status=QualityTerminalStatus.DIAGNOSTIC_ONLY,
                reasons=("126_SESSION_LONG_HORIZON_OBSERVATION_IS_INTERIM_ONLY",),
                metric_evidence_hash=item.metric_evidence_hash,
            )
            for item in target_evidence
        )
        overall = QualityTerminalStatus.DIAGNOSTIC_ONLY
    else:
        results = tuple(
            _target_status(
                item,
                policy_minimum=policy.minimum_eligible_security_decisions,
                policy_coverage=Decimal(policy.minimum_coverage_ratio),
                horizon=completed_sessions,
            )
            for item in target_evidence
        )
        statuses = {item.status for item in results}
        if statuses == {QualityTerminalStatus.VALIDATED}:
            overall = QualityTerminalStatus.VALIDATED
        elif QualityTerminalStatus.BLOCKED_BY_DATA in statuses:
            overall = QualityTerminalStatus.BLOCKED_BY_DATA
        elif QualityTerminalStatus.INSUFFICIENT_EVIDENCE in statuses:
            overall = QualityTerminalStatus.INSUFFICIENT_EVIDENCE
        elif statuses == {QualityTerminalStatus.NOT_VALIDATED}:
            overall = QualityTerminalStatus.NOT_VALIDATED
        else:
            overall = QualityTerminalStatus.MIXED

    body: dict[str, Any] = {
        "schemaVersion": FORWARD_V2_QUALITY_REPORT_VERSION,
        "modelTrack": model_track.value,
        "modelVersion": model_version,
        "completedSessions": completed_sessions,
        "evaluationRole": policy.evaluation_role.value,
        "assessedAt": assessed_at,
        "preregistrationContentHash": preregistration.preregistration_content_hash,
        "operationalCompleteness": operational_completeness.value,
        "modelQualityStatus": overall.value,
        "targetResults": tuple(
            item.model_dump(mode="json", by_alias=True) for item in results
        ),
        "sourceOutcomeBatchHashes": tuple(
            sorted(
                {
                    value
                    for item in target_evidence
                    for value in item.outcome_batch_hashes
                }
            )
        ),
        "sourceDecisionManifestHashes": tuple(
            sorted(
                {
                    value
                    for item in target_evidence
                    for value in item.decision_manifest_hashes
                }
            )
        ),
        "maturedThrough": min(item.matured_through for item in target_evidence),
        "ordinaryIidBootstrapUsed": False,
        "aiInfluence": False,
    }
    return ForwardQualityReport.model_validate(
        {**body, "reportContentHash": canonical_hash(body)}
    )


def build_outcome_v16_audit_event_payload(
    bundle: OutcomeBatchBundle,
) -> ForwardV2AuditEventPayload:
    verify_outcome_bundle(bundle)
    detail: dict[str, Any] = {
        "contractVersion": FORWARD_V2_AUDIT_EVENT_VERSION,
        "outcomeBatchContentHash": bundle.batch.outcome_batch_content_hash,
        "manifestContentHash": bundle.manifest.manifest_content_hash,
        "enrollmentContentHash": bundle.batch.enrollment_content_hash,
        "decisionManifestContentHash": bundle.batch.decision_manifest_content_hash,
        "completedSessions": bundle.batch.completed_sessions,
        "evaluationRole": bundle.batch.evaluation_role,
        "securityCount": bundle.batch.security_count,
        "terminalCounts": bundle.manifest.terminal_counts,
        "benchmarkStates": bundle.manifest.benchmark_states,
        "operationalCompleteness": bundle.batch.operational_completeness,
        "modelQualityStatus": "NOT_EVALUATED",
        "decisionSnapshotMutated": False,
        "aiStatus": "NOT_EXECUTED",
        "databaseWriteExecuted": False,
        "providerNetworkRequests": 0,
    }
    return ForwardV2AuditEventPayload(
        event_type=FORWARD_V2_OUTCOME_EVENT_TYPE,
        entity_type="OUTCOME_BATCH",
        entity_id=str(bundle.batch.outcome_batch_id),
        occurred_at=bundle.batch.observed_at,
        correlation_id=str(bundle.batch.outcome_batch_id),
        event_hash=canonical_hash(detail),
        detail=detail,
    )


def build_quality_v16_audit_event_payload(
    report: ForwardQualityReport,
) -> ForwardV2AuditEventPayload:
    if _hash_without(report, "reportContentHash") != report.report_content_hash:
        raise ValueError("Forward quality report canonical hash is invalid")
    detail: dict[str, Any] = {
        "contractVersion": FORWARD_V2_AUDIT_EVENT_VERSION,
        "reportContentHash": report.report_content_hash,
        "preregistrationContentHash": report.preregistration_content_hash,
        "modelTrack": report.model_track,
        "modelVersion": report.model_version,
        "completedSessions": report.completed_sessions,
        "operationalCompleteness": report.operational_completeness,
        "modelQualityStatus": report.model_quality_status,
        "targetResults": [
            {
                "target": item.target,
                "status": item.status,
                "metricEvidenceHash": item.metric_evidence_hash,
            }
            for item in report.target_results
        ],
        "sourceOutcomeBatchHashes": report.source_outcome_batch_hashes,
        "sourceDecisionManifestHashes": report.source_decision_manifest_hashes,
        "maturedThrough": report.matured_through,
        "aiStatus": "NOT_EXECUTED",
        "databaseWriteExecuted": False,
        "providerNetworkRequests": 0,
    }
    return ForwardV2AuditEventPayload(
        event_type=FORWARD_V2_QUALITY_EVENT_TYPE,
        entity_type="MODEL_VALIDATION_REPORT",
        entity_id=report.report_content_hash.removeprefix("sha256:"),
        occurred_at=report.assessed_at,
        correlation_id=report.report_content_hash,
        event_hash=canonical_hash(detail),
        detail=detail,
    )


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_or_verify(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"Immutable artifact conflict: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def write_outcome_bundle(
    bundle: OutcomeBatchBundle,
    *,
    repository_root: Path,
    git_safe_manifest_path: Path,
) -> tuple[Path, Path]:
    verify_outcome_bundle(bundle)
    controlled_path = repository_root / Path(bundle.controlled_artifact_reference)
    _write_or_verify(
        controlled_path,
        _json_bytes(bundle.batch.model_dump(mode="json", by_alias=True)),
    )
    _write_or_verify(
        git_safe_manifest_path,
        _json_bytes(bundle.manifest.model_dump(mode="json", by_alias=True)),
    )
    return controlled_path, git_safe_manifest_path
