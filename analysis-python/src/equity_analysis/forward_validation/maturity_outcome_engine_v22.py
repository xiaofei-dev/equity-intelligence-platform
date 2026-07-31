from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.outcomes_v2 import (
    BenchmarkOutcomeState,
    OperationalCompleteness,
    OutcomeObservationState,
)
from equity_analysis.forward_validation.outcomes_v21 import (
    BenchmarkOutcomeV21,
    ForwardOutcomeBatchV21,
    PathMetricCode,
    PathMetricState,
    PathMetricSubjectType,
    PathMetricV21,
    SecurityOutcomeV21,
)
from equity_analysis.forward_validation.outcomes_v211 import (
    ForwardDqvEnrollmentV211,
)
from equity_analysis.historical_validation.protocol_v2 import (
    BenchmarkKind,
    LiquiditySensitiveCostPolicy,
)

MATURITY_ENGINE_V22 = "FORWARD-DQV-MATURITY-ENGINE-v2.2.0"
MATURITY_ANALYTICS_V22 = "FORWARD-DQV-MATURITY-ANALYTICS-v2.2.0"
_SHA = r"^sha256:[0-9a-f]{64}$"
_NAMESPACE = UUID("81969c71-fe78-4bc9-a459-281eb7293163")
_HORIZONS = (5, 20, 60, 126, 252)
_COST = LiquiditySensitiveCostPolicy(
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


class EvidenceState(StrEnum):
    READY = "READY"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    EXCLUDED = "EXCLUDED"


class ProvenanceType(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    HUMAN = "HUMAN"
    AI_NARRATIVE = "AI_NARRATIVE"
    SOURCE_EVIDENCE = "SOURCE_EVIDENCE"


class TurnoverState(StrEnum):
    NOT_COMPUTABLE_MISSING_PORTFOLIO_DENOMINATOR = "NOT_COMPUTABLE_MISSING_PORTFOLIO_DENOMINATOR"


class DownsideCaptureState(StrEnum):
    VALID = "VALID"
    MISSING_SPY_PATH_NOT_READY = "MISSING_SPY_PATH_NOT_READY"
    NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS = "NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS"


class ProvenanceBoundary(ContractModel):
    provenance_type: ProvenanceType
    reference: str = Field(min_length=1)
    content_hash: str = Field(pattern=_SHA)
    may_affect_deterministic_outcome: bool

    @model_validator(mode="after")
    def enforce_boundary(self) -> ProvenanceBoundary:
        if (
            self.provenance_type in {ProvenanceType.HUMAN, ProvenanceType.AI_NARRATIVE}
            and self.may_affect_deterministic_outcome
        ):
            raise ValueError("Human and AI provenance cannot alter outcomes")
        return self


class CompletedSessionBar(ContractModel):
    session_close: datetime
    adjusted_open: Decimal = Field(gt=0)
    adjusted_high: Decimal = Field(gt=0)
    adjusted_low: Decimal = Field(gt=0)
    adjusted_close: Decimal = Field(gt=0)
    available_at: datetime
    source_hash: str = Field(pattern=_SHA)
    action_adjustment_hash: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def enforce_bar(self) -> CompletedSessionBar:
        if self.session_close.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("Completed-session timestamps must be timezone-aware")
        if self.available_at < self.session_close:
            raise ValueError("Evidence cannot be available before session close")
        if not self.adjusted_low <= min(self.adjusted_open, self.adjusted_close):
            raise ValueError("Adjusted low is inconsistent")
        if not self.adjusted_high >= max(self.adjusted_open, self.adjusted_close):
            raise ValueError("Adjusted high is inconsistent")
        return self


class MaturityPathInput(ContractModel):
    subject_id: str = Field(min_length=1)
    public_security_id: UUID | None = None
    benchmark_kind: BenchmarkKind | None = None
    state: EvidenceState
    entry_open: Decimal | None = Field(default=None, gt=0)
    bars: tuple[CompletedSessionBar, ...] = ()
    order_notional: Decimal | None = Field(default=None, gt=0)
    average_daily_dollar_volume: Decimal | None = Field(default=None, gt=0)
    calendar_evidence_hash: str | None = Field(default=None, pattern=_SHA)
    source_manifest_hash: str | None = Field(default=None, pattern=_SHA)
    reason_codes: tuple[str, ...] = ()
    provenance: tuple[ProvenanceBoundary, ...] = ()

    @model_validator(mode="after")
    def enforce_input(self) -> MaturityPathInput:
        if (self.public_security_id is None) == (self.benchmark_kind is None):
            raise ValueError("Path input requires exactly one subject identity")
        values = (
            self.entry_open,
            self.order_notional,
            self.average_daily_dollar_volume,
            self.calendar_evidence_hash,
            self.source_manifest_hash,
        )
        if self.state == EvidenceState.READY:
            if any(value is None for value in values) or not self.bars:
                raise ValueError("READY path requires complete bounded evidence")
            if self.reason_codes:
                raise ValueError("READY path cannot carry reasons")
        elif any(value is not None for value in values) or self.bars:
            raise ValueError("Non-ready path cannot carry numeric evidence")
        elif not self.reason_codes:
            raise ValueError("Non-ready path requires explicit reasons")
        return self


class SupplementalPathAnalyticsV22(ContractModel):
    subject_id: str
    stable_identity: str = Field(pattern=r"^(SECURITY|BENCHMARK):.+$")
    order_notional: Decimal = Field(gt=0)
    average_daily_dollar_volume: Decimal = Field(gt=0)
    liquidity_participation_rate: Decimal = Field(gt=0)
    portfolio_turnover: None = None
    portfolio_turnover_state: Literal["NOT_COMPUTABLE_MISSING_PORTFOLIO_DENOMINATOR"]
    downside_capture: Decimal | None = Field(default=None, ge=0)
    downside_capture_state: DownsideCaptureState
    downside_deviation: Decimal
    realized_volatility: Decimal
    negative_session_count: int = Field(ge=0)
    evidence_hash: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def enforce_downside_capture(self) -> SupplementalPathAnalyticsV22:
        if (self.downside_capture_state == DownsideCaptureState.VALID) != (
            self.downside_capture is not None
        ):
            raise ValueError("Downside-capture value and state are inconsistent")
        return self


class MaturityEvaluationBundleV22(ContractModel):
    schema_version: Literal["FORWARD-DQV-MATURITY-ANALYTICS-v2.2.0"]
    outcome_batch: ForwardOutcomeBatchV21
    supplemental_path_analytics: tuple[SupplementalPathAnalyticsV22, ...]
    tactical_entry_thesis_hash: str | None = Field(default=None, pattern=_SHA)
    tactical_timing_category: str | None = None
    long_expected_return_low: Decimal | None = None
    long_expected_return_high: Decimal | None = None
    long_calibration_payload_hash: str | None = Field(default=None, pattern=_SHA)
    provenance: tuple[ProvenanceBoundary, ...]
    bundle_content_hash: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def enforce_model_track_payload(self) -> MaturityEvaluationBundleV22:
        tactical = self.outcome_batch.completed_sessions in {5, 20, 60}
        tactical_fields = (
            self.tactical_entry_thesis_hash,
            self.tactical_timing_category,
        )
        long_fields = (
            self.long_expected_return_low,
            self.long_expected_return_high,
            self.long_calibration_payload_hash,
        )
        if tactical and any(value is not None for value in long_fields):
            raise ValueError("Tactical outcomes cannot carry long-horizon payloads")
        if not tactical and any(value is not None for value in tactical_fields):
            raise ValueError("Long outcomes cannot carry tactical payloads")
        if (self.long_expected_return_low is None) != (self.long_expected_return_high is None):
            raise ValueError("Expected-return range requires both bounds")
        if (
            self.long_expected_return_low is not None
            and self.long_expected_return_low > self.long_expected_return_high
        ):
            raise ValueError("Expected-return range is inverted")
        return self


@dataclass(frozen=True)
class MaturityPreflight:
    status: str
    blockers: tuple[str, ...]
    artifact: dict[str, Any]


def build_preflight(*, enrollment_count: int, matured_count: int) -> MaturityPreflight:
    blockers = []
    if enrollment_count == 0:
        blockers.append("BLOCKED_NO_ENROLLMENT")
    if matured_count == 0:
        blockers.append("NO_MATURED_OUTCOMES")
    body = {
        "schemaVersion": MATURITY_ENGINE_V22,
        "status": "BLOCKED" if blockers else "READY",
        "blockers": blockers,
        "supportedHorizons": list(_HORIZONS),
        "requiredBenchmarkCount": 6,
        "networkRequestsExecuted": 0,
        "databaseWritesExecuted": 0,
        "realOutcomesComputed": 0,
    }
    artifact = {**body, "artifactContentHash": canonical_hash(body)}
    return MaturityPreflight(artifact["status"], tuple(blockers), artifact)


def evaluate_maturity(
    *,
    enrollment: ForwardDqvEnrollmentV211,
    completed_sessions: int,
    observed_at: datetime,
    security_paths: tuple[MaturityPathInput, ...],
    benchmark_paths: tuple[MaturityPathInput, ...],
    source_manifest_hash: str,
    calendar_evidence_hash: str,
    action_evidence_hash: str,
    price_evidence_hash: str,
    result_version: int = 1,
    supersedes_batch_id: UUID | None = None,
    tactical_entry_thesis_hash: str | None = None,
    tactical_timing_category: str | None = None,
    long_expected_return_range: tuple[Decimal, Decimal] | None = None,
    long_calibration_payload_hash: str | None = None,
    provenance: tuple[ProvenanceBoundary, ...] = (),
) -> MaturityEvaluationBundleV22:
    if completed_sessions not in _HORIZONS:
        raise ValueError("Unsupported completed-session horizon")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("OBSERVED_AT_TIMEZONE_REQUIRED")
    schedule = next(
        item
        for item in enrollment.maturity_schedule
        if item.completed_sessions == completed_sessions
    )
    if observed_at.astimezone(UTC) < schedule.matures_at_completed_session.astimezone(UTC):
        raise ValueError("FUTURE_MATURITY_NOT_AVAILABLE")
    if (
        len(benchmark_paths) != 6
        or any(
            item.public_security_id is not None or item.benchmark_kind is None
            for item in benchmark_paths
        )
        or {item.benchmark_kind for item in benchmark_paths} != set(BenchmarkKind)
    ):
        raise ValueError("Exactly six benchmark paths are required")
    if len(security_paths) != enrollment.security_count:
        raise ValueError("FROZEN_SECURITY_POPULATION_COUNT_MISMATCH")
    if any(
        item.public_security_id is None or item.benchmark_kind is not None
        for item in security_paths
    ):
        raise ValueError("SECURITY_PATH_IDENTITY_REQUIRED")
    security_ids = tuple(item.public_security_id for item in security_paths)
    if len(set(security_ids)) != len(security_ids):
        raise ValueError("DUPLICATE_PUBLIC_SECURITY_ID")
    expected_roots = build_evidence_root_hashes((*security_paths, *benchmark_paths))
    supplied_roots = {
        "source_manifest_hash": source_manifest_hash,
        "calendar_evidence_hash": calendar_evidence_hash,
        "action_evidence_hash": action_evidence_hash,
        "price_evidence_hash": price_evidence_hash,
    }
    if supplied_roots != expected_roots:
        raise ValueError("BATCH_EVIDENCE_ROOT_BINDING_MISMATCH")
    market = next(item for item in benchmark_paths if item.benchmark_kind == BenchmarkKind.SPY)
    for item in (*security_paths, *benchmark_paths):
        if item.state != EvidenceState.READY:
            continue
        if any(
            bar.session_close <= enrollment.effective_at_completed_session_open for bar in item.bars
        ):
            raise ValueError("PATH_SESSION_NOT_AFTER_ENTRY_OPEN")
        if item.bars[-1].session_close != schedule.matures_at_completed_session:
            raise ValueError("PATH_MATURITY_SESSION_MISMATCH")
        if any(bar.available_at > observed_at for bar in item.bars):
            raise ValueError("PATH_EVIDENCE_AFTER_OBSERVATION_CUTOFF")
    if market.state == EvidenceState.READY:
        market_sessions = tuple(bar.session_close for bar in market.bars)
        if any(
            item.state == EvidenceState.READY
            and tuple(bar.session_close for bar in item.bars) != market_sessions
            for item in (*security_paths, *benchmark_paths)
        ):
            raise ValueError("PATH_SESSION_CALENDAR_MISMATCH")

    security_outcomes = tuple(
        _security_outcome(item, completed_sessions) for item in security_paths
    )
    benchmark_outcomes = tuple(
        _benchmark_outcome(item, completed_sessions) for item in benchmark_paths
    )
    metrics = tuple(
        metric
        for item in (*security_paths, *benchmark_paths)
        for metric in _path_metrics(item, completed_sessions)
    )
    downside = _aggregate_downside_metric(security_paths, benchmark_paths)
    metrics = (*metrics, downside)
    terminal_counts = {
        state.value: sum(item.state.value == state.value for item in security_outcomes)
        for state in OutcomeObservationState
    }
    blockers = tuple(
        sorted(
            {reason for item in (*security_paths, *benchmark_paths) for reason in item.reason_codes}
        )
    )
    completeness = (
        OperationalCompleteness.COMPLETE if not blockers else OperationalCompleteness.INCOMPLETE
    )
    batch_id = uuid5(
        _NAMESPACE,
        f"{enrollment.enrollment_id}:{completed_sessions}:{result_version}:{source_manifest_hash}",
    )
    batch_payload = {
        "schemaVersion": "FORWARD-DQV-OUTCOME-v2.1.0",
        "outcomeBatchId": str(batch_id),
        "enrollmentId": str(enrollment.enrollment_id),
        "completedSessions": completed_sessions,
        "evaluationRole": schedule.evaluation_role.value,
        "resultVersion": result_version,
        "supersedesBatchId": str(supersedes_batch_id) if supersedes_batch_id else None,
        "observedAt": observed_at,
        "maturedAtCompletedSession": schedule.matures_at_completed_session,
        "operationalCompleteness": completeness.value,
        "securityCount": enrollment.security_count,
        "terminalCounts": terminal_counts,
        "preregistrationContentHash": enrollment.preregistration_content_hash,
        "decisionManifestContentHash": enrollment.decision_manifest_content_hash,
        "frozenPopulationHash": enrollment.frozen_population_hash,
        "modelFreezeHashes": enrollment.model_freeze_hashes,
        "benchmarkContractHash": enrollment.benchmark_contract_hash,
        "costPolicyHash": enrollment.cost_policy_hash,
        "sourceManifestHash": source_manifest_hash,
        "calendarEvidenceHash": calendar_evidence_hash,
        "actionEvidenceHash": action_evidence_hash,
        "priceEvidenceHash": price_evidence_hash,
        "evidenceBlockers": list(blockers),
        "securityOutcomes": [
            item.model_dump(mode="json", by_alias=True) for item in security_outcomes
        ],
        "benchmarkOutcomes": [
            item.model_dump(mode="json", by_alias=True) for item in benchmark_outcomes
        ],
        "pathMetrics": [item.model_dump(mode="json", by_alias=True) for item in metrics],
    }
    batch = ForwardOutcomeBatchV21.model_validate(
        {**batch_payload, "outcomeBatchContentHash": canonical_hash(batch_payload)}
    )
    supplement = tuple(
        _supplement(item, completed_sessions, market)
        for item in (*security_paths, *benchmark_paths)
        if item.state == EvidenceState.READY
    )
    low, high = long_expected_return_range or (None, None)
    bundle_payload = {
        "schemaVersion": MATURITY_ANALYTICS_V22,
        "outcomeBatch": batch.model_dump(mode="json", by_alias=True),
        "supplementalPathAnalytics": [
            item.model_dump(mode="json", by_alias=True) for item in supplement
        ],
        "tacticalEntryThesisHash": tactical_entry_thesis_hash,
        "tacticalTimingCategory": tactical_timing_category,
        "longExpectedReturnLow": low,
        "longExpectedReturnHigh": high,
        "longCalibrationPayloadHash": long_calibration_payload_hash,
        "provenance": [item.model_dump(mode="json", by_alias=True) for item in provenance],
    }
    return MaturityEvaluationBundleV22.model_validate(
        {**bundle_payload, "bundleContentHash": canonical_hash(bundle_payload)}
    )


def build_evidence_root_hashes(
    paths: tuple[MaturityPathInput, ...],
) -> dict[str, str]:
    identities = tuple(_stable_path_identity(item) for item in paths)
    if len(set(identities)) != len(identities):
        raise ValueError("DUPLICATE_TYPED_PATH_IDENTITY")
    ready = tuple(
        item
        for item in sorted(paths, key=_stable_path_identity)
        if item.state == EvidenceState.READY
    )
    return {
        "source_manifest_hash": canonical_hash(
            [(_stable_path_identity(item), item.source_manifest_hash) for item in ready]
        ),
        "calendar_evidence_hash": canonical_hash(
            [(_stable_path_identity(item), item.calendar_evidence_hash) for item in ready]
        ),
        "action_evidence_hash": canonical_hash(
            [
                (
                    _stable_path_identity(item),
                    [bar.action_adjustment_hash for bar in item.bars],
                )
                for item in ready
            ]
        ),
        "price_evidence_hash": canonical_hash(
            [
                (
                    _stable_path_identity(item),
                    [bar.source_hash for bar in item.bars],
                )
                for item in ready
            ]
        ),
    }


def _stable_path_identity(value: MaturityPathInput) -> str:
    if value.public_security_id is not None:
        return f"SECURITY:{value.public_security_id}"
    if value.benchmark_kind is not None:
        return f"BENCHMARK:{value.benchmark_kind.value}"
    raise ValueError("PATH_STABLE_IDENTITY_REQUIRED")


def _state(value: EvidenceState) -> OutcomeObservationState:
    return OutcomeObservationState(value.value)


def _returns(value: MaturityPathInput, horizon: int) -> tuple[Decimal, Decimal, Decimal]:
    assert value.entry_open is not None
    if len(value.bars) != horizon:
        raise ValueError("COMPLETED_SESSION_PATH_LENGTH_MISMATCH")
    if (
        tuple(item.session_close for item in value.bars)
        != tuple(sorted(item.session_close for item in value.bars))
        or len({item.session_close for item in value.bars}) != horizon
    ):
        raise ValueError("COMPLETED_SESSION_CALENDAR_INVALID")
    gross = value.bars[-1].adjusted_close / value.entry_open - Decimal(1)
    assert value.order_notional is not None and value.average_daily_dollar_volume is not None
    cost = _COST.round_trip_cost_rate(
        order_notional=value.order_notional,
        average_daily_dollar_volume=value.average_daily_dollar_volume,
    )
    return gross, cost, gross - cost


def _security_outcome(value: MaturityPathInput, horizon: int) -> SecurityOutcomeV21:
    if value.state != EvidenceState.READY:
        payload = {
            "publicSecurityId": str(value.public_security_id),
            "state": _state(value.state).value,
            "reasonCodes": list(value.reason_codes),
        }
    else:
        gross, cost, net = _returns(value, horizon)
        payload = {
            "publicSecurityId": str(value.public_security_id),
            "state": "ASSESSED",
            "grossReturn": gross,
            "roundTripCostRate": cost,
            "netReturn": net,
            "priceActionEvidenceHash": canonical_hash([bar.source_hash for bar in value.bars]),
            "sourceManifestHash": value.source_manifest_hash,
            "reasonCodes": [],
        }
    return SecurityOutcomeV21.model_validate({**payload, "recordHash": canonical_hash(payload)})


def _benchmark_outcome(value: MaturityPathInput, horizon: int) -> BenchmarkOutcomeV21:
    state = BenchmarkOutcomeState(
        value.state.value
        if value.state
        in {
            EvidenceState.MISSING,
            EvidenceState.STALE,
            EvidenceState.INVALID,
        }
        else "AVAILABLE"
    )
    if value.state in {EvidenceState.NOT_APPLICABLE, EvidenceState.EXCLUDED}:
        state = BenchmarkOutcomeState.INVALID
    if value.state != EvidenceState.READY:
        payload = {
            "kind": value.benchmark_kind.value,
            "identifier": value.subject_id,
            "state": state.value,
            "reasonCodes": list(value.reason_codes),
        }
    else:
        gross, cost, net = _returns(value, horizon)
        payload = {
            "kind": value.benchmark_kind.value,
            "identifier": value.subject_id,
            "state": "AVAILABLE",
            "grossReturn": gross,
            "roundTripCostRate": cost,
            "netReturn": net,
            "priceActionEvidenceHash": canonical_hash([bar.source_hash for bar in value.bars]),
            "sourceManifestHash": value.source_manifest_hash,
            "reasonCodes": [],
        }
    return BenchmarkOutcomeV21.model_validate({**payload, "recordHash": canonical_hash(payload)})


def _path_metrics(value: MaturityPathInput, horizon: int) -> tuple[PathMetricV21, ...]:
    subject_type = (
        PathMetricSubjectType.SECURITY
        if value.public_security_id
        else PathMetricSubjectType.BENCHMARK
    )
    codes = (
        (
            PathMetricCode.MAXIMUM_ADVERSE_EXCURSION,
            PathMetricCode.MAXIMUM_FAVORABLE_EXCURSION,
            PathMetricCode.MAXIMUM_DRAWDOWN,
        )
        if value.public_security_id
        else (PathMetricCode.BENCHMARK_MAXIMUM_DRAWDOWN,)
    )
    if value.state != EvidenceState.READY:
        return ()
    assert value.entry_open is not None
    _returns(value, horizon)
    closes = [bar.adjusted_close for bar in value.bars]
    peak = value.entry_open
    drawdowns = []
    for close in closes:
        peak = max(peak, close)
        drawdowns.append(close / peak - Decimal(1))
    values = {
        PathMetricCode.MAXIMUM_ADVERSE_EXCURSION: min(
            bar.adjusted_low / value.entry_open - Decimal(1) for bar in value.bars
        ),
        PathMetricCode.MAXIMUM_FAVORABLE_EXCURSION: max(
            Decimal(0),
            max(bar.adjusted_high / value.entry_open - Decimal(1) for bar in value.bars),
        ),
        PathMetricCode.MAXIMUM_DRAWDOWN: min(drawdowns),
        PathMetricCode.BENCHMARK_MAXIMUM_DRAWDOWN: min(drawdowns),
    }
    evidence_hash = canonical_hash([bar.source_hash for bar in value.bars])
    result = []
    for code in codes:
        payload = {
            "subjectType": subject_type.value,
            "publicSecurityId": str(value.public_security_id) if value.public_security_id else None,
            "benchmarkKind": value.benchmark_kind.value if value.benchmark_kind else None,
            "metricCode": code.value,
            "state": PathMetricState.VALID.value,
            "metricValue": values[code],
            "sourceEvidenceHash": evidence_hash,
            "reasonCodes": [],
        }
        result.append(
            PathMetricV21.model_validate({**payload, "metricRecordHash": canonical_hash(payload)})
        )
    return tuple(result)


def _aggregate_downside_metric(
    securities: tuple[MaturityPathInput, ...],
    benchmarks: tuple[MaturityPathInput, ...],
) -> PathMetricV21:
    available = [item for item in securities if item.state == EvidenceState.READY]
    market = next(
        (item for item in benchmarks if item.benchmark_kind == BenchmarkKind.SPY),
        None,
    )
    if not available or market is None or market.state != EvidenceState.READY:
        payload = {
            "subjectType": "AGGREGATE",
            "metricCode": "DOWNSIDE_CAPTURE",
            "state": "MISSING",
            "reasonCodes": ["DOWNSIDE_CAPTURE_INPUT_MISSING"],
        }
    else:
        negative = [
            index
            for index, bar in enumerate(market.bars)
            if index and bar.adjusted_close < market.bars[index - 1].adjusted_close
        ]
        if not negative:
            payload = {
                "subjectType": "AGGREGATE",
                "metricCode": "DOWNSIDE_CAPTURE",
                "state": "NOT_APPLICABLE",
                "reasonCodes": ["DOWNSIDE_CAPTURE_NO_SPY_NEGATIVE_SESSIONS"],
            }
        else:
            market_losses = sum(
                abs(market.bars[index].adjusted_close / market.bars[index - 1].adjusted_close - 1)
                for index in negative
            )
            security_losses = Decimal(0)
            observations = 0
            for item in available:
                for index in negative:
                    if index < len(item.bars):
                        security_losses += abs(
                            min(
                                Decimal(0),
                                item.bars[index].adjusted_close
                                / item.bars[index - 1].adjusted_close
                                - 1,
                            )
                        )
                        observations += 1
            value = (
                security_losses / Decimal(observations) / (market_losses / Decimal(len(negative)))
                if observations and market_losses
                else Decimal(0)
            )
            evidence = canonical_hash(
                [market.source_manifest_hash, *(item.source_manifest_hash for item in available)]
            )
            payload = {
                "subjectType": "AGGREGATE",
                "metricCode": "DOWNSIDE_CAPTURE",
                "state": "VALID",
                "metricValue": value,
                "sourceEvidenceHash": evidence,
                "reasonCodes": [],
            }
    return PathMetricV21.model_validate({**payload, "metricRecordHash": canonical_hash(payload)})


def _supplement(
    value: MaturityPathInput,
    horizon: int,
    market: MaturityPathInput,
) -> SupplementalPathAnalyticsV22:
    _returns(value, horizon)
    assert value.order_notional is not None
    assert value.average_daily_dollar_volume is not None
    downside_capture, downside_capture_state = _path_downside_capture(value, market)
    returns = [
        value.bars[index].adjusted_close
        / (value.entry_open if index == 0 else value.bars[index - 1].adjusted_close)
        - Decimal(1)
        for index in range(len(value.bars))
    ]
    mean = sum(returns) / Decimal(len(returns))
    variance = sum((item - mean) ** 2 for item in returns) / Decimal(len(returns))
    downside = [min(Decimal(0), item) for item in returns]
    downside_variance = sum(item * item for item in downside) / Decimal(len(downside))
    payload = {
        "subjectId": value.subject_id,
        "stableIdentity": _stable_path_identity(value),
        "orderNotional": value.order_notional,
        "averageDailyDollarVolume": value.average_daily_dollar_volume,
        "liquidityParticipationRate": (value.order_notional / value.average_daily_dollar_volume),
        "portfolioTurnover": None,
        "portfolioTurnoverState": (
            TurnoverState.NOT_COMPUTABLE_MISSING_PORTFOLIO_DENOMINATOR.value
        ),
        "downsideCapture": downside_capture,
        "downsideCaptureState": downside_capture_state.value,
        "downsideDeviation": downside_variance.sqrt(),
        "realizedVolatility": variance.sqrt(),
        "negativeSessionCount": sum(item < 0 for item in returns),
    }
    return SupplementalPathAnalyticsV22.model_validate(
        {**payload, "evidenceHash": canonical_hash(payload)}
    )


def _path_downside_capture(
    value: MaturityPathInput,
    market: MaturityPathInput,
) -> tuple[Decimal | None, DownsideCaptureState]:
    if market.state != EvidenceState.READY:
        return None, DownsideCaptureState.MISSING_SPY_PATH_NOT_READY
    negative = tuple(
        index
        for index, bar in enumerate(market.bars)
        if index and bar.adjusted_close < market.bars[index - 1].adjusted_close
    )
    if not negative:
        return None, DownsideCaptureState.NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS
    market_loss = sum(
        abs(market.bars[index].adjusted_close / market.bars[index - 1].adjusted_close - 1)
        for index in negative
    )
    path_loss = sum(
        abs(
            min(
                Decimal(0),
                value.bars[index].adjusted_close / value.bars[index - 1].adjusted_close - 1,
            )
        )
        for index in negative
    )
    return path_loss / market_loss, DownsideCaptureState.VALID
