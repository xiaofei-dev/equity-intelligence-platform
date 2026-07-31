from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import ModelTrack
from equity_analysis.forward_validation.outcomes_v2 import (
    BenchmarkOutcomeState,
    OperationalCompleteness,
    OutcomeObservationState,
    QualityTarget,
    QualityTerminalStatus,
)
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    HorizonEvaluationRole,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

FORWARD_DQV_ENROLLMENT_V21 = "FORWARD-DQV-ENROLLMENT-v2.1.0"
FORWARD_DQV_OUTCOME_V21 = "FORWARD-DQV-OUTCOME-v2.1.0"
FORWARD_DQV_QUALITY_REPORT_V21 = "FORWARD-DQV-QUALITY-REPORT-v2.1.0"

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_HORIZONS = (5, 20, 60, 126, 252)
_BENCHMARKS = tuple(BenchmarkKind)
_RETURN_TOLERANCE = Decimal("0.000000000001")


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )


class PathMetricCode(StrEnum):
    MAXIMUM_ADVERSE_EXCURSION = "MAXIMUM_ADVERSE_EXCURSION"
    MAXIMUM_FAVORABLE_EXCURSION = "MAXIMUM_FAVORABLE_EXCURSION"
    MAXIMUM_DRAWDOWN = "MAXIMUM_DRAWDOWN"
    DOWNSIDE_CAPTURE = "DOWNSIDE_CAPTURE"
    BENCHMARK_MAXIMUM_DRAWDOWN = "BENCHMARK_MAXIMUM_DRAWDOWN"


class PathMetricState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PathMetricSubjectType(StrEnum):
    SECURITY = "SECURITY"
    BENCHMARK = "BENCHMARK"
    AGGREGATE = "AGGREGATE"


class MaturityScheduleV21(ContractModel):
    completed_sessions: int
    evaluation_role: HorizonEvaluationRole
    formal_gate_eligible: bool
    matures_at_completed_session: datetime
    schedule_content_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_horizon(self) -> MaturityScheduleV21:
        expected = {
            5: (HorizonEvaluationRole.TACTICAL_FORMAL, True),
            20: (HorizonEvaluationRole.TACTICAL_FORMAL, True),
            60: (HorizonEvaluationRole.TACTICAL_FORMAL, True),
            126: (HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC, False),
            252: (HorizonEvaluationRole.LONG_HORIZON_FORMAL, True),
        }.get(self.completed_sessions)
        if expected is None or (
            self.evaluation_role,
            self.formal_gate_eligible,
        ) != expected:
            raise ValueError("Maturity schedule does not match the frozen horizon policy")
        _aware(self.matures_at_completed_session, "Maturity timestamp")
        return self


