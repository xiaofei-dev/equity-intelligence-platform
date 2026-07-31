from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator
from pydantic.alias_generators import to_camel

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import ModelTrack
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind
from equity_analysis.tactical.contracts_v22 import Actionability, SetupThesis

FORWARD_DQV_STATISTICS_INPUT_V22 = "FORWARD-DQV-STATISTICS-INPUT-v2.2.0"
FORWARD_DQV_STATISTICS_REPORT_V22 = "FORWARD-DQV-STATISTICS-REPORT-v2.2.0"
FORWARD_DQV_STATISTICS_POLICY_V22 = "FORWARD-DQV-STATISTICS-POLICY-v2.2.0"
EXPECTED_RETURN_CALIBRATION_V22 = "LONG-EXPECTED-RETURN-CALIBRATION-v2.2.0"

FORMAL_HORIZONS = (5, 20, 60, 252)
DIAGNOSTIC_HORIZONS = (126,)
ALL_HORIZONS = (*FORMAL_HORIZONS[:3], *DIAGNOSTIC_HORIZONS, 252)
BOOTSTRAP_ITERATIONS = 10_000
BOOTSTRAP_SEED = 20260729
CONFIDENCE_LEVEL = Decimal("0.90")
FAMILY_WISE_ALPHA = Decimal("0.10")
TOP_BAND_FRACTION = Decimal("0.20")
MINIMUM_ELIGIBLE_DECISIONS = 100
MINIMUM_COVERAGE_RATIO = Decimal("0.80")
MINIMUM_DISTINCT_DECISION_DATES = 2
MINIMUM_STRATUM_DECISIONS = 20

_SHA = r"^sha256:[0-9a-f]{64}$"


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )


class EvaluationState(StrEnum):
    ASSESSED = "ASSESSED"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"
    EXCLUDED = "EXCLUDED"


class DqvTerminalClassification(StrEnum):
    VALIDATED = "VALIDATED"
    MIXED = "MIXED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_VALIDATED = "NOT_VALIDATED"
    BLOCKED_BY_EVIDENCE = "BLOCKED_BY_EVIDENCE"
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"


class TargetKind(StrEnum):
    TACTICAL_DECISION_QUALITY = "TACTICAL_DECISION_QUALITY"
    BUSINESS_QUALITY = "BUSINESS_QUALITY"
    SECURITY_ATTRACTIVENESS = "SECURITY_ATTRACTIVENESS"
    DOWNSIDE_RISK = "DOWNSIDE_RISK"
    EXPECTED_RETURN_CALIBRATION = "EXPECTED_RETURN_CALIBRATION"


class SizeBand(StrEnum):
    MEGA = "MEGA"
    LARGE = "LARGE"
    MID = "MID"
    SMALL = "SMALL"
    MISSING = "MISSING"


class AiProvenance(StrEnum):
    NOT_EXECUTED = "NOT_EXECUTED"
    NARRATIVE_ONLY = "NARRATIVE_ONLY"


class HumanProvenance(StrEnum):
    NOT_REVIEWED = "NOT_REVIEWED"
    REVIEWED_NO_ACTION = "REVIEWED_NO_ACTION"
    REVIEWED_SEPARATE_ACTION = "REVIEWED_SEPARATE_ACTION"


class DownsideCaptureState(StrEnum):
    VALID = "VALID"
    MISSING_SPY_PATH_NOT_READY = "MISSING_SPY_PATH_NOT_READY"
    NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS = "NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS"