class ForwardDqvEnrollmentV21(ContractModel):
    schema_version: Literal["FORWARD-DQV-ENROLLMENT-v2.1.0"]
    enrollment_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    canonical_request_hash: str = Field(pattern=_SHA256_PATTERN)
    preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_controlled_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_controlled_artifact_reference: str = Field(min_length=1)
    decision_data_snapshot_id: UUID
    decision_as_of: datetime
    effective_at_completed_session_open: datetime
    universe_version: str = Field(min_length=1)
    frozen_population_hash: str = Field(pattern=_SHA256_PATTERN)
    model_freeze_hashes: dict[str, str]
    benchmark_contract_version: str = Field(min_length=1)
    benchmark_contract_hash: str = Field(pattern=_SHA256_PATTERN)
    cost_policy_version: str = Field(min_length=1)
    cost_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    security_count: int = Field(ge=1)
    terminal_counts: dict[str, int]
    maturity_schedule: tuple[MaturityScheduleV21, ...]
    sealed_at: datetime
    enrollment_content_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_enrollment(self) -> ForwardDqvEnrollmentV21:
        _aware(self.decision_as_of, "Decision timestamp")
        _aware(self.effective_at_completed_session_open, "Entry timestamp")
        _aware(self.sealed_at, "Seal timestamp")
        if not (
            self.decision_as_of
            <= self.effective_at_completed_session_open
            <= self.sealed_at
        ):
            raise ValueError("Enrollment chronology is invalid")
        sessions = tuple(item.completed_sessions for item in self.maturity_schedule)
        if sessions != _HORIZONS:
            raise ValueError("Enrollment requires ordered 5/20/60/126/252 maturities")
        if len({item.matures_at_completed_session for item in self.maturity_schedule}) != 5:
            raise ValueError("Maturity timestamps must be unique")
        if tuple(
            sorted(item.matures_at_completed_session for item in self.maturity_schedule)
        ) != tuple(item.matures_at_completed_session for item in self.maturity_schedule):
            raise ValueError("Maturity timestamps must be chronological")
        if any(
            item.matures_at_completed_session <= self.effective_at_completed_session_open
            for item in self.maturity_schedule
        ):
            raise ValueError("Every maturity must follow the prospective entry")
        if (
            not self.model_freeze_hashes
            or any(not value.startswith("sha256:") for value in self.model_freeze_hashes.values())
        ):
            raise ValueError("Model freeze hashes are required")
        if not self.terminal_counts or any(value < 0 for value in self.terminal_counts.values()):
            raise ValueError("Terminal counts must be explicit non-negative counts")
        if sum(self.terminal_counts.values()) != self.security_count:
            raise ValueError("Terminal counts must equal the frozen population")
        return self


class SecurityOutcomeV21(ContractModel):
    public_security_id: UUID
    state: OutcomeObservationState
    gross_return: Decimal | None = None
    round_trip_cost_rate: Decimal | None = None
    net_return: Decimal | None = None
    price_action_evidence_hash: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    source_manifest_hash: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    reason_codes: tuple[str, ...] = ()
    record_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_terminal_state(self) -> SecurityOutcomeV21:
        _enforce_return_state(
            available=self.state == OutcomeObservationState.ASSESSED,
            gross=self.gross_return,
            cost=self.round_trip_cost_rate,
            net=self.net_return,
            price_hash=self.price_action_evidence_hash,
            source_hash=self.source_manifest_hash,
            reasons=self.reason_codes,
            label="Security",
        )
        return self


class BenchmarkOutcomeV21(ContractModel):
    kind: BenchmarkKind
    identifier: str = Field(min_length=1)
    state: BenchmarkOutcomeState
    gross_return: Decimal | None = None
    round_trip_cost_rate: Decimal | None = None
    net_return: Decimal | None = None
    price_action_evidence_hash: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    source_manifest_hash: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    reason_codes: tuple[str, ...] = ()
    record_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_terminal_state(self) -> BenchmarkOutcomeV21:
        _enforce_return_state(
            available=self.state == BenchmarkOutcomeState.AVAILABLE,
            gross=self.gross_return,
            cost=self.round_trip_cost_rate,
            net=self.net_return,
            price_hash=self.price_action_evidence_hash,
            source_hash=self.source_manifest_hash,
            reasons=self.reason_codes,
            label="Benchmark",
        )
        return self


class PathMetricV21(ContractModel):
    subject_type: PathMetricSubjectType
    public_security_id: UUID | None = None
    benchmark_kind: BenchmarkKind | None = None
    metric_code: PathMetricCode
    state: PathMetricState
    metric_value: Decimal | None = None
    source_evidence_hash: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    reason_codes: tuple[str, ...] = ()
    metric_record_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_metric(self) -> PathMetricV21:
        if self.subject_type == PathMetricSubjectType.SECURITY:
            if self.public_security_id is None or self.benchmark_kind is not None:
                raise ValueError("Security path metrics require exactly one security")
        elif self.subject_type == PathMetricSubjectType.BENCHMARK:
            if self.public_security_id is not None or self.benchmark_kind is None:
                raise ValueError("Benchmark path metrics require exactly one benchmark")
        elif self.public_security_id is not None or self.benchmark_kind is not None:
            raise ValueError("Aggregate path metrics cannot carry a subject identity")
        if self.state == PathMetricState.VALID:
            if self.metric_value is None or self.source_evidence_hash is None:
                raise ValueError("Valid path metrics require value and source evidence")
            if self.reason_codes:
                raise ValueError("Valid path metrics cannot carry missing-data reasons")
            if self.metric_code in {
                PathMetricCode.MAXIMUM_ADVERSE_EXCURSION,
                PathMetricCode.MAXIMUM_DRAWDOWN,
                PathMetricCode.BENCHMARK_MAXIMUM_DRAWDOWN,
            } and not Decimal("-1") <= self.metric_value <= Decimal("0"):
                raise ValueError("Adverse path metrics must be between -1 and 0")
            if (
                self.metric_code == PathMetricCode.MAXIMUM_FAVORABLE_EXCURSION
                and self.metric_value < 0
            ):
                raise ValueError("Maximum favorable excursion cannot be negative")
            if (
                self.metric_code == PathMetricCode.DOWNSIDE_CAPTURE
                and self.metric_value < 0
            ):
                raise ValueError("Downside capture cannot be negative")
        else:
            if self.metric_value is not None or self.source_evidence_hash is not None:
                raise ValueError("Non-valid path metrics cannot carry numeric evidence")
            if not self.reason_codes:
                raise ValueError("Non-valid path metrics require explicit reasons")
        return self


class ForwardOutcomeBatchV21(ContractModel):
    schema_version: Literal["FORWARD-DQV-OUTCOME-v2.1.0"]
    outcome_batch_id: UUID
    enrollment_id: UUID
    completed_sessions: int
    evaluation_role: HorizonEvaluationRole
    result_version: int = Field(ge=1)
    supersedes_batch_id: UUID | None = None
    observed_at: datetime
    matured_at_completed_session: datetime
    operational_completeness: OperationalCompleteness
    security_count: int = Field(ge=1)
    terminal_counts: dict[str, int]
    preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    frozen_population_hash: str = Field(pattern=_SHA256_PATTERN)
    model_freeze_hashes: dict[str, str]
    benchmark_contract_hash: str = Field(pattern=_SHA256_PATTERN)
    cost_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    source_manifest_hash: str = Field(pattern=_SHA256_PATTERN)
    calendar_evidence_hash: str = Field(pattern=_SHA256_PATTERN)
    action_evidence_hash: str = Field(pattern=_SHA256_PATTERN)
    price_evidence_hash: str = Field(pattern=_SHA256_PATTERN)
    evidence_blockers: tuple[str, ...] = ()
    security_outcomes: tuple[SecurityOutcomeV21, ...]
    benchmark_outcomes: tuple[BenchmarkOutcomeV21, ...]
    path_metrics: tuple[PathMetricV21, ...]
    outcome_batch_content_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_batch(self) -> ForwardOutcomeBatchV21:
        expected_role = {
            5: HorizonEvaluationRole.TACTICAL_FORMAL,
            20: HorizonEvaluationRole.TACTICAL_FORMAL,
            60: HorizonEvaluationRole.TACTICAL_FORMAL,
            126: HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC,
            252: HorizonEvaluationRole.LONG_HORIZON_FORMAL,
        }.get(self.completed_sessions)
        if self.evaluation_role != expected_role:
            raise ValueError("Outcome horizon and evaluation role differ")
        _aware(self.observed_at, "Outcome observation timestamp")
        _aware(self.matured_at_completed_session, "Outcome maturity timestamp")
        if self.matured_at_completed_session > self.observed_at:
            raise ValueError("Outcome observation cannot precede maturity")
        if (self.result_version == 1) != (self.supersedes_batch_id is None):
            raise ValueError("Only correction versions carry a predecessor")
        if not self.terminal_counts or sum(self.terminal_counts.values()) != self.security_count:
            raise ValueError("Outcome terminal counts must equal the frozen population")
        security_ids = tuple(item.public_security_id for item in self.security_outcomes)
        if len(set(security_ids)) != len(security_ids):
            raise ValueError("Security outcome identities must be unique")
        kinds = tuple(item.kind for item in self.benchmark_outcomes)
        if len(set(kinds)) != len(kinds):
            raise ValueError("Benchmark outcome identities must be unique")
        if self.operational_completeness == OperationalCompleteness.COMPLETE:
            if len(self.security_outcomes) != self.security_count:
                raise ValueError("Complete outcomes require the full frozen population")
            if set(kinds) != set(_BENCHMARKS) or len(kinds) != 6:
                raise ValueError("Complete outcomes require all six benchmarks")
            if self.evidence_blockers:
                raise ValueError("Complete outcomes cannot carry operational blockers")
            _enforce_complete_path_metrics(self)
        elif not self.evidence_blockers:
            raise ValueError("Incomplete or blocked outcomes require explicit blockers")
        return self