class MaturedDecisionObservationV22(ContractModel):
    """Hash-bound adapter row consumed by the strictly offline evaluator.

    The maturity engine may persist a different internal shape. Its adapter
    must construct this row without filling missing fields from later data.
    """

    schema_version: Literal["FORWARD-DQV-STATISTICS-INPUT-v2.2.0"]
    observation_id: str = Field(min_length=1, max_length=255)
    enrollment_id: UUID
    decision_manifest_hash: str = Field(pattern=_SHA)
    outcome_batch_hash: str = Field(pattern=_SHA)
    public_security_id: UUID
    decision_date: date
    decision_completed_session_index: int = Field(ge=0)
    frozen_population_count: Literal[66] = 66
    completed_sessions: Literal[5, 20, 60, 126, 252]
    model_track: ModelTrack
    model_version: str = Field(min_length=1)
    state: EvaluationState
    reason_codes: tuple[str, ...] = ()
    sector: str | None = None
    size_band: SizeBand

    deterministic_score: Decimal | None = None
    selected_thesis: SetupThesis | None = None
    timing_category: Actionability | None = None
    abstained: bool = False

    business_quality_score: Decimal | None = None
    security_attractiveness_score: Decimal | None = None
    downside_risk_score: Decimal | None = None
    expected_return_low: Decimal | None = None
    expected_return_base: Decimal | None = None
    expected_return_high: Decimal | None = None
    future_business_quality_outcome: Decimal | None = None

    gross_return: Decimal | None = None
    round_trip_cost_rate: Decimal | None = Field(default=None, ge=0)
    net_return: Decimal | None = None
    liquidity_participation_rate: Decimal | None = Field(default=None, ge=0)
    liquidity_evidence_hash: str | None = Field(default=None, pattern=_SHA)
    benchmark_net_returns: dict[BenchmarkKind, Decimal] = Field(default_factory=dict)
    benchmark_maximum_drawdowns: dict[BenchmarkKind, Decimal] = Field(default_factory=dict)
    maximum_adverse_excursion: Decimal | None = None
    maximum_favorable_excursion: Decimal | None = None
    maximum_drawdown: Decimal | None = None
    downside_capture_state: DownsideCaptureState
    downside_capture: Decimal | None = Field(default=None, ge=0)
    realized_volatility: Decimal | None = Field(default=None, ge=0)
    time_to_first_positive_session: int | None = Field(default=None, ge=1)
    time_to_maximum_favorable_session: int | None = Field(default=None, ge=1)

    ai_provenance: AiProvenance
    human_provenance: HumanProvenance
    ai_affected_deterministic_result: Literal[False] = False
    human_affected_deterministic_result: Literal[False] = False
    provenance_hash: str = Field(pattern=_SHA)
    source_evidence_hash: str = Field(pattern=_SHA)
    observation_content_hash: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def enforce_observation(
        self,
        info: ValidationInfo,
    ) -> MaturedDecisionObservationV22:
        expected_track = (
            ModelTrack.TACTICAL
            if self.completed_sessions in {5, 20, 60}
            else ModelTrack.LONG_HORIZON
        )
        if self.model_track != expected_track:
            raise ValueError("Model track does not match the completed-session horizon")
        if self.completed_sessions == 126 and self.model_track != ModelTrack.LONG_HORIZON:
            raise ValueError("The 126-session observation is Long diagnostic only")
        if self.sector is not None and not self.sector.strip():
            raise ValueError("A present sector must not be blank")

        numeric_outcomes = (
            self.gross_return,
            self.round_trip_cost_rate,
            self.net_return,
            self.maximum_adverse_excursion,
            self.maximum_favorable_excursion,
            self.maximum_drawdown,
            self.realized_volatility,
        )
        if self.state == EvaluationState.ASSESSED:
            if self.reason_codes:
                raise ValueError("ASSESSED observations cannot carry terminal reasons")
            if any(item is None for item in numeric_outcomes):
                raise ValueError("ASSESSED observations require return and path metrics")
            if set(self.benchmark_net_returns) != set(BenchmarkKind):
                raise ValueError("ASSESSED observations require all six benchmarks")
            if set(self.benchmark_maximum_drawdowns) != set(BenchmarkKind):
                raise ValueError("ASSESSED observations require six benchmark drawdowns")
            if any(
                not Decimal("-1") <= value <= Decimal("0")
                for value in self.benchmark_maximum_drawdowns.values()
            ):
                raise ValueError("Benchmark drawdowns must be between -1 and 0")
            assert self.gross_return is not None
            assert self.round_trip_cost_rate is not None
            assert self.net_return is not None
            if abs(self.net_return - (self.gross_return - self.round_trip_cost_rate)) > Decimal(
                "0.000000000001"
            ):
                raise ValueError("Net return must equal gross return minus frozen cost")
            if self.maximum_adverse_excursion is not None and not (
                Decimal("-1") <= self.maximum_adverse_excursion <= Decimal("0")
            ):
                raise ValueError("MAE must be between -1 and 0")
            if self.maximum_drawdown is not None and not (
                Decimal("-1") <= self.maximum_drawdown <= Decimal("0")
            ):
                raise ValueError("Maximum drawdown must be between -1 and 0")
            if (
                self.maximum_favorable_excursion is not None
                and self.maximum_favorable_excursion < 0
            ):
                raise ValueError("MFE cannot be negative")
            if (self.downside_capture_state == DownsideCaptureState.VALID) != (
                self.downside_capture is not None
            ):
                raise ValueError("Numeric downside capture is allowed only for VALID state")
            if self.model_track == ModelTrack.TACTICAL:
                if (
                    self.deterministic_score is None
                    or self.selected_thesis is None
                    or self.timing_category is None
                ):
                    raise ValueError(
                        "Tactical observations require the frozen score, thesis, and timing"
                    )
                expected_abstention = self.timing_category not in {
                    Actionability.ENTRY,
                    Actionability.LIMITED_ENTRY,
                }
                if self.abstained != expected_abstention:
                    raise ValueError("Tactical abstention must follow the frozen actionability")
                if any(
                    item is not None
                    for item in (
                        self.business_quality_score,
                        self.security_attractiveness_score,
                        self.downside_risk_score,
                        self.expected_return_low,
                        self.expected_return_base,
                        self.expected_return_high,
                        self.future_business_quality_outcome,
                    )
                ):
                    raise ValueError("Tactical rows cannot carry Long target fields")
            else:
                if self.abstained:
                    raise ValueError("Long observations do not use Tactical abstention")
                if any(
                    item is not None
                    for item in (
                        self.deterministic_score,
                        self.selected_thesis,
                        self.timing_category,
                    )
                ):
                    raise ValueError("Long rows cannot carry Tactical decision fields")
                values = (
                    self.expected_return_low,
                    self.expected_return_base,
                    self.expected_return_high,
                )
                if any(item is not None for item in values):
                    if any(item is None for item in values):
                        raise ValueError("Expected-return calibration requires low, base, and high")
                    assert (
                        self.expected_return_low is not None
                        and self.expected_return_base is not None
                        and self.expected_return_high is not None
                    )
                    if not (
                        self.expected_return_low
                        <= self.expected_return_base
                        <= self.expected_return_high
                    ):
                        raise ValueError("Expected-return range must be ordered")
        else:
            if not self.reason_codes:
                raise ValueError("Non-assessed observations require explicit reasons")
            if any(item is not None for item in numeric_outcomes):
                raise ValueError("Non-assessed observations cannot carry outcomes")
            if self.benchmark_net_returns:
                raise ValueError("Non-assessed observations cannot carry benchmarks")
            if self.benchmark_maximum_drawdowns:
                raise ValueError("Non-assessed observations cannot carry benchmark drawdowns")
            if any(
                item is not None
                for item in (
                    self.deterministic_score,
                    self.selected_thesis,
                    self.timing_category,
                    self.business_quality_score,
                    self.security_attractiveness_score,
                    self.downside_risk_score,
                    self.expected_return_low,
                    self.expected_return_base,
                    self.expected_return_high,
                    self.future_business_quality_outcome,
                    self.time_to_first_positive_session,
                    self.time_to_maximum_favorable_session,
                    self.downside_capture,
                    self.liquidity_participation_rate,
                    self.liquidity_evidence_hash,
                )
            ):
                raise ValueError("Non-assessed observations cannot carry model results")

        if not (info.context or {}).get("skip_hash_verification"):
            body = self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"observation_content_hash"},
            )
            if canonical_hash(body) != self.observation_content_hash:
                raise ValueError("Matured observation canonical hash is invalid")
        return self


class MaturedOutcomeAdapterV22(Protocol):
    """Boundary implemented by the Gate-H persistence/readback adapter."""

    def load_matured_observations(
        self,
        *,
        completed_sessions: int,
    ) -> tuple[MaturedDecisionObservationV22, ...]: ...


def seal_matured_observation(
    payload: dict[str, object],
) -> MaturedDecisionObservationV22:
    body = dict(payload)
    body.pop("observationContentHash", None)
    provisional = MaturedDecisionObservationV22.model_validate(
        {
            **body,
            "observationContentHash": ("sha256:" + "0" * 64),
        },
        context={"skip_hash_verification": True},
    )
    normalized = provisional.model_dump(
        mode="json",
        by_alias=True,
        exclude={"observation_content_hash"},
    )
    return MaturedDecisionObservationV22.model_validate(
        {
            **normalized,
            "observationContentHash": canonical_hash(normalized),
        }
    )