class ForwardQualityTargetV21(ContractModel):
    target: QualityTarget
    status: QualityTerminalStatus
    reason_codes: tuple[str, ...]
    metric_evidence_hash: str = Field(pattern=_SHA256_PATTERN)


class ForwardQualityReportV21(ContractModel):
    schema_version: Literal["FORWARD-DQV-QUALITY-REPORT-v2.1.0"]
    report_id: UUID
    enrollment_id: UUID
    completed_sessions: int
    model_track: ModelTrack
    model_version: str = Field(min_length=1)
    evaluation_role: HorizonEvaluationRole
    result_version: int = Field(ge=1)
    supersedes_report_id: UUID | None = None
    assessed_at: datetime
    matured_through: datetime
    preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)
    operational_completeness: OperationalCompleteness
    model_quality_status: QualityTerminalStatus
    target_results: tuple[ForwardQualityTargetV21, ...] = Field(min_length=1)
    source_outcome_batch_hashes: tuple[str, ...] = Field(min_length=1)
    source_decision_manifest_hashes: tuple[str, ...] = Field(min_length=1)
    resampling_policy_version: str = Field(min_length=1)
    resampling_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    ordinary_iid_bootstrap_used: Literal[False] = False
    ai_influence: Literal[False] = False
    report_content_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_report(self) -> ForwardQualityReportV21:
        _aware(self.assessed_at, "Quality assessment timestamp")
        _aware(self.matured_through, "Quality maturity timestamp")
        if self.matured_through > self.assessed_at:
            raise ValueError("Quality assessment cannot precede maturity")
        expected_track = ModelTrack.TACTICAL if self.completed_sessions in {5, 20, 60} else (
            ModelTrack.LONG_HORIZON
        )
        if self.model_track != expected_track:
            raise ValueError("Quality report track does not match the horizon")
        if (self.result_version == 1) != (self.supersedes_report_id is None):
            raise ValueError("Only correction reports carry a predecessor")
        if len(set(self.source_outcome_batch_hashes)) != len(
            self.source_outcome_batch_hashes
        ):
            raise ValueError("Source outcome batch hashes must be unique")
        if len(set(self.source_decision_manifest_hashes)) != len(
            self.source_decision_manifest_hashes
        ):
            raise ValueError("Source decision manifest hashes must be unique")
        return self


def verify_enrollment_v21(enrollment: ForwardDqvEnrollmentV21) -> None:
    if _hash_without(enrollment, "enrollmentContentHash") != (
        enrollment.enrollment_content_hash
    ):
        raise ValueError("Forward DQV v2.1 enrollment canonical hash is invalid")
    for item in enrollment.maturity_schedule:
        if _hash_without(item, "scheduleContentHash") != item.schedule_content_hash:
            raise ValueError("Forward DQV v2.1 maturity canonical hash is invalid")


def verify_outcome_batch_v21(batch: ForwardOutcomeBatchV21) -> None:
    if _hash_without(batch, "outcomeBatchContentHash") != (
        batch.outcome_batch_content_hash
    ):
        raise ValueError("Forward DQV v2.1 outcome canonical hash is invalid")
    for item in batch.security_outcomes:
        if _hash_without(item, "recordHash") != item.record_hash:
            raise ValueError("Security outcome canonical hash is invalid")
    for item in batch.benchmark_outcomes:
        if _hash_without(item, "recordHash") != item.record_hash:
            raise ValueError("Benchmark outcome canonical hash is invalid")
    for item in batch.path_metrics:
        if _hash_without(item, "metricRecordHash") != item.metric_record_hash:
            raise ValueError("Path metric canonical hash is invalid")


def verify_quality_report_v21(report: ForwardQualityReportV21) -> None:
    if _hash_without(report, "reportContentHash") != report.report_content_hash:
        raise ValueError("Forward DQV v2.1 quality report canonical hash is invalid")


def sealed_model_payload(model: BaseModel, hash_field: str) -> dict[str, Any]:
    payload = model.model_dump(mode="json", by_alias=True)
    payload[hash_field] = canonical_hash(
        {key: value for key, value in payload.items() if key != hash_field}
    )
    return payload


def _hash_without(model: BaseModel, field: str) -> str:
    payload = model.model_dump(mode="json", by_alias=True)
    payload.pop(field)
    return canonical_hash(payload)


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _enforce_return_state(
    *,
    available: bool,
    gross: Decimal | None,
    cost: Decimal | None,
    net: Decimal | None,
    price_hash: str | None,
    source_hash: str | None,
    reasons: tuple[str, ...],
    label: str,
) -> None:
    if available:
        if any(item is None for item in (gross, cost, net, price_hash, source_hash)):
            raise ValueError(f"{label} assessed outcomes require numeric and source evidence")
        assert gross is not None and cost is not None and net is not None
        if cost < 0 or abs(net - (gross - cost)) > _RETURN_TOLERANCE:
            raise ValueError(f"{label} net return must equal gross return minus cost")
        if reasons:
            raise ValueError(f"{label} assessed outcomes cannot carry reasons")
    else:
        if any(item is not None for item in (gross, cost, net, price_hash, source_hash)):
            raise ValueError(f"{label} unavailable outcomes cannot carry numeric evidence")
        if not reasons:
            raise ValueError(f"{label} unavailable outcomes require explicit reasons")


def _enforce_complete_path_metrics(batch: ForwardOutcomeBatchV21) -> None:
    metric_keys = [
        (
            item.subject_type,
            item.public_security_id,
            item.benchmark_kind,
            item.metric_code,
        )
        for item in batch.path_metrics
    ]
    if len(set(metric_keys)) != len(metric_keys):
        raise ValueError("Path metric subject/code identities must be unique")
    security_metrics = {
        item.public_security_id: {
            value.metric_code
            for value in batch.path_metrics
            if value.subject_type == PathMetricSubjectType.SECURITY
            and value.public_security_id == item.public_security_id
        }
        for item in batch.security_outcomes
        if item.state == OutcomeObservationState.ASSESSED
    }
    required_security = {
        PathMetricCode.MAXIMUM_ADVERSE_EXCURSION,
        PathMetricCode.MAXIMUM_FAVORABLE_EXCURSION,
        PathMetricCode.MAXIMUM_DRAWDOWN,
    }
    if any(values != required_security for values in security_metrics.values()):
        raise ValueError("Every assessed security requires MAE, MFE, and drawdown")
    required_benchmarks = {
        item.kind
        for item in batch.benchmark_outcomes
        if item.state == BenchmarkOutcomeState.AVAILABLE
    }
    observed_benchmarks = {
        item.benchmark_kind
        for item in batch.path_metrics
        if item.subject_type == PathMetricSubjectType.BENCHMARK
        and item.metric_code == PathMetricCode.BENCHMARK_MAXIMUM_DRAWDOWN
    }
    if observed_benchmarks != required_benchmarks:
        raise ValueError("Every available benchmark requires maximum drawdown")
    aggregate_downside = [
        item
        for item in batch.path_metrics
        if item.subject_type == PathMetricSubjectType.AGGREGATE
        and item.metric_code == PathMetricCode.DOWNSIDE_CAPTURE
    ]
    if len(aggregate_downside) != 1:
        raise ValueError("Complete outcomes require one aggregate downside-capture metric")


def json_payload(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
